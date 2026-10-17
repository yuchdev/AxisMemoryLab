"""ELF reading, build-id matching, tool parsing, sample loading: all with synthetic inputs."""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import pytest
from elf_builder import EM_ARM, build_elf
from sample_files import alloc, free, header, module, summary, write_samples

from axis_memlab.errors import CollectionError, RunDataError
from axis_memlab.symbolization.elf import ElfError, read_build_id, read_elf
from axis_memlab.symbolization.resolve import (
    Resolver,
    SymbolIndex,
    _parse_addr2line,
    _parse_llvm_symbolizer,
)
from axis_memlab.symbolization.stackmap import load_samples

BUILD_A = bytes.fromhex("aabbccddeeff00112233445566778899aabbccdd")
BUILD_B = bytes.fromhex("11" * 20)
HEX_A = BUILD_A.hex()
HEX_B = BUILD_B.hex()
FUNCS = [
    ("_start", 0x1000, 0x20),
    ("leaky_function", 0x1100, 0x80),
    ("_ZN3foo3barEv", 0x1200, 0x40),
]


# ---- ELF -------------------------------------------------------------------------------------
def test_build_id_from_segment_section_or_missing(tmp_path: Path) -> None:
    both = build_elf(tmp_path / "both", build_id=BUILD_A, symbols=FUNCS)
    assert read_build_id(both) == HEX_A
    only_section = build_elf(tmp_path / "sec", build_id=BUILD_A, note_segment=False)
    assert read_build_id(only_section) == HEX_A
    only_segment = build_elf(tmp_path / "seg", build_id=BUILD_A, note_section=False)
    assert read_build_id(only_segment) == HEX_A
    assert read_build_id(build_elf(tmp_path / "none", build_id=None)) is None


def test_symbol_lookup_boundaries(tmp_path: Path) -> None:
    image = read_elf(build_elf(tmp_path / "f", build_id=BUILD_A, symbols=FUNCS))
    assert image.lookup(0x1100) == ("leaky_function", 0)
    assert image.lookup(0x117F) == ("leaky_function", 0x7F)
    assert image.lookup(0x1180) is None  # one past the end of a sized symbol
    assert image.lookup(0x0FFF) is None  # before the first symbol
    assert image.lookup(0x1205) == ("_ZN3foo3barEv", 5)


def test_unsized_symbols_are_only_trusted_for_a_short_distance(tmp_path: Path) -> None:
    image = read_elf(build_elf(tmp_path / "f", build_id=None, symbols=[("stub", 0x2000, 0)]))
    assert image.lookup(0x2010) == ("stub", 0x10)
    assert image.lookup(0x2000 + 100000) is None


def test_only_defined_functions_are_symbols(tmp_path: Path) -> None:
    data = build_elf(tmp_path / "obj", build_id=None, symbols=FUNCS, symbol_type=1)  # OBJECT
    assert read_elf(data).symbols == []
    undefined = build_elf(tmp_path / "und", build_id=None, symbols=FUNCS, shndx=0)
    assert read_elf(undefined).symbols == []
    ifunc = build_elf(tmp_path / "ifunc", build_id=None, symbols=FUNCS[:1], symbol_type=10)
    assert [s.name for s in read_elf(ifunc).symbols] == ["_start"]


def test_elf32_arm_thumb_bit_is_cleared(tmp_path: Path) -> None:
    path = build_elf(
        tmp_path / "arm", build_id=BUILD_A, bits=32, machine=EM_ARM,
        symbols=[("thumb_fn", 0x8001, 0x20)],
    )  # fmt: skip
    image = read_elf(path)
    assert image.bits == 32 and image.build_id == HEX_A
    assert image.lookup(0x8000) == ("thumb_fn", 0)
    assert image.lookup(0x8010) == ("thumb_fn", 0x10)


def test_corrupt_or_foreign_files_raise_elferror_only(tmp_path: Path) -> None:
    good = build_elf(tmp_path / "good", build_id=BUILD_A, symbols=FUNCS).read_bytes()
    cases = {
        "text": b"hello world, not an elf",
        "empty": b"",
        "truncated": good[:100],
        "bigendian": good[:5] + b"\x02" + good[6:],
        "badclass": good[:4] + b"\x07" + good[5:],
    }
    for name, blob in cases.items():
        path = tmp_path / name
        path.write_bytes(blob)
        with pytest.raises(ElfError):
            read_elf(path)
    # Section header offset pointing far outside the file: still an ElfError.
    broken = bytearray(good)
    broken[40:48] = struct.pack("<Q", 2**40)
    path = tmp_path / "bad_shoff"
    path.write_bytes(bytes(broken))
    with pytest.raises(ElfError):
        read_elf(path)
    with pytest.raises(ElfError):
        read_elf(tmp_path / "does-not-exist")


# ---- index and build-id matching -----------------------------------------------------------------
def _symbols_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "symbols"
    (directory / "nested").mkdir(parents=True)
    build_elf(directory / "app.debug", build_id=BUILD_A, symbols=FUNCS)
    build_elf(
        directory / "nested" / "libother.so", build_id=BUILD_B, symbols=[("other", 0x500, 0x10)]
    )
    (directory / "README.txt").write_text("not an elf")
    (directory / "broken").write_bytes(b"\x7fELF" + b"\0" * 10)
    return directory


def test_index_finds_files_by_content_not_name(tmp_path: Path) -> None:
    index = SymbolIndex.build(_symbols_dir(tmp_path))
    assert index.by_build_id[HEX_A].name == "app.debug"
    assert index.by_build_id[HEX_B].name == "libother.so"
    assert index.unreadable == 1  # the truncated ELF
    with pytest.raises(CollectionError):
        SymbolIndex.build(tmp_path / "missing")


def _session(tmp_path: Path, modules: list[dict[str, str]], allocs: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    path = write_samples(tmp_path / "s.jsonl", [header(modules), *allocs, summary()])
    return load_samples(path).sessions[0]


def test_resolution_by_build_id_returns_function_names(tmp_path: Path) -> None:
    session = _session(tmp_path, [module("app", HEX_A, 0x400000)], [alloc(1, 100, [0x401105])])
    resolver = Resolver(SymbolIndex.build(_symbols_dir(tmp_path)), tool="builtin", demangle=False)
    frames = resolver.resolve_all(session, [0x401105, 0x401206])
    assert frames[0x401105][0].function == "leaky_function"
    assert frames[0x401105][0].status == "resolved" and frames[0x401105][0].offset == 0x1105
    assert frames[0x401206][0].function == "_ZN3foo3barEv"  # mangled without c++filt


def test_a_return_address_just_past_a_function_belongs_to_that_function(tmp_path: Path) -> None:
    # The sampled pc is a RETURN address: 0x1180 is the first byte after leaky_function's call.
    session = _session(tmp_path, [module("app", HEX_A, 0)], [alloc(1, 8, [0x1180])])
    resolver = Resolver(SymbolIndex.build(_symbols_dir(tmp_path)), tool="builtin", demangle=False)
    assert resolver.resolve_all(session, [0x1180])[0x1180][0].function == "leaky_function"


def test_wrong_symbols_are_refused_not_used(tmp_path: Path) -> None:
    directory = tmp_path / "symbols"
    directory.mkdir()
    # Same file name as the module but a DIFFERENT build: must not be used.
    build_elf(directory / "app", build_id=BUILD_B, symbols=FUNCS)
    modules = [
        module("app", HEX_A, 0x400000),
        module("nolib", "ab" * 20, 0x500000),
        module("anonymous", "", 0x600000),
    ]
    session = _session(tmp_path, modules, [alloc(1, 8, [0x401105])])
    resolver = Resolver(SymbolIndex.build(directory), tool="builtin")
    out = resolver.resolve_all(session, [0x401105, 0x500123, 0x600123, 0x900000])
    assert out[0x401105][0].status == "build_id_mismatch" and out[0x401105][0].function is None
    assert out[0x500123][0].status == "no_symbols"
    assert out[0x600123][0].status == "unrecorded_build_id"
    assert out[0x900000][0].status == "no_module"
    assert out[0x401105][0].label == "app+0x1105"  # shown as module+offset, never guessed
    assert out[0x900000][0].label == "0x900000"


def test_unreadable_symbol_files_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _symbols_dir(tmp_path)
    session = _session(tmp_path, [module("app", HEX_A, 0x400000)], [alloc(1, 8, [0x401105])])
    index = SymbolIndex.build(directory)
    (directory / "app.debug").write_bytes((directory / "app.debug").read_bytes()[:200])
    resolver = Resolver(index, tool="builtin")
    assert resolver.resolve_all(session, [0x401105])[0x401105][0].status == "unreadable_symbols"


# ---- external tools (fake runner) ----------------------------------------------------------------------
def test_llvm_symbolizer_output_with_inlined_frames() -> None:
    text = (
        "inner_helper\n/src/a.cc:10:5\nleaky_function\n/src/a.cc:42:3\n\n"
        "??\n??:0:0\n\n"
        "plain\n/src/b.cc:7\n\n"
    )
    blocks = _parse_llvm_symbolizer(text, 3)
    assert blocks[0] == [("inner_helper", "/src/a.cc", 10), ("leaky_function", "/src/a.cc", 42)]
    assert blocks[1] == [(None, None, None)]
    assert blocks[2] == [("plain", "/src/b.cc", 7)]


def test_addr2line_output() -> None:
    text = (
        "0x0000000000001105\nleaky_function\n/src/a.cc:42\n"
        "0x0000000000001206\nfoo::bar()\n/src/b.cc:9 (discriminator 3)\nouter()\n/src/b.cc:20\n"
        "0x0000000000001300\n??\n??:0\n"
    )
    blocks = _parse_addr2line(text, 3)
    assert blocks[0] == [("leaky_function", "/src/a.cc", 42)]
    assert blocks[1] == [("foo::bar()", "/src/b.cc", 9), ("outer()", "/src/b.cc", 20)]
    assert blocks[2] == [(None, None, None)]


class FakeTools:
    def __init__(self, stdout: bytes = b"", code: int = 0) -> None:
        self.calls: list[tuple[list[str], bytes]] = []
        self.stdout, self.code = stdout, code

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.available else None

    available: tuple[str, ...] = ("llvm-symbolizer", "c++filt")

    def run(self, argv, stdin):  # type: ignore[no-untyped-def]
        self.calls.append((list(argv), stdin))
        if argv[0].endswith("c++filt"):
            return 0, b"foo::bar()\n", b""
        return self.code, self.stdout, b""


def test_tool_is_run_without_a_shell_on_the_matched_file_only(tmp_path: Path) -> None:
    session = _session(tmp_path, [module("app", HEX_A, 0x400000)], [alloc(1, 8, [0x401105])])
    tools = FakeTools(stdout=b"leaky_function\n/src/a.cc:42:3\n\n")
    resolver = Resolver(
        SymbolIndex.build(_symbols_dir(tmp_path)), runner=tools.run, which=tools.which
    )
    frame = resolver.resolve_all(session, [0x401105])[0x401105][0]
    assert (frame.function, frame.file, frame.line) == ("leaky_function", "/src/a.cc", 42)
    argv, stdin = tools.calls[0]
    assert argv[0] == "/usr/bin/llvm-symbolizer" and argv[1].startswith("--obj=")
    assert argv[1].endswith("app.debug") and "libother" not in argv[1]
    assert stdin == b"0x1104\n"  # return address minus one
    assert resolver.tool_used == "llvm-symbolizer"


def test_tool_failure_falls_back_to_builtin_and_says_so(tmp_path: Path) -> None:
    session = _session(tmp_path, [module("app", HEX_A, 0x400000)], [alloc(1, 8, [0x401105])])
    tools = FakeTools(code=1)
    resolver = Resolver(
        SymbolIndex.build(_symbols_dir(tmp_path)),
        runner=tools.run,
        which=tools.which,
        demangle=False,
    )
    frame = resolver.resolve_all(session, [0x401105])[0x401105][0]
    assert frame.function == "leaky_function" and frame.file is None
    assert any("failed" in note for note in resolver.limitations)


def test_demangling_uses_cxxfilt_when_available_and_reports_when_not(tmp_path: Path) -> None:
    session = _session(tmp_path, [module("app", HEX_A, 0x400000)], [alloc(1, 8, [0x401206])])
    index = SymbolIndex.build(_symbols_dir(tmp_path))
    tools = FakeTools()
    resolver = Resolver(index, tool="builtin", runner=tools.run, which=tools.which)
    assert resolver.resolve_all(session, [0x401206])[0x401206][0].function == "foo::bar()"
    assert tools.calls[0][1] == b"_ZN3foo3barEv\n"

    none = FakeTools()
    none.available = ()
    resolver = Resolver(index, tool="builtin", runner=none.run, which=none.which)
    assert resolver.resolve_all(session, [0x401206])[0x401206][0].function == "_ZN3foo3barEv"
    assert any("mangled" in note for note in resolver.limitations)


def test_requested_tool_must_exist() -> None:
    with pytest.raises(CollectionError, match="not found"):
        Resolver(SymbolIndex(), tool="addr2line", which=lambda _n: None)
    with pytest.raises(CollectionError):
        Resolver(SymbolIndex(), tool="gdb")
    auto = Resolver(SymbolIndex(), tool="auto", which=lambda _n: None)
    assert auto.tool_used == "builtin"


# ---- sample file loading -----------------------------------------------------------------------------------
def test_sessions_are_kept_apart(tmp_path: Path) -> None:
    mods = [module("app", HEX_A, 0x400000)]
    path = write_samples(
        tmp_path / "two.jsonl",
        [
            header(mods), alloc(1, 100, [0x401000]), free(1), summary(final=True),
            header(mods), alloc(1, 200, [0x401000]), summary(final=False),
        ],
    )  # fmt: skip
    loaded = load_samples(path)
    assert [len(s.allocs) for s in loaded.sessions] == [1, 1]
    assert loaded.sessions[0].freed == {1} and loaded.sessions[1].freed == set()
    assert loaded.sessions[0].summary_final and not loaded.sessions[1].summary_final


def test_invalid_lines_are_reported_and_skipped(tmp_path: Path) -> None:
    mods = [module("app", HEX_A, 0x400000)]
    bad_weight = alloc(2, 10, [0x401000])
    bad_weight["weight_count"] = 0.5
    deep = alloc(3, 10, [0x401000 + i for i in range(17)])  # deeper than max_stack_depth 16
    nan_line = json.dumps(alloc(4, 10, [0x401000])).replace(
        '"weight_count": ', '"weight_count": NaN, "x": '
    )
    lines = [
        '{"type":"alloc"}',  # before any header
        header(mods),
        alloc(1, 100, [0x401000]),
        alloc(1, 100, [0x401000]),  # duplicate id
        bad_weight,
        deep,
        nan_line,
        "{broken",
        {"type": "mystery"},
        free(1),
        free(1),
        free(77),
        summary(alloc_requests=-1),
        "",
    ]
    path = write_samples(tmp_path / "bad.jsonl", lines)
    loaded = load_samples(path)
    session = loaded.sessions[0]
    assert [a.id for a in session.allocs] == [1]
    assert (
        session.duplicate_ids == 1 and session.duplicate_frees == 1 and session.unknown_frees == 1
    )
    assert session.summary is None
    assert len(loaded.problems) == 1  # the record before any header
    assert len(session.problems) >= 7  # bad weight, too deep, NaN, broken JSON, unknown type, ...


def test_a_file_without_a_header_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RunDataError):
        load_samples(write_samples(tmp_path / "x.jsonl", [alloc(1, 10, [0x1000])]))
    invalid_header = header([], max_stack_depth=99)
    with pytest.raises(RunDataError):
        load_samples(write_samples(tmp_path / "y.jsonl", [invalid_header]))


def test_modules_records_update_the_map_newest_first(tmp_path: Path) -> None:
    first = [module("app", HEX_A, 0x400000)]
    later = [module("app", HEX_A, 0x400000), module("plugin", HEX_B, 0x700000)]
    path = write_samples(
        tmp_path / "m.jsonl",
        [
            header(first),
            {"type": "modules", "ts_mono_ns": 5, "modules": later},
            alloc(1, 8, [0x700010]),
        ],
    )
    session = load_samples(path).sessions[0]
    located = session.locate(0x700010)
    assert located is not None and located[0].name == "plugin" and located[1] == 0x10
    assert session.locate(0x100) is None
    assert {m.name for m in session.all_modules()} == {"app", "plugin"}
    _ = shutil  # keep import used for platforms where copy helpers are needed later

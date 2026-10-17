"""Offline address-to-symbol resolution, strictly by build identity.

Nothing here runs on a device and nothing is looked up online. A module is resolved only against a
local symbol file whose GNU build-id equals the module's recorded build-id, found by *content*,
never by file name. If the only file with the right name carries a different build-id, the frames
are reported as ``build_id_mismatch`` instead of being resolved to wrong symbols.

Backends, tried in order under ``tool="auto"``: ``llvm-symbolizer`` (function, file, line,
inlined frames), ``addr2line`` (same), then the built-in ELF reader (function names only). A tool
is run with an argument list, never through a shell, on files the user supplied.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from axis_memlab.errors import CollectionError
from axis_memlab.symbolization.elf import ElfError, ElfImage, read_build_id, read_elf
from axis_memlab.symbolization.stackmap import Module, Session

ToolRunner = Callable[[Sequence[str], bytes], tuple[int, bytes, bytes]]

STATUSES = (
    "resolved",
    "no_symbol",
    "no_module",
    "unrecorded_build_id",
    "no_symbols",
    "build_id_mismatch",
    "unreadable_symbols",
)
TOOLS = ("auto", "builtin", "llvm-symbolizer", "addr2line")
_MAX_INDEX_FILES = 8192


@dataclass(frozen=True)
class Frame:
    pc: int
    module: str | None
    function: str | None
    file: str | None
    line: int | None
    status: str
    offset: int | None = None  # address inside the module's file

    @property
    def label(self) -> str:
        if self.function:
            return self.function
        if self.module is not None and self.offset is not None:
            return f"{self.module}+0x{self.offset:x}"
        return f"0x{self.pc:x}"

    def as_dict(self) -> dict[str, object]:
        return {
            "address": f"0x{self.pc:x}",
            "label": self.label,
            "module": self.module,
            "function": self.function,
            "file": self.file,
            "line": self.line,
            "status": self.status,
        }


def default_runner(argv: Sequence[str], stdin: bytes) -> tuple[int, bytes, bytes]:
    try:
        done = subprocess.run(
            list(argv), input=stdin, capture_output=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, b"", str(exc).encode()
    return done.returncode, done.stdout, done.stderr


@dataclass
class SymbolIndex:
    """Local symbol files indexed by the build-id found inside them."""

    by_build_id: dict[str, Path] = field(default_factory=dict)
    by_name: dict[str, list[tuple[Path, str | None]]] = field(default_factory=dict)
    unreadable: int = 0

    @classmethod
    def build(cls, directory: Path) -> SymbolIndex:
        if not directory.is_dir():
            raise CollectionError(f"symbols directory not found: {directory}")
        index = cls()
        seen = 0
        for root, _dirs, files in os.walk(directory, followlinks=False):
            for name in sorted(files):
                path = Path(root) / name
                if path.is_symlink() or not path.is_file():
                    continue
                seen += 1
                if seen > _MAX_INDEX_FILES:
                    raise CollectionError("symbols directory has too many files to index")
                try:
                    with path.open("rb") as stream:
                        if stream.read(4) != b"\x7fELF":
                            continue
                    build_id = read_build_id(path)
                except (ElfError, OSError):
                    index.unreadable += 1
                    continue
                index.by_name.setdefault(name, []).append((path, build_id))
                if build_id and build_id not in index.by_build_id:
                    index.by_build_id[build_id] = path
        return index


def _parse_llvm_symbolizer(
    text: str, count: int
) -> list[list[tuple[str | None, str | None, int | None]]]:
    """Blocks of (function, file, line) per input address; blank line ends a block."""
    blocks: list[list[tuple[str | None, str | None, int | None]]] = []
    current: list[tuple[str | None, str | None, int | None]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line == "":
            blocks.append(current)
            current = []
            i += 1
            continue
        location = lines[i + 1] if i + 1 < len(lines) else ""
        function = None if line.startswith("??") else line
        file_part, line_no = _split_location(location)
        current.append((function, file_part, line_no))
        i += 2
    if current:
        blocks.append(current)
    return (blocks + [[] for _ in range(count)])[:count]


def _split_location(location: str) -> tuple[str | None, int | None]:
    """``file:line[:col]`` (``??:0:0`` for unknown) -> (file, line)."""
    if not location or location.startswith("??"):
        return None, None
    parts = location.rsplit(":", 2)
    numeric = [p for p in parts[1:] if p.isdigit()]
    if len(parts) == 3 and len(numeric) == 2:
        file_part, line = parts[0], int(parts[1])
    elif len(parts) >= 2 and parts[-1].isdigit():
        file_part, line = ":".join(parts[:-1]), int(parts[-1])
    else:
        file_part, line = location, None
    return (file_part if file_part and not file_part.startswith("??") else None), (
        line if line else None
    )


def _parse_addr2line(
    text: str, count: int
) -> list[list[tuple[str | None, str | None, int | None]]]:
    """``addr2line -a -f -C -i`` output: an address line, then function / location pairs."""
    blocks: list[list[tuple[str | None, str | None, int | None]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("0x") and all(c in "0123456789abcdefx" for c in lines[i].lower()):
            blocks.append([])
            i += 1
            continue
        if not blocks:
            i += 1
            continue
        function = None if lines[i].startswith("??") else lines[i]
        location = lines[i + 1] if i + 1 < len(lines) else ""
        file_part, line_no = _split_location(location.split(" (")[0])
        blocks[-1].append((function, file_part, line_no))
        i += 2
    return (blocks + [[] for _ in range(count)])[:count]


class Resolver:
    def __init__(
        self,
        index: SymbolIndex,
        *,
        tool: str = "auto",
        runner: ToolRunner = default_runner,
        which: Callable[[str], str | None] = shutil.which,
        demangle: bool = True,
    ) -> None:
        if tool not in TOOLS:
            raise CollectionError(f"unknown symbolizer tool {tool!r}")
        self._index = index
        self._runner = runner
        self._which = which
        self._demangle = demangle
        self._images: dict[Path, ElfImage | None] = {}
        self._cache: dict[tuple[int, int], list[Frame]] = {}
        self.limitations: list[str] = []
        self.tool_used = "builtin"
        self._tool_path: str | None = None
        if tool in ("auto", "llvm-symbolizer", "addr2line"):
            names = ["llvm-symbolizer", "addr2line"] if tool == "auto" else [tool]
            for name in names:
                found = which(name)
                if found:
                    self._tool_path, self.tool_used = found, name
                    break
            if self._tool_path is None and tool != "auto":
                raise CollectionError(f"requested tool {tool!r} was not found on PATH")

    # ---- module -> symbol file ------------------------------------------------------------
    def _symbol_file(self, module: Module) -> tuple[Path | None, str]:
        if not module.build_id:
            return None, "unrecorded_build_id"
        path = self._index.by_build_id.get(module.build_id)
        if path is not None:
            return path, "ok"
        for _path, found_id in self._index.by_name.get(module.name, []):
            if found_id != module.build_id:
                return None, "build_id_mismatch"
        return None, "no_symbols"

    def _image(self, path: Path) -> ElfImage | None:
        if path not in self._images:
            try:
                self._images[path] = read_elf(path)
            except ElfError:
                self._images[path] = None
        return self._images[path]

    # ---- batch resolution -------------------------------------------------------------------
    def resolve_all(self, session: Session, pcs: Iterable[int]) -> dict[int, list[Frame]]:
        unique = sorted(set(pcs))
        pending: dict[Path, list[tuple[int, int, str]]] = {}
        out: dict[int, list[Frame]] = {}
        for pc in unique:
            cached = self._cache.get((session.index, pc))
            if cached is not None:
                out[pc] = cached
                continue
            located = session.locate(pc)
            if located is None:
                out[pc] = [Frame(pc, None, None, None, None, "no_module")]
                continue
            module, address = located
            path, state = self._symbol_file(module)
            if path is None:
                out[pc] = [Frame(pc, module.name, None, None, None, state, address)]
                continue
            pending.setdefault(path, []).append((pc, address, module.name))
        for path, items in pending.items():
            image = self._image(path)
            if image is None:
                for pc, address, name in items:
                    out[pc] = [Frame(pc, name, None, None, None, "unreadable_symbols", address)]
                continue
            lookups = {pc: max(address - 1, 0) for pc, address, _ in items}
            detailed = (
                self._run_tool(path, sorted(set(lookups.values()))) if self._tool_path else {}
            )
            for pc, address, name in items:
                lookup = lookups[pc]
                frames = detailed.get(lookup)
                if frames:
                    out[pc] = [
                        Frame(pc, name, f, fl, ln, "resolved", address) for f, fl, ln in frames
                    ]
                    continue
                hit = image.lookup(lookup)
                if hit is None:
                    out[pc] = [Frame(pc, name, None, None, None, "no_symbol", address)]
                else:
                    out[pc] = [Frame(pc, name, hit[0], None, None, "resolved", address)]
        out = self._demangled(out)
        for pc, resolved in out.items():
            self._cache[(session.index, pc)] = resolved
        return out

    def _run_tool(
        self, path: Path, addresses: list[int]
    ) -> dict[int, list[tuple[str | None, str | None, int | None]]]:
        assert self._tool_path is not None
        stdin = "".join(f"0x{a:x}\n" for a in addresses).encode()
        if self.tool_used == "llvm-symbolizer":
            argv = [self._tool_path, f"--obj={path.resolve()}", "--demangle", "--inlining"]
            parse = _parse_llvm_symbolizer
        else:
            argv = [self._tool_path, "-e", str(path.resolve()), "-f", "-C", "-i", "-a"]
            parse = _parse_addr2line
        code, stdout, _stderr = self._runner(argv, stdin)
        if code != 0:
            self.limitations.append(
                f"{self.tool_used} failed on {path.name} (exit {code}); function names come from "
                "the built-in reader without file and line"
            )
            return {}
        blocks = parse(stdout.decode("utf-8", errors="replace"), len(addresses))
        return {
            address: [t for t in block if t[0] is not None or t[1] is not None]
            for address, block in zip(addresses, blocks, strict=True)
        }

    def _demangled(self, frames_by_pc: dict[int, list[Frame]]) -> dict[int, list[Frame]]:
        if not self._demangle:
            return frames_by_pc
        names = sorted(
            {
                f.function
                for fs in frames_by_pc.values()
                for f in fs
                if f.function and f.function.startswith("_Z")
            }
        )
        if not names:
            return frames_by_pc
        tool = self._which("c++filt")
        if tool is None:
            note = "names are mangled: c++filt was not found on PATH"
            if note not in self.limitations:
                self.limitations.append(note)
            return frames_by_pc
        code, stdout, _ = self._runner([tool], ("\n".join(names) + "\n").encode())
        decoded = stdout.decode("utf-8", errors="replace").splitlines()
        if code != 0 or len(decoded) != len(names):
            self.limitations.append("c++filt failed; names are left mangled")
            return frames_by_pc
        mapping = dict(zip(names, decoded, strict=True))
        return {
            pc: [
                Frame(
                    f.pc,
                    f.module,
                    mapping.get(f.function or "", f.function),
                    f.file,
                    f.line,
                    f.status,
                    f.offset,
                )
                for f in fs
            ]
            for pc, fs in frames_by_pc.items()
        }

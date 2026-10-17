"""Minimal, defensive ELF reader: build identity and function symbols.

Only what offline symbolization needs: the GNU build-id (the identity check that decides whether
a symbol file may be used for a module) and the function symbols of ``.symtab`` / ``.dynsym``.
Little-endian ELF32 and ELF64 are supported (ARM and AArch64 and x86 cameras and workstations).
Every offset and size is checked against the file before use, input size is capped, and the file
is only ever read, never executed.
"""

from __future__ import annotations

import bisect
import struct
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_SYMBOLS = 4_000_000
MAX_SECTIONS = 4096

_PT_NOTE = 4
_SHT_SYMTAB = 2
_SHT_DYNSYM = 11
_SHT_NOTE = 7
_STT_FUNC = 2
_STT_GNU_IFUNC = 10
_NT_GNU_BUILD_ID = 3
_EM_ARM = 40
_MAX_UNSIZED_OFFSET = 4096


class ElfError(ValueError):
    """The file is not an ELF image this reader can use."""


@dataclass(frozen=True)
class Symbol:
    address: int
    size: int
    name: str


@dataclass
class ElfImage:
    path: Path
    bits: int
    machine: int
    build_id: str | None
    symbols: list[Symbol]  # sorted by address
    _starts: list[int]

    def lookup(self, address: int) -> tuple[str, int] | None:
        """Function containing ``address`` (a file/virtual address) and the offset into it."""
        index = bisect.bisect_right(self._starts, address) - 1
        if index < 0:
            return None
        symbol = self.symbols[index]
        offset = address - symbol.address
        if symbol.size > 0:
            return (symbol.name, offset) if offset < symbol.size else None
        # Unsized symbols (assembly stubs): accept only a short distance and only before the
        # next symbol, which the bisect already guarantees.
        return (symbol.name, offset) if offset < _MAX_UNSIZED_OFFSET else None


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def take(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise ElfError("offset outside the file (truncated or corrupt ELF)")
        return self.data[offset : offset + size]

    def unpack(self, fmt: str, offset: int) -> tuple[int, ...]:
        return struct.unpack(fmt, self.take(offset, struct.calcsize(fmt)))


def _cstring(blob: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(blob):
        return ""
    end = blob.find(b"\0", offset)
    end = len(blob) if end < 0 else end
    return blob[offset:end].decode("utf-8", errors="replace")


def _parse_notes(blob: bytes) -> str | None:
    position = 0
    while position + 12 <= len(blob):
        namesz, descsz, kind = struct.unpack_from("<III", blob, position)
        name_end = position + 12 + ((namesz + 3) & ~3)
        desc_end = name_end + ((descsz + 3) & ~3)
        if desc_end > len(blob):
            break
        name = blob[position + 12 : position + 12 + namesz].rstrip(b"\0")
        if kind == _NT_GNU_BUILD_ID and name == b"GNU" and 0 < descsz <= 64:
            return blob[name_end : name_end + descsz].hex()
        position = desc_end
    return None


def read_build_id(path: Path) -> str | None:
    """Build-id of an ELF file, or ``None`` if it has none. Raises ``ElfError`` if not ELF."""
    image = _load(path, with_symbols=False)
    return image.build_id


def read_elf(path: Path) -> ElfImage:
    return _load(path, with_symbols=True)


def _load(path: Path, *, with_symbols: bool) -> ElfImage:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ElfError(f"cannot read {path.name}: {exc.strerror}") from None
    if size > MAX_FILE_BYTES:
        raise ElfError(f"{path.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ElfError(f"cannot read {path.name}: {exc.strerror}") from None
    try:
        return _parse(path, _Reader(data), with_symbols)
    except (struct.error, IndexError, OverflowError) as exc:
        raise ElfError(f"{path.name} is corrupt or truncated: {exc}") from None


def _parse(path: Path, r: _Reader, with_symbols: bool) -> ElfImage:
    ident = r.take(0, 16)
    if ident[:4] != b"\x7fELF":
        raise ElfError(f"{path.name} is not an ELF file")
    if ident[4] not in (1, 2):
        raise ElfError("unknown ELF class")
    if ident[5] != 1:
        raise ElfError("big-endian ELF is not supported")
    bits = 32 if ident[4] == 1 else 64
    if bits == 64:
        (_, machine, _, _, phoff, shoff, _, _, phentsize, phnum, shentsize, shnum, shstrndx) = (
            r.unpack("<HHIQQQIHHHHHH", 16)
        )
    else:
        (_, machine, _, _, phoff, shoff, _, _, phentsize, phnum, shentsize, shnum, shstrndx) = (
            r.unpack("<HHIIIIIHHHHHH", 16)
        )
    if shnum > MAX_SECTIONS or phnum > MAX_SECTIONS:
        raise ElfError("implausible number of ELF headers")

    build_id: str | None = None
    # Program headers: PT_NOTE segments (present even in section-stripped files).
    for i in range(phnum):
        base = phoff + i * phentsize
        if bits == 64:
            p_type, _, p_offset, _, _, p_filesz, _, _ = r.unpack("<IIQQQQQQ", base)
        else:
            p_type, p_offset, _, _, p_filesz, _, _, _ = r.unpack("<IIIIIIII", base)
        if p_type == _PT_NOTE and build_id is None:
            build_id = _parse_notes(r.take(p_offset, p_filesz))

    # Section headers: notes, symbol tables, string tables.
    sections: list[
        tuple[int, int, int, int, int, int]
    ] = []  # type, name, offset, size, link, entsize
    for i in range(shnum):
        base = shoff + i * shentsize
        if bits == 64:
            sh_name, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = r.unpack(
                "<IIQQQQIIQQ", base
            )
        else:
            sh_name, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = r.unpack(
                "<IIIIIIIIII", base
            )
        sections.append((sh_type, sh_name, sh_offset, sh_size, sh_link, sh_entsize))

    if build_id is None:
        for sh_type, _, offset, sz, _, _ in sections:
            if sh_type == _SHT_NOTE:
                build_id = _parse_notes(r.take(offset, sz))
                if build_id:
                    break

    symbols: list[Symbol] = []
    if with_symbols:
        for sh_type, _, offset, sz, link, entsize in sections:
            if sh_type not in (_SHT_SYMTAB, _SHT_DYNSYM):
                continue
            if link >= len(sections):
                raise ElfError("symbol table points at a missing string table")
            _, _, str_off, str_size, _, _ = sections[link]
            strtab = r.take(str_off, str_size)
            width = 24 if bits == 64 else 16
            count = sz // (entsize or width)
            if count > MAX_SYMBOLS:
                raise ElfError("implausible number of symbols")
            table = r.take(offset, count * (entsize or width))
            for k in range(count):
                if bits == 64:
                    st_name, st_info, _, st_shndx, st_value, st_size = struct.unpack_from(
                        "<IBBHQQ", table, k * (entsize or width)
                    )
                else:
                    st_name, st_value, st_size, st_info, _, st_shndx = struct.unpack_from(
                        "<IIIBBH", table, k * (entsize or width)
                    )
                kind = st_info & 0xF
                if kind not in (_STT_FUNC, _STT_GNU_IFUNC) or st_shndx == 0 or st_value == 0:
                    continue
                if machine == _EM_ARM:
                    st_value &= ~1  # Thumb functions carry the mode in bit 0
                name = _cstring(strtab, st_name)
                if name:
                    symbols.append(Symbol(st_value, st_size, name))
        # Prefer the full symbol table's entries when both tables define the same address.
        symbols.sort(key=lambda s: (s.address, -s.size))
        unique: list[Symbol] = []
        for symbol in symbols:
            if unique and unique[-1].address == symbol.address:
                continue
            unique.append(symbol)
        symbols = unique
    return ElfImage(
        path=path,
        bits=bits,
        machine=machine,
        build_id=build_id,
        symbols=symbols,
        _starts=[s.address for s in symbols],
    )

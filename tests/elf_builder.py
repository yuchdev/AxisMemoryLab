"""Builds tiny synthetic little-endian ELF files for symbolization tests (no compiler needed)."""

from __future__ import annotations

import struct
from pathlib import Path

EM_X86_64 = 62
EM_ARM = 40
EM_AARCH64 = 183


def _note(build_id: bytes) -> bytes:
    desc = build_id + b"\0" * ((4 - len(build_id) % 4) % 4)
    return struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + desc


def build_elf(
    path: Path,
    *,
    build_id: bytes | None,
    symbols: list[tuple[str, int, int]] | None = None,
    bits: int = 64,
    machine: int = EM_X86_64,
    note_segment: bool = True,
    note_section: bool = True,
    symbol_type: int = 2,  # STT_FUNC
    shndx: int = 1,
) -> Path:
    """Write an ELF with an optional build-id note and a ``.symtab`` of the given symbols."""
    symbols = symbols or []
    is64 = bits == 64
    ehsize, phentsize, shentsize = (64, 56, 64) if is64 else (52, 32, 40)

    note = _note(build_id) if build_id is not None else b""
    names = b"\0"
    name_offsets = []
    for name, _, _ in symbols:
        name_offsets.append(len(names))
        names += name.encode() + b"\0"

    sym_size = 24 if is64 else 16
    symtab = b"\0" * sym_size
    for (_, addr, size), name_off in zip(symbols, name_offsets, strict=True):
        info = (1 << 4) | symbol_type
        if is64:
            symtab += struct.pack("<IBBHQQ", name_off, info, 0, shndx, addr, size)
        else:
            symtab += struct.pack("<IIIBBH", name_off, addr, size, info, 0, shndx)

    shstr = b"\0.note.gnu.build-id\0.symtab\0.strtab\0.shstrtab\0"
    n_note = shstr.index(b".note.gnu.build-id")
    n_symtab = shstr.index(b".symtab")
    n_strtab = shstr.index(b".strtab")
    n_shstrtab = shstr.index(b".shstrtab")

    phnum = 1 if (note_segment and note) else 0
    offset = ehsize + phnum * phentsize
    note_off = offset
    offset += len(note)
    str_off = offset
    offset += len(names)
    sym_off = offset
    offset += len(symtab)
    shstr_off = offset
    offset += len(shstr)
    shoff = (offset + 7) & ~7

    sections = [(0, 0, 0, 0, 0, 0, 0)]  # name, type, offset, size, link, entsize
    if note_section and note:
        sections.append((n_note, 7, note_off, len(note), 0, 0, 0))
    symtab_index = len(sections)
    sections.append((n_symtab, 2, sym_off, len(symtab), symtab_index + 1, sym_size, 0))
    sections.append((n_strtab, 3, str_off, len(names), 0, 0, 0))
    sections.append((n_shstrtab, 3, shstr_off, len(shstr), 0, 0, 0))
    shstrndx = len(sections) - 1

    out = bytearray()
    ident = b"\x7fELF" + bytes([2 if is64 else 1, 1, 1, 0]) + b"\0" * 8
    if is64:
        out += ident + struct.pack(
            "<HHIQQQIHHHHHH", 3, machine, 1, 0, ehsize if phnum else 0, shoff, 0, ehsize,
            phentsize, phnum, shentsize, len(sections), shstrndx,
        )  # fmt: skip
    else:
        out += ident + struct.pack(
            "<HHIIIIIHHHHHH", 3, machine, 1, 0, ehsize if phnum else 0, shoff, 0, ehsize,
            phentsize, phnum, shentsize, len(sections), shstrndx,
        )  # fmt: skip
    if phnum:
        if is64:
            out += struct.pack("<IIQQQQQQ", 4, 4, note_off, 0, 0, len(note), len(note), 4)
        else:
            out += struct.pack("<IIIIIIII", 4, note_off, 0, 0, len(note), len(note), 4, 4)
    out += note + names + symtab + shstr
    out += b"\0" * (shoff - len(out))
    for name, kind, off, size, link, entsize, _ in sections:
        if is64:
            out += struct.pack("<IIQQQQIIQQ", name, kind, 0, 0, off, size, link, 0, 8, entsize)
        else:
            out += struct.pack("<IIIIIIIIII", name, kind, 0, 0, off, size, link, 0, 4, entsize)
    path.write_bytes(bytes(out))
    return path

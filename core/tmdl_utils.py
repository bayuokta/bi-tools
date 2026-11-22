"""Utilitas teks TMDL/TMSL untuk compare.

Modul ini tidak memuat TOM dan tidak memahami properti model. Fungsinya hanya
membuang blok anak dari definisi yang sudah diserialisasi TOM (mis. measure dari
definisi table) serta menormalkan line ending/trailing whitespace sebelum
dibandingkan.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


def normalize_definition(text: str) -> str:
    """Normalisasi line ending dan trailing whitespace tanpa mengubah isi."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def remove_blocks(text: str, keyword: str, *, min_level: int = 1) -> str:
    """Buang blok TMDL yang baris pertamanya diawali ``keyword``.

    ``keyword`` dicocokkan pada baris yang sudah di-strip; blok berakhir ketika
    ada baris non-kosong dengan indentasi <= indentasi baris pembuka.
    """
    lines = (text or "").splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if _indent(line) >= min_level and stripped.startswith(keyword):
            level = _indent(line)
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate.strip() and _indent(candidate) <= level:
                    break
                index += 1
            # Jangan menyisakan baris kosong ganda di tempat blok dihapus.
            while output and not output[-1].strip():
                output.pop()
            continue
        output.append(line)
        index += 1
    return "\n".join(output)


def remove_properties(text: str, prefixes: Iterable[str]) -> str:
    """Buang properti TMDL (dan isi multi-barisnya) berdasarkan prefix."""
    prefix_tuple = tuple(prefixes)
    if not prefix_tuple:
        return text
    lines = (text or "").splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(prefix_tuple):
            level = _indent(line)
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate.strip() and _indent(candidate) <= level:
                    break
                index += 1
            continue
        output.append(line)
        index += 1
    return "\n".join(output)


def _clean_json_value(
    value: Any, *, annotations: bool, lineage_tag: bool
) -> Any:
    if isinstance(value, dict):
        cleaned = {
            key: _clean_json_value(item, annotations=annotations, lineage_tag=lineage_tag)
            for key, item in value.items()
        }
        if not annotations:
            cleaned.pop("annotations", None)
        if not lineage_tag:
            cleaned.pop("lineageTag", None)
        return cleaned
    if isinstance(value, list):
        return [
            _clean_json_value(item, annotations=annotations, lineage_tag=lineage_tag)
            for item in value
        ]
    return value


def _is_json_definition(text: str) -> bool:
    return (text or "").lstrip().startswith("{")


def clean_object_definition(
    text: str,
    *,
    annotations: bool,
    lineage_tag: bool,
    tmsl: bool = False,
) -> str:
    """Bersihkan annotation/lineage dari definisi TMDL atau TMSL."""
    value = text or ""
    if tmsl or _is_json_definition(value):
        try:
            data = json.loads(value)
        except ValueError:
            data = None
        if data is not None:
            cleaned = _clean_json_value(
                data, annotations=annotations, lineage_tag=lineage_tag
            )
            return normalize_definition(
                json.dumps(cleaned, ensure_ascii=False, indent=2)
            )
    if not annotations:
        value = remove_properties(value, ("annotation ",))
    if not lineage_tag:
        value = remove_properties(value, ("lineageTag:",))
    return normalize_definition(value)


def table_definition(
    text: str,
    *,
    partitions: bool,
    annotations: bool,
    lineage_tag: bool,
    calculation_group: bool = False,
    tmsl: bool = False,
) -> str:
    """Definisi table tanpa measure; partition/calc item sesuai opsi."""
    value = text or ""
    if tmsl or _is_json_definition(value):
        try:
            data = json.loads(value)
        except ValueError:
            data = None
        if isinstance(data, dict):
            data.pop("measures", None)
            if not partitions:
                data.pop("partitions", None)
            if calculation_group:
                data.pop("calculationItems", None)
            cleaned = _clean_json_value(
                data, annotations=annotations, lineage_tag=lineage_tag
            )
            return normalize_definition(
                json.dumps(cleaned, ensure_ascii=False, indent=2)
            )
    value = remove_blocks(value, "measure ", min_level=1)
    if not partitions:
        value = remove_blocks(value, "partition ", min_level=1)
    if calculation_group:
        value = remove_blocks(value, "calculationItem ", min_level=2)
    value = clean_object_definition(
        value, annotations=annotations, lineage_tag=lineage_tag, tmsl=tmsl
    )
    return value

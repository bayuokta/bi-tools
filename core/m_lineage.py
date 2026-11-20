"""
Parser lineage kolom dari query M (Power Query) secara deterministik.

Modul ini membaca teks M sebuah partisi, mensimulasikan langkah-langkah
`let ... in` dari sumber sampai tabel akhir, lalu memetakan setiap kolom
akhir ke kolom asli di sumbernya.

Yang ditangani:
  - navigasi sumber: Sql.Database + {[Schema, Item]}, dataflow {[entity]},
    tabel inline (Table.FromRows / #table)
  - Table.SelectColumns, Table.RemoveColumns
  - Table.RenameColumns (termasuk rename berantai)
  - Table.DuplicateColumn
  - Table.AddColumn, Table.AddIndexColumn, Table.Group, Table.CombineColumns,
    Table.UnpivotOtherColumns, Table.ExpandTableColumn
  - fungsi yang tidak mengubah nama kolom (SelectRows, TransformColumnTypes, ...)
  - rename dinamis (Table.TransformColumnNames) -> unresolved
  - rename kolom yang tidak ada -> orphan_rename
  - rename ke nama yang sudah ada -> rename_conflict

Tidak ada AI/tebakan: kasus yang tidak bisa dipastikan ditandai `unresolved`
beserta alasannya.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Struktur hasil
# ---------------------------------------------------------------------------
@dataclass
class StepLink:
    """Satu langkah M yang membentuk/mengubah kolom (untuk graph lineage)."""

    step: str
    function: str
    column: str
    from_column: str = ""


@dataclass
class ColumnLineage:
    """Lineage satu kolom hasil akhir M."""

    name: str = ""
    source_column: str = ""
    source_object: str = ""
    origin: str = ""
    status: str = "unresolved"
    confidence: str = "low"
    chain: list[str] = field(default_factory=list)
    columns_used: list[str] = field(default_factory=list)
    step: str = ""
    detail: str = ""
    logic: str = ""
    steps: list[StepLink] = field(default_factory=list)

    def chain_text(self) -> str:
        return " -> ".join(self.chain) if self.chain else ""

    def used_text(self) -> str:
        return ", ".join(self.columns_used)


@dataclass
class Warning:
    """Satu peringatan lineage (dipakai sheet 25_M_Lineage_Warnings)."""

    step: str
    column: str
    status: str
    detail: str


@dataclass
class LineageResult:
    columns: dict[str, ColumnLineage] = field(default_factory=dict)
    warnings: list[Warning] = field(default_factory=list)
    origin: str = ""
    source_object: str = ""
    columns_known: bool = False


@dataclass
class State:
    """Kondisi tabel pada satu titik simulasi."""

    columns: dict[str, ColumnLineage] = field(default_factory=dict)
    origin: str = ""
    source_object: str = ""
    columns_known: bool = False
    is_table: bool = False

    def clone(self) -> "State":
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Scanner M: komentar, string, dan pemisahan top-level
# ---------------------------------------------------------------------------
def strip_comments(text: str) -> str:
    """Buang komentar `//` dan `/* */` tanpa menyentuh isi string."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        out.append(text[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _skip_string(text: str, i: int) -> int:
    """i menunjuk tanda kutip pembuka; kembalikan indeks setelah kutip penutup."""
    n = len(text)
    i += 1
    while i < n:
        if text[i] == '"':
            if i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return n


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """Pisah teks pada `sep` level teratas (abaikan string & bracket)."""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            end = _skip_string(text, i)
            buffer.append(text[i:end])
            i = end
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(ch)
        i += 1
    parts.append("".join(buffer))
    return [part.strip() for part in parts if part.strip()]


def _strip_outer(text: str) -> str:
    """Hapus kurung pembungkus berlebih: ((expr)) -> expr."""
    value = text.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        balanced = True
        i = 0
        while i < len(value):
            ch = value[i]
            if ch == '"':
                i = _skip_string(value, i)
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(value) - 1:
                    balanced = False
                    break
            i += 1
        if not balanced:
            break
        value = value[1:-1].strip()
    return value


def _match_bracket(text: str, start: int, open_ch: str = "(", close_ch: str = ")") -> int:
    """Kembalikan indeks penutup yang cocok, atau -1."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i = _skip_string(text, i)
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_word(text: str, word: str, start: int = 0) -> int:
    """Cari kata kunci pada depth 0 (bukan di dalam string/bracket)."""
    i = start
    n = len(text)
    depth = 0
    while i < n:
        ch = text[i]
        if ch == '"':
            i = _skip_string(text, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and text.startswith(word, i):
            before = text[i - 1] if i > 0 else " "
            after = text[i + len(word)] if i + len(word) < n else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return -1


def _find_matching_in(text: str, start: int) -> int:
    """Cari `in` yang menutup `let` luar (memperhitungkan let bersarang)."""
    i = start
    n = len(text)
    depth = 0
    let_depth = 0
    while i < n:
        ch = text[i]
        if ch == '"':
            i = _skip_string(text, i)
            continue
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth -= 1
            i += 1
            continue
        if depth == 0 and text.startswith("let", i) and not (
            (text[i - 1].isalnum() if i > 0 else False) or text[i + 3 : i + 4].isalnum()
        ):
            let_depth += 1
            i += 3
            continue
        if depth == 0 and text.startswith("in", i) and not (
            (text[i - 1].isalnum() if i > 0 else False) or text[i + 2 : i + 3].isalnum()
        ):
            if let_depth == 0:
                return i
            let_depth -= 1
            i += 2
            continue
        i += 1
    return -1


# ---------------------------------------------------------------------------
# Identifier & literal
# ---------------------------------------------------------------------------
def unquote(name: str) -> str:
    value = name.strip()
    if value.startswith('#"') and value.endswith('"') and len(value) >= 3:
        return value[2:-1].replace('""', '"')
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return value[1:-1].replace('""', '"')
    return value


def _is_identifier(value: str) -> bool:
    return bool(
        re.fullmatch(
            r'#"(?:[^"]|"")*"|"(?:[^"]|"")*"|[A-Za-z_][\w.]*',
            value.strip(),
        )
    )


def _parse_name(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.startswith('#"') or value.startswith('"'):
        if value.endswith('"'):
            return unquote(value)
        return None
    if re.fullmatch(r"[A-Za-z_][\w.]*", value):
        return value
    return None


def _parse_string_list(expr: str) -> list[str] | None:
    value = _strip_outer(expr.strip())
    if not (value.startswith("{") and value.endswith("}")):
        return None
    inner = value[1:-1].strip()
    if not inner:
        return []
    items = split_top_level(inner)
    names: list[str] = []
    for item in items:
        name = _parse_name(item)
        if name is None:
            return None
        names.append(name)
    return names


def _parse_pairs(expr: str) -> list[tuple[str, str]] | None:
    value = _strip_outer(expr.strip())
    if not (value.startswith("{") and value.endswith("}")):
        return None
    items = split_top_level(value[1:-1])
    pairs: list[tuple[str, str]] = []
    for item in items:
        pair = _strip_outer(item.strip())
        if not (pair.startswith("{") and pair.endswith("}")):
            return None
        parts = split_top_level(pair[1:-1])
        if len(parts) != 2:
            return None
        old = _parse_name(parts[0])
        new = _parse_name(parts[1])
        if old is None or new is None:
            return None
        pairs.append((old, new))
    return pairs


def _parse_transform_columns(expr: str) -> list[str] | None:
    """Ambil nama kolom dari daftar `Table.TransformColumns` (elemen pertama)."""
    value = _strip_outer(expr.strip())
    if not (value.startswith("{") and value.endswith("}")):
        return None
    items = split_top_level(value[1:-1])
    names: list[str] = []
    for item in items:
        pair = _strip_outer(item.strip())
        if pair.startswith("{") and pair.endswith("}"):
            parts = split_top_level(pair[1:-1])
        else:
            parts = split_top_level(item)
        if not parts:
            return None
        name = _parse_name(parts[0])
        if name is None:
            return None
        names.append(name)
    return names


def _parse_type_table(expr: str) -> list[str] | None:
    """Ambil nama kolom dari `type table [a = _t, b = _t]`."""
    match = re.search(r"\btype\s+table\s*\[", expr)
    if not match:
        return None
    start = expr.find("[", match.start())
    end = _match_bracket(expr, start, "[", "]")
    if end == -1:
        return None
    inner = expr[start + 1 : end]
    names: list[str] = []
    for item in split_top_level(inner):
        text = item.strip()
        if text.startswith("optional "):
            text = text[len("optional ") :].strip()
        parts = split_top_level(text, "=")
        name = _parse_name(parts[0]) if parts else None
        if name is None:
            return None
        names.append(name)
    return names


def _extract_refs(expr: str) -> list[str]:
    """Ambil referensi kolom `[Nama Kolom]` dari sebuah ekspresi M."""
    refs: list[str] = []
    for match in re.finditer(r"\[([^\[\]]+)\]", expr):
        name = unquote(match.group(1).strip())
        if name and name not in refs:
            refs.append(name)
    return refs


# ---------------------------------------------------------------------------
# Struktur M: let, function call, navigasi
# ---------------------------------------------------------------------------
def parse_let(text: str) -> tuple[list[tuple[str, str]], str]:
    """Pecah `let ... in ...` menjadi daftar (nama_step, ekspresi) + hasil."""
    clean = strip_comments(text).strip()
    let_pos = _find_word(clean, "let")
    if let_pos == -1:
        return [], clean
    in_pos = _find_matching_in(clean, let_pos + 3)
    if in_pos == -1:
        return [], clean
    body = clean[let_pos + 3 : in_pos]
    result = clean[in_pos + 2 :].strip()
    steps: list[tuple[str, str]] = []
    for chunk in split_top_level(body):
        match = re.match(
            r'^(#"(?:[^"]|"")*"|"(?:[^"]|"")*"|[A-Za-z_][\w.]*)\s*=\s*(.*)$',
            chunk,
            re.S,
        )
        if not match:
            continue
        steps.append((unquote(match.group(1)), match.group(2).strip()))
    return steps, result


def parse_function_call(expr: str) -> tuple[str, list[str]] | None:
    """Kenali `Nama.Fungsi(arg1, arg2, ...)` dan kembalikan argumennya."""
    value = _strip_outer(expr.strip())
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == '"':
            i = _skip_string(value, i)
            continue
        if ch == "(":
            name = value[:i].strip()
            if not re.fullmatch(r"#?[A-Za-z_][\w.]*", name):
                return None
            end = _match_bracket(value, i)
            if end != n - 1:
                return None
            return name, split_top_level(value[i + 1 : end])
        if ch in "[{":
            return None
        i += 1
    return None


def parse_navigation(expr: str) -> tuple[str, dict[str, str]] | None:
    """Kenali `Base{[Key=Value,...]}[Data]` dan kembalikan base + key/value."""
    value = _strip_outer(expr.strip())
    if not value.endswith("[Data]"):
        return None
    close = value.rfind("}")
    if close == -1 or value[close + 1 :].strip() != "[Data]":
        return None
    # Cari pasangan '{' terakhir sebelum '}'.
    depth = 0
    open_pos = -1
    i = 0
    while i <= close:
        ch = value[i]
        if ch == '"':
            i = _skip_string(value, i)
            continue
        if ch == "{":
            if depth == 0:
                open_pos = i
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if open_pos == -1:
        return None
    inner = value[open_pos + 1 : close].strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        return None
    key_values: dict[str, str] = {}
    for part in split_top_level(inner[1:-1]):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key_values[key.strip()] = unquote(val.strip())
    return value[:open_pos].strip(), key_values


# ---------------------------------------------------------------------------
# Simulasi state
# ---------------------------------------------------------------------------
_PASSTHROUGH = {
    "table.selectrows",
    "table.transformcolumntypes",
    "table.sort",
    "table.buffer",
    "table.firstn",
    "table.lastn",
    "table.distinct",
    "table.reordercolumns",
    "table.removealternaterows",
    "table.range",
    "table.skip",
    "table.reverse",
    "table.changetype",
    "table.replacevalue",
    "table.replaceregex",
    "table.filldown",
    "table.fillup",
    "table.addkey",
    "table.nestedjoin",
    "table.fuzzynestedjoin",
    "table.profiling",
    "table.stop",
}


def _confidence_for(origin: str) -> str:
    if origin in {"sql", "dataflow", "table", "file", "odata", "sharepoint", "inline"}:
        return "high"
    return "medium"


def _record_step(
    column: ColumnLineage,
    step: str,
    function: str,
    name: str,
    from_name: str = "",
) -> None:
    """Catat satu langkah M pada kolom tanpa menduplikasi langkah yang sama."""
    if column.steps:
        last = column.steps[-1]
        if last.step == step and last.column == name:
            return
    column.steps.append(
        StepLink(step=step, function=function, column=name, from_column=from_name)
    )


def _ensure_column(state: State, name: str, step: str, warnings: list[Warning]) -> ColumnLineage:
    """Ambil kolom; bila belum ada, buat sebagai kolom langsung dari sumber."""
    if name in state.columns:
        return state.columns[name]
    column = ColumnLineage(
        name=name,
        source_column=name,
        source_object=state.source_object,
        origin=state.origin or "unknown",
        status="direct",
        confidence=_confidence_for(state.origin),
        chain=[name],
        step=step,
        steps=[StepLink(step=step, function="", column=name)],
    )
    if state.columns_known:
        column.status = "orphan_rename"
        column.confidence = "low"
        column.detail = f"Kolom '{name}' tidak ada pada langkah sebelumnya."
        warnings.append(Warning(step, name, "orphan_rename", column.detail))
    state.columns[name] = column
    return column


def _mark_all(state: State, status: str, confidence: str, detail: str, step: str, warnings: list[Warning]) -> None:
    for column in state.columns.values():
        column.status = status
        column.confidence = confidence
        column.detail = detail
        column.step = step
        warnings.append(Warning(step, column.name, status, detail))


def _derived_column(
    state: State,
    name: str,
    refs: list[str],
    step: str,
    detail: str = "",
    logic: str = "",
    function: str = "",
) -> ColumnLineage:
    used: list[str] = []
    for ref in refs:
        existing = state.columns.get(ref)
        if existing is not None:
            used.append(existing.source_column or ref)
        else:
            used.append(ref)
    return ColumnLineage(
        name=name,
        source_column="",
        source_object=state.source_object,
        origin="derived",
        status="derived",
        confidence="high" if refs else "medium",
        chain=[name],
        columns_used=used,
        step=step,
        detail=detail,
        logic=logic,
        steps=[StepLink(step=step, function=function, column=name)],
    )


def _apply_function(
    name: str,
    args: list[str],
    expr: str,
    states: dict[str, State],
    step: str,
    warnings: list[Warning],
) -> State:
    lowered = name.lower()

    if lowered in {"sql.database", "sql.databases"}:
        return State(origin="sql", is_table=False)
    if lowered == "powerplatform.dataflows":
        return State(origin="dataflow", is_table=False)
    if lowered in {"odata.feed"}:
        return State(origin="odata", is_table=False)
    if lowered in {"sharepoint.tables", "sharepoint.files"}:
        return State(origin="sharepoint", is_table=False)
    if lowered in {"excel.workbook", "csv.document", "json.document", "xml.tables", "folder.files", "file.contents", "web.contents"}:
        base = _evaluate(args[0], states, step, warnings) if args else State()
        base.is_table = lowered in {"excel.workbook"}
        if not base.origin:
            base.origin = "file"
        return base
    if lowered in {"binary.decompress", "binary.fromtext", "text.frombinary"}:
        return _evaluate(args[0], states, step, warnings) if args else State(is_table=False)

    if lowered == "table.fromrows":
        state = State(origin="inline", source_object="inline", is_table=True, columns_known=True)
        columns = _parse_type_table(expr)
        if columns is None and len(args) >= 2:
            columns = _parse_type_table(args[1])
        if columns is None:
            warnings.append(
                Warning(step, "", "unresolved", "Table.FromRows tanpa definisi kolom yang bisa dibaca.")
            )
            state.columns_known = False
            return state
        for column_name in columns:
            state.columns[column_name] = ColumnLineage(
                name=column_name,
                source_column="",
                source_object="inline",
                origin="inline",
                status="inline",
                confidence="high",
                chain=[column_name],
                step=step,
                detail="Kolom didefinisikan langsung di dalam M (tabel inline).",
                steps=[StepLink(step=step, function=name, column=column_name)],
            )
        return state

    if lowered in {"#table", "table.fromrecords", "table.fromvalue", "table.fromlist"}:
        state = State(origin="inline", source_object="inline", is_table=True, columns_known=False)
        columns = _parse_string_list(args[0]) if args and lowered == "#table" else None
        if columns is None and lowered == "table.fromrecords":
            columns = None
        if columns:
            state.columns_known = True
            for column_name in columns:
                state.columns[column_name] = ColumnLineage(
                    name=column_name,
                    source_column="",
                    source_object="inline",
                    origin="inline",
                    status="inline",
                    confidence="high",
                    chain=[column_name],
                    step=step,
                    steps=[StepLink(step=step, function=name, column=column_name)],
                )
        return state

    base = _evaluate(args[0], states, step, warnings) if args else State()
    state = base.clone()
    state.is_table = True

    if lowered in _PASSTHROUGH:
        return state

    if lowered == "table.selectcolumns":
        selected = _parse_string_list(args[1]) if len(args) >= 2 else None
        if selected is None:
            warnings.append(Warning(step, "", "dynamic_columns", "Table.SelectColumns memakai daftar kolom dinamis."))
            state.columns_known = False
            return state
        chosen: dict[str, ColumnLineage] = {}
        for column_name in selected:
            column = _ensure_column(state, column_name, step, warnings)
            _record_step(column, step, "Table.SelectColumns", column_name, column_name)
            chosen[column_name] = column
        state.columns = chosen
        state.columns_known = True
        return state

    if lowered == "table.removecolumns":
        removed = _parse_string_list(args[1]) if len(args) >= 2 else None
        if removed is None:
            warnings.append(Warning(step, "", "dynamic_columns", "Table.RemoveColumns memakai daftar kolom dinamis."))
            state.columns_known = False
            return state
        for column_name in removed:
            state.columns.pop(column_name, None)
        return state

    if lowered == "table.renamecolumns":
        expr = args[1] if len(args) >= 2 else ""
        pairs = _parse_pairs(expr) if expr else None
        if pairs is None:
            single = _parse_string_list(expr) if expr else None
            if single is not None and len(single) == 2:
                pairs = [(single[0], single[1])]
        if pairs is None:
            warnings.append(
                Warning(step, "", "dynamic_rename", "Table.RenameColumns memakai daftar rename dinamis.")
            )
            state.columns_known = False
            return state
        for old, new in pairs:
            column = _ensure_column(state, old, step, warnings)
            state.columns.pop(old, None)
            if new in state.columns:
                existing = state.columns[new]
                existing.status = "rename_conflict"
                existing.confidence = "low"
                existing.detail = f"Rename '{old}' -> '{new}': nama tujuan sudah ada."
                column.status = "rename_conflict"
                column.confidence = "low"
                column.detail = existing.detail
                warnings.append(Warning(step, new, "rename_conflict", existing.detail))
            if column.status == "direct":
                column.status = "renamed"
            column.name = new
            column.step = step
            if not column.chain:
                column.chain = [old]
            column.chain.append(new)
            _record_step(column, step, "Table.RenameColumns", new, old)
            state.columns[new] = column
        return state

    if lowered == "table.duplicatecolumn":
        if len(args) < 3:
            return state
        source_name = _parse_name(args[1])
        new_name = _parse_name(args[2])
        if source_name is None or new_name is None:
            warnings.append(Warning(step, "", "dynamic_rename", "Table.DuplicateColumn tanpa nama statis."))
            state.columns_known = False
            return state
        source = _ensure_column(state, source_name, step, warnings)
        duplicate = copy.deepcopy(source)
        duplicate.name = new_name
        duplicate.status = "duplicated"
        duplicate.step = step
        duplicate.chain = list(source.chain) + [new_name]
        duplicate.logic = f"Duplicate of [{source_name}]"
        duplicate.steps = list(source.steps) + [
            StepLink(
                step=step,
                function="Table.DuplicateColumn",
                column=new_name,
                from_column=source_name,
            )
        ]
        state.columns[new_name] = duplicate
        return state

    if lowered in {"table.addcolumn", "table.addindexcolumn"}:
        if len(args) < 2:
            return state
        new_name = _parse_name(args[1])
        if new_name is None:
            warnings.append(Warning(step, "", "dynamic_columns", f"{name} tanpa nama kolom statis."))
            state.columns_known = False
            return state
        refs = _extract_refs(args[2]) if lowered == "table.addcolumn" and len(args) >= 3 else []
        logic = ""
        if lowered == "table.addcolumn" and len(args) >= 3:
            logic = _strip_outer(args[2]).strip()
        elif lowered == "table.addindexcolumn":
            logic = "Index column"
        state.columns[new_name] = _derived_column(
            state, new_name, refs, step, logic=logic, function=name
        )
        return state

    if lowered == "table.combinecolumns":
        if len(args) < 4:
            return state
        used = _parse_string_list(args[1])
        new_name = _parse_name(args[3])
        if used is None or new_name is None:
            warnings.append(Warning(step, "", "dynamic_columns", "Table.CombineColumns tidak statis."))
            state.columns_known = False
            return state
        for column_name in used:
            state.columns.pop(column_name, None)
        logic = _strip_outer(args[2]).strip() if len(args) >= 3 else ""
        state.columns[new_name] = _derived_column(
            state, new_name, used, step, logic=logic, function=name
        )
        return state

    if lowered == "table.splitcolumn":
        if len(args) < 4:
            warnings.append(
                Warning(step, "", "unresolved", "Table.SplitColumn tanpa argumen lengkap.")
            )
            state.columns_known = False
            return state
        source = _parse_name(args[1])
        names = _parse_string_list(args[3])
        if not source or not names:
            warnings.append(
                Warning(
                    step,
                    "",
                    "dynamic_columns",
                    "Table.SplitColumn memakai kolom hasil split dinamis.",
                )
            )
            state.columns_known = False
            return state
        _ensure_column(state, source, step, warnings)
        logic = _strip_outer(args[2]).strip() if len(args) >= 3 else ""
        for new_name in names:
            column = _derived_column(
                state,
                new_name,
                [source],
                step,
                detail="Kolom hasil split.",
                logic=logic,
                function=name,
            )
            column.confidence = "medium"
            state.columns[new_name] = column
        if source not in names:
            state.columns.pop(source, None)
        return state

    if lowered == "table.transformcolumns":
        names = _parse_transform_columns(args[1]) if len(args) >= 2 else None
        if not names:
            warnings.append(
                Warning(
                    step,
                    "",
                    "dynamic_columns",
                    "Table.TransformColumns memakai daftar kolom dinamis.",
                )
            )
            state.columns_known = False
            return state
        for column_name in names:
            column = _ensure_column(state, column_name, step, warnings)
            _record_step(column, step, name, column_name, column_name)
            if column.confidence == "high":
                column.confidence = "medium"
            if not column.detail:
                column.detail = (
                    "Transformasi Table.TransformColumns tidak dianalisa; "
                    "sumber kolom tetap."
                )
        warnings.append(
            Warning(
                step,
                "",
                "transform_columns",
                "Table.TransformColumns pada "
                + ", ".join(names)
                + ": logika transformasi tidak dianalisa.",
            )
        )
        return state

    if lowered == "table.group":
        keys = _parse_string_list(args[1]) if len(args) >= 2 else None
        if keys is None:
            state.columns_known = False
            warnings.append(Warning(step, "", "dynamic_columns", "Table.Group memakai key dinamis."))
            return state
        grouped: dict[str, ColumnLineage] = {}
        for key in keys:
            grouped[key] = _ensure_column(state, key, step, warnings)
        aggregations = split_top_level(_strip_outer(args[2])[1:-1]) if len(args) >= 3 else []
        for item in aggregations:
            parts = split_top_level(_strip_outer(item)[1:-1]) if item.strip().startswith("{") else []
            if len(parts) < 2:
                continue
            agg_name = _parse_name(parts[0])
            if agg_name is None:
                continue
            grouped[agg_name] = _derived_column(
                state,
                agg_name,
                _extract_refs(parts[1]),
                step,
                logic=_strip_outer(parts[1]).strip(),
                function=name,
            )
        state.columns = grouped
        state.columns_known = True
        return state

    if lowered in {"table.unpivotothercolumns", "table.unpivotcolumns"}:
        anchors = _parse_string_list(args[1]) if len(args) >= 2 else None
        if anchors is None or len(args) < 4:
            state.columns_known = False
            warnings.append(Warning(step, "", "unresolved", f"{name} tidak bisa dipastikan kolomnya."))
            return state
        attribute = _parse_name(args[2])
        value_name = _parse_name(args[3])
        kept: dict[str, ColumnLineage] = {}
        if lowered == "table.unpivotothercolumns":
            kept = {key: col for key, col in state.columns.items() if key in anchors}
        else:
            kept = {key: col for key, col in state.columns.items() if key not in anchors}
        for key in anchors:
            if key not in kept:
                kept[key] = _ensure_column(state, key, step, warnings)
        if attribute:
            kept[attribute] = _derived_column(
                state, attribute, [], step, function=name
            )
        if value_name:
            kept[value_name] = _derived_column(
                state, value_name, [], step, function=name
            )
        state.columns = kept
        state.columns_known = True
        return state

    if lowered in {"table.expandtablecolumn", "table.expandrecordcolumn"}:
        if len(args) < 3:
            return state
        new_names = _parse_string_list(args[2])
        old_names = _parse_string_list(args[3]) if len(args) >= 4 else None
        if new_names is None:
            state.columns_known = False
            warnings.append(Warning(step, "", "dynamic_columns", f"{name} memakai daftar kolom dinamis."))
            return state
        for index, new_name in enumerate(new_names):
            refs = [old_names[index]] if old_names and index < len(old_names) else []
            column = _derived_column(
                state, new_name, refs, step, "Kolom hasil expand.", function=name
            )
            column.confidence = "medium"
            state.columns[new_name] = column
        return state

    if lowered in {"table.pivot", "table.transformcolumnnames"}:
        detail = (
            "Rename kolom dinamis (Table.TransformColumnNames) tidak bisa dipastikan."
            if lowered == "table.transformcolumnnames"
            else "Table.Pivot mengubah nama kolom secara dinamis."
        )
        _mark_all(state, "dynamic_rename", "low", detail, step, warnings)
        return state

    if lowered in {"table.combine"}:
        warnings.append(
            Warning(step, "", "unresolved", "Table.Combine menggabungkan tabel; kolom tidak bisa dipastikan.")
        )
        state.columns = {}
        state.columns_known = False
        return state

    # Fungsi tak dikenal: anggap passthrough tetapi turunkan keyakinan.
    warnings.append(
        Warning(step, "", "unknown_function", f"Fungsi '{name}' belum dikenali; lineage kolom diturunkan sebagai passthrough.")
    )
    for column in state.columns.values():
        if column.confidence == "high":
            column.confidence = "medium"
        if not column.detail:
            column.detail = f"Melewati fungsi yang belum dikenali: {name}."
    return state


def _evaluate(expr: str, states: dict[str, State], step: str, warnings: list[Warning]) -> State:
    value = _strip_outer(strip_comments(expr).strip())
    if not value:
        return State()

    navigation = parse_navigation(value)
    if navigation is not None:
        base_expr, key_values = navigation
        base = _evaluate(base_expr, states, step, warnings)
        state = base.clone()
        state.is_table = True
        if "entity" in key_values:
            state.origin = "dataflow"
            state.source_object = key_values["entity"]
            state.columns = {}
            state.columns_known = False
        elif "Item" in key_values:
            schema = key_values.get("Schema", "")
            state.source_object = f"{schema}.{key_values['Item']}" if schema else key_values["Item"]
            if state.origin not in {"sql", "dataflow", "table", "file", "odata", "sharepoint"}:
                state.origin = "table"
            state.columns = {}
            state.columns_known = False
        return state

    call = parse_function_call(value)
    if call is not None:
        function_name, args = call
        return _apply_function(function_name, args, value, states, step, warnings)

    if _is_identifier(value):
        return states.get(unquote(value), State()).clone()

    return State(is_table=False)


# ---------------------------------------------------------------------------
# API utama
# ---------------------------------------------------------------------------
def build_lineage(m_text: str) -> LineageResult:
    """Bangun lineage kolom dari teks query M sebuah partisi."""
    result = LineageResult()
    if not m_text or not m_text.strip():
        result.warnings.append(Warning("", "", "no_query", "Partisi tidak memiliki query M."))
        return result

    states: dict[str, State] = {}
    steps, final_expr = parse_let(m_text)
    for step_name, expr in steps:
        states[step_name] = _evaluate(expr, states, step_name, result.warnings)

    if final_expr:
        final = _evaluate(final_expr, states, "<in>", result.warnings)
    elif steps:
        final = states.get(steps[-1][0], State())
    else:
        final = State()

    result.columns = final.columns
    result.origin = final.origin
    result.source_object = final.source_object
    result.columns_known = final.columns_known
    return result


PARTIAL_WARNING_STATUSES = {
    "dynamic_columns",
    "dynamic_rename",
    "unresolved",
    "unknown_function",
    "rename_conflict",
    "orphan_rename",
    "transform_columns",
}


def lineage_confidence(result: LineageResult) -> str:
    """Tingkat keyakinan lineage M: complete/partial/unavailable."""
    if not result.columns:
        return "unavailable"
    if not result.columns_known:
        return "partial"
    if any(warning.status in PARTIAL_WARNING_STATUSES for warning in result.warnings):
        return "partial"
    return "complete"


def column_confidence(result: LineageResult, column_name: str) -> str:
    """Keyakinan lineage M untuk satu kolom (complete/partial/unavailable)."""
    wanted = str(column_name or "").casefold()
    column = None
    for name, value in (result.columns or {}).items():
        if str(name).casefold() == wanted:
            column = value
            break
    if column is None:
        return "unavailable"
    if column.confidence == "low" or column.status in {
        "unresolved",
        "orphan_rename",
        "rename_conflict",
        "dynamic_rename",
        "unknown_function",
    }:
        return "partial"
    for warning in result.warnings:
        if (
            warning.column
            and warning.column.casefold() == wanted
            and warning.status in PARTIAL_WARNING_STATUSES
        ):
            return "partial"
    for warning in result.warnings:
        if not warning.column and warning.status in PARTIAL_WARNING_STATUSES:
            return "partial"
    return "complete"


def warning_rows(result: LineageResult, limit: int = 20) -> list[dict[str, Any]]:
    """Baris warning M siap dikirim ke web (dibatasi ``limit``)."""
    return [
        {
            "step": warning.step,
            "column": warning.column,
            "status": warning.status,
            "detail": warning.detail,
        }
        for warning in result.warnings[:limit]
    ]


def apply_lineage(
    rows: list[dict[str, Any]],
    result: LineageResult,
    calculated_names: set[str] | None = None,
    engine_key: str = "source_column",
) -> list[Warning]:
    """Tempel hasil lineage ke baris kolom dan kembalikan daftar warning."""
    calculated_names = calculated_names or set()
    warnings = list(result.warnings)

    for row in rows:
        name = str(row.get("column") or "")
        engine_value = str(row.get(engine_key) or "")
        row["engine_source_column"] = engine_value

        if name in calculated_names:
            row["source_column"] = ""
            row["m_source_object"] = result.source_object
            row["m_source_column"] = ""
            row["m_source_origin"] = "dax"
            row["m_source_columns_used"] = ""
            row["m_transform_chain"] = ""
            row["m_lineage_confidence"] = "high"
            row["m_lineage_status"] = "calculated"
            continue

        column = result.columns.get(name)
        if column is None and not result.columns_known:
            source = engine_value or name
            row["source_column"] = source
            row["m_source_object"] = result.source_object
            row["m_source_column"] = source
            row["m_source_origin"] = result.origin or "unknown"
            row["m_source_columns_used"] = ""
            row["m_transform_chain"] = source
            row["m_lineage_confidence"] = "medium"
            row["m_lineage_status"] = "direct_assumed"
            continue

        if column is None:
            row["source_column"] = ""
            row["m_source_object"] = result.source_object
            row["m_source_column"] = ""
            row["m_source_origin"] = result.origin or "unknown"
            row["m_source_columns_used"] = ""
            row["m_transform_chain"] = ""
            row["m_lineage_confidence"] = "low"
            row["m_lineage_status"] = "unresolved"
            warnings.append(
                Warning(
                    "<final>",
                    name,
                    "missing_column",
                    "Kolom tidak ditemukan pada hasil akhir query M.",
                )
            )
            continue

        row["source_column"] = column.source_column
        row["m_source_object"] = column.source_object or result.source_object
        row["m_source_column"] = column.source_column
        row["m_source_origin"] = column.origin
        row["m_source_columns_used"] = column.used_text()
        row["m_transform_chain"] = column.chain_text()
        row["m_lineage_confidence"] = column.confidence
        row["m_lineage_status"] = column.status

    return warnings


def warnings_rows(warnings: list[Warning]) -> list[dict[str, Any]]:
    """Ubah warning menjadi baris siap tulis Excel."""
    seen: set[tuple[str, str, str, str]] = set()
    rows: list[dict[str, Any]] = []
    for warning in warnings:
        key = (warning.step, warning.column, warning.status, warning.detail)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "step": warning.step,
                "column": warning.column,
                "status": warning.status,
                "detail": warning.detail,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Self-test sederhana (python m_lineage.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = {
        "rename_chain": """
            let
                Source = Sql.Database(ServerURL, Datamart),
                dbo_t = Source{[Schema="dbo",Item="t"]}[Data],
                #"Renamed 1" = Table.RenameColumns(dbo_t, {{"kode", "Kode"}}),
                #"Renamed 2" = Table.RenameColumns(#"Renamed 1", {{"Kode", "Kode Lama"}})
            in
                #"Renamed 2"
        """,
        "duplicate": """
            let
                Source = Sql.Database("srv", "db"),
                t = Source{[Schema="dbo",Item="sumber"]}[Data],
                d = Table.DuplicateColumn(t, "validasi", "validasi - Copy"),
                r = Table.RenameColumns(d, {{"validasi - Copy", "Status Filter"}})
            in
                r
        """,
        "add_column": """
            let
                Source = PowerPlatform.Dataflows(null),
                e = Source{[entity="master"]}[Data],
                r = Table.RenameColumns(e, {{"kodelama", "Kode Lama"}, {"nama", "Nama"}}),
                a = Table.AddColumn(r, "Label", each [Kode Lama] & " - " & [Nama], type text)
            in
                a
        """,
        "inline": """
            let
                Source = Table.FromRows(Json.Document(Binary.Decompress(Binary.FromText("abc"), Compression.Deflate)),
                    let _t = ((type nullable text) meta [Serialized.Text = true]) in type table [#"# RO Baru" = _t, Sequence = _t]),
                c = Table.TransformColumnTypes(Source, {{"# RO Baru", type text}})
            in
                c
        """,
        "select": """
            let
                Source = Sql.Database("srv", "db"),
                t = Source{[Schema="dbo",Item="x"]}[Data],
                s = Table.SelectColumns(t, {"a", "b", "c"}),
                r = Table.RemoveColumns(s, {"c"})
            in
                r
        """,
    }
    for label, text in samples.items():
        parsed = build_lineage(text)
        print(f"[{label}] origin={parsed.origin} object={parsed.source_object} known={parsed.columns_known}")
        for column_name, column in sorted(parsed.columns.items()):
            print(
                f"  {column_name!r}: source={column.source_column!r} status={column.status} "
                f"chain={column.chain_text()!r} used={column.used_text()!r}"
            )
        for warning in parsed.warnings:
            print(f"  ! {warning.step}/{warning.column}: {warning.status} - {warning.detail}")

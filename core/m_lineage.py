"""
Parser lineage kolom dari query M (Power Query) secara deterministik.

Modul ini membaca teks M sebuah partisi, mensimulasikan langkah-langkah
`let ... in` dari sumber sampai tabel akhir, lalu memetakan setiap kolom
akhir ke kolom asli di sumbernya.

Yang ditangani:
  - navigasi sumber: Sql.Database + {[Schema, Item]}, dataflow {[entity]},
    konektor ber-navigasi `Name` (BigQuery/Snowflake/PostgreSQL/OData), tabel
    inline (Table.FromRows / #table)
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
from urllib.parse import urlparse


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
    source_path: list[str] = field(default_factory=list)
    connection_path: list[str] = field(default_factory=list)
    columns_known: bool = False
    # Nama parameter M yang dipakai menyusun sumber (mis. ServerURL). Nilainya
    # tidak masuk label karena baru diketahui saat refresh.
    source_params: list[str] = field(default_factory=list)
    # Keterangan tambahan sumber: path/URL lengkap, nama konektor native.
    details: list[str] = field(default_factory=list)
    native_query: bool = False
    # Query yang sumbernya query lain (`#"Nama"`) dan belum bisa ditelusuri.
    references: list[str] = field(default_factory=list)


@dataclass
class State:
    """Kondisi tabel pada satu titik simulasi."""

    columns: dict[str, ColumnLineage] = field(default_factory=dict)
    origin: str = ""
    # Level path sumber dari luar ke dalam (mis. ["dbo", "Sales"] atau
    # ["proyek", "dataset", "tabel"]). `source_object` adalah turunannya.
    source_path: list[str] = field(default_factory=list)
    # Level koneksi dari argumen fungsi (server/database/proyek). Dipakai
    # sebagai label hanya bila tidak ada navigasi tabel yang lebih spesifik.
    connection_path: list[str] = field(default_factory=list)
    columns_known: bool = False
    is_table: bool = False
    source_params: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    native_query: bool = False
    references: list[str] = field(default_factory=list)

    @property
    def source_object(self) -> str:
        return ".".join(self.source_path or self.connection_path)

    def clone(self) -> "State":
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Adapter konektor: fungsi M sumber -> origin + label
# ---------------------------------------------------------------------------
# Origin dipakai sebagai `context` node datasource dan sebagai penentu keyakinan
# lineage M (`_confidence_for`). Setiap konektor database yang navigasinya
# memakai `Item`/`Name` wajib terdaftar; konektor di luar daftar ini tidak
# ditebak namanya (path tetap dibaca, origin jatuh ke `table`).
#
# `kind` menentukan cara argumen dijadikan label:
#   connection -> string koneksi/DSN (hanya kunci aman yang dipakai)
#   path       -> nama berkas (path lengkap disimpan di `details`)
#   folder     -> folder tidak masuk label; path lengkap di `details`
#   url        -> host URL (URL tanpa query/userinfo di `details`)
#   identifier -> teks literal apa adanya
# `label_args` adalah indeks argumen yang membentuk level path. Parameter M
# (bukan string literal) tidak masuk label, hanya dicatat di `source_params`.
@dataclass(frozen=True)
class ConnectorSpec:
    origin: str
    kind: str = "identifier"
    label_args: tuple[int, ...] = ()
    static_label: str = ""
    inherit: bool = False
    is_table: bool = False
    native: bool = False


CONNECTOR_SPECS: dict[str, ConnectorSpec] = {
    # Database relasional / analitik
    "sql.database": ConnectorSpec("sql", "connection", (0, 1)),
    "sql.databases": ConnectorSpec("sql", "connection", (0,)),
    "azuresql.database": ConnectorSpec("sql", "connection", (0, 1)),
    "azuresynapseanalytics.database": ConnectorSpec("sql", "connection", (0, 1)),
    "analysisservices.database": ConnectorSpec(
        "analysis services", "connection", (0, 1)
    ),
    "analysisservices.databases": ConnectorSpec(
        "analysis services", "connection", (0,)
    ),
    "googlebigquery.database": ConnectorSpec("bigquery", "identifier", (0,)),
    "googlebigqueryaad.database": ConnectorSpec("bigquery", "identifier", (0,)),
    "snowflake.databases": ConnectorSpec("snowflake", "connection", (0,)),
    "postgresql.database": ConnectorSpec("postgresql", "connection", (0, 1)),
    "mysql.database": ConnectorSpec("mysql", "connection", (0, 1)),
    "oracle.database": ConnectorSpec("oracle", "connection", (0, 1)),
    "teradata.database": ConnectorSpec("teradata", "connection", (0, 1)),
    "db2.database": ConnectorSpec("db2", "connection", (0, 1)),
    "saphana.database": ConnectorSpec("sap hana", "connection", (0, 1)),
    "sybase.database": ConnectorSpec("sybase", "connection", (0, 1)),
    "informix.database": ConnectorSpec("informix", "connection", (0, 1)),
    "odbc.query": ConnectorSpec("odbc", "connection", (0,), native=True),
    "odbc.datasource": ConnectorSpec("odbc", "connection", (0,)),
    "sapbusinesswarehouse.cubes": ConnectorSpec("sap bw", "connection", (0,)),
    "dataverse.contents": ConnectorSpec("dataverse", "url", (0,)),
    "commondataservice.database": ConnectorSpec("dataverse", "url", (0,)),
    # Dataflow / dataset
    "powerplatform.dataflows": ConnectorSpec("dataflow"),
    "powerbi.dataflows": ConnectorSpec("dataflow"),
    "fabric.dataflows": ConnectorSpec("dataflow"),
    "powerplatform.datasets": ConnectorSpec("dataset"),
    "fabric.datasets": ConnectorSpec("dataset"),
    "usagemetricsdataconnector.getmetricsdata": ConnectorSpec(
        "usage metrics", static_label="Usage Metrics"
    ),
    # Layanan lain
    "odata.feed": ConnectorSpec("odata", "url", (0,)),
    "sharepoint.files": ConnectorSpec("sharepoint", "url", (0,)),
    "sharepoint.contents": ConnectorSpec("sharepoint", "url", (0,)),
    "sharepoint.tables": ConnectorSpec("sharepoint", "url", (0,)),
    # Berkas
    "excel.workbook": ConnectorSpec("file", inherit=True, is_table=True),
    "excel.currentworkbook": ConnectorSpec(
        "file", static_label="Current Workbook", is_table=True
    ),
    "file.contents": ConnectorSpec("file", "path", (0,)),
    "folder.files": ConnectorSpec("file", "folder", (0,)),
    "csv.document": ConnectorSpec("file", inherit=True),
    "json.document": ConnectorSpec("file", inherit=True),
    "xml.tables": ConnectorSpec("file", inherit=True),
    "parquet.document": ConnectorSpec("file", inherit=True),
    "pdf.tables": ConnectorSpec("file", inherit=True),
    "pdf.data": ConnectorSpec("file", inherit=True),
    "googlesheets.contents": ConnectorSpec("googlesheets", "url", (0,)),
    "azurestorage.blobs": ConnectorSpec("azure storage", "url", (0,)),
    "azurestorage.datalake": ConnectorSpec("azure storage", "url", (0,)),
    "web.contents": ConnectorSpec("web", "url", (0,)),
    "web.page": ConnectorSpec("web", inherit=True),
    "web.browsercontents": ConnectorSpec("web", "url", (0,)),
    "html.table": ConnectorSpec("web", inherit=True),
    "html.browsercontents": ConnectorSpec("web", "url", (0,)),
}

# Dipakai pemanggil lama/uji: nama fungsi -> origin.
CONNECTOR_ORIGINS: dict[str, str] = {
    name: spec.origin for name, spec in CONNECTOR_SPECS.items()
}

DATABASE_ORIGINS = frozenset(
    {
        "sql",
        "analysis services",
        "bigquery",
        "snowflake",
        "postgresql",
        "mysql",
        "oracle",
        "teradata",
        "db2",
        "sap hana",
        "sap bw",
        "sybase",
        "informix",
        "odbc",
        "dataverse",
        "table",
    }
)
LIVE_ORIGINS = frozenset({"dataflow", "dataset", "usage metrics"})
FILE_ORIGINS = frozenset({"file", "googlesheets", "azure storage", "web"})
KNOWN_ORIGINS = (
    DATABASE_ORIGINS
    | LIVE_ORIGINS
    | FILE_ORIGINS
    | {"odata", "sharepoint", "inline"}
)


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
# Label sumber: literal vs parameter, path, URL, dan connection string
# ---------------------------------------------------------------------------
_SAFE_CONNECTION_KEYS = (
    "dsn",
    "server",
    "data source",
    "host",
    "database",
    "db",
    "initial catalog",
    "warehouse",
    "project",
)
_PARAM_KEYWORDS = {"null", "true", "false", "type"}


def _is_string_literal(value: str) -> bool:
    """True untuk satu string literal M (`"teks"`), bukan identifier `#"teks"`."""
    if len(value) < 2 or not value.startswith('"') or value.startswith('#"'):
        return False
    index = 1
    length = len(value)
    while index < length:
        if value[index] == '"':
            if index + 1 < length and value[index + 1] == '"':
                index += 2
                continue
            return index == length - 1
        index += 1
    return False


def _declared_name(expr: str) -> str:
    """Nama parameter/ekspresi yang bisa ditampilkan sebagai penanda."""
    value = _strip_outer(expr.strip())
    if not value or _is_string_literal(value):
        return ""
    if value.startswith('#"') and value.endswith('"'):
        return unquote(value)
    if value.casefold() in _PARAM_KEYWORDS:
        return ""
    if _is_identifier(value) and value.casefold() not in _PARAM_KEYWORDS:
        return value
    if "(" in value:
        return ""
    match = re.match(r"[A-Za-z_][\w]*", value)
    return match.group(0) if match else ""


def _path_label(value: str) -> str:
    """Nama berkas/folder terakhir dari sebuah path."""
    text = value.replace("\\", "/").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1].strip()


def _sanitize_url(value: str) -> str:
    """Buang query, fragment, dan userinfo agar token di URL tidak ikut tampil."""
    text = value.strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text.split("?", 1)[0].split("#", 1)[0]
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path}"


def _url_label(value: str) -> str:
    parsed = urlparse(value.strip())
    return (parsed.hostname or "").strip()


def _connection_label(value: str) -> str:
    """Ambil bagian aman dari connection string (tanpa user/password/token)."""
    text = value.strip()
    if not text:
        return ""
    if "=" not in text:
        return text
    found: dict[str, str] = {}
    for chunk in text.split(";"):
        key, separator, raw = chunk.partition("=")
        if not separator:
            continue
        name = key.strip().casefold()
        item = raw.strip()
        if name in _SAFE_CONNECTION_KEYS and item and name not in found:
            found[name] = item
    values: list[str] = []
    for key in _SAFE_CONNECTION_KEYS:
        item = found.get(key)
        if item and item not in values:
            values.append(item)
    return ".".join(values)


def _argument_level(arg: str, kind: str) -> tuple[str, str, str]:
    """(level label, nama parameter, detail) dari satu argumen konektor."""
    raw = _strip_outer(arg.strip())
    if not raw:
        return "", "", ""
    literal = _is_string_literal(raw)
    if kind == "path":
        if literal:
            text = unquote(raw)
            return _path_label(text), "", f"path:{text}"
        return "", _declared_name(raw), ""
    if kind == "folder":
        if literal:
            return "", "", f"path:{unquote(raw)}"
        return "", _declared_name(raw), ""
    if kind == "url":
        if literal:
            text = unquote(raw)
            return _url_label(text), "", f"url:{_sanitize_url(text)}"
        return "", _declared_name(raw), ""
    if kind == "connection":
        if literal:
            return _connection_label(unquote(raw)), "", ""
        return "", _declared_name(raw), ""
    if literal:
        return unquote(raw), "", ""
    return "", _declared_name(raw), ""


def _add_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)


def _parse_expression_list(expr: str) -> list[str]:
    """Pecah `{a, b, c}` menjadi ekspresi mentah tiap elemen."""
    value = _strip_outer(expr.strip())
    if not (value.startswith("{") and value.endswith("}")):
        return []
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [item.strip() for item in split_top_level(inner)]


_FIELD_ACCESS = re.compile(r"^(.*?)((?:\[[^\[\]]+\]|\{\s*\d+\s*\})+)$", re.S)


def _parse_field_access(expr: str) -> tuple[str, bool] | None:
    """Kenali `Base[Kolom]{0}` / `Base[Kolom]` (akses field, bukan navigasi).

    Mengembalikan ekspresi basis dan apakah hasilnya tabel (indeks `{n}`).
    """
    value = expr.strip()
    match = _FIELD_ACCESS.match(value)
    if not match:
        return None
    base = match.group(1).strip()
    if not base or base.endswith("[Data]"):
        return None
    return base, "{" in match.group(2)


def _merge_states(candidates: list[State]) -> State:
    """Gabungkan beberapa cabang (Table.Combine / if-then-else)."""
    merged = State(is_table=True)
    for candidate in candidates:
        if not merged.origin and candidate.origin:
            merged.origin = candidate.origin
        if not merged.source_path and candidate.source_path:
            merged.source_path = list(candidate.source_path)
        if not merged.connection_path and candidate.connection_path:
            merged.connection_path = list(candidate.connection_path)
        _add_unique(merged.source_params, candidate.source_params)
        _add_unique(merged.details, candidate.details)
        _add_unique(merged.references, candidate.references)
        merged.native_query = merged.native_query or candidate.native_query
    known = [set(candidate.columns) for candidate in candidates if candidate.columns_known]
    if (
        known
        and len(known) == len(candidates)
        and all(columns == known[0] for columns in known)
    ):
        merged.columns = copy.deepcopy(candidates[0].columns)
        merged.columns_known = True
    return merged



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


_NAVIGATION_ACCESSOR = re.compile(r"\[(Data|Content|Value)\]\s*$")


def parse_navigation(
    expr: str,
) -> tuple[str, dict[str, str], set[str], str] | None:
    """Kenali `Base{[Key=Value,...]}[Data|Content|Value]`.

    Mengembalikan base, nilai kunci, kunci yang nilainya string literal, dan
    accessor terakhir. Nilai non-literal (mis. `{[Name=projectID]}`) adalah
    parameter/ekspresi, bukan bagian label.
    """
    value = _strip_outer(expr.strip())
    accessor_match = _NAVIGATION_ACCESSOR.search(value)
    if not accessor_match:
        return None
    accessor = accessor_match.group(1)
    value = value[: accessor_match.start()].rstrip()
    if not value.endswith("}"):
        return None
    close = len(value) - 1
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
    literal_keys: set[str] = set()
    for part in split_top_level(inner[1:-1]):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        raw = val.strip()
        key_values[key] = unquote(raw)
        if _is_string_literal(raw):
            literal_keys.add(key)
    return value[:open_pos].strip(), key_values, literal_keys, accessor


def navigation_levels(
    key_values: dict[str, str],
    literal_keys: set[str] | None = None,
    origin: str = "",
) -> list[str]:
    """Level path sumber dari satu navigasi `Base{[Key=Value,...]}[...]`.

    Bentuk yang dikenal:

    - ``{[Schema="dbo", Item="Sales"]}`` (SQL Server, Azure SQL, Synapse)
    - ``{[entity="Sales"]}`` (dataflow)
    - ``{[Name="proyek"]}`` lalu ``{[Name="dataset", Kind="Schema"]}`` lalu
      ``{[Name="tabel"]}`` (BigQuery, Snowflake, PostgreSQL, MySQL, OData)
    - ``{[Item="Sheet1", Kind="Sheet"]}`` (Excel/berkas)
    - ``{[name="target", ItemKind="Table"]}`` (Google Sheets/ODBC)

    Kunci layanan (``Id``, ``workspaceId``, ``dataflowId``, ``version``) dan
    kunci tipe (``Kind``, ``ItemKind``) tidak pernah menjadi level label.
    Kunci dengan nilai parameter dilewati; pemanggil mencatatnya terpisah.
    """
    if literal_keys is None:
        literal_keys = set(key_values)

    def literal(key: str) -> str:
        if key not in literal_keys:
            return ""
        return str(key_values.get(key) or "").strip()

    entity = literal("entity")
    if entity:
        return [entity]
    schema = literal("Schema")
    item = literal("Item")
    if schema or item:
        return [level for level in (schema, item) if level]
    for key in ("Name", "name"):
        value = literal(key)
        if value:
            return [value]
    return []


def navigation_params(
    key_values: dict[str, str], literal_keys: set[str]
) -> list[str]:
    """Nama parameter pada kunci navigasi yang nilainya bukan literal."""
    params: list[str] = []
    for key in ("entity", "Schema", "Item", "Name", "name"):
        if key in key_values and key not in literal_keys:
            text = str(key_values.get(key) or "").strip()
            if text:
                params.append(text)
    return params


def _append_source_path(state: State, levels: list[str]) -> None:
    """Tambahkan level path sumber tanpa mengulang level yang sudah di ujung."""
    cleaned = [str(level or "").strip() for level in levels]
    cleaned = [level for level in cleaned if level]
    if not cleaned:
        return
    path = list(state.source_path)
    if path[-len(cleaned):] == cleaned:
        return
    state.source_path = path + cleaned


def _append_connection_path(state: State, levels: list[str]) -> None:
    """Tambahkan level koneksi (server/database/proyek) tanpa duplikasi."""
    cleaned = [str(level or "").strip() for level in levels]
    cleaned = [level for level in cleaned if level]
    if not cleaned:
        return
    path = list(state.connection_path)
    if path[-len(cleaned):] == cleaned:
        return
    state.connection_path = path + cleaned


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
    "table.join",
    "table.fuzzyjoin",
    "table.profiling",
    "table.stop",
    # Fungsi yang hanya membuang/mengganti nilai; bentuk tabel tetap.
    "table.replaceerrorvalues",
    "table.removerowswitherrors",
    "table.selectrowswitherrors",
    "table.removelastn",
    "table.removefirstn",
    "table.removematchingrows",
    "table.expandlistcolumn",
    "table.insertrows",
    "table.alternaterows",
}
_TABLE_PREFIXES = ("cube.",)

# Fungsi yang mengubah header sehingga nama kolom tidak lagi bisa dipastikan.
# Tidak diberi warning: ketidakpastian ini sudah diwakili `columns_known=False`.
_COLUMN_RESET = {
    "table.promoteheaders",
    "table.demoteheaders",
    "table.transpose",
    "table.aggregatetablecolumn",
}

# Fungsi skalar/nilai: tidak mengubah bentuk tabel, jadi tidak boleh memicu
# `unknown_function` saat muncul di dalam `Table.AddColumn`.
_SCALAR_PREFIXES = (
    "date.",
    "datetime.",
    "datetimezone.",
    "time.",
    "duration.",
    "text.",
    "number.",
    "logical.",
    "list.",
    "record.",
    "type.",
    "uri.",
    "character.",
    "binary.",
)
_SCALAR_FUNCTIONS = {
    "#date",
    "#datetime",
    "#datetimezone",
    "#time",
    "#duration",
    "#infinity",
    "#nan",
    "error",
    "try",
    "each",
    "table.columnnames",
    "table.torecords",
    "table.rowcount",
    "table.isempty",
    "table.contains",
}


def _confidence_for(origin: str) -> str:
    if origin in KNOWN_ORIGINS:
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


def _apply_connector(
    spec: ConnectorSpec,
    args: list[str],
    states: dict[str, State],
    step: str,
    warnings: list[Warning],
) -> State:
    """Bangun state sumber dari satu connector yang sudah terdaftar."""
    if spec.inherit and args:
        state = _evaluate(args[0], states, step, warnings).clone()
        if not state.origin:
            state.origin = spec.origin
    else:
        state = State(origin=spec.origin)
    state.is_table = spec.is_table or state.is_table
    if spec.native:
        state.native_query = True
    if spec.static_label:
        _append_connection_path(state, [spec.static_label])
    for index in spec.label_args:
        if index >= len(args):
            continue
        level, param, detail = _argument_level(args[index], spec.kind)
        if level:
            _append_connection_path(state, [level])
        if param:
            _add_unique(state.source_params, [param])
        if detail:
            _add_unique(state.details, [detail])
    # Opsi native query pada Sql.Database(..., [Query="..."]).
    if any(re.search(r"\bQuery\s*=", arg) for arg in args):
        state.native_query = True
    return state


def _apply_function(
    name: str,
    args: list[str],
    expr: str,
    states: dict[str, State],
    step: str,
    warnings: list[Warning],
) -> State:
    lowered = name.lower()

    spec = CONNECTOR_SPECS.get(lowered)
    if spec is not None:
        return _apply_connector(spec, args, states, step, warnings)
    if lowered in {"binary.decompress", "binary.fromtext", "text.frombinary"}:
        return _evaluate(args[0], states, step, warnings) if args else State(is_table=False)

    if lowered == "value.nativequery":
        # Native query tetap memakai sumber dan path tabel basisnya.
        state = _evaluate(args[0], states, step, warnings) if args else State()
        state.is_table = True
        state.native_query = True
        return state

    if lowered in _SCALAR_FUNCTIONS or lowered.startswith(_SCALAR_PREFIXES):
        return _evaluate(args[0], states, step, warnings) if args else State(is_table=False)

    if lowered == "table.fromrows":
        state = State(origin="inline", source_path=["inline"], is_table=True, columns_known=True)
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
        state = State(origin="inline", source_path=["inline"], is_table=True, columns_known=False)
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

    if lowered in _COLUMN_RESET:
        # Header berasal dari isi data / bentuk tabel berubah: nama kolom tidak
        # bisa dipastikan. Tidak ada warning karena ini perilaku normal M.
        state.columns = {}
        state.columns_known = False
        return state

    if lowered.startswith(_TABLE_PREFIXES):
        # Cube.* (SAP BW / Analysis Services) mengubah bentuk tabel dan tidak
        # membawa nama kolom yang bisa dipetakan.
        state.columns = {}
        state.columns_known = False
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

    if lowered == "table.unpivot":
        pivot_values = _parse_string_list(args[1]) if len(args) >= 2 else None
        attribute = _parse_name(args[2]) if len(args) >= 3 else None
        value_name = _parse_name(args[3]) if len(args) >= 4 else None
        if pivot_values is None or not attribute or not value_name:
            state.columns = {}
            state.columns_known = False
            return state
        kept = {
            key: column
            for key, column in state.columns.items()
            if key not in pivot_values
        }
        kept[attribute] = _derived_column(
            state, attribute, [], step, function=name
        )
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

    if lowered == "table.combine":
        items = _parse_expression_list(args[0]) if args else []
        candidates = [_evaluate(item, states, step, warnings) for item in items]
        if not candidates:
            state.columns = {}
            state.columns_known = False
            return state
        return _merge_states(candidates)

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

    # `let` bersarang di dalam satu langkah.
    if _find_word(value, "let") == 0:
        steps, final_expr = parse_let(value)
        if steps and final_expr and final_expr != value:
            local = dict(states)
            for step_name, step_expr in steps:
                local[step_name] = _evaluate(
                    step_expr, local, step_name, warnings
                )
            return _evaluate(final_expr, local, step, warnings)

    # `if ... then ... else ...`: cabang membawa sumber yang sama.
    if _find_word(value, "if") == 0:
        then_pos = _find_word(value, "then")
        if then_pos != -1:
            else_pos = _find_word(value, "else", then_pos + 4)
            if else_pos != -1:
                branches = [
                    value[then_pos + 4 : else_pos].strip(),
                    value[else_pos + 4 :].strip(),
                ]
                return _merge_states(
                    [
                        _evaluate(branch, states, step, warnings)
                        for branch in branches
                    ]
                )

    navigation = parse_navigation(value)
    if navigation is not None:
        base_expr, key_values, literal_keys, accessor = navigation
        base = _evaluate(base_expr, states, step, warnings)
        state = base.clone()
        state.is_table = accessor == "Data"
        levels = navigation_levels(key_values, literal_keys)
        if levels:
            _append_source_path(state, levels)
            # Navigasi turun ke objek lain: kolom objek tujuan tidak terbaca
            # dari M (tabel, sheet, berkas, atau record).
            state.columns = {}
            state.columns_known = False
        _add_unique(
            state.source_params, navigation_params(key_values, literal_keys)
        )
        if "entity" in key_values:
            state.origin = "dataflow"
        elif not state.origin:
            # Konektor tidak dikenal: tetap tandai sebagai tabel generik,
            # jangan menebak nama konektornya.
            state.origin = "table"
        return state

    call = parse_function_call(value)
    if call is not None:
        function_name, args = call
        return _apply_function(function_name, args, value, states, step, warnings)

    field_access = _parse_field_access(value)
    if field_access is not None:
        base_expr, is_table = field_access
        base = _evaluate(base_expr, states, step, warnings)
        state = base.clone()
        state.is_table = is_table or state.is_table
        # Akses field/record bukan tabel utuh: kolomnya tidak bisa dipastikan.
        state.columns = {}
        state.columns_known = False
        return state

    if _is_identifier(value):
        name = unquote(value)
        if name.casefold() in _PARAM_KEYWORDS:
            return State(is_table=False)
        if name in states:
            return states[name].clone()
        # Query lain (`#"Nama"` / nama shared query) belum bisa ditelusuri.
        return State(is_table=False, references=[name])

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
    result.source_path = list(final.source_path)
    result.connection_path = list(final.connection_path)
    result.columns_known = final.columns_known
    result.source_params = list(final.source_params)
    result.details = list(final.details)
    result.native_query = final.native_query
    result.references = list(final.references)
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

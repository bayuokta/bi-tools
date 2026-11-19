"""Klien TOM/XMLA untuk inventaris dan refresh partisi semantic model.

Modul ini adalah satu-satunya jalur tulis XMLA di aplikasi. Koneksi memakai
TOM (pythonnet + .NET Framework) dan token Power BI dari :mod:`core.auth`;
token tidak pernah masuk ke connection string. Perintah refresh memakai TMSL
``<Statement>`` seperti Tabular Editor 2, bukan ``SaveChanges`` metadata.

Batas yang disengaja:

- hanya me-refresh partisi yang sudah ada;
- tidak membuat/menghapus partisi, mengubah query M, atau refresh policy;
- DLL TOM berada di ``libs/tom`` di samping executable (lihat
  ``packaging/bi_tools.spec``).
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from xml.sax.saxutils import escape

from .auth import POWERBI_SCOPE
from .errors import ExtractionError
from .paths import APP_DIR
from .xmla_client import (
    _blocked_assembly_message,
    pythonnet_assembly,
    readwrite_endpoint,
    unblock_dotnet_assemblies,
)

ROOT = APP_DIR
TOM_DIR = ROOT / "libs" / "tom"
APPLICATION_NAME = "BI Tools"

# Nilai yang diterima TOM/TMSL. Nama kanonik mengikuti JSON TMSL.
REFRESH_TYPES: dict[str, str] = {
    "full": "full",
    "automatic": "automatic",
    "dataonly": "dataOnly",
    "clearvalues": "clearValues",
    "calculate": "calculate",
    "add": "add",
    "defragment": "defragment",
    "indexes": "indexes",
}
REFRESH_TYPE_ORDER = tuple(REFRESH_TYPES.values())

_TOM: tuple[Any, Any, Any] | None = None


class TomError(ExtractionError):
    """Kegagalan koneksi atau operasi TOM/XMLA."""


# ---------------------------------------------------------------------------
# Pemuatan assembly
# ---------------------------------------------------------------------------
def load_tom(dll_dir: str | Path | None = None) -> tuple[Any, Any, Any]:
    """Muat TOM dari ``libs/tom`` dan kembalikan ``(Server, AccessToken, DateTimeOffset)``."""
    global _TOM
    if _TOM is not None and dll_dir is None:
        return _TOM

    folder = Path(dll_dir) if dll_dir else TOM_DIR
    main_dll = folder / "Microsoft.AnalysisServices.Tabular.dll"
    if not main_dll.exists():
        raise TomError(
            f"DLL TOM tidak ditemukan: {main_dll}. "
            "Pasang ulang aplikasi atau jalankan dari source dengan folder libs/tom."
        )

    dlls = sorted(folder.rglob("*.dll"))
    blocked = unblock_dotnet_assemblies(pythonnet_assembly(), *dlls)

    try:
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
        import clr  # pythonnet

        clr.AddReference("Microsoft.AnalysisServices.Tabular")
        clr.AddReference("Microsoft.AnalysisServices.Tabular.Json")

        from Microsoft.AnalysisServices import AccessToken
        from Microsoft.AnalysisServices.Tabular import Server
        from System import DateTimeOffset
    except Exception as exc:  # noqa: BLE001 - pesan .NET tidak seragam
        if blocked:
            raise TomError(_blocked_assembly_message(blocked, str(exc))) from exc
        raise TomError(
            f"Assembly TOM tidak bisa dimuat dari {folder}: {exc}"
        ) from exc

    loaded = (Server, AccessToken, DateTimeOffset)
    if dll_dir is None:
        _TOM = loaded
    return loaded


# ---------------------------------------------------------------------------
# Koneksi
# ---------------------------------------------------------------------------
def build_connection_string(endpoint: str, dataset: str) -> str:
    """Bangun connection string MSOLAP read-write tanpa token.

    Endpoint boleh berupa URL ``powerbi://``/``asazure://`` atau connection
    string lengkap. ``?readonly`` dibuang karena refresh membutuhkan akses
    tulis. Token dipasang lewat ``Server.AccessToken``, bukan kredensial di
    connection string.
    """
    data_source = readwrite_endpoint(endpoint)
    if not data_source:
        raise TomError("Endpoint XMLA kosong; koneksi TOM tidak bisa dibuat.")
    catalog = str(dataset or "").strip()
    if not catalog:
        raise TomError("Nama semantic model kosong; koneksi TOM tidak bisa dibuat.")

    if "=" in data_source:
        connection = data_source
    else:
        connection = f'Provider=MSOLAP;Data Source="{data_source}";'

    if "initial catalog=" not in connection.lower():
        escaped = catalog.replace('"', '""')
        connection = f'{connection}Initial Catalog="{escaped}";'
    if "application name=" not in connection.lower():
        connection = f"{connection}Application Name={APPLICATION_NAME};"
    return connection


@contextmanager
def connect_server(
    endpoint: str,
    dataset: str,
    tokens: Any,
    *,
    dll_dir: str | Path | None = None,
    server_cls: Any | None = None,
    access_token_cls: Any | None = None,
    offset_factory: Any | None = None,
    wrap_expired: Any | None = None,
) -> Iterator[Any]:
    """Buka TOM ``Server`` dengan access token dan tutup di ``finally``.

    ``server_cls``/``access_token_cls``/``offset_factory`` bisa di-inject oleh
    uji tanpa .NET. ``tokens`` adalah :class:`core.auth.EntraTokens`.
    """
    if server_cls is None:
        server_cls, loaded_token, loaded_offset = load_tom(dll_dir)
        access_token_cls = access_token_cls or loaded_token
        offset_factory = offset_factory or loaded_offset.FromUnixTimeSeconds
    if access_token_cls is None or offset_factory is None:
        _server, loaded_token, loaded_offset = load_tom(dll_dir)
        access_token_cls = access_token_cls or loaded_token
        offset_factory = offset_factory or loaded_offset.FromUnixTimeSeconds

    def build(token: Any) -> Any:
        return access_token_cls(
            token.value, offset_factory(int(token.expires_on)), None
        )

    server = server_cls()
    try:
        server.AccessToken = build(tokens.get(POWERBI_SCOPE))

        def on_expired(_expired: Any) -> Any:
            return build(tokens.get(POWERBI_SCOPE, force=True))

        wrapper = wrap_expired
        if wrapper is None:
            from System import Func

            wrapper = lambda function: Func[access_token_cls, access_token_cls](function)  # noqa: E731
        try:
            server.OnAccessTokenExpired = wrapper(on_expired)
        except Exception:  # noqa: BLE001 - event opsional pada TOM lama
            pass

        try:
            server.Connect(build_connection_string(endpoint, dataset))
        except Exception as exc:  # noqa: BLE001 - pesan koneksi perlu konteks
            raise TomError(
                f"Koneksi XMLA ke '{dataset}' gagal: {exc}\n"
                "Pastikan workspace berada di kapasitas Premium/PPU/Fabric, "
                "XMLA endpoint Read Write, dan service principal punya akses "
                "Member/Admin ke workspace."
            ) from exc
        yield server
    finally:
        dispose = getattr(server, "Dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:  # noqa: BLE001 - dispose bersifat best-effort
                pass


# ---------------------------------------------------------------------------
# Range partisi (best-effort)
# ---------------------------------------------------------------------------
_DATE_LITERAL = re.compile(
    r"#(?:datetime|date)\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})",
    re.IGNORECASE,
)
_ISO_LITERAL = re.compile(
    r"\b((?:19|20)\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"
)
_MONTH_LITERAL = re.compile(
    r"\b((?:19|20)\d{2})[-/](\d{1,2})(?![-/]\d{1,2})\b"
)
_YEAR_LITERAL = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass(frozen=True)
class PartitionRange:
    start: str = ""
    end: str = ""
    label: str = ""
    source: str = ""


@dataclass(frozen=True)
class PartitionInfo:
    table: str
    name: str
    state: str
    mode: str
    data_view: str
    source_type: str
    expression: str
    description: str
    modified_time: str
    refreshed_time: str
    is_calculated: bool
    range: PartitionRange = PartitionRange()


def _iso_date(year: str, month: str, day: str) -> str:
    try:
        value = date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return ""
    return value.isoformat()


def _date_tokens(text: str) -> list[tuple[int, str]]:
    tokens: list[tuple[int, str]] = []
    for match in _DATE_LITERAL.finditer(text):
        value = _iso_date(match.group(1), match.group(2), match.group(3))
        if value:
            tokens.append((match.start(), value))
    for match in _ISO_LITERAL.finditer(text):
        value = _iso_date(match.group(1), match.group(2), match.group(3))
        if value:
            tokens.append((match.start(), value))
    tokens.sort(key=lambda item: item[0])
    return tokens


def _literal_after(text: str, marker: str) -> str:
    index = text.find(marker)
    if index < 0:
        return ""
    window = text[index : index + 260]
    tokens = _date_tokens(window)
    return tokens[0][1] if tokens else ""


def _range_label(start: str, end: str, source: str) -> PartitionRange:
    if start and end and start != end:
        label = f"{start} \u2192 {end}"
    elif start and end:
        label = start
    elif start:
        label = f"from {start}"
    elif end:
        label = f"until {end}"
    else:
        label = ""
    return PartitionRange(start=start, end=end, label=label, source=source)


def parse_partition_range(name: str, expression: str) -> PartitionRange:
    """Ambil rentang partisi dari ekspresi M atau nama (best-effort).

    TOM tidak menyediakan properti range. Nilai diambil dari literal tanggal
    di sekitar ``RangeStart``/``RangeEnd``, lalu dari tanggal pada nama partisi.
    Bila tidak ada, hasilnya kosong dan UI menampilkan ``-`` — jangan mengarang
    rentang.
    """
    text = str(expression or "")
    start = _literal_after(text, "RangeStart")
    end = _literal_after(text, "RangeEnd")

    if start or end:
        return _range_label(start, end, "M")

    if "RangeStart" not in text and "RangeEnd" not in text:
        tokens = [value for _index, value in _date_tokens(text)]
        if len(tokens) >= 2:
            return _range_label(tokens[0], tokens[-1], "M")
        if len(tokens) == 1:
            return _range_label(tokens[0], "", "M")

    name_text = str(name or "")
    name_tokens = [value for _index, value in _date_tokens(name_text)]
    if len(name_tokens) >= 2:
        return _range_label(name_tokens[0], name_tokens[-1], "name")
    if len(name_tokens) == 1:
        return _range_label(name_tokens[0], "", "name")

    months = [
        f"{match.group(1)}-{int(match.group(2)):02d}"
        for match in _MONTH_LITERAL.finditer(name_text)
        if 1 <= int(match.group(2)) <= 12
    ]
    if len(months) >= 2:
        return _range_label(months[0], months[-1], "name")
    if len(months) == 1:
        return _range_label(months[0], "", "name")

    year = _YEAR_LITERAL.search(name_text)
    if year:
        return _range_label(year.group(1), "", "name")
    return PartitionRange()


# ---------------------------------------------------------------------------
# Inventaris
# ---------------------------------------------------------------------------
def _datetime_text(value: Any) -> str:
    if value is None:
        return ""
    year = getattr(value, "Year", None)
    if year is not None:
        try:
            if int(year) <= 1900:
                return ""
        except (TypeError, ValueError):
            pass
    to_string = getattr(value, "ToString", None)
    if callable(to_string):
        try:
            return str(to_string("yyyy-MM-dd HH:mm:ss"))
        except Exception:  # noqa: BLE001 - format tanggal berbeda antar versi
            pass
    return str(value)


def _enum_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _source_type(source: Any) -> str:
    if source is None:
        return "Push"
    get_type = getattr(source, "GetType", None)
    if callable(get_type):
        try:
            return str(get_type().Name)
        except Exception:  # noqa: BLE001
            pass
    return type(source).__name__


def _source_expression(source: Any) -> str:
    for attribute in ("Expression", "Query"):
        value = getattr(source, attribute, "")
        if value:
            return str(value)
    return ""


def list_partitions(server: Any, dataset: str) -> list[PartitionInfo]:
    """Baca semua partisi satu dataset dari koneksi TOM yang sudah terbuka."""
    try:
        database = server.Databases.GetByName(dataset)
    except Exception as exc:  # noqa: BLE001 - beri daftar nama yang tersedia
        try:
            available = [str(item.Name) for item in server.Databases]
        except Exception:  # noqa: BLE001
            available = []
        detail = f" Dataset tersedia: {', '.join(available)}." if available else ""
        raise TomError(f"Dataset '{dataset}' tidak ditemukan.{detail}") from exc

    rows: list[PartitionInfo] = []
    try:
        tables = list(database.Model.Tables)
    except Exception as exc:  # noqa: BLE001
        raise TomError(f"Tabel model '{dataset}' tidak bisa dibaca: {exc}") from exc

    for table in tables:
        table_name = str(table.Name)
        try:
            partitions = list(table.Partitions)
        except Exception as exc:  # noqa: BLE001
            raise TomError(
                f"Partisi tabel '{table_name}' tidak bisa dibaca: {exc}"
            ) from exc
        for partition in partitions:
            source = getattr(partition, "Source", None)
            source_type = _source_type(source)
            expression = _source_expression(source)
            name = str(partition.Name)
            rows.append(
                PartitionInfo(
                    table=table_name,
                    name=name,
                    state=_enum_text(getattr(partition, "State", "")),
                    mode=_enum_text(getattr(partition, "Mode", "")),
                    data_view=_enum_text(getattr(partition, "DataView", "")),
                    source_type=source_type,
                    expression=expression,
                    description=str(getattr(partition, "Description", "") or ""),
                    modified_time=_datetime_text(
                        getattr(partition, "ModifiedTime", None)
                    ),
                    refreshed_time=_datetime_text(
                        getattr(partition, "RefreshedTime", None)
                    ),
                    is_calculated="Calculated" in source_type,
                    range=parse_partition_range(name, expression),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# TMSL refresh
# ---------------------------------------------------------------------------
def normalize_refresh_type(value: str) -> str:
    """Normalisasi nama refresh type; nilai asing ditolak."""
    key = str(value or "").strip().lower().replace("_", "").replace("-", "")
    try:
        return REFRESH_TYPES[key]
    except KeyError as exc:
        allowed = ", ".join(REFRESH_TYPE_ORDER)
        raise TomError(
            f"Jenis refresh tidak dikenal: {value!r}. Pilihan: {allowed}."
        ) from exc


def _normalize_targets(
    targets: Iterable[tuple[str, str] | Mapping[str, str]],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in targets:
        if isinstance(item, Mapping):
            table = str(item.get("table") or "").strip()
            partition = str(item.get("partition") or "").strip()
        else:
            try:
                table, partition = item
            except (TypeError, ValueError) as exc:
                raise TomError(
                    "Target partisi harus berisi pasangan (table, partition)."
                ) from exc
            table = str(table or "").strip()
            partition = str(partition or "").strip()
        if not table or not partition:
            raise TomError("Nama tabel dan partisi tidak boleh kosong.")
        key = (table, partition)
        if key not in seen:
            seen.add(key)
            result.append(key)
    if not result:
        raise TomError("Pilih minimal satu partisi untuk diproses.")
    return result


def validate_refresh_targets(
    refresh_type: str, partitions: Sequence[PartitionInfo]
) -> str:
    """Validasi kombinasi refresh type dan partisi terpilih.

    ``add`` tidak berlaku untuk calculated partition atau partisi DirectQuery.
    ``defragment`` berlaku untuk tabel, jadi targetnya dikirim tanpa nama
    partisi oleh :func:`build_refresh_tmsl`.
    """
    normalized = normalize_refresh_type(refresh_type)
    if normalized != "add":
        return normalized
    for partition in partitions:
        if partition.is_calculated:
            raise TomError(
                f"Refresh 'add' tidak berlaku untuk calculated partition "
                f"'{partition.table}' / '{partition.name}'."
            )
        if partition.mode.lower() == "directquery":
            raise TomError(
                f"Refresh 'add' tidak berlaku untuk partition DirectQuery "
                f"'{partition.table}' / '{partition.name}'."
            )
    return normalized


def build_refresh_tmsl(
    dataset: str,
    targets: Iterable[tuple[str, str] | Mapping[str, str]],
    refresh_type: str = "full",
) -> str:
    """Bangun TMSL ``refresh`` untuk satu atau banyak partisi.

    ``defragment`` mengirim objek tabel tanpa ``partition`` karena perintah itu
    berlaku pada level tabel, bukan partisi.
    """
    catalog = str(dataset or "").strip()
    if not catalog:
        raise TomError("Nama dataset TMSL tidak boleh kosong.")
    normalized = normalize_refresh_type(refresh_type)
    pairs = _normalize_targets(targets)

    if normalized == "defragment":
        tables: list[str] = []
        for table, _partition in pairs:
            if table not in tables:
                tables.append(table)
        objects = [{"database": catalog, "table": table} for table in tables]
    else:
        objects = [
            {"database": catalog, "table": table, "partition": partition}
            for table, partition in pairs
        ]

    payload = {"refresh": {"type": normalized, "objects": objects}}
    return json.dumps(payload, ensure_ascii=False)


def execute_refresh(server: Any, tmsl: str) -> Any:
    """Eksekusi TMSL sebagai XMLA ``<Statement>`` dan gagal bila ada error."""
    xmla = f"<Statement>{escape(tmsl)}</Statement>"
    try:
        results = server.Execute(xmla)
    except Exception as exc:  # noqa: BLE001 - pengalaman server beragam
        raise TomError(f"Perintah refresh TMSL gagal: {exc}") from exc
    if bool(getattr(results, "ContainsErrors", False)):
        raise TomError(f"Perintah refresh TMSL mengembalikan error: {results}")
    return results

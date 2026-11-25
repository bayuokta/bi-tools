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

Tipe data, parser range, dan validasi TMSL berada di
:mod:`core.partition_plan` yang bebas CLR. Proses server tidak boleh memuat
modul ini: TOM dan ADOMD memakai versi assembly ``Microsoft.AnalysisServices``
yang tidak kompatibel dalam satu proses.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from xml.sax.saxutils import escape

from .auth import POWERBI_SCOPE
from .partition_plan import (  # noqa: F401 - re-export untuk pemanggil lama
    REFRESH_TYPE_ORDER,
    REFRESH_TYPES,
    PartitionInfo,
    PartitionRange,
    TomError,
    build_refresh_tmsl,
    normalize_refresh_type,
    parse_partition_range,
    validate_refresh_targets,
)
from .paths import APP_DIR
from .xmla_client import (
    INTERACTIVE_LOGIN_PROPS,
    _blocked_assembly_message,
    register_assembly_resolver,
    pythonnet_assembly,
    readwrite_endpoint,
    unblock_dotnet_assemblies,
)

ROOT = APP_DIR
TOM_DIR = ROOT / "libs" / "tom"
APPLICATION_NAME = "BI Tools"

_TOM: tuple[Any, Any, Any] | None = None


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

        if str(folder.parent) not in sys.path:
            sys.path.insert(0, str(folder.parent))
        register_assembly_resolver([folder, folder.parent])
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
def build_connection_string(
    endpoint: str, dataset: str, *, interactive: bool = False
) -> str:
    """Bangun connection string MSOLAP read-write tanpa token.

    Endpoint boleh berupa URL ``powerbi://``/``asazure://`` atau connection
    string lengkap. ``?readonly`` dibuang karena refresh membutuhkan akses
    tulis. Token dipasang lewat ``Server.AccessToken``, bukan kredensial di
    connection string. Pada ``interactive=True`` autentikasi diserahkan ke
    MSOLAP (akun 365 tanpa client id).
    """
    data_source = readwrite_endpoint(endpoint)
    if not data_source:
        raise TomError("Endpoint XMLA kosong; koneksi TOM tidak bisa dibuat.")
    catalog = str(dataset or "").strip()
    if not catalog:
        raise TomError("Nama semantic model kosong; koneksi TOM tidak bisa dibuat.")

    if interactive:
        # Samakan dengan contoh pbi_one_login: URL PaaS polos, tanpa quote,
        # tanpa Provider, dan dengan Connect Timeout.
        if "=" in data_source:
            connection = data_source
            if "initial catalog=" not in connection.lower():
                connection = f'{connection};Initial Catalog={catalog}'
        else:
            connection = (
                f"Data Source={data_source};Initial Catalog={catalog};"
                "Connect Timeout=60;"
            )
        if "interactive login=" not in connection.lower():
            connection = f"{connection}{INTERACTIVE_LOGIN_PROPS}"
        if "authentication=" not in connection.lower():
            connection = f"{connection}Authentication=ActiveDirectoryInteractive;"
        return connection

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
    tokens: Any | None,
    *,
    dll_dir: str | Path | None = None,
    server_cls: Any | None = None,
    access_token_cls: Any | None = None,
    offset_factory: Any | None = None,
    wrap_expired: Any | None = None,
    interactive: bool = False,
) -> Iterator[Any]:
    """Buka TOM ``Server`` dengan access token atau login interaktif MSOLAP.

    ``server_cls``/``access_token_cls``/``offset_factory`` bisa di-inject oleh
    uji tanpa .NET. ``tokens`` adalah :class:`core.auth.EntraTokens` pada mode
    service principal; ``interactive=True`` tidak memakai token sama sekali.
    """
    if server_cls is None:
        server_cls, loaded_token, loaded_offset = load_tom(dll_dir)
        access_token_cls = access_token_cls or loaded_token
        offset_factory = offset_factory or loaded_offset.FromUnixTimeSeconds
    if not interactive and (access_token_cls is None or offset_factory is None):
        _server, loaded_token, loaded_offset = load_tom(dll_dir)
        access_token_cls = access_token_cls or loaded_token
        offset_factory = offset_factory or loaded_offset.FromUnixTimeSeconds

    def build(token: Any) -> Any:
        return access_token_cls(
            token.value, offset_factory(int(token.expires_on)), None
        )

    server = server_cls()
    try:
        if not interactive:
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
            server.Connect(
                build_connection_string(endpoint, dataset, interactive=interactive)
            )
        except Exception as exc:  # noqa: BLE001 - pesan koneksi perlu konteks
            hint = (
                "Akun 365 perlu akses workspace dan XMLA endpoint Read Write."
                if interactive
                else "XMLA endpoint Read Write, dan service principal punya akses "
                "Member/Admin ke workspace."
            )
            raise TomError(
                f"Koneksi XMLA ke '{dataset}' gagal: {exc}\n"
                "Pastikan workspace berada di kapasitas Premium/PPU/Fabric, "
                + hint
            ) from exc
        yield server
    finally:
        dispose = getattr(server, "Dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:  # noqa: BLE001 - dispose bersifat best-effort
                pass


@contextmanager
def connect_desktop_server(
    port: int,
    dataset: str,
    *,
    dll_dir: str | Path | None = None,
    server_cls: Any | None = None,
) -> Iterator[Any]:
    """Buka TOM ke instance Power BI Desktop (tanpa token)."""
    if server_cls is None:
        server_cls, _token, _offset = load_tom(dll_dir)
    catalog = str(dataset or "").strip()
    if not catalog:
        raise TomError("Nama semantic model Desktop kosong.")
    server = server_cls()
    connection = (
        f'Provider=MSOLAP;Data Source="localhost:{int(port)}";'
        f'Initial Catalog="{escape(catalog)}";Application Name={APPLICATION_NAME};'
    )
    try:
        try:
            server.Connect(connection)
        except Exception as exc:  # noqa: BLE001
            raise TomError(
                f"Koneksi TOM ke Desktop localhost:{int(port)} gagal: {exc}"
            ) from exc
        yield server
    finally:
        dispose = getattr(server, "Dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:  # noqa: BLE001
                pass


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
# Eksekusi TMSL
# ---------------------------------------------------------------------------
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

"""
Klien XMLA minimal untuk semantic model Power BI (ADOMD + DMV).

Dipakai oleh extract_model_metadata.py. Read-only: hanya SELECT ke DMV.
Tidak menulis apa pun ke model.

Catatan penting:
- DLL ADOMD dimuat lewat path absolut (pyadomd gagal tanpa DLL di PATH).
- Setiap reader WAJIB ditutup. Jika tidak, koneksi ikut tertutup dan
  query berikutnya gagal dengan "The connection is not open".
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse

from .auth import POWERBI_SCOPE
from .paths import APP_DIR

# Aset mengikuti folder aplikasi (folder .exe saat dipaket), bukan lokasi modul:
# saat frozen, modul berada di _internal\ sehingga DLL tidak akan ditemukan.
ROOT = APP_DIR
DEFAULT_DLL = ROOT / "libs" / "Microsoft.AnalysisServices.AdomdClient.dll"
DMV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CLOUD_XMLA = ("powerbi://", "asazure://")
INTERACTIVE_LOGIN_PROPS = "Interactive Login=Always; Identity Mode=Connection;"
INTERACTIVE_REUSE_PROPS = "Interactive Login=Enabled; Identity Mode=Connection;"


class XmlaError(RuntimeError):
    """Kegagalan koneksi / query XMLA."""


_ADOMD: tuple[Any, Any, Any] | None = None

# Mark of the Web: berkas hasil unduhan ZIP ditandai Windows dengan stream
# alternatif ini, dan .NET Framework menolak memuat assembly bertanda tersebut
# (HRESULT 0x80131515). Gejalanya menyesatkan: pythonnet hanya melaporkan
# "Failed to resolve Python.Runtime.Loader.Initialize".
ZONE_IDENTIFIER = ":Zone.Identifier"


def zone_marked(path: Path) -> bool:
    """True bila berkas Windows masih bertanda "berasal dari internet"."""
    if os.name != "nt":
        return False
    try:
        os.stat(f"{path}{ZONE_IDENTIFIER}")
    except OSError:
        return False
    return True


def unblock_file(path: Path) -> bool:
    """Hapus Mark of the Web dari satu berkas; True bila bersih setelahnya."""
    if os.name != "nt" or not zone_marked(path):
        return True
    try:
        os.remove(f"{path}{ZONE_IDENTIFIER}")
    except OSError:
        return False
    return not zone_marked(path)


def pythonnet_assembly() -> Path | None:
    """Lokasi ``Python.Runtime.dll`` milik pythonnet (juga saat dipaket)."""
    try:
        import pythonnet
    except ImportError:
        return None
    module_file = getattr(pythonnet, "__file__", None)
    if module_file:
        return Path(module_file).parent / "runtime" / "Python.Runtime.dll"
    return ROOT / "_internal" / "pythonnet" / "runtime" / "Python.Runtime.dll"


def unblock_dotnet_assemblies(*paths: Path | None) -> list[Path]:
    """Buka blokir assembly .NET; kembalikan yang masih tidak bisa dimuat."""
    blocked: list[Path] = []
    for path in paths:
        if path is None or not path.exists():
            continue
        unblock_file(path)
        if zone_marked(path):
            blocked.append(path)
    return blocked


def _blocked_assembly_message(paths: list[Path], detail: str = "") -> str:
    listing = "\n".join(f"  - {path}" for path in paths)
    message = (
        "Berkas .NET aplikasi masih ditandai berasal dari internet "
        "(Mark of the Web) dan Windows menolak memuatnya:\n"
        f"{listing}\n"
        "Jalankan PowerShell berikut satu kali, lalu ulangi:\n"
        f'  Get-ChildItem -Recurse -Path "{ROOT}" | Unblock-File\n'
        "Cara lain: klik kanan ZIP -> Properties -> Unblock sebelum ekstrak, "
        "atau pakai installer (BI Tools Setup) yang tidak menandai berkas."
    )
    if detail:
        message += f"\nDetail: {detail}"
    return message



_ASSEMBLY_RESOLVER_READY = False


def register_assembly_resolver(directories: list[Path]) -> None:
    """Daftarkan resolver DLL .NET (ADOMD + MSAL native) satu kali per proses."""
    global _ASSEMBLY_RESOLVER_READY
    if _ASSEMBLY_RESOLVER_READY:
        return
    try:
        from System import AppDomain
        from System.Reflection import Assembly
    except Exception:  # noqa: BLE001 - pythonnet belum siap
        return

    folders = [Path(item) for item in directories if Path(item).is_dir()]

    def _resolve(_sender: Any, args: Any) -> Any:
        try:
            simple = str(args.Name).split(",")[0].strip()
        except Exception:  # noqa: BLE001
            return None
        for folder in folders:
            candidate = folder / f"{simple}.dll"
            if candidate.is_file():
                try:
                    return Assembly.LoadFrom(str(candidate))
                except Exception:  # noqa: BLE001 - coba folder berikutnya
                    continue
        return None

    AppDomain.CurrentDomain.AssemblyResolve += _resolve
    _ASSEMBLY_RESOLVER_READY = True


def load_adomd(dll_path: str | Path | None = None) -> tuple[Any, Any, Any]:
    """Muat assembly ADOMD. Return (AdomdConnection, AdomdCommand, DBNull)."""
    global _ADOMD
    if _ADOMD is not None:
        return _ADOMD

    path = Path(dll_path) if dll_path else DEFAULT_DLL
    if not path.exists():
        raise XmlaError(f"DLL ADOMD tidak ditemukan: {path}")

    folders = [path.parent]
    tom_dir = path.parent / "tom"
    if tom_dir.is_dir():
        folders.append(tom_dir)
    blocked = unblock_dotnet_assemblies(
        pythonnet_assembly(),
        *[dll for folder in folders for dll in folder.glob("*.dll")],
    )

    try:
        import clr  # pythonnet
        for folder in folders:
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
        register_assembly_resolver(folders)
        clr.AddReference(str(path))
        from Microsoft.AnalysisServices.AdomdClient import AdomdCommand, AdomdConnection
        from System import DBNull
    except Exception as exc:  # noqa: BLE001 - pesan .NET tidak seragam
        if blocked:
            raise XmlaError(_blocked_assembly_message(blocked, str(exc))) from exc
        raise

    _ADOMD = (AdomdConnection, AdomdCommand, DBNull)
    return _ADOMD


_CHANNEL_CACHE_CLEARED = False


def _is_channel_cache_error(exc: BaseException) -> bool:
    """Error deserialisasi cache controller HTTP milik ADOMD.

    Cache ``XmlaLibControllerCache`` disimpan di shared memory dan dipakai
    bersama semua proses di mesin. Entri yang ditulis ADOMD versi lain tidak
    bisa dibaca versi ini dan muncul sebagai ``Specified cast is not valid``
    di ``DeserializeFromGlobalObject``.
    """
    text = str(exc)
    if "Specified cast is not valid" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "HttpStream",
            "SharedMemoryCache",
            "DeserializeFromGlobalObject",
            "CreateControllerFromGlobalObject",
        )
    )


def _clear_adomd_channel_cache(*, force: bool = False) -> bool:
    """Kosongkan cache controller HTTP ADOMD (best-effort).

    Cache ini hanya mempercepat handshake, jadi mengosongkannya aman. Refleksi
    dipakai karena API-nya internal dan bisa berubah antar versi ADOMD; semua
    kegagalan diabaikan. Return ``True`` bila pembersihan dijalankan.
    """
    global _CHANNEL_CACHE_CLEARED
    if _CHANNEL_CACHE_CLEARED and not force:
        return False
    _CHANNEL_CACHE_CLEARED = True
    try:
        import clr  # pythonnet
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection
        from System.Reflection import BindingFlags

        assembly = clr.GetClrType(AdomdConnection).Assembly
        manager = assembly.GetType(
            "Microsoft.AnalysisServices.AdomdClient.HttpStream+HttpChannelManager"
        )
        if manager is None:
            return False
        flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static
        active = manager.GetField("activeControllers", flags).GetValue(None)
        if active is not None:
            try:
                active.Clear()
            except Exception:  # noqa: BLE001 - cache hanya optimasi
                pass
        controllers = manager.GetField("controllers", flags).GetValue(None)
        if controllers is not None:
            try:
                controllers.ClearResources()
            except Exception:  # noqa: BLE001
                pass
        cache = manager.GetField("controllerCache", flags).GetValue(None)
        if cache is not None:
            try:
                cache.Clear()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001 - jangan gagalkan koneksi karena cache
        return False
    return True


def _channel_cache_message(exc: BaseException) -> str:
    return (
        "Koneksi XMLA gagal karena cache channel ADOMD tidak kompatibel "
        "dengan versi lain di mesin ini (Specified cast is not valid).\n"
        "Tutup aplikasi lain yang memakai ADOMD/XMLA (Power BI Desktop, "
        "DAX Studio, Tabular Editor, SSMS), lalu coba lagi.\n"
        f"Detail: {exc}"
    )


def _clean(value: Any) -> Any:
    """Ubah DBNull menjadi None."""
    if value is None:
        return None
    if _ADOMD is not None and value is _ADOMD[2].Value:
        return None
    return value


def label(value: Any, mapping: dict[int, str], prefix: str = "value") -> str:
    """Terjemahkan enum numerik ke label. Nilai tak dikenal -> '<prefix>_<n>'."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    try:
        key = int(value)
    except (TypeError, ValueError):
        return str(value)
    return mapping.get(key, f"{prefix}_{key}")


def workspace_roots() -> list[Path]:
    """Folder workspace Power BI Desktop yang mungkin dipakai.

    Power BI Desktop dari installer klasik memakai ``%LOCALAPPDATA%\\Microsoft\\Power BI Desktop``.
    Versi Microsoft Store memakai ``%USERPROFILE%\\Microsoft\\Power BI Desktop Store App``
    (beberapa build lama menyimpannya di LocalCache paket). Keduanya diperiksa.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    local = Path(base)
    store_cache = (
        local
        / "Packages"
        / "Microsoft.MicrosoftPowerBIDesktop_8wekyb3d8bbwe"
        / "LocalCache"
        / "Local"
        / "Microsoft"
        / "Power BI Desktop"
    )
    return [
        local / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces",
        Path.home() / "Microsoft" / "Power BI Desktop Store App" / "AnalysisServicesWorkspaces",
        store_cache / "AnalysisServicesWorkspaces",
    ]


def _read_port(path: Path) -> int | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for encoding in ("utf-16-le", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding, errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        digits = "".join(char for char in text if char.isdigit())
        if digits:
            return int(digits)
    return None


def detect_ports() -> list[tuple[int, Path]]:
    """Port instance Power BI Desktop lokal, terbaru lebih dulu."""
    found: list[tuple[float, int, Path]] = []
    for root in workspace_roots():
        if not root.is_dir():
            continue
        for path in root.glob("*/Data/msmdsrv.port.txt"):
            port = _read_port(path)
            if not port:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            found.append((mtime, port, path))

    found.sort(key=lambda item: item[0], reverse=True)
    seen: set[int] = set()
    result: list[tuple[int, Path]] = []
    for _, port, path in found:
        if port in seen:
            continue
        seen.add(port)
        result.append((port, path))
    return result


@dataclass
class XmlaClient:
    connection: Any
    command_cls: Any
    connection_string: str
    server_version: str = ""
    endpoint: str = ""
    catalog: str = ""
    catalog_info: dict[str, Any] = field(default_factory=dict)

    # -- query -------------------------------------------------------------
    def query_sql(self, sql: str, timeout: int | None = None) -> list[dict[str, Any]]:
        command = self.command_cls(sql, self.connection)
        if timeout is not None:
            command.CommandTimeout = int(timeout)
        reader = command.ExecuteReader()
        try:
            names = [reader.GetName(index) for index in range(reader.FieldCount)]
            rows: list[dict[str, Any]] = []
            while reader.Read():
                rows.append({name: _clean(reader[index]) for index, name in enumerate(names)})
            return rows
        finally:
            reader.Close()

    def query(self, dmv: str) -> list[dict[str, Any]]:
        if not DMV_RE.match(dmv):
            raise XmlaError(f"Nama DMV tidak valid: {dmv}")
        return self.query_sql(f"SELECT * FROM $SYSTEM.{dmv}")

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        try:
            self.connection.Close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "XmlaClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()



def _interactive_connection_string(
    endpoint: str, catalog: str | None = None
) -> str:
    """Connection string gaya contoh MSOLAP: tanpa quote dan tanpa ?readonly.

    ADOMD 19.120 hanya mau memakai login interaktif bila Data Source berupa
    URL PaaS polos (seperti contoh ``pbi_one_login``); query ``?readonly`` dan
    nilai ber-quote membuatnya meminta access token eksternal.
    """
    text = str(endpoint or "").strip()
    if "=" in text:
        connection = text
    else:
        normalized = normalize_powerbi_endpoint(text, readonly=False)
        if normalized.startswith('Data Source="') and normalized.endswith('"'):
            url = normalized[len('Data Source="') : -1].replace('""', '"')
        else:
            url = normalized
        url = url.replace("?readonly", "").replace("&readonly", "")
        connection = f"Data Source={url}"
    if not connection.endswith(";"):
        connection += ";"
    if catalog and "initial catalog=" not in connection.lower():
        name = str(catalog)
        if ";" in name or '"' in name:
            name = '"' + name.replace('"', '""') + '"'
        connection += f"Initial Catalog={name};"
    if "connect timeout=" not in connection.lower():
        connection += "Connect Timeout=60;"
    return connection


def interactive_connection_string(
    connection_string: str, *, reuse: bool = False
) -> str:
    """Tambahkan properti login interaktif MSOLAP untuk endpoint cloud.

    Dipakai jalur akun 365 tanpa client id: token browser ditolak XMLA, jadi
    autentikasi diserahkan ke MSOLAP. ``reuse=True`` memakai
    ``Interactive Login=Enabled`` agar TOM memakai ulang identitas ADOMD.
    """
    if not _is_cloud(connection_string):
        return connection_string
    lowered = connection_string.lower()
    if "interactive login=" in lowered or "identity mode=" in lowered:
        return connection_string
    props = INTERACTIVE_REUSE_PROPS if reuse else INTERACTIVE_LOGIN_PROPS
    return connection_string.rstrip("; ") + ";" + props



def _call_on_sta(func: Any) -> Any:
    """Jalankan fungsi .NET di thread STA (dibutuhkan dialog MSOLAP)."""
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}
    try:
        from System.Threading import ApartmentState, Thread, ThreadStart
    except Exception:  # noqa: BLE001 - tanpa pythonnet, jalankan langsung
        return func()

    def target() -> None:
        try:
            result["value"] = func()
        except BaseException as exc:  # noqa: BLE001 - diteruskan ke pemanggil
            error["value"] = exc

    thread = Thread(ThreadStart(target))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _connect(
    connection_string: str,
    dll_path: str | Path | None = None,
    *,
    tokens: Any | None = None,
    scope: str = POWERBI_SCOPE,
    access_token_cls: Any | None = None,
    wrap_expired: Any | None = None,
    interactive: bool = False,
    reuse_identity: bool = False,
) -> XmlaClient:
    if interactive:
        connection_string = interactive_connection_string(
            connection_string, reuse=reuse_identity
        )
    connection_cls, command_cls, _ = load_adomd(dll_path)
    # Cache controller ADOMD dipakai bersama semua proses. Entri dari versi
    # ADOMD lain tidak bisa dibaca (Specified cast is not valid), jadi cache
    # dibersihkan sekali per proses sebelum koneksi pertama.
    _clear_adomd_channel_cache()

    def open_connection() -> Any:
        connection = connection_cls(connection_string)
        if tokens is not None and not interactive and _is_cloud(connection_string):
            attach_token(
                connection,
                tokens,
                scope=scope,
                access_token_cls=access_token_cls,
                wrap_expired=wrap_expired,
            )
        connection.Open()
        return connection

    def make_client(connection: Any) -> XmlaClient:
        return XmlaClient(
            connection=connection,
            command_cls=command_cls,
            connection_string=connection_string,
            server_version=str(getattr(connection, "ServerVersion", "") or ""),
        )

    if interactive and _is_cloud(connection_string):
        try:
            return make_client(_call_on_sta(open_connection))
        except Exception as exc:  # noqa: BLE001
            if _is_channel_cache_error(exc):
                _clear_adomd_channel_cache(force=True)
                return make_client(_call_on_sta(open_connection))
            raise

    for attempt in (1, 2):
        connection = connection_cls(connection_string)
        if tokens is not None and not interactive and _is_cloud(connection_string):
            attach_token(
                connection,
                tokens,
                scope=scope,
                access_token_cls=access_token_cls,
                wrap_expired=wrap_expired,
            )
        try:
            connection.Open()
        except Exception as exc:  # noqa: BLE001 - periksa jenis kegagalan
            try:
                connection.Close()
            except Exception:  # noqa: BLE001
                pass
            if not _is_channel_cache_error(exc):
                raise
            if attempt == 1:
                _clear_adomd_channel_cache(force=True)
                continue
            raise XmlaError(_channel_cache_message(exc)) from exc
        return make_client(connection)
    raise XmlaError("Koneksi XMLA tidak bisa dibuka.")


def _is_cloud(connection_string: str) -> bool:
    lowered = connection_string.lower()
    return any(marker in lowered for marker in CLOUD_XMLA)


# Akhiran ``" - <GUID>"`` dipakai Power BI untuk membedakan dua workspace yang
# namanya sama (lihat dokumentasi "Duplicate workspace names"). Nama workspace
# sendiri boleh mengandung ``" - "``, jadi hanya GUID lengkap yang dipisah.
WORKSPACE_GUID_RE = re.compile(
    r"^(?P<name>.+?)\s-\s(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


@dataclass(frozen=True)
class WorkspaceEndpoint:
    """Bagian penting endpoint XMLA: tenant, nama workspace, dan ID (opsional)."""

    tenant: str
    name: str
    workspace_id: str = ""


def parse_workspace_endpoint(value: str) -> WorkspaceEndpoint | None:
    """Baca ``powerbi://api.powerbi.com/v1.0/<tenant>/<nama workspace>``.

    Menerima URL polos maupun connection string lengkap (``Data Source=...``).
    Nama workspace di-percent-decode. Bila diakhiri ``" - <GUID>"`` (bentuk
    disambiguasi resmi untuk nama workspace duplikat), GUID dipisah ke
    ``workspace_id``. Kembalikan ``None`` bila nilainya bukan endpoint Power BI
    cloud.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if "=" in text:
        match = re.search(r'data\s+source\s*=\s*"?([^";]+)"?', text, re.IGNORECASE)
        if not match:
            return None
        text = match.group(1).strip()
    if urlparse(text).scheme.lower() != "powerbi":
        return None

    segments = [segment for segment in urlparse(text).path.split("/") if segment]
    # Path yang diharapkan: v1.0/<tenant>/<workspace>
    if len(segments) < 3:
        return None
    tenant = unquote(segments[-2]).strip()
    workspace = unquote(segments[-1]).strip()
    if not workspace:
        return None
    match = WORKSPACE_GUID_RE.match(workspace)
    if match:
        return WorkspaceEndpoint(
            tenant=tenant,
            name=match.group("name").strip(),
            workspace_id=match.group("id"),
        )
    return WorkspaceEndpoint(tenant=tenant, name=workspace)


def workspace_endpoint(
    tenant: str,
    name: str,
    workspace_id: str = "",
    *,
    disambiguate: bool = False,
) -> str:
    """Bangun URL XMLA workspace Power BI dari nama (dan ID bila perlu).

    ``disambiguate`` menambahkan ``" - <workspace_id>"``, bentuk yang dipakai
    Power BI saat ada workspace dengan nama sama. Hasil belum memuat
    ``?readonly``; :func:`normalize_powerbi_endpoint` yang menambahkannya.
    """
    workspace = str(name or "").strip()
    if not workspace:
        raise XmlaError("Nama workspace kosong; endpoint XMLA tidak bisa dibangun.")
    if disambiguate and workspace_id:
        workspace = f"{workspace} - {str(workspace_id).strip()}"
    part_tenant = str(tenant or "myorg").strip() or "myorg"
    return (
        "powerbi://api.powerbi.com/v1.0/"
        f"{quote(part_tenant, safe='')}/{quote(workspace, safe='')}"
    )


def normalize_powerbi_endpoint(value: str, *, readonly: bool = True) -> str:
    """Rapikan URL XMLA Power BI menjadi bagian connection string.

    Hanya menyentuh nilai berbentuk URL tanpa ``=``:

    - workspace di-percent-encode (spasi jadi ``%20``);
    - ``?readonly`` ditambahkan bila belum ada ``readonly``/``readwrite``;
    - hasil dibungkus ``Data Source="..."``.

    Connection string lengkap (mengandung ``=``) dan endpoint Desktop
    (``localhost:port``) dikembalikan apa adanya.
    """
    text = str(value or "").strip()
    if not text or "=" in text:
        return text
    lowered = text.lower()
    if not lowered.startswith(CLOUD_XMLA):
        return text

    parsed = urlparse(text)
    segments = parsed.path.split("/")
    if segments:
        segments[-1] = quote(unquote(segments[-1]), safe="")
    path = "/".join(segments)

    query = parsed.query
    if readonly and "readonly" not in query.lower() and "readwrite" not in query.lower():
        query = f"{query}&readonly" if query else "readonly"

    url = urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, query, parsed.fragment))
    return 'Data Source="{}"'.format(url.replace('"', '""'))


def readwrite_endpoint(value: str) -> str:
    """Kembalikan endpoint XMLA tanpa suffix ``?readonly``.

    Jalur tulis (TOM ``Server.Execute``) membutuhkan endpoint read-write.
    Endpoint turunan :func:`workspace_endpoint` tidak menambahkan query, tetapi
    nilai lama/katalog bisa membawa ``?readonly``; query itu harus dibuang agar
    Power BI tidak membuka koneksi baca-saja.
    """
    text = str(value or "").strip()
    if not text or "=" in text:
        return text
    if not text.lower().startswith(CLOUD_XMLA):
        return text
    parsed = urlparse(text)
    query = "&".join(
        part
        for part in parsed.query.split("&")
        if part and not part.lower().startswith(("readonly", "readwrite"))
    )
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


def connection_catalog(connection_string: str) -> str:
    """Nama catalog yang sudah tertulis di connection string (bila ada)."""
    match = re.search(
        r'initial\s+catalog\s*=\s*"?([^";]+)"?', connection_string, re.IGNORECASE
    )
    return match.group(1).strip() if match else ""


def _with_catalog(connection_string: str, catalog: str | None) -> str:
    if not catalog or "initial catalog=" in connection_string.lower():
        return connection_string
    escaped = str(catalog).replace('"', '""')
    return f'{connection_string};Initial Catalog="{escaped}"'


def attach_token(
    connection: Any,
    tokens: Any,
    *,
    scope: str = POWERBI_SCOPE,
    access_token_cls: Any | None = None,
    wrap_expired: Any | None = None,
    offset_factory: Any | None = None,
) -> None:
    """Pasang access token Power BI ke koneksi ADOMD (sebelum ``Open``).

    ``tokens`` adalah :class:`core.auth.EntraTokens`. Token yang dipakai sama
    dengan REST API Power BI, sehingga hanya ada satu login untuk semua jalur.
    ``access_token_cls``/``wrap_expired``/``offset_factory`` bisa di-inject oleh
    uji tanpa .NET.
    """
    if tokens is None:
        return
    token_cls = access_token_cls or _access_token_cls()
    offset = offset_factory or _datetime_offset

    def build(token: Any) -> Any:
        return token_cls(token.value, offset(int(token.expires_on)))

    connection.AccessToken = build(tokens.get(scope))

    def on_expired(_expired: Any) -> Any:
        return build(tokens.get(scope, force=True))

    wrapper = wrap_expired
    if wrapper is None:
        from System import Func

        wrapper = lambda function: Func[token_cls, token_cls](function)  # noqa: E731
    connection.OnAccessTokenExpired = wrapper(on_expired)


def _datetime_offset(epoch_seconds: int) -> Any:
    from System import DateTimeOffset

    return DateTimeOffset.FromUnixTimeSeconds(int(epoch_seconds))


def _access_token_cls() -> Any:
    load_adomd()
    from Microsoft.AnalysisServices.AdomdClient import AccessToken

    return AccessToken


def list_catalogs(client: XmlaClient) -> list[dict[str, Any]]:
    rows = client.query_sql("SELECT * FROM $SYSTEM.DBSCHEMA_CATALOGS")
    out: list[dict[str, Any]] = []
    for row in rows:
        upper = {str(key).upper(): value for key, value in row.items()}
        out.append(
            {
                "name": str(upper.get("CATALOG_NAME") or ""),
                "description": upper.get("DESCRIPTION") or "",
                "compatibility_level": upper.get("COMPATIBILITY_LEVEL"),
                "version": upper.get("VERSION"),
                "type": upper.get("TYPE"),
                "date_modified": upper.get("DATE_MODIFIED"),
                "roles": upper.get("ROLES"),
            }
        )
    return out


@dataclass(frozen=True)
class DesktopInstance:
    """Satu instance Power BI Desktop yang sedang terbuka dan memuat satu model."""

    port: int
    catalog: str
    model_name: str
    modified: str
    file_name: str = ""

    @property
    def label(self) -> str:
        name = self.file_name or self.model_name or "(tanpa nama)"
        stamp = f" - dibuka {self.modified}" if self.modified else ""
        return f"{name} - localhost:{self.port}{stamp}"


_WINDOW_TITLE_SCRIPT = (
    # -State Listen tidak dipakai: listener msmdsrv tidak selalu muncul sebagai "Listen"
    # di Get-NetTCPConnection, jadi cari pemilik port lalu cocokkan nama prosesnya.
    "$owners = Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue "
    "| Where-Object {{ $_.OwningProcess -ne 0 }} "
    "| Select-Object -ExpandProperty OwningProcess -Unique; "
    "foreach ($owner in $owners) {{ "
    "$proc = Get-CimInstance Win32_Process -Filter \"ProcessId=$owner\" -ErrorAction SilentlyContinue; "
    "if ($proc -and $proc.Name -eq 'msmdsrv.exe') {{ "
    "$parent = Get-Process -Id $proc.ParentProcessId -ErrorAction SilentlyContinue; "
    "if ($parent) {{ $parent.MainWindowTitle; break }} }} }}"
)
_DESKTOP_SUFFIX = " - Power BI Desktop"


def desktop_file_name(port: int) -> str:
    """Nama file report yang dibuka di instance Power BI Desktop pada port tersebut.

    Diambil dari judul jendela PBIDesktop: port -> proses msmdsrv -> proses induk.
    Mengembalikan "" bila tidak bisa dibaca (misalnya bukan Windows).
    """
    if sys.platform != "win32":
        return ""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOW_TITLE_SCRIPT.format(port=port)],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    title = completed.stdout.strip()
    if title.endswith(_DESKTOP_SUFFIX):
        title = title[: -len(_DESKTOP_SUFFIX)]
    return title.strip().lstrip("*").strip()


def list_instances(dll_path: str | Path | None = None) -> list[DesktopInstance]:
    """Daftar semua instance Power BI Desktop lokal beserta nama modelnya."""
    instances: list[DesktopInstance] = []
    for port, _ in detect_ports():
        try:
            base = _connect(f"Data Source=localhost:{port}", dll_path)
        except Exception:  # noqa: BLE001 - instance sudah ditutup, lewati
            continue
        try:
            catalogs = list_catalogs(base)
        except Exception:  # noqa: BLE001
            catalogs = []
        finally:
            base.close()

        file_name = desktop_file_name(port) if catalogs else ""
        for info in catalogs:
            name = info["name"]
            if not name:
                continue
            model_name = ""
            try:
                client = _connect(f"Data Source=localhost:{port};Initial Catalog={name}", dll_path)
                try:
                    rows = client.query("TMSCHEMA_MODEL")
                    model_name = str(rows[0].get("Name") or "") if rows else ""
                finally:
                    client.close()
            except Exception:  # noqa: BLE001 - nama tetap bisa ditampilkan tanpa model
                model_name = ""
            modified = info.get("date_modified")
            instances.append(
                DesktopInstance(
                    port=port,
                    catalog=name,
                    model_name=model_name,
                    modified=str(modified) if modified else "",
                    file_name=file_name,
                )
            )
    return instances


def open_client(
    endpoint: str | None = None,
    catalog: str | None = None,
    port: int | None = None,
    dll_path: str | Path | None = None,
    *,
    tokens: Any | None = None,
    readonly: bool = True,
    access_token_cls: Any | None = None,
    wrap_expired: Any | None = None,
    interactive: bool = False,
) -> XmlaClient:
    """Buka koneksi ke Desktop lokal atau endpoint eksplisit.

    Aturan pemilihan instance Desktop:
    - --port diberikan: hanya port itu yang dipakai (tanpa cadangan ke instance lain).
    - tanpa --port/--catalog dan lebih dari satu instance: error, pengguna harus memilih.
    - --catalog saja: dicari di semua instance yang terbuka.

    ``tokens`` (opsional) dipakai untuk endpoint XMLA Power BI/AS; instance
    Desktop lokal tidak diberi token.
    """
    candidates: list[tuple[str, str]] = []
    if endpoint:
        normalized = normalize_powerbi_endpoint(endpoint, readonly=readonly)
        connection_string = (
            normalized if "=" in normalized else f"Data Source={normalized}"
        )
        candidates.append((connection_string, endpoint))
    else:
        ports = detect_ports()
        if port:
            ports = [(port, Path())]
        elif len(ports) > 1 and not catalog:
            listing = "\n".join(f"  - localhost:{item[0]}" for item in ports)
            raise XmlaError(
                "Ada lebih dari satu instance Power BI Desktop yang terbuka. "
                "Pilih salah satu dengan --port atau --catalog:\n" + listing
            )
        if not ports:
            raise XmlaError(
                "Tidak ada instance Power BI Desktop yang berjalan.\n"
                "Buka file .pbix/.pbip di Power BI Desktop, lalu jalankan ulang script ini."
            )
        candidates = [(f"Data Source=localhost:{item[0]}", f"localhost:{item[0]}") for item in ports]

    errors: list[str] = []
    token_kwargs: dict[str, Any] = {}
    if tokens is not None:
        token_kwargs["tokens"] = tokens
    if access_token_cls is not None:
        token_kwargs["access_token_cls"] = access_token_cls
    if wrap_expired is not None:
        token_kwargs["wrap_expired"] = wrap_expired
    if interactive:
        token_kwargs["interactive"] = True

    # Jalur umum Service: catalog sudah diketahui, jadi cukup satu koneksi.
    # Ini penting untuk login MSOLAP interaktif agar dialog tidak muncul dua kali.
    if endpoint and catalog:
        if interactive:
            connection_string = _interactive_connection_string(endpoint, catalog)
        else:
            normalized = normalize_powerbi_endpoint(endpoint, readonly=readonly)
            connection_string = (
                normalized if "=" in normalized else f"Data Source={normalized}"
            )
            connection_string = _with_catalog(connection_string, catalog)
        client = _connect(
            connection_string,
            dll_path,
            **token_kwargs,
        )
        client.endpoint = endpoint
        client.catalog = catalog
        try:
            catalogs = list_catalogs(client)
            info = next(
                (item for item in catalogs if item["name"] == catalog), None
            )
            if info:
                client.catalog_info = dict(info)
        except Exception:  # noqa: BLE001 - info katalog opsional
            pass
        return client

    for connection_string, endpoint_label in candidates:
        base: XmlaClient | None = None
        try:
            base = _connect(connection_string, dll_path, **token_kwargs)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{endpoint_label}: {exc}")
            continue

        try:
            catalogs = list_catalogs(base)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{endpoint_label}: gagal membaca catalog ({exc})")
            base.close()
            continue
        finally:
            base.close()

        names = [item["name"] for item in catalogs if item["name"]]
        if not names:
            errors.append(f"{endpoint_label}: tidak ada catalog")
            continue

        requested = connection_catalog(connection_string) or catalog
        if requested:
            match = [name for name in names if name.lower() == requested.lower()]
            if not match:
                errors.append(
                    f"{endpoint_label}: catalog '{requested}' tidak ada "
                    f"(tersedia: {', '.join(names)})"
                )
                continue
            chosen = match[0]
        elif len(names) == 1:
            chosen = names[0]
        else:
            errors.append(
                f"{endpoint_label}: ada {len(names)} catalog, tentukan dengan --catalog "
                f"({', '.join(names[:6])}{'...' if len(names) > 6 else ''})"
            )
            continue

        info = next(item for item in catalogs if item["name"] == chosen)
        try:
            client = _connect(
                _with_catalog(connection_string, chosen),
                dll_path,
                **{**token_kwargs, "reuse_identity": True},
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{endpoint_label}/{chosen}: {exc}")
            continue

        client.endpoint = endpoint_label
        client.catalog = chosen
        client.catalog_info = info
        return client

    detail = "\n".join(f"  - {item}" for item in errors)
    raise XmlaError(f"Tidak bisa terhubung ke model.\n{detail}")

"""CLI ``bi-tools-sync``: sinkronisasi Admin API lalu terbitkan snapshot.

Perintah:

- ``run``        katalog workspace + lineage + katalog report + snapshot
- ``workspaces`` katalog workspace saja
- ``lineage``    scan lineage saja

Tanpa nama perintah, argumen dianggap milik ``run`` (kompatibel dengan
pemanggilan lama ``bi-tools-sync --snapshot-out ...``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.paths import data_dir

from .catalog import run_workspace_sync
from .flow import SyncOptions, run_sync
from .graph import GraphUploader, SharePointTarget
from .lineage import run_lineage_scan

COMMANDS = ("run", "workspaces", "lineage", "check")
MODES = ("auto", "admin", "member")

USAGE = """\
bi-tools-sync - program sync database bersama (service principal)

Pemakaian:
  bi-tools-sync [run] [opsi]        katalog + lineage + report + snapshot
  bi-tools-sync workspaces [opsi]   katalog workspace saja
  bi-tools-sync lineage [opsi]      scan lineage saja
  bi-tools-sync check [opsi]        cek site/library/folder SharePoint

Opsi umum:
  --database PATH       database kerja SQLite
  --mode auto|admin|member
  --env-file PATH       berkas .env kredensial service principal
  -h, --help            bantuan per perintah
"""


def _silent(_message: str) -> None:
    """Log default untuk pemanggil non-CLI."""


def _principal(args: argparse.Namespace) -> ServicePrincipal:
    if getattr(args, "env_file", ""):
        env_file = Path(args.env_file).expanduser()
        if not env_file.exists():
            raise ExtractionError(f"Berkas .env tidak ditemukan: {env_file}")
    else:
        default_env = Path.cwd() / ".env"
        env_file = default_env if default_env.exists() else None
    principal = ServicePrincipal.from_env(env_file)
    principal.validate()
    return principal


def _database(value: str, *, default: Path | None = None) -> Path:
    if value:
        return Path(value).expanduser()
    if default is not None:
        return default
    return data_dir() / "bi_tools_sync.db"


def _log(message: str) -> None:
    print(message, flush=True)


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bi-tools-sync run",
        description=(
            "Sinkronisasi katalog/lineage dengan service principal lalu "
            "menerbitkan snapshot SQLite untuk aplikasi interaktif."
        ),
    )
    parser.add_argument("--database", default="", help="database kerja lokal")
    parser.add_argument(
        "--snapshot-out",
        default="",
        help="file snapshot tujuan (folder share); default di samping database",
    )
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--full", action="store_true", help="lineage scan penuh")
    parser.add_argument(
        "--include-personal",
        action="store_true",
        help="sertakan My Workspace (hanya mode admin)",
    )
    parser.add_argument("--skip-catalog", action="store_true")
    parser.add_argument("--skip-lineage", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    parser.add_argument("--upload", action="store_true", help="upload snapshot ke SharePoint")
    parser.add_argument("--sharepoint-host", default="", help="hostname SharePoint")
    parser.add_argument("--sharepoint-site", default="", help="path site (mis. /teams/Data)")
    parser.add_argument("--sharepoint-library", default="", help="nama document library")
    parser.add_argument("--sharepoint-folder", default="", help="folder tujuan di library")
    parser.add_argument("--env-file", default="", help="berkas .env kredensial")
    return parser


def _workspaces_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bi-tools-sync workspaces",
        description="Sinkronkan daftar workspace ke SQLite (tanpa snapshot).",
    )
    parser.add_argument("--database", default="", help="database SQLite tujuan")
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--env-file", default="", help="berkas .env kredensial")
    parser.add_argument("--json", action="store_true", help="cetak ringkasan JSON")
    return parser


def _lineage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bi-tools-sync lineage",
        description="Scan lineage Power BI Service ke SQLite (tanpa snapshot).",
    )
    parser.add_argument("--database", default="", help="database SQLite tujuan")
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--full", action="store_true", help="paksa full scan")
    parser.add_argument(
        "--include-personal",
        action="store_true",
        help="sertakan My Workspace (hanya mode admin)",
    )
    parser.add_argument("--env-file", default="", help="berkas .env kredensial")
    parser.add_argument("--json", action="store_true", help="cetak ringkasan JSON")
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _target(args: argparse.Namespace) -> SharePointTarget | None:
    """Target SharePoint dari argumen; kosong berarti upload tidak dikonfigurasi."""
    host = str(getattr(args, "sharepoint_host", "") or os.environ.get("SP_HOSTNAME", ""))
    site = str(getattr(args, "sharepoint_site", "") or os.environ.get("SP_SITE_PATH", ""))
    library = str(
        getattr(args, "sharepoint_library", "") or os.environ.get("SP_DRIVE_NAME", "")
    )
    folder = str(
        getattr(args, "sharepoint_folder", "") or os.environ.get("SP_FOLDER", "")
    )
    if not host and not site:
        return None
    return SharePointTarget.from_values(host, site, library, folder)


def _cmd_run(argv: list[str]) -> int:
    args = _run_parser().parse_args(argv)
    principal = _principal(args)
    database = _database(args.database)
    snapshot = (
        Path(args.snapshot_out).expanduser()
        if args.snapshot_out
        else database.with_name("bi_tools_snapshot.db")
    )
    result = run_sync(
        SyncOptions(
            database=database,
            snapshot=snapshot,
            mode=args.mode,
            full=args.full,
            include_personal=args.include_personal,
            skip_catalog=args.skip_catalog,
            skip_lineage=args.skip_lineage,
            skip_reports=args.skip_reports,
            upload=args.upload,
            sharepoint=_target(args),
        ),
        principal,
        log=_log,
    )
    _log(f"Selesai dalam {result.duration_seconds:.1f} detik.")
    return 0


def _cmd_workspaces(argv: list[str]) -> int:
    args = _workspaces_parser().parse_args(argv)
    principal = _principal(args)
    database = _database(args.database, default=DEFAULT_DB)
    log = (lambda line: print(line, file=sys.stderr)) if args.json else _log
    result = run_workspace_sync(database, principal, mode=args.mode, log=log)
    if args.json:
        _print_json(
            {
                "database": str(result.database),
                "sync_id": result.sync_id,
                "mode": result.mode,
                "workspace_count": result.workspace_count,
                "active_count": result.active_count,
                "added": result.added,
                "updated": result.updated,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "duration_seconds": round(result.duration_seconds, 2),
            }
        )
    else:
        print(
            f"\nSelesai: {result.workspace_count} workspace "
            f"({result.added} baru, {result.updated} diperbarui) "
            f"dalam {result.duration_seconds:.1f} detik."
        )
    return 0


def _cmd_lineage(argv: list[str]) -> int:
    args = _lineage_parser().parse_args(argv)
    principal = _principal(args)
    database = _database(args.database, default=DEFAULT_DB)
    log = (lambda line: print(line, file=sys.stderr)) if args.json else _log
    result = run_lineage_scan(
        database,
        principal,
        mode=args.mode,
        full=args.full,
        include_personal=args.include_personal,
        log=log,
    )
    if args.json:
        _print_json(
            {
                "database": str(result.database),
                "scan_id": result.scan_id,
                "mode": result.mode,
                "workspace_count": result.workspace_count,
                "node_count": result.node_count,
                "edge_count": result.edge_count,
                "unresolved_sources": result.unresolved_sources,
                "include_personal": result.include_personal,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "duration_seconds": round(result.duration_seconds, 2),
            }
        )
    else:
        print(
            f"\nSelesai: {result.workspace_count} workspace, "
            f"{result.node_count} node, {result.edge_count} edge "
            f"dalam {result.duration_seconds:.1f} detik."
        )
    return 0


def _check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bi-tools-sync check",
        description="Verifikasi site, document library, dan isi folder SharePoint.",
    )
    parser.add_argument("--sharepoint-host", default="", help="hostname SharePoint")
    parser.add_argument("--sharepoint-site", default="", help="path site")
    parser.add_argument("--sharepoint-library", default="", help="nama document library")
    parser.add_argument("--sharepoint-folder", default="", help="folder tujuan")
    parser.add_argument("--env-file", default="", help="berkas .env kredensial")
    parser.add_argument("--limit", type=int, default=20, help="jumlah file ditampilkan")
    parser.add_argument("--json", action="store_true", help="cetak ringkasan JSON")
    return parser


def _cmd_check(argv: list[str]) -> int:
    args = _check_parser().parse_args(argv)
    target = _target(args)
    if target is None:
        raise ExtractionError(
            "Target SharePoint belum diisi (--sharepoint-host/--sharepoint-site "
            "atau SP_HOSTNAME/SP_SITE_PATH)."
        )
    principal = _principal(args)
    with GraphUploader(principal, target, log=_log) as uploader:
        data = uploader.check()
        data["files"] = uploader.list_files(limit=args.limit)
    if args.json:
        _print_json(data)
        return 0
    print(f"Target  : {data['target']}")
    print(f"Site    : {data['site']} ({data['site_url']})")
    print(f"Library : {data['library']} ({data['library_url']})")
    print(f"Folder  : {data['path'] or '/'}")
    if not data["files"]:
        print("Folder kosong.")
        return 0
    print(f"{len(data['files'])} file:")
    for row in data["files"]:
        print(
            f"  {row.get('name')} ({int(row.get('size') or 0)} byte, "
            f"{row.get('lastModifiedDateTime')})"
        )
    return 0


HANDLERS = {
    "run": _cmd_run,
    "workspaces": _cmd_workspaces,
    "lineage": _cmd_lineage,
    "check": _cmd_check,
}


def main(argv: list[str] | None = None) -> int:
    """Jalankan perintah sync; kembalikan exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"-h", "--help"}:
        print(USAGE, end="")
        return 0
    command = "run"
    if args and args[0] in COMMANDS:
        command = args.pop(0)
    try:
        return HANDLERS[command](args)
    except ExtractionError as exc:
        print(f"Sync gagal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

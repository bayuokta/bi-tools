"""Program sync database bersama (service principal).

Menjalankan Admin API untuk katalog workspace, lineage, dan katalog report,
lalu menerbitkan snapshot SQLite untuk dibaca aplikasi interaktif.

Perintah ini sengaja terpisah dari ``bi-tools-cli`` interaktif: hanya program
sync yang memegang client secret dan memanggil endpoint ``admin/*``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.lineage_scan import run_lineage_scan
from core.paths import data_dir
from core.report_catalog import sync_report_catalog
from core.snapshot import publish_snapshot


def _database(value: str) -> Path:
    if value:
        return Path(value).expanduser()
    return data_dir() / "bi_tools_sync.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bi-tools-sync",
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
    parser.add_argument("--mode", choices=("auto", "admin", "member"), default="auto")
    parser.add_argument("--full", action="store_true", help="lineage scan penuh")
    parser.add_argument(
        "--include-personal",
        action="store_true",
        help="sertakan My Workspace (hanya mode admin)",
    )
    parser.add_argument("--skip-catalog", action="store_true")
    parser.add_argument("--skip-lineage", action="store_true")
    parser.add_argument("--skip-reports", action="store_true")
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(message, flush=True)

    try:
        principal = ServicePrincipal.from_env()
        principal.validate()
        database = _database(args.database)
        snapshot = (
            Path(args.snapshot_out).expanduser()
            if args.snapshot_out
            else database.with_name("bi_tools_snapshot.db")
        )

        if not args.skip_catalog:
            from core.catalog_sync import run_workspace_sync

            result = run_workspace_sync(
                database, principal, mode=args.mode, log=log
            )
            log(
                f"Katalog: {result.workspace_count} workspace "
                f"(mode {result.mode})"
            )

        if not args.skip_lineage:
            result = run_lineage_scan(
                database,
                principal,
                mode=args.mode,
                full=args.full,
                include_personal=args.include_personal,
                log=log,
            )
            log(
                f"Lineage: {result.workspace_count} workspace, "
                f"{result.node_count} node, {result.edge_count} edge"
            )

        if not args.skip_reports:
            try:
                count = sync_report_catalog(principal, database, log=log)
            except Exception as exc:  # noqa: BLE001 - katalog report opsional
                log(f"Katalog report dilewati: {exc}")
            else:
                log(f"Katalog report: {count} report")

        summary = publish_snapshot(
            database,
            snapshot,
            extra_meta={
                "mode": args.mode,
                "full": "1" if args.full else "0",
            },
        )
        log(f"Snapshot: {summary['path']} ({summary['size']} byte)")
        return 0
    except ExtractionError as exc:
        print(f"Sync gagal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

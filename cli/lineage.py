"""CLI lineage Power BI Service: pencarian, impact analysis, dan diagnostik.

Scan dan sinkronisasi katalog workspace tidak lagi ada di sini: keduanya
memakai Admin API dan hanya dijalankan oleh ``bi-tools-sync``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

from core.errors import ExtractionError
from core.lineage_export import write_lineage_csv
from core.lineage_store import (
    DEFAULT_DB,
    close_quietly,
    diagnostics,
    lineage,
    open_read_only,
    search,
    stats,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lineage item Power BI Service dari database SQLite: cari item, "
            "lalu telusuri upstream/downstream."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"Path database SQLite (default: {DEFAULT_DB.name}).",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--search", metavar="QUERY", help="Cari item berdasarkan nama.")
    actions.add_argument(
        "--impact",
        metavar="NODE_ID",
        help="Daftar item downstream (dipakai oleh) dari satu node.",
    )
    actions.add_argument(
        "--upstream",
        metavar="NODE_ID",
        help="Daftar item upstream (bersumber dari) satu node.",
    )
    actions.add_argument("--stats", action="store_true", help="Statistik database.")
    actions.add_argument(
        "--check",
        action="store_true",
        help="Diagnostik edge, referensi node yang hilang, dan riwayat scan.",
    )

    parser.add_argument(
        "--workspace", help="Filter nama workspace untuk --search."
    )
    parser.add_argument("--type", help="Filter tipe node untuk --search.")
    parser.add_argument(
        "--limit",
        type=int,
        default=300,
        help="Batas hasil pencarian (default: 300).",
    )
    parser.add_argument(
        "--export-csv",
        help="Simpan hasil --impact/--upstream ke file CSV.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Cetak hasil dalam JSON (selain progres scan).",
    )
    return parser.parse_args(argv)


def _print_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    values = [list(map(lambda value: "" if value is None else str(value), row)) for row in rows]
    widths = [len(header) for header in headers]
    for row in values:
        for index, value in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(value))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in values:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _open_database(path: str):
    return open_read_only(Path(path))


def _search(args: argparse.Namespace) -> int:
    conn = None
    try:
        conn = _open_database(args.db)
        rows = search(
            conn,
            args.search,
            args.workspace or "",
            args.type or "",
            limit=max(1, args.limit),
        )
    except (ExtractionError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            close_quietly(conn)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("Tidak ada hasil.")
        return 0
    _print_table(
        ["Tipe", "Nama", "Workspace", "Owner", "ID"],
        (
            (
                row.get("node_type"),
                row.get("name"),
                row.get("workspace_name"),
                row.get("owner"),
                row.get("node_id"),
            )
            for row in rows
        ),
    )
    print(f"\n{len(rows)} hasil" + (" (dibatasi)" if len(rows) >= args.limit else ""))
    return 0


def _lineage(args: argparse.Namespace) -> int:
    node_id = args.impact or args.upstream
    direction = "downstream" if args.impact else "upstream"
    conn = None
    try:
        conn = _open_database(args.db)
        result = lineage(conn, node_id, direction)
    except (ExtractionError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            close_quietly(conn)

    if result is None:
        print(f"ERROR: node tidak ditemukan: {node_id}", file=sys.stderr)
        return 2

    if args.export_csv:
        try:
            target = write_lineage_csv(args.export_csv, result)
        except OSError as exc:
            print(f"ERROR: gagal menulis CSV: {exc}", file=sys.stderr)
            return 2
        if not args.json:
            print(f"CSV: {target}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    root = result["root"]
    print(f"Root      : [{root.get('node_type')}] {root.get('name')}")
    print(f"Workspace : {root.get('workspace_name') or '-'}")
    print(f"Arah      : {direction}")
    if not result["nodes"]:
        print("Tidak ada item pada arah ini.")
        return 0
    _print_table(
        ["Depth", "Tipe", "Nama", "Workspace", "Owner", "Relasi"],
        (
            (
                node.get("depth"),
                node.get("node_type"),
                node.get("name"),
                node.get("workspace_name"),
                node.get("owner"),
                node.get("edge_type"),
            )
            for node in sorted(
                result["nodes"],
                key=lambda item: (
                    item.get("depth", 0),
                    item.get("node_type") or "",
                    (item.get("name") or "").casefold(),
                ),
            )
        ),
    )
    return 0


def _stats(args: argparse.Namespace) -> int:
    conn = None
    try:
        conn = _open_database(args.db)
        data = stats(conn)
    except (ExtractionError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            close_quietly(conn)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"Scan terakhir: {data.get('last_scan') or '-'}")
    _print_table(
        ["Tipe", "Jumlah"],
        ((item["node_type"], item["n"]) for item in data["types"]),
    )
    return 0


def _check(args: argparse.Namespace) -> int:
    conn = None
    try:
        conn = _open_database(args.db)
        data = diagnostics(conn)
    except (ExtractionError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if conn is not None:
            close_quietly(conn)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("Edge aktif per tipe (hilang = ID tidak ada di tabel nodes):")
    _print_table(
        ["Edge", "Total", "Source hilang", "Target hilang"],
        (
            (
                row["edge_type"],
                row["total"],
                row["source_missing"],
                row["target_missing"],
            )
            for row in data["edges"]
        ),
    )
    if data["missing_samples"]:
        print("\nContoh ID yang hilang:")
        _print_table(
            ["Edge", "Sisi", "Node ID"],
            (
                (row["edge_type"], row["side"], row["node_id"])
                for row in data["missing_samples"]
            ),
        )
    else:
        print("\nTidak ada ID yang hilang.")

    print(f"\nSumber feed tanpa metadata: {data['unresolved_feed_sources']}")
    if data["scans"]:
        print("\nRiwayat scan:")
        _print_table(
            ["Waktu", "Mode", "Workspace", "Status", "Scan ID"],
            (
                (
                    row["started_at"],
                    row["mode"],
                    row["workspace_count"],
                    row["status"],
                    row["scan_id"],
                )
                for row in data["scans"]
            ),
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.search is not None:
        return _search(args)
    if args.impact or args.upstream:
        return _lineage(args)
    if args.stats:
        return _stats(args)
    if args.check:
        return _check(args)
    print(
        "Pilih salah satu aksi: --search, --impact, --upstream, --stats, --check."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

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
            "Power BI Service item lineage from the SQLite database: search items, "
            "then trace upstream/downstream."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"Path database SQLite (default: {DEFAULT_DB.name}).",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--search", metavar="QUERY", help="Search items by name.")
    actions.add_argument(
        "--impact",
        metavar="NODE_ID",
        help="List downstream items (used by) for one node.",
    )
    actions.add_argument(
        "--upstream",
        metavar="NODE_ID",
        help="List upstream items (sourced from) for one node.",
    )
    actions.add_argument("--stats", action="store_true", help="Statistik database.")
    actions.add_argument(
        "--check",
        action="store_true",
        help="Edge diagnostics, missing node references, and scan history.",
    )

    parser.add_argument(
        "--workspace", help="Filter workspace name for --search."
    )
    parser.add_argument("--type", help="Filter node type for --search.")
    parser.add_argument(
        "--limit",
        type=int,
        default=300,
        help="Search result limit (default: 300).",
    )
    parser.add_argument(
        "--export-csv",
        help="Save --impact/--upstream results to a CSV file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON (besides scan progress).",
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
        print("No results.")
        return 0
    _print_table(
        ["Type", "Name", "Workspace", "Owner", "ID"],
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
    print(f"\n{len(rows)} results" + (" (limited)" if len(rows) >= args.limit else ""))
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
        print(f"ERROR: node not found: {node_id}", file=sys.stderr)
        return 2

    if args.export_csv:
        try:
            target = write_lineage_csv(args.export_csv, result)
        except OSError as exc:
            print(f"ERROR: failed to write CSV: {exc}", file=sys.stderr)
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
        print("No items in this direction.")
        return 0
    _print_table(
        ["Depth", "Type", "Name", "Workspace", "Owner", "Relationship"],
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
    print(f"Last scan: {data.get('last_scan') or '-'}")
    _print_table(
        ["Type", "Count"],
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

    print("Active edges per type (missing = ID not present in the nodes table):")
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
        print("\nExample missing IDs:")
        _print_table(
            ["Edge", "Sisi", "Node ID"],
            (
                (row["edge_type"], row["side"], row["node_id"])
                for row in data["missing_samples"]
            ),
        )
    else:
        print("\nNo missing IDs.")

    print(f"\nFeed sources without metadata: {data['unresolved_feed_sources']}")
    if data["scans"]:
        print("\nScan history:")
        _print_table(
            ["Time", "Mode", "Workspace", "Status", "Scan ID"],
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
        "Choose one action: --search, --impact, --upstream, --stats, --check."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

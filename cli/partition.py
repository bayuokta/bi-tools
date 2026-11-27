"""CLI inventaris dan refresh partisi semantic model via XMLA/TOM.

Contoh::

    python -m cli partition --workspace-id <ws> --dataset-id <ds> --list
    python -m cli partition --workspace-id <ws> --dataset-id <ds> \
        --table "Fact Sales" --partition "Fact Sales 2025" --refresh-type full --yes
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from core.auth import ServicePrincipal, Token
from core.column_stats import STORAGE_DMV
from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.partition_plan import (
    build_refresh_tmsl,
    normalize_refresh_type,
    partition_payload,
    validate_refresh_targets,
)
from core.partition_service import process_partitions, read_partition_inventory
from core.requests import PARTITION_CONFIRMATION, PartitionRefreshRequest
from core.tom_client import connect_server, execute_refresh, list_partitions
from core.usage_service import resolve_names
from core.xmla_client import open_client


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Partition inventory for a Power BI Service semantic model and refresh "
            "of selected partitions via XMLA/TOM."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--workspace-id", help="Workspace ID (GUID).")
    parser.add_argument("--dataset-id", help="Semantic model ID (GUID).")
    parser.add_argument("--workspace-name", help="Workspace name (default: SQLite catalog).")
    parser.add_argument("--dataset-name", help="Semantic model name (default: SQLite catalog).")
    parser.add_argument("--db", help=f"Database SQLite (default: {DEFAULT_DB}).")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Only list the partition inventory (no refresh).",
    )
    parser.add_argument(
        "--table",
        action="append",
        default=[],
        help="Target table name; repeat paired with --partition.",
    )
    parser.add_argument(
        "--partition",
        action="append",
        default=[],
        help="Target partition name; repeat paired with --table.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Alternative target 'Table|Partition'; may be repeated.",
    )
    parser.add_argument(
        "--refresh-type",
        default="full",
        help=(
            "full | automatic | dataOnly | clearValues | calculate | add | "
            "defragment | indexes"
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=f"Required for refresh; equivalent to typing {PARTITION_CONFIRMATION}.",
    )
    # Mode internal: TOM dan ADOMD dipisah ke proses berbeda agar dua assembly
    # Microsoft.AnalysisServices tidak bentrok. Token dan target lewat stdin.
    parser.add_argument("--dmv-json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--inventory-json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--refresh-json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--endpoint", help=argparse.SUPPRESS)
    parser.add_argument("--catalog", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


class _StaticTokens:
    """Token tunggal untuk mode internal (tanpa MSAL di proses anak)."""

    def __init__(self, value: str, expires_on: int) -> None:
        self._token = Token(value=value, expires_on=expires_on)

    def get(self, _scope: str, *, force: bool = False) -> Token:
        return self._token


def _read_stdin(args: argparse.Namespace, mode: str) -> tuple[str, str, _StaticTokens | None, dict[str, Any]]:
    endpoint = str(args.endpoint or "").strip()
    catalog = str(args.catalog or "").strip()
    if not endpoint or not catalog:
        raise ExtractionError(
            f"Mode {mode} requires --endpoint and --catalog."
        )
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        raise ExtractionError(f"Payload token {mode} is not valid: {exc}") from exc
    if bool((payload or {}).get("interactive")):
        return endpoint, catalog, None, payload
    token = str((payload or {}).get("token") or "").strip()
    if not token:
        raise ExtractionError(f"Empty {mode} token.")
    expires_on = int((payload or {}).get("expires_on") or (time.time() + 3000))
    return endpoint, catalog, _StaticTokens(token, expires_on), payload


def _dmv_json(args: argparse.Namespace) -> int:
    """Ambil segmen VertiPaq dan cetak JSON; dipanggil dari proses server."""
    endpoint, catalog, tokens, _payload = _read_stdin(args, "--dmv-json")
    with open_client(
        endpoint=endpoint,
        catalog=catalog,
        tokens=tokens,
        interactive=tokens is None,
    ) as client:
        rows = client.query(STORAGE_DMV)
    # ASCII agar aman di pipe Windows dengan encoding console yang berbeda.
    print(json.dumps(rows, ensure_ascii=True, default=str))
    return 0


def _inventory_json(args: argparse.Namespace) -> int:
    """Baca partisi lewat TOM dan cetak JSON; dipanggil dari proses server."""
    endpoint, catalog, tokens, _payload = _read_stdin(args, "--inventory-json")
    with connect_server(
        endpoint, catalog, tokens, interactive=tokens is None
    ) as server:
        rows = list_partitions(server, catalog)
    print(json.dumps(partition_payload(rows), ensure_ascii=True))
    return 0


def _refresh_json(args: argparse.Namespace) -> int:
    """Validasi target, kirim satu TMSL, lalu cetak inventaris terbaru."""
    endpoint, catalog, tokens, payload = _read_stdin(args, "--refresh-json")
    targets: list[tuple[str, str]] = []
    for item in payload.get("targets") or []:
        table = str((item or {}).get("table") or "").strip()
        partition = str((item or {}).get("partition") or "").strip()
        if not table or not partition:
            raise ExtractionError("Table and partition names cannot be empty.")
        targets.append((table, partition))
    if not targets:
        raise ExtractionError("Select at least one partition to process.")
    refresh_type = normalize_refresh_type(str(payload.get("refresh_type") or "full"))

    with connect_server(
        endpoint, catalog, tokens, interactive=tokens is None
    ) as server:
        partitions = list_partitions(server, catalog)
        by_key = {(item.table, item.name): item for item in partitions}
        missing = [key for key in targets if key not in by_key]
        if missing:
            listing = ", ".join(f"{table}/{name}" for table, name in missing)
            raise ExtractionError(
                f"Partition not found in the model: {listing}. Reload the inventory."
            )
        refresh_type = validate_refresh_targets(
            refresh_type, [by_key[key] for key in targets]
        )
        tmsl = build_refresh_tmsl(catalog, targets, refresh_type)
        print(
            f"Sending TMSL refresh for {len(targets)} partitions; "
            "the command cannot be cancelled once sent.",
            file=sys.stderr,
            flush=True,
        )
        execute_refresh(server, tmsl)
        print(
            "Refresh completed; re-reading partition status.",
            file=sys.stderr,
            flush=True,
        )
        refreshed = list_partitions(server, catalog)
    print(json.dumps(partition_payload(refreshed), ensure_ascii=True))
    return 0


def _names(args: argparse.Namespace) -> tuple[str, str]:
    workspace_name = str(args.workspace_name or "").strip()
    dataset_name = str(args.dataset_name or "").strip()
    if workspace_name and dataset_name:
        return workspace_name, dataset_name
    database = Path(args.db) if args.db else DEFAULT_DB
    from_catalog_ws, from_catalog_ds = resolve_names(
        database, args.workspace_id, args.dataset_id
    )
    return workspace_name or from_catalog_ws, dataset_name or from_catalog_ds


def _targets(args: argparse.Namespace) -> tuple[tuple[str, str], ...]:
    tables = [str(item).strip() for item in args.table]
    partitions = [str(item).strip() for item in args.partition]
    if len(tables) != len(partitions):
        raise ExtractionError(
            "The number of --table and --partition values must match and be paired."
        )
    pairs = list(zip(tables, partitions))
    for item in args.target:
        text = str(item or "")
        if "|" not in text:
            raise ExtractionError(
                f"The --target format must be 'Table|Partition': {text!r}"
            )
        table, partition = text.split("|", 1)
        pairs.append((table.strip(), partition.strip()))
    if not pairs:
        raise ExtractionError("Specify --table/--partition or --target to refresh.")
    return tuple(pairs)


def _print_inventory(payload: dict[str, Any]) -> None:
    dataset = payload.get("dataset") or {}
    print(f"Workspace    : {(payload.get('workspace') or {}).get('name', '')}")
    print(f"Model        : {dataset.get('name', '')}")
    print(f"Endpoint     : {payload.get('endpoint', '')}")
    print(f"Partisi      : {len(payload.get('partitions') or [])}")
    print()
    print(f"{'Table':<28} {'Partition':<34} {'Rows':>10} {'Range':<24} {'State':<12} Last processed")
    print("-" * 128)
    for row in payload.get("partitions") or []:
        rows = row.get("rows")
        print(
            f"{str(row.get('table') or ''):<28} "
            f"{str(row.get('partition') or ''):<34} "
            f"{(rows if rows is not None else '-'):>10} "
            f"{str(row.get('range') or '-'):<24} "
            f"{str(row.get('state') or '-'):<12} "
            f"{row.get('last_processed') or '-'}"
        )
    for warning in payload.get("warnings") or []:
        print(f"CATATAN: {warning}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.dmv_json:
            return _dmv_json(args)
        if args.inventory_json:
            return _inventory_json(args)
        if args.refresh_json:
            return _refresh_json(args)
        if not args.workspace_id or not args.dataset_id:
            raise ExtractionError("--workspace-id and --dataset-id are required.")
        workspace_name, dataset_name = _names(args)
        if not workspace_name or not dataset_name:
            raise ExtractionError(
                "Workspace/model names were not found in the SQLite catalog; fill in "
                "--workspace-name and --dataset-name."
            )
        principal = ServicePrincipal.from_env()
        if args.list:
            payload = read_partition_inventory(
                workspace_id=args.workspace_id,
                workspace_name=workspace_name,
                dataset_id=args.dataset_id,
                dataset_name=dataset_name,
                principal=principal,
                log=print,
            )
            _print_inventory(payload)
            return 0

        if not args.yes:
            raise ExtractionError(
                f"Refresh mengubah data model. Tambahkan --yes (konfirmasi "
                f"{PARTITION_CONFIRMATION}) to continue."
            )
        request = PartitionRefreshRequest(
            workspace_id=args.workspace_id,
            dataset_id=args.dataset_id,
            workspace_name=workspace_name,
            dataset_name=dataset_name,
            targets=_targets(args),
            refresh_type=args.refresh_type,
            confirmation=PARTITION_CONFIRMATION,
        )
        payload = process_partitions(
            **request.to_refresh_kwargs(),
            principal=principal,
            log=print,
        )
        print()
        print(payload.get("refresh", {}).get("message", "Refresh completed."))
        _print_inventory(payload)
        return 0
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

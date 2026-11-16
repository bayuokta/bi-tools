"""CLI ekstraksi model: python extract_model_metadata.py [opsi]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.auth import EntraTokens, ServicePrincipal
from core.errors import ExtractionError
from core.model import DEFAULT_OUT, run_model
from core.xmla_client import list_instances


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ekstraksi metadata semantic model via XMLA ke Excel.")
    parser.add_argument("--report", help="File .pbix untuk kolom usage report.")
    parser.add_argument("--out", help="Path file Excel output.")
    parser.add_argument("--endpoint", help="Endpoint XMLA (host:port atau connection string).")
    parser.add_argument("--catalog", help="Nama catalog/dataset (wajib bila ada lebih dari satu instance tanpa --port).")
    parser.add_argument("--port", type=int, help="Port instance Power BI Desktop lokal (lihat --list-instances).")
    parser.add_argument("--no-report", action="store_true", help="Lewati pemakaian report (thin report).")
    parser.add_argument("--list-instances", action="store_true", help="Tampilkan instance Power BI Desktop yang terbuka, lalu berhenti.")
    return parser.parse_args(argv)


def print_instances() -> int:
    instances = list_instances()
    if not instances:
        print("Tidak ada instance Power BI Desktop yang terbuka.")
        return 0
    print("Instance Power BI Desktop yang terbuka:")
    for index, item in enumerate(instances, start=1):
        print(f"  {index}. {item.label}")
        print(f"     --port {item.port}  --catalog {item.catalog}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_instances:
        return print_instances()
    try:
        run_model(
            endpoint=args.endpoint,
            catalog=args.catalog,
            port=args.port,
            report=Path(args.report) if args.report else None,
            no_report=args.no_report,
            out_file=Path(args.out).resolve() if args.out else DEFAULT_OUT,
            tokens=_xmla_tokens(args.endpoint),
            log=print,
        )
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


def _xmla_tokens(endpoint: str | None) -> EntraTokens | None:
    """Token Power BI untuk endpoint XMLA cloud; Desktop lokal tidak perlu token."""
    if not endpoint:
        return None
    lowered = endpoint.lower()
    if "powerbi://" not in lowered and "asazure://" not in lowered:
        return None
    return EntraTokens(ServicePrincipal.from_env())

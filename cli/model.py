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
    parser.add_argument("--report", help=".pbix file for the report usage columns (required unless --no-report is used).")
    parser.add_argument("--out", help="Path file Excel output.")
    parser.add_argument("--endpoint", help="XMLA endpoint (host:port or connection string).")
    parser.add_argument("--catalog", help="Catalog/dataset name (required when more than one instance is open without --port).")
    parser.add_argument("--port", type=int, help="Port instance Power BI Desktop lokal (lihat --list-instances).")
    parser.add_argument("--no-report", action="store_true", help="Lewati pemakaian report (thin report).")
    parser.add_argument("--list-instances", action="store_true", help="List open Power BI Desktop instances, then exit.")
    return parser.parse_args(argv)


def print_instances() -> int:
    instances = list_instances()
    if not instances:
        print("No Power BI Desktop instance is open.")
        return 0
    print("Open Power BI Desktop instances:")
    for index, item in enumerate(instances, start=1):
        print(f"  {index}. {item.label}")
        print(f"     --port {item.port}  --catalog {item.catalog}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_instances:
        return print_instances()
    try:
        if not args.no_report and not args.report:
            raise ExtractionError(
                "The .pbix file for report usage is required via --report, "
                "or skip it with --no-report."
            )
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

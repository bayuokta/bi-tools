"""CLI snapshot TOM untuk halaman Compare (mode internal).

Server memanggil proses ini agar TOM tidak dimuat di proses server:

    bi-tools-cli compare --snapshot-json --endpoint <xmla> --catalog <model>

Payload stdin: ``{token, expires_on, options}``. Output stdout: JSON snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from core.auth import Token
from core.errors import ExtractionError
from core.tom_client import TomError, connect_desktop_server, connect_server
from core.tom_compare import serialize_snapshot


class _StaticTokens:
    def __init__(self, token: str, expires_on: int) -> None:
        self._token = Token(token, int(expires_on))

    def get(self, _scope: str, *, force: bool = False) -> Token:
        return self._token


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot TOM untuk perbandingan semantic model (internal).",
        allow_abbrev=False,
    )
    parser.add_argument("--snapshot-json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--endpoint", help=argparse.SUPPRESS)
    parser.add_argument("--catalog", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _read_stdin(args: argparse.Namespace) -> tuple[dict[str, Any], _StaticTokens | None]:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        raise ExtractionError(f"Payload compare tidak valid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExtractionError("Payload compare harus berupa object JSON.")
    if args.port:
        return payload, None
    token = str(payload.get("token") or "").strip()
    if not token:
        raise ExtractionError("Token compare kosong.")
    expires_on = int(payload.get("expires_on") or (time.time() + 3000))
    return payload, _StaticTokens(token, expires_on)


def _snapshot_json(args: argparse.Namespace) -> int:
    catalog = str(args.catalog or "").strip()
    if not catalog:
        raise ExtractionError("Mode snapshot membutuhkan --catalog.")
    payload, tokens = _read_stdin(args)
    options = payload.get("options") or {}
    if args.port:
        with connect_desktop_server(int(args.port), catalog) as server:
            text = serialize_snapshot(server, catalog, options)
    else:
        endpoint = str(args.endpoint or "").strip()
        if not endpoint:
            raise ExtractionError("Mode snapshot membutuhkan --endpoint.")
        if tokens is None:
            raise ExtractionError("Token compare kosong.")
        with connect_server(endpoint, catalog, tokens) as server:
            text = serialize_snapshot(server, catalog, options)
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.snapshot_json:
            return _snapshot_json(args)
        raise ExtractionError("Mode compare tidak dikenal.")
    except (ExtractionError, TomError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - proses anak harus memberi pesan
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

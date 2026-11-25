"""Orkestrasi snapshot TOM untuk halaman Compare.

Modul ini **tidak** memuat TOM. Snapshot dibuat oleh proses CLI anak
(``compare --snapshot-json``) karena TOM dan ADOMD tidak boleh berada dalam
satu proses server. Token dikirim lewat stdin.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Mapping

from .auth import POWERBI_SCOPE, EntraTokens
from .errors import ExtractionError
from .paths import APP_DIR, cli_argv

TOM_TIMEOUT = 300


def _token_payload(
    tokens: EntraTokens | None, interactive: bool = False
) -> dict[str, Any]:
    if interactive or tokens is None:
        return {"interactive": True}
    token = tokens.get(POWERBI_SCOPE)
    return {"token": token.value, "expires_on": token.expires_on}


def _cli_command(*, endpoint: str = "", catalog: str = "", port: int = 0) -> list[str]:
    command = ["compare", "--snapshot-json", "--catalog", catalog]
    if port:
        command.extend(["--port", str(int(port))])
    else:
        command.extend(["--endpoint", endpoint])
    return cli_argv(command)


def _cli_env() -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _error_line(text: str) -> str:
    detail = (text or "").strip()
    line = next((item.strip() for item in detail.splitlines() if item.strip()), "")
    if line.upper().startswith("ERROR:"):
        return line[len("ERROR:") :].strip()
    return line


def read_snapshot(
    *,
    endpoint: str = "",
    catalog: str,
    port: int = 0,
    tokens: EntraTokens | None = None,
    options: Mapping[str, Any] | None = None,
    interactive: bool = False,
) -> dict[str, Any]:
    """Baca snapshot TOM lewat proses anak (read-only)."""
    name = str(catalog or "").strip()
    if not name:
        raise ExtractionError("Catalog semantic model kosong.")
    if not port and not str(endpoint or "").strip():
        raise ExtractionError("Endpoint XMLA kosong.")
    payload: dict[str, Any] = {
        "options": dict(options or {}),
        **_token_payload(tokens, interactive),
    }
    completed = subprocess.run(
        _cli_command(endpoint=endpoint, catalog=name, port=port),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(APP_DIR),
        env=_cli_env(),
        timeout=TOM_TIMEOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        line = _error_line(completed.stderr or completed.stdout)
        raise ExtractionError(line or "Proses snapshot TOM gagal tanpa pesan.")
    try:
        data = json.loads(completed.stdout or "{}")
    except ValueError as exc:
        raise ExtractionError(f"Output snapshot TOM tidak valid: {exc}") from exc
    if not isinstance(data, dict) or not data.get("objects"):
        raise ExtractionError("Snapshot TOM tidak berisi objek yang bisa dibandingkan.")
    return data

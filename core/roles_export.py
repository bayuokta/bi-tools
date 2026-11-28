"""Ekspor tab Roles dalam format internal BI Tools.

Tidak ada template Measure Killer untuk Roles. Satu baris per objek: role,
member, dan table permission (RLS/OLS), dengan urutan role → member →
permission seperti tabel UI. ``Filter expression`` ditulis utuh (tidak
dipotong).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .metadata_common import write_sheet

ROLE_COLUMNS = [
    "Role",
    "Type",
    "Object",
    "Model permission",
    "Member type",
    "Provider",
    "Member ID",
    "Filter expression",
    "OLS",
    "Modified",
    "Description",
    "Member count",
    "Table permission count",
]


def _blank() -> dict[str, Any]:
    return {column: "" for column in ROLE_COLUMNS}


def build_role_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 13 kolom dari ``AnalysisResult.roles``."""
    rows: list[dict[str, Any]] = []
    for role in getattr(result, "roles", []) or []:
        if not isinstance(role, Mapping):
            continue
        name = str(role.get("name") or "")
        members = [
            member for member in (role.get("members") or [])
            if isinstance(member, Mapping)
        ]
        permissions = [
            permission for permission in (role.get("permissions") or [])
            if isinstance(permission, Mapping)
        ]

        summary = _blank()
        summary.update(
            {
                "Role": name,
                "Type": "Role",
                "Object": name,
                "Model permission": str(role.get("model_permission") or ""),
                "Modified": str(role.get("modified") or ""),
                "Description": str(role.get("description") or ""),
                "Member count": len(members),
                "Table permission count": len(permissions),
            }
        )
        rows.append(summary)

        for member in members:
            row = _blank()
            row.update(
                {
                    "Role": name,
                    "Type": "Member",
                    "Object": str(member.get("name") or ""),
                    "Member type": str(member.get("member_type") or ""),
                    "Provider": str(member.get("provider") or ""),
                    "Member ID": str(member.get("member_id") or ""),
                    "Modified": str(member.get("modified") or ""),
                }
            )
            rows.append(row)

        for permission in permissions:
            row = _blank()
            row.update(
                {
                    "Role": name,
                    "Type": "Table permission",
                    "Object": str(permission.get("table") or ""),
                    "Filter expression": str(permission.get("expression") or ""),
                    "OLS": "Yes" if bool(permission.get("has_ols")) else "No",
                }
            )
            rows.append(row)
    return rows


def write_roles_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet Roles dengan 13 kolom internal."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_role_rows(result), columns=ROLE_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Roles")
    return target

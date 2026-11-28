"""Uji ekspor tab Roles (format internal BI Tools)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.roles_export import ROLE_COLUMNS, build_role_rows, write_roles_export


def sample() -> SimpleNamespace:
    return SimpleNamespace(
        roles=[
            {
                "id": 1,
                "name": "Dealer",
                "model_permission": "read",
                "description": "Dealer security",
                "modified": "2026-01-01T00:00:00",
                "members": [
                    {
                        "name": "Dealer A",
                        "member_id": "m1",
                        "member_type": "User",
                        "provider": "AzureAD",
                        "modified": "2026-01-02T00:00:00",
                    },
                    {
                        "name": "Dealer B",
                        "member_id": "m2",
                        "member_type": "User",
                        "provider": "AzureAD",
                        "modified": "2026-01-03T00:00:00",
                    },
                ],
                "permissions": [
                    {
                        "table": "RLS Dealer",
                        "expression": "[Email] = USERPRINCIPALNAME()",
                        "has_ols": False,
                    },
                    {
                        "table": "Pages Logic",
                        "expression": "",
                        "has_ols": True,
                    },
                ],
            },
            {
                "id": 2,
                "name": "HO",
                "model_permission": "read",
                "description": "",
                "modified": "",
                "members": [],
                "permissions": [
                    {"table": "Pages", "expression": "TRUE()", "has_ols": False}
                ],
            },
        ]
    )


class RolesExportTests(unittest.TestCase):
    def test_rows_match_columns_and_object_order(self) -> None:
        rows = build_role_rows(sample())
        self.assertEqual(list(rows[0].keys()), ROLE_COLUMNS)
        self.assertEqual(len(rows), 7)
        self.assertEqual(
            [(row["Role"], row["Type"], row["Object"]) for row in rows],
            [
                ("Dealer", "Role", "Dealer"),
                ("Dealer", "Member", "Dealer A"),
                ("Dealer", "Member", "Dealer B"),
                ("Dealer", "Table permission", "RLS Dealer"),
                ("Dealer", "Table permission", "Pages Logic"),
                ("HO", "Role", "HO"),
                ("HO", "Table permission", "Pages"),
            ],
        )

    def test_role_row_has_counts_and_permission(self) -> None:
        rows = build_role_rows(sample())
        dealer = rows[0]
        self.assertEqual(dealer["Model permission"], "read")
        self.assertEqual(dealer["Description"], "Dealer security")
        self.assertEqual(dealer["Modified"], "2026-01-01T00:00:00")
        self.assertEqual(dealer["Member count"], 2)
        self.assertEqual(dealer["Table permission count"], 2)
        self.assertEqual(dealer["OLS"], "")
        ho = next(row for row in rows if row["Role"] == "HO" and row["Type"] == "Role")
        self.assertEqual(ho["Member count"], 0)
        self.assertEqual(ho["Table permission count"], 1)

    def test_member_row_fields(self) -> None:
        rows = build_role_rows(sample())
        member = rows[1]
        self.assertEqual(member["Role"], "Dealer")
        self.assertEqual(member["Member type"], "User")
        self.assertEqual(member["Provider"], "AzureAD")
        self.assertEqual(member["Member ID"], "m1")
        self.assertEqual(member["Modified"], "2026-01-02T00:00:00")
        self.assertEqual(member["Member count"], "")

    def test_permission_rows_have_full_expression_and_ols(self) -> None:
        rows = build_role_rows(sample())
        permissions = [row for row in rows if row["Type"] == "Table permission"]
        self.assertEqual(len(permissions), 3)
        dealer = next(row for row in permissions if row["Object"] == "RLS Dealer")
        self.assertEqual(
            dealer["Filter expression"], "[Email] = USERPRINCIPALNAME()"
        )
        self.assertEqual(dealer["OLS"], "No")
        pages_logic = next(
            row for row in permissions if row["Object"] == "Pages Logic"
        )
        self.assertEqual(pages_logic["OLS"], "Yes")

    def test_write_roles_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Roles.xlsx"
            write_roles_export(sample(), target)
            frame = pd.read_excel(target, "Roles", keep_default_na=False)
        self.assertEqual(list(frame.columns), ROLE_COLUMNS)
        self.assertEqual(len(frame), 7)

    def test_empty_result_writes_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Roles.xlsx"
            write_roles_export(SimpleNamespace(roles=[]), target)
            frame = pd.read_excel(target, "Roles", keep_default_na=False)
        self.assertEqual(list(frame.columns), ROLE_COLUMNS)
        self.assertEqual(len(frame), 0)


if __name__ == "__main__":
    unittest.main()

"""Uji metadata role (tab Roles) dari DMV TMSCHEMA."""

from __future__ import annotations

import unittest

from core.model import LiveModel, build_role_details


class FakeClient:
    endpoint = "powerbi://test"
    catalog = "Model"
    server_version = "17.0"
    catalog_info = {}

    def __init__(self, rows):
        self.rows = rows

    def query(self, dmv):
        return self.rows.get(dmv, [])


def model() -> LiveModel:
    rows = {
        "TMSCHEMA_MODEL": [{"ID": 1, "Name": "Model"}],
        "TMSCHEMA_TABLES": [{"ID": 2, "Name": "Sales"}],
        "TMSCHEMA_ROLES": [
            {
                "ID": 90,
                "Name": "Region",
                "ModelPermission": 2,
                "ModifiedTime": "2026-11-20T10:00:00",
            }
        ],
        "TMSCHEMA_ROLE_MEMBERSHIPS": [
            {
                "ID": 1,
                "RoleID": 90,
                "MemberName": "a@example.com",
                "MemberID": "member-a",
                "MemberType": 0,
                "IdentityProvider": "AzureAD",
                "ModifiedTime": "2026-11-20T11:00:00",
            },
            {
                "ID": 2,
                "RoleID": 90,
                "MemberName": "b@example.com",
                "MemberID": "member-b",
                "MemberType": 1,
                "IdentityProvider": "Windows",
                "ModifiedTime": "",
            },
        ],
        "TMSCHEMA_TABLE_PERMISSIONS": [
            {
                "ID": 80,
                "RoleID": 90,
                "TableID": 2,
                "FilterExpression": 'Sales[Region] = "A"',
            }
        ],
        "TMSCHEMA_COLUMN_PERMISSIONS": [{"TablePermissionID": 80}],
    }
    return LiveModel(FakeClient(rows))


class RoleDetailTests(unittest.TestCase):
    def test_role_contains_members_and_rls(self) -> None:
        roles = build_role_details(model())
        self.assertEqual(len(roles), 1)
        role = roles[0]
        self.assertEqual(role["name"], "Region")
        self.assertEqual(role["model_permission"], "read")
        self.assertEqual(
            [member["name"] for member in role["members"]],
            ["a@example.com", "b@example.com"],
        )
        self.assertEqual(role["members"][0]["member_type"], "User")
        self.assertEqual(role["members"][1]["member_type"], "Group")
        self.assertEqual(role["members"][0]["provider"], "AzureAD")
        self.assertEqual(len(role["permissions"]), 1)
        self.assertEqual(role["permissions"][0]["table"], "Sales")
        self.assertTrue(role["permissions"][0]["has_ols"])

    def test_missing_membership_dmv_is_empty(self) -> None:
        rows = {
            "TMSCHEMA_MODEL": [{"ID": 1}],
            "TMSCHEMA_ROLES": [{"ID": 1, "Name": "NoMembers"}],
        }
        role = build_role_details(LiveModel(FakeClient(rows)))[0]
        self.assertEqual(role["members"], [])
        self.assertEqual(role["permissions"], [])


if __name__ == "__main__":
    unittest.main()

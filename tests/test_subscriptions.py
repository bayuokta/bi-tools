"""Uji parsing subscription Admin REST (tanpa network)."""

from __future__ import annotations

import unittest

from core.subscriptions import (
    has_enabled,
    parse_subscriptions,
    unmapped_reports,
)


def row(**overrides):
    data = {
        "id": "sub-1",
        "title": "Daily Sales",
        "artifactType": "Report",
        "isEnabled": True,
        "frequency": "Daily",
        "subArtifactDisplayName": "Overview",
        "attachmentFormat": "PNG",
        "startDate": "2026-01-01T00:00:00",
        "endDate": "2026-12-31T00:00:00",
        "users": [
            {"emailAddress": "a@example.com", "identifier": "a"},
            {"emailAddress": "b@example.com"},
            {"displayName": "tanpa email"},
        ],
    }
    data.update(overrides)
    return data


class ParseSubscriptionTests(unittest.TestCase):
    def test_maps_admin_payload(self) -> None:
        items = parse_subscriptions("report-1", [row()])
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.report_id, "report-1")
        self.assertEqual(item.subscription_id, "sub-1")
        self.assertEqual(item.page_name, "Overview")
        self.assertEqual(item.frequency, "Daily")
        self.assertTrue(item.is_enabled)
        self.assertEqual(item.receiver_count, 2)
        self.assertEqual(
            item.receivers, ("a@example.com", "b@example.com")
        )
        self.assertTrue(item.payload()["is_enabled"])

    def test_skips_rows_without_id_and_bad_shapes(self) -> None:
        items = parse_subscriptions(
            "report-1", [row(id=""), "bukan-object", None, row(id="sub-2")]
        )
        self.assertEqual([item.subscription_id for item in items], ["sub-2"])

    def test_tolerates_missing_users_and_fields(self) -> None:
        items = parse_subscriptions("report-1", [{"id": "sub-3"}])
        self.assertEqual(items[0].receiver_count, 0)
        self.assertEqual(items[0].page_name, "")
        self.assertFalse(items[0].is_enabled)

    def test_has_enabled_and_unmapped_count(self) -> None:
        enabled = parse_subscriptions("r1", [row()])
        disabled = parse_subscriptions("r2", [row(isEnabled=False)])
        self.assertTrue(has_enabled(enabled))
        self.assertFalse(has_enabled(disabled))
        self.assertEqual(
            unmapped_reports(
                ["r1", "r2", "r3"], {"r1": enabled, "r2": disabled}
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()

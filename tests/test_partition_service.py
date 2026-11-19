"""Uji orkestrasi inventaris/proses partisi tanpa XMLA asli."""

from __future__ import annotations

import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from core.auth import ServicePrincipal, Token
from core.column_stats import partition_row_counts
from core.errors import ExtractionError
from core.partition_service import (
    _dmv_rows_subprocess,
    inventory_rows,
    process_partitions,
    read_partition_inventory,
)
from core.tom_client import PartitionInfo, PartitionRange


def _partition(
    table: str = "Fact",
    name: str = "P1",
    *,
    is_calculated: bool = False,
    mode: str = "Import",
    range_label: str = "",
) -> PartitionInfo:
    return PartitionInfo(
        table=table,
        name=name,
        state="Ready",
        mode=mode,
        data_view="Full",
        source_type="CalculatedPartitionSource" if is_calculated else "MPartitionSource",
        expression="RangeStart",
        description="",
        modified_time="2026-01-01 00:00:00",
        refreshed_time="2026-01-02 00:00:00",
        is_calculated=is_calculated,
        range=PartitionRange(label=range_label, source="M"),
    )


class FakeDmvClient:
    def __init__(self, segments: list[dict] | None = None) -> None:
        self.segments = segments or []
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def query(self, name: str) -> list[dict]:
        self.queries.append(name)
        return self.segments


class PartitionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = ServicePrincipal("tenant", "client", "secret")

    def test_partition_row_counts_uses_largest_data_segment(self) -> None:
        counts = partition_row_counts(
            [
                {"MEASURE_GROUP_NAME": "Fact", "PARTITION_NAME": "P1", "COLUMN_ID": "A (1)", "RECORDS_COUNT": 10},
                {"MEASURE_GROUP_NAME": "Fact", "PARTITION_NAME": "P1", "COLUMN_ID": "B (2)", "RECORDS_COUNT": 12},
                {"MEASURE_GROUP_NAME": "Fact", "PARTITION_NAME": "P1", "COLUMN_ID": "POS_TO_ID", "RECORDS_COUNT": 999},
                {"MEASURE_GROUP_NAME": "Fact", "PARTITION_NAME": "P1", "COLUMN_ID": "C (3)", "COLUMN_TYPE": "INDEX", "RECORDS_COUNT": 999},
            ]
        )
        self.assertEqual(counts, {("Fact", "P1"): 12})

    def test_inventory_rows_keeps_unknown_rows_empty(self) -> None:
        rows = inventory_rows(
            [_partition(range_label="2026-01-01 → 2026-02-01")],
            {},
        )
        self.assertIsNone(rows[0]["rows"])
        self.assertEqual(rows[0]["range"], "2026-01-01 → 2026-02-01")
        self.assertEqual(rows[0]["source_type"], "MPartitionSource")

    def test_dmv_subprocess_keeps_token_out_of_arguments(self) -> None:
        tokens = SimpleNamespace(
            get=lambda _scope: Token(value="secret-token", expires_on=123)
        )
        completed = SimpleNamespace(
            returncode=0,
            stdout='[{"TABLE_NAME": "Fact"}]',
            stderr="",
        )
        with patch(
            "core.partition_service.cli_argv",
            return_value=["bi-tools-cli.exe", "partition", "--dmv-json"],
        ), patch("core.partition_service.subprocess.run", return_value=completed) as run:
            rows = _dmv_rows_subprocess("powerbi://endpoint", "Model", tokens)
        command = run.call_args.args[0]
        self.assertNotIn("secret-token", " ".join(command))
        self.assertIn("secret-token", run.call_args.kwargs["input"])
        self.assertEqual(rows[0]["TABLE_NAME"], "Fact")

    def test_read_inventory_combines_tom_and_dmv(self) -> None:
        dmv = FakeDmvClient(
            [
                {
                    "MEASURE_GROUP_NAME": "Fact",
                    "PARTITION_NAME": "P1",
                    "COLUMN_ID": "A (1)",
                    "RECORDS_COUNT": 42,
                }
            ]
        )
        with patch(
            "core.partition_service.list_partitions",
            return_value=[_partition(range_label="2026-01")],
        ):
            payload = read_partition_inventory(
                workspace_id="11111111-2222-3333-4444-555555555555",
                workspace_name="Workspace",
                dataset_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                dataset_name="Model",
                principal=self.principal,
                connect_factory=lambda *_args, **_kwargs: nullcontext(object()),
                open_factory=lambda **_kwargs: dmv,
            )
        self.assertEqual(payload["dataset"]["name"], "Model")
        self.assertEqual(payload["partitions"][0]["rows"], 42)
        self.assertEqual(payload["partitions"][0]["range"], "2026-01")
        self.assertEqual(dmv.queries, ["DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS"])

    def test_process_builds_one_tmsl_for_all_targets(self) -> None:
        partitions = [_partition("Fact", "P1"), _partition("Fact", "P2")]
        seen: dict[str, str] = {}

        def execute(_server, tmsl: str) -> None:
            seen["tmsl"] = tmsl

        with patch(
            "core.partition_service.list_partitions", return_value=partitions
        ):
            payload = process_partitions(
                workspace_id="11111111-2222-3333-4444-555555555555",
                workspace_name="Workspace",
                dataset_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                dataset_name="Model",
                targets=(("Fact", "P1"), ("Fact", "P2")),
                refresh_type="dataOnly",
                principal=self.principal,
                connect_factory=lambda *_args, **_kwargs: nullcontext(object()),
                open_factory=lambda **_kwargs: FakeDmvClient(),
                execute_factory=execute,
            )
        body = json.loads(seen["tmsl"])
        self.assertEqual(body["refresh"]["type"], "dataOnly")
        self.assertEqual(len(body["refresh"]["objects"]), 2)
        self.assertEqual(payload["refresh"]["type"], "dataOnly")
        self.assertEqual(len(payload["refresh"]["targets"]), 2)

    def test_process_rejects_missing_target_and_calculated_add(self) -> None:
        with patch(
            "core.partition_service.list_partitions", return_value=[_partition()]
        ):
            with self.assertRaises(ExtractionError):
                process_partitions(
                    workspace_id="11111111-2222-3333-4444-555555555555",
                    workspace_name="Workspace",
                    dataset_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    dataset_name="Model",
                    targets=(("Fact", "Missing"),),
                    refresh_type="full",
                    principal=self.principal,
                    connect_factory=lambda *_args, **_kwargs: nullcontext(object()),
                )

        calculated = _partition("Calc", "P", is_calculated=True)
        with patch(
            "core.partition_service.list_partitions", return_value=[calculated]
        ):
            with self.assertRaises(ExtractionError):
                process_partitions(
                    workspace_id="11111111-2222-3333-4444-555555555555",
                    workspace_name="Workspace",
                    dataset_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    dataset_name="Model",
                    targets=(("Calc", "P"),),
                    refresh_type="add",
                    principal=self.principal,
                    connect_factory=lambda *_args, **_kwargs: nullcontext(object()),
                )


if __name__ == "__main__":
    unittest.main()

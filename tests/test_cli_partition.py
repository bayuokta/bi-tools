"""Uji CLI partisi tanpa XMLA atau jaringan."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from cli import partition as cli
from core.partition_plan import PartitionInfo


WORKSPACE = "11111111-2222-3333-4444-555555555555"
DATASET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _cli_partition(
    table: str = "Fact", name: str = "P1", *, is_calculated: bool = False
) -> PartitionInfo:
    return PartitionInfo(
        table=table,
        name=name,
        state="Ready",
        mode="Import",
        data_view="Full",
        source_type="CalculatedPartitionSource" if is_calculated else "MPartitionSource",
        expression="",
        description="",
        modified_time="",
        refreshed_time="",
        is_calculated=is_calculated,
    )


class PartitionCliTests(unittest.TestCase):
    def test_list_prints_inventory(self) -> None:
        payload = {
            "workspace": {"name": "Workspace"},
            "dataset": {"name": "Model"},
            "endpoint": "powerbi://endpoint",
            "partitions": [
                {
                    "table": "Fact",
                    "partition": "P1",
                    "rows": 10,
                    "range": "2026-01",
                    "state": "Ready",
                    "last_processed": "2026-01-02 00:00:00",
                }
            ],
            "warnings": [],
        }
        buffer = io.StringIO()
        with patch.object(cli, "_names", return_value=("Workspace", "Model")), patch.object(
            cli.ServicePrincipal, "from_env", return_value=object()
        ), patch.object(cli, "read_partition_inventory", return_value=payload) as read, contextlib.redirect_stdout(buffer):
            code = cli.main(
                ["--workspace-id", WORKSPACE, "--dataset-id", DATASET, "--list"]
            )
        self.assertEqual(code, 0)
        self.assertIn("Fact", buffer.getvalue())
        self.assertIn("2026-01", buffer.getvalue())
        read.assert_called_once()

    def test_process_requires_yes(self) -> None:
        buffer = io.StringIO()
        with patch.object(cli, "_names", return_value=("Workspace", "Model")), patch.object(
            cli.ServicePrincipal, "from_env", return_value=object()
        ), contextlib.redirect_stderr(buffer):
            code = cli.main(
                [
                    "--workspace-id",
                    WORKSPACE,
                    "--dataset-id",
                    DATASET,
                    "--table",
                    "Fact",
                    "--partition",
                    "P1",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("--yes", buffer.getvalue())

    def test_dmv_json_reads_token_from_stdin(self) -> None:
        class FakeClient:
            def query(self, name: str):
                self.name = name
                return [{"TABLE_NAME": "Fact", "RECORDS_COUNT": 3}]

        fake = FakeClient()
        buffer = io.StringIO()
        stdin = io.StringIO(
            json.dumps({"token": "secret-token", "expires_on": 123})
        )
        with patch.object(
            cli, "open_client", return_value=contextlib.nullcontext(fake)
        ) as opened, patch("sys.stdin", stdin), contextlib.redirect_stdout(buffer):
            code = cli.main(
                [
                    "--dmv-json",
                    "--endpoint",
                    "powerbi://api.powerbi.com/v1.0/myorg/W",
                    "--catalog",
                    "Model",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())[0]["RECORDS_COUNT"], 3)
        tokens = opened.call_args.kwargs["tokens"]
        self.assertEqual(tokens.get("scope").value, "secret-token")
        self.assertEqual(fake.name, "DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS")

    def test_dmv_json_requires_token(self) -> None:
        buffer = io.StringIO()
        with patch("sys.stdin", io.StringIO("{}")), contextlib.redirect_stderr(buffer):
            code = cli.main(
                [
                    "--dmv-json",
                    "--endpoint",
                    "powerbi://api.powerbi.com/v1.0/myorg/W",
                    "--catalog",
                    "Model",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("Token", buffer.getvalue())

    def test_process_with_yes_delegates(self) -> None:
        payload = {
            "workspace": {"name": "Workspace"},
            "dataset": {"name": "Model"},
            "endpoint": "powerbi://endpoint",
            "partitions": [],
            "warnings": [],
            "refresh": {"message": "Refresh selesai."},
        }
        buffer = io.StringIO()
        with patch.object(cli, "_names", return_value=("Workspace", "Model")), patch.object(
            cli.ServicePrincipal, "from_env", return_value=object()
        ), patch.object(cli, "process_partitions", return_value=payload) as process, contextlib.redirect_stdout(buffer):
            code = cli.main(
                [
                    "--workspace-id",
                    WORKSPACE,
                    "--dataset-id",
                    DATASET,
                    "--table",
                    "Fact",
                    "--partition",
                    "P1",
                    "--refresh-type",
                    "dataOnly",
                    "--yes",
                ]
            )
        self.assertEqual(code, 0)
        kwargs = process.call_args.kwargs
        self.assertEqual(kwargs["targets"], (("Fact", "P1"),))
        self.assertEqual(kwargs["refresh_type"], "dataOnly")
        self.assertIn("Refresh selesai.", buffer.getvalue())


    def test_inventory_json_reads_token_from_stdin(self) -> None:
        partition = PartitionInfo(
            table="Fact",
            name="P1",
            state="Ready",
            mode="Import",
            data_view="Full",
            source_type="MPartitionSource",
            expression="RangeStart",
            description="",
            modified_time="2026-01-01 00:00:00",
            refreshed_time="2026-01-02 00:00:00",
            is_calculated=False,
        )
        buffer = io.StringIO()
        stdin = io.StringIO(json.dumps({"token": "secret-token", "expires_on": 123}))
        with patch.object(
            cli, "connect_server", return_value=contextlib.nullcontext(object())
        ) as opened, patch.object(
            cli, "list_partitions", return_value=[partition]
        ), patch("sys.stdin", stdin), contextlib.redirect_stdout(buffer):
            code = cli.main(
                [
                    "--inventory-json",
                    "--endpoint",
                    "powerbi://api.powerbi.com/v1.0/myorg/W",
                    "--catalog",
                    "Model",
                ]
            )
        self.assertEqual(code, 0)
        rows = json.loads(buffer.getvalue())
        self.assertEqual(rows[0]["partition"], "P1")
        tokens = opened.call_args.args[2]
        self.assertEqual(tokens.get("scope").value, "secret-token")

    def test_refresh_json_executes_one_tmsl(self) -> None:
        partitions = [
            _cli_partition("Fact", "P1"),
            _cli_partition("Fact", "P2"),
        ]
        seen: dict[str, str] = {}
        buffer = io.StringIO()
        errors = io.StringIO()
        stdin = io.StringIO(
            json.dumps(
                {
                    "token": "secret-token",
                    "expires_on": 123,
                    "refresh_type": "dataOnly",
                    "targets": [
                        {"table": "Fact", "partition": "P1"},
                        {"table": "Fact", "partition": "P2"},
                    ],
                }
            )
        )

        def execute(_server, tmsl: str) -> None:
            seen["tmsl"] = tmsl

        with patch.object(
            cli, "connect_server", return_value=contextlib.nullcontext(object())
        ), patch.object(cli, "list_partitions", return_value=partitions), patch.object(
            cli, "execute_refresh", side_effect=execute
        ), patch("sys.stdin", stdin), contextlib.redirect_stdout(
            buffer
        ), contextlib.redirect_stderr(errors):
            code = cli.main(
                [
                    "--refresh-json",
                    "--endpoint",
                    "powerbi://api.powerbi.com/v1.0/myorg/W",
                    "--catalog",
                    "Model",
                ]
            )
        self.assertEqual(code, 0)
        body = json.loads(seen["tmsl"])
        self.assertEqual(body["refresh"]["type"], "dataOnly")
        self.assertEqual(len(body["refresh"]["objects"]), 2)
        self.assertIn("Sending TMSL refresh", errors.getvalue())
        self.assertEqual(len(json.loads(buffer.getvalue())), 2)

    def test_refresh_json_rejects_missing_and_calculated_add(self) -> None:
        errors = io.StringIO()
        stdin = io.StringIO(
            json.dumps(
                {
                    "token": "secret-token",
                    "refresh_type": "full",
                    "targets": [{"table": "Fact", "partition": "Missing"}],
                }
            )
        )
        with patch.object(
            cli, "connect_server", return_value=contextlib.nullcontext(object())
        ), patch.object(
            cli, "list_partitions", return_value=[_cli_partition("Fact", "P1")]
        ), patch("sys.stdin", stdin), contextlib.redirect_stderr(errors):
            code = cli.main(
                [
                    "--refresh-json",
                    "--endpoint",
                    "powerbi://api.powerbi.com/v1.0/myorg/W",
                    "--catalog",
                    "Model",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("not found", errors.getvalue())

        calculated = _cli_partition("Calc", "P", is_calculated=True)
        errors = io.StringIO()
        stdin = io.StringIO(
            json.dumps(
                {
                    "token": "secret-token",
                    "refresh_type": "add",
                    "targets": [{"table": "Calc", "partition": "P"}],
                }
            )
        )
        with patch.object(
            cli, "connect_server", return_value=contextlib.nullcontext(object())
        ), patch.object(cli, "list_partitions", return_value=[calculated]), patch(
            "sys.stdin", stdin
        ), contextlib.redirect_stderr(errors):
            code = cli.main(
                [
                    "--refresh-json",
                    "--endpoint",
                    "powerbi://api.powerbi.com/v1.0/myorg/W",
                    "--catalog",
                    "Model",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("calculated partition", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

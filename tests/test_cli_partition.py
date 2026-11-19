"""Uji CLI partisi tanpa XMLA atau jaringan."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from cli import partition as cli


WORKSPACE = "11111111-2222-3333-4444-555555555555"
DATASET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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


if __name__ == "__main__":
    unittest.main()

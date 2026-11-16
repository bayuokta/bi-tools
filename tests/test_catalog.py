"""Uji katalog workspace: konversi endpoint XMLA, penyimpanan, sync, dan CLI."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.lineage import main as cli_main
from core.auth import ServicePrincipal
from core.catalog_sync import WorkspaceSyncResult, run_workspace_sync
from core.errors import ExtractionError
from core.lineage_api import LineageApiError, PowerBILineageClient
from core.lineage_service import (
    workspace_lookup,
    workspace_options,
    workspace_status,
)
from core.lineage_store import (
    close_quietly,
    connect,
    initialize,
    save_workspace_sync_run,
    save_workspaces,
    workspace_by_id,
    workspace_by_name,
    workspace_list,
    workspace_sync_stats,
)
from core.xmla_client import (
    WorkspaceEndpoint,
    XmlaError,
    normalize_powerbi_endpoint,
    parse_workspace_endpoint,
    workspace_endpoint,
)

SETTINGS = ServicePrincipal.from_values("tenant", "client", "secret")


# --------------------------------------------------------------- endpoint
class WorkspaceEndpointTests(unittest.TestCase):
    def test_parse_real_endpoint(self) -> None:
        parsed = parse_workspace_endpoint(
            "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO"
        )
        self.assertEqual(parsed, WorkspaceEndpoint("myorg", "Contoh - SO"))
        self.assertEqual(parsed.workspace_id, "")

    def test_parse_guid_suffix_from_duplicate_workaround(self) -> None:
        parsed = parse_workspace_endpoint(
            "powerbi://api.powerbi.com/v1.0/myorg/"
            "Contoso%20Sales%20-%20aaaabbbb-0000-cccc-1111-dddd2222eeee"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.name, "Contoso Sales")
        self.assertEqual(parsed.workspace_id, "aaaabbbb-0000-cccc-1111-dddd2222eeee")

    def test_parse_keeps_dash_in_name_without_guid(self) -> None:
        parsed = parse_workspace_endpoint(
            "powerbi://api.powerbi.com/v1.0/myorg/Report%20Uji"
        )
        self.assertEqual(parsed.name, "Report Uji")
        self.assertEqual(parsed.workspace_id, "")

    def test_parse_connection_string_and_query(self) -> None:
        parsed = parse_workspace_endpoint(
            'Data Source="powerbi://api.powerbi.com/v1.0/contoso.com/'
            'Sales%20WS?readonly";Initial Catalog="Model"'
        )
        self.assertEqual(parsed, WorkspaceEndpoint("contoso.com", "Sales WS"))

    def test_parse_rejects_other_values(self) -> None:
        for value in (
            "",
            "localhost:50000",
            "powerbi://api.powerbi.com/v1.0",
            "asazure://region.asazure.windows.net/srv",
            "Sales Workspace",
        ):
            self.assertIsNone(parse_workspace_endpoint(value), value)

    def test_build_matches_known_endpoint_and_roundtrips(self) -> None:
        url = workspace_endpoint("myorg", "Contoh - SO")
        self.assertEqual(
            url, "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO"
        )
        self.assertEqual(parse_workspace_endpoint(url).name, "Contoh - SO")
        self.assertEqual(
            normalize_powerbi_endpoint(url),
            'Data Source="powerbi://api.powerbi.com/v1.0/myorg/'
            'Contoh%20-%20SO?readonly"',
        )

    def test_build_with_disambiguation(self) -> None:
        url = workspace_endpoint(
            "myorg",
            "Sales",
            "aaaabbbb-0000-cccc-1111-dddd2222eeee",
            disambiguate=True,
        )
        self.assertEqual(
            url,
            "powerbi://api.powerbi.com/v1.0/myorg/"
            "Sales%20-%20aaaabbbb-0000-cccc-1111-dddd2222eeee",
        )
        parsed = parse_workspace_endpoint(url)
        self.assertEqual(parsed.name, "Sales")
        self.assertEqual(parsed.workspace_id, "aaaabbbb-0000-cccc-1111-dddd2222eeee")

    def test_build_requires_name(self) -> None:
        with self.assertRaises(XmlaError):
            workspace_endpoint("myorg", "   ")


# ------------------------------------------------------------------ store
def workspace_row(**overrides: object) -> dict:
    row = {"id": "ws-1", "name": "Alpha", "state": "Active", "type": "Workspace"}
    row.update(overrides)
    return row


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "lineage.db"
        conn = connect(self.db)
        try:
            initialize(conn)
        finally:
            close_quietly(conn)

    def save(
        self, rows: list[dict], *, full: bool = True, sync_id: str = "ws-sync"
    ) -> tuple[int, int]:
        conn = connect(self.db)
        try:
            return save_workspaces(conn, sync_id, rows, full=full)
        finally:
            close_quietly(conn)

    def rows(self, query: str, params: tuple = ()) -> list[dict]:
        conn = connect(self.db)
        try:
            return [dict(row) for row in conn.execute(query, params)]
        finally:
            close_quietly(conn)

    def test_full_sync_updates_and_deactivates_missing(self) -> None:
        self.assertEqual(
            self.save([workspace_row(), workspace_row(id="ws-2", name="Beta")]),
            (2, 0),
        )
        self.assertEqual(
            self.save([workspace_row(name="Alpha Baru")], sync_id="ws-sync-2"),
            (0, 1),
        )

        conn = connect(self.db)
        try:
            names = [row["name"] for row in workspace_list(conn)]
        finally:
            close_quietly(conn)
        self.assertEqual(names, ["Alpha Baru"])
        self.assertEqual(
            [row["is_active"] for row in self.rows("SELECT is_active FROM workspace ORDER BY workspace_id")],
            [1, 0],
        )

    def test_member_sync_never_deactivates(self) -> None:
        self.save([workspace_row(), workspace_row(id="ws-2", name="Beta")], full=False)
        self.save([workspace_row()], full=False, sync_id="ws-sync-2")

        conn = connect(self.db)
        try:
            rows = workspace_list(conn)
        finally:
            close_quietly(conn)
        self.assertEqual(len(rows), 2)

    def test_deleted_state_is_inactive(self) -> None:
        self.save([workspace_row(state="Deleted")])
        conn = connect(self.db)
        try:
            self.assertEqual(workspace_list(conn), [])
            self.assertEqual(len(workspace_list(conn, active_only=False)), 1)
        finally:
            close_quietly(conn)

    def test_personal_types_hidden_by_default(self) -> None:
        self.save([workspace_row(id="p-1", name="My workspace", type="PersonalGroup")])
        conn = connect(self.db)
        try:
            self.assertEqual(workspace_list(conn), [])
            hidden = workspace_list(conn, include_personal=True)
        finally:
            close_quietly(conn)
        self.assertEqual([row["workspace_id"] for row in hidden], ["p-1"])

    def test_lookup_by_name_and_id(self) -> None:
        self.save([workspace_row(), workspace_row(id="ws-2", name="Alpha")])
        conn = connect(self.db)
        try:
            by_name = workspace_by_name(conn, "Alpha")
            by_id = workspace_by_id(conn, "ws-2")
        finally:
            close_quietly(conn)
        self.assertEqual({row["workspace_id"] for row in by_name}, {"ws-1", "ws-2"})
        self.assertEqual(by_id["name"], "Alpha")

    def test_sync_does_not_clobber_node_is_active(self) -> None:
        self.save([workspace_row()])
        conn = connect(self.db)
        try:
            conn.execute("UPDATE nodes SET is_active = 0 WHERE node_id = 'ws-1'")
            conn.commit()
            save_workspaces(conn, "ws-sync-2", [workspace_row()], full=True)
            node = conn.execute(
                "SELECT is_active, name FROM nodes WHERE node_id = 'ws-1'"
            ).fetchone()
        finally:
            close_quietly(conn)
        self.assertEqual(node["is_active"], 0)
        self.assertEqual(node["name"], "Alpha")

    def test_sync_stats(self) -> None:
        self.save([workspace_row(), workspace_row(id="ws-2", name="Beta")])
        conn = connect(self.db)
        try:
            save_workspace_sync_run(
                conn,
                "ws-run",
                started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:00:05Z",
                mode="admin",
                workspace_count=2,
                active_count=2,
                status="Succeeded",
            )
            summary = workspace_sync_stats(conn)
        finally:
            close_quietly(conn)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["active"], 2)
        self.assertEqual(summary["last_mode"], "admin")
        self.assertEqual(summary["last_sync"], "2026-01-01T00:00:05Z")

    def test_service_returns_empty_for_old_database(self) -> None:
        legacy = Path(self._tmp.name) / "legacy.db"
        conn = connect(legacy)
        try:
            conn.execute("CREATE TABLE nodes (node_id TEXT PRIMARY KEY)")
            conn.commit()
        finally:
            close_quietly(conn)

        self.assertEqual(workspace_options(legacy), [])
        self.assertEqual(workspace_lookup(legacy, "Alpha"), [])
        self.assertEqual(workspace_status(legacy)["total"], 0)

    def test_service_reads_options(self) -> None:
        self.save([workspace_row(), workspace_row(id="ws-2", name="Beta")])
        options = workspace_options(self.db)
        self.assertEqual([option.name for option in options], ["Alpha", "Beta"])
        self.assertEqual(workspace_lookup(self.db, "Alpha")[0].workspace_id, "ws-1")


# -------------------------------------------------------------------- API
class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.text = ""
        self.content = b"{}" if payload is not None else b""

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("bukan JSON")
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"request tak terduga: {method} {url}")
        return self.responses.pop(0)

    def close(self) -> None:
        pass


class RoutingSession(FakeSession):
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        super().__init__()
        self.routes = routes

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response
        return FakeResponse(404, {"error": {"message": "not found"}})


class FakeMsal:
    def acquire_token_for_client(self, scopes: list[str]) -> dict:
        return {"access_token": "token-1", "expires_in": 3600}


def client_with(session: FakeSession) -> PowerBILineageClient:
    return PowerBILineageClient(
        SETTINGS, session=session, msal_app=FakeMsal(), sleep=lambda _seconds: None
    )


class WorkspaceApiTests(unittest.TestCase):
    def test_admin_workspaces_pages_with_top_and_skip(self) -> None:
        session = FakeSession(
            [
                FakeResponse(200, {"value": [{"id": "a"}, {"id": "b"}]}),
                FakeResponse(200, {"value": [{"id": "c"}]}),
            ]
        )
        client = client_with(session)
        try:
            rows = client.admin_workspaces(page_size=2)
        finally:
            client.close()
        self.assertEqual([row["id"] for row in rows], ["a", "b", "c"])
        self.assertEqual(session.calls[0][2]["params"], {"$top": 2, "$skip": 0})
        self.assertEqual(session.calls[1][2]["params"], {"$top": 2, "$skip": 2})

    def test_paging_stops_when_endpoint_ignores_skip(self) -> None:
        repeated = {"value": [{"id": "a"}, {"id": "b"}]}
        session = FakeSession(
            [FakeResponse(200, repeated), FakeResponse(200, dict(repeated))]
        )
        client = client_with(session)
        try:
            rows = client.admin_workspaces(page_size=2)
        finally:
            client.close()
        self.assertEqual([row["id"] for row in rows], ["a", "b"])
        self.assertEqual(len(session.calls), 2)

    def test_datasets_and_reports_in_group(self) -> None:
        session = RoutingSession(
            {
                "groups/ws-1/datasets": FakeResponse(
                    200, {"value": [{"id": "ds-1", "name": "Model"}]}
                ),
                "groups/ws-1/reports": FakeResponse(
                    200,
                    {
                        "value": [
                            {
                                "id": "rep-1",
                                "name": "Report",
                                "datasetId": "ds-1",
                                "reportType": "PowerBIReport",
                            }
                        ]
                    },
                ),
            }
        )
        client = client_with(session)
        try:
            datasets = client.datasets_in_group("ws-1")
            reports = client.reports_in_group("ws-1")
        finally:
            client.close()
        self.assertEqual(datasets[0]["name"], "Model")
        self.assertEqual(reports[0]["datasetId"], "ds-1")

    def test_item_list_raises_api_error(self) -> None:
        client = client_with(
            FakeSession([FakeResponse(403, {"error": {"message": "Forbidden"}})])
        )
        try:
            with self.assertRaises(LineageApiError):
                client.datasets_in_group("ws-1")
        finally:
            client.close()


# ------------------------------------------------------------------- sync
class FakeWorkspaceClient:
    def __init__(
        self,
        *,
        admin: bool = True,
        admin_rows: list[dict] | None = None,
        member_rows: list[tuple[str, str]] | None = None,
        fail: bool = False,
    ) -> None:
        self.admin = admin
        self.admin_rows = admin_rows if admin_rows is not None else [workspace_row()]
        self.member_rows = (
            member_rows if member_rows is not None else [("ws-1", "Sales Workspace")]
        )
        self.fail = fail
        self.closed = False
        self.calls: list[str] = []

    def probe_admin(self) -> bool:
        return self.admin

    def admin_workspaces(self, page_size: int | None = None) -> list[dict]:
        self.calls.append(f"admin:{page_size}")
        if self.fail:
            raise ExtractionError("daftar workspace gagal")
        return list(self.admin_rows)

    def member_workspaces(self, page_size: int | None = None) -> list[tuple[str, str]]:
        self.calls.append(f"member:{page_size}")
        if self.fail:
            raise ExtractionError("daftar workspace gagal")
        return list(self.member_rows)

    def close(self) -> None:
        self.closed = True


class WorkspaceSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "lineage.db"

    def sync(self, client: FakeWorkspaceClient, **kwargs: object):
        return run_workspace_sync(
            self.db,
            SETTINGS,
            client_factory=lambda settings, log=None: client,
            **kwargs,
        )

    def test_admin_sync_saves_and_records_run(self) -> None:
        client = FakeWorkspaceClient(
            admin_rows=[workspace_row(), workspace_row(id="ws-2", name="Beta")]
        )
        result = self.sync(client)

        self.assertEqual(result.mode, "admin")
        self.assertEqual(result.workspace_count, 2)
        self.assertEqual(result.active_count, 2)
        self.assertEqual(result.added, 2)
        self.assertEqual(result.updated, 0)
        self.assertTrue(client.closed)

        conn = connect(self.db)
        try:
            runs = [
                dict(row)
                for row in conn.execute(
                    "SELECT mode, status, workspace_count FROM workspace_sync_run"
                )
            ]
        finally:
            close_quietly(conn)
        self.assertEqual(
            runs, [{"mode": "admin", "status": "Succeeded", "workspace_count": 2}]
        )

    def test_auto_falls_back_to_member_without_deactivation(self) -> None:
        client = FakeWorkspaceClient(admin=False)
        result = self.sync(client)
        self.assertEqual(result.mode, "member")
        self.assertEqual(result.workspace_count, 1)

        empty = FakeWorkspaceClient(admin=False, member_rows=[])
        second = self.sync(empty)
        self.assertEqual(second.workspace_count, 0)

        conn = connect(self.db)
        try:
            rows = workspace_list(conn)
        finally:
            close_quietly(conn)
        self.assertEqual([row["workspace_id"] for row in rows], ["ws-1"])

    def test_failure_records_failed_run_and_closes_client(self) -> None:
        client = FakeWorkspaceClient(fail=True)
        with self.assertRaises(ExtractionError):
            self.sync(client)
        self.assertTrue(client.closed)

        conn = connect(self.db)
        try:
            run = conn.execute(
                "SELECT status, message FROM workspace_sync_run"
            ).fetchone()
        finally:
            close_quietly(conn)
        self.assertEqual(run["status"], "Failed")
        self.assertIn("daftar workspace gagal", run["message"])

    def test_unknown_mode_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            run_workspace_sync(self.db, SETTINGS, mode="lain")


# -------------------------------------------------------------------- CLI
class WorkspaceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "lineage.db"

    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli_main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_sync_json_keeps_stdout_parseable(self) -> None:
        result = WorkspaceSyncResult(
            database=self.db,
            sync_id="ws-1",
            mode="admin",
            workspace_count=2,
            active_count=2,
            added=2,
            updated=0,
            started_at="2026-01-01T00:00:00.0000000Z",
            finished_at="2026-01-01T00:00:01.0000000Z",
            duration_seconds=1.5,
        )

        def fake_sync(database, settings, *, mode, log):
            log("progres sync")
            return result

        with patch.dict(
            os.environ,
            {"TENANT_ID": "t", "CLIENT_ID": "c", "CLIENT_SECRET": "s"},
            clear=False,
        ), patch("cli.lineage.run_workspace_sync", side_effect=fake_sync):
            code, out, err = self.run_cli(
                ["--db", str(self.db), "--sync-workspaces", "--json"]
            )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["workspace_count"], 2)
        self.assertEqual(data["added"], 2)
        self.assertAlmostEqual(data["duration_seconds"], 1.5)
        self.assertIn("progres sync", err)

    def test_missing_credentials_exit_code(self) -> None:
        clean = {
            key: value
            for key, value in os.environ.items()
            if key not in {"TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"}
        }
        with patch.dict(os.environ, clean, clear=True):
            code, _, err = self.run_cli(["--db", str(self.db), "--sync-workspaces"])
        self.assertEqual(code, 2)
        self.assertIn("TENANT_ID", err)


if __name__ == "__main__":
    unittest.main()

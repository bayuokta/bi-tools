"""Uji modul lineage: transform, SQLite, REST client, scan, CSV, CLI, dan GUI."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication
except Exception:  # noqa: BLE001 - PySide6 opsional untuk uji core
    GUI_AVAILABLE = False
else:
    GUI_AVAILABLE = True

from cli.lineage import main as cli_main
from core.errors import ExtractionError
from core.lineage_api import LineageApiError, PowerBILineageClient
from core.auth import ServicePrincipal
from core.lineage_export import CSV_FIELDS, write_lineage_csv
from core.lineage_layout import build_graph
from core.lineage_scan import LineageScanResult, run_lineage_scan
from core.lineage_store import (
    DEFAULT_DB,
    active_counts,
    close_quietly,
    connect,
    diagnostics,
    initialize,
    lineage,
    open_read_only,
    save,
    search,
    stats,
)
from core.lineage_transform import transform
from core.pbix import ROOT

SETTINGS = ServicePrincipal.from_values("tenant", "client", "secret")


def sample_scan() -> dict:
    """Satu workspace lengkap: dataflow -> semantic model -> report -> dashboard."""
    return {
        "workspaces": [
            {
                "id": "ws-1",
                "name": "Sales Workspace",
                "reports": [
                    {
                        "id": "rep-1",
                        "name": "Sales Report",
                        "datasetId": "ds-1",
                        "modifiedBy": "owner@example.com",
                        "modifiedDateTime": "2026-01-02T00:00:00Z",
                        "endorsementDetails": {"endorsement": "Certified"},
                    }
                ],
                "datasets": [
                    {
                        "id": "ds-1",
                        "name": "Sales Model",
                        "configuredBy": "owner@example.com",
                        "createdDate": "2026-01-01T00:00:00Z",
                        "datasourceUsages": [{"datasourceInstanceId": "sql-1"}],
                        "upstreamDataflows": [{"targetDataflowId": "df-1"}],
                    }
                ],
                "dataflows": [
                    {
                        "objectId": "df-1",
                        "name": "Sales Dataflow",
                        "datasourceUsages": [
                            {"datasourceInstanceId": "sharepoint-1"}
                        ],
                        "upstreamDataflows": [],
                    }
                ],
                "dashboards": [
                    {
                        "id": "dash-1",
                        "displayName": "Sales Dashboard",
                        "tiles": [{"reportId": "rep-1"}],
                    }
                ],
                "datasourceInstances": [
                    {
                        "datasourceId": "sql-1",
                        "datasourceType": "Sql",
                        "connectionDetails": {
                            "server": "srv",
                            "database": "SalesDB",
                        },
                    },
                    {
                        "datasourceId": "sharepoint-1",
                        "datasourceType": "SharePoint",
                        "connectionDetails": {
                            "url": "https://contoso.sharepoint.com/sites/sales"
                        },
                    },
                ],
            }
        ]
    }


def seed_database(path: Path) -> None:
    nodes, edges, datasources = transform(sample_scan())
    conn = connect(path)
    try:
        initialize(conn)
        save(conn, "scan-1", ["ws-1"], nodes, edges, datasources)
        conn.execute(
            "INSERT OR REPLACE INTO scan_run VALUES (?,?,?,?,?,?)",
            (
                "scan-1",
                "2025-12-31T23:59:00.0000000Z",
                "2026-01-01T00:00:00.0000000Z",
                "full",
                1,
                "Succeeded",
            ),
        )
        conn.commit()
    finally:
        close_quietly(conn)


class TransformTest(unittest.TestCase):
    def test_nodes_edges_and_datasources(self) -> None:
        nodes, edges, datasources = transform(sample_scan())
        by_id = {node[0]: node for node in nodes}
        self.assertEqual(
            set(by_id),
            {"ws-1", "ds-1", "rep-1", "df-1", "dash-1", "sql-1", "sharepoint-1"},
        )
        self.assertEqual(by_id["rep-1"][1], "Report")
        self.assertEqual(by_id["rep-1"][5], "Certified")
        self.assertEqual(by_id["ds-1"][2], "Sales Model")
        self.assertEqual(by_id["sql-1"][2], "Sql: srv / SalesDB")
        self.assertEqual(by_id["sharepoint-1"][2], "SharePoint: https://contoso.sharepoint.com/sites/sales")

        edge_set = set(edges)
        self.assertIn(("sql-1", "ds-1", "feeds"), edge_set)
        self.assertIn(("df-1", "ds-1", "feeds"), edge_set)
        self.assertIn(("sharepoint-1", "df-1", "feeds"), edge_set)
        self.assertIn(("ds-1", "rep-1", "uses_dataset"), edge_set)
        self.assertIn(("rep-1", "dash-1", "pinned_to"), edge_set)
        self.assertIn(("ws-1", "rep-1", "contains"), edge_set)
        self.assertEqual(len(edges), 9)

        details = {row[0]: row for row in datasources}
        self.assertEqual(details["sql-1"][2], "srv")
        self.assertEqual(details["sql-1"][3], "SalesDB")
        self.assertEqual(json.loads(details["sql-1"][6])["database"], "SalesDB")

    def test_datasource_id_is_stable(self) -> None:
        from core.lineage_transform import datasource_id

        first = datasource_id(
            {"datasourceType": "Sql", "connectionDetails": {"server": "srv"}}
        )
        second = datasource_id(
            {"datasourceType": "Sql", "connectionDetails": {"server": "srv"}}
        )
        other = datasource_id(
            {"datasourceType": "Sql", "connectionDetails": {"server": "lain"}}
        )
        self.assertTrue(first.startswith("ds-"))
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)


class DefaultDatabaseTest(unittest.TestCase):
    def test_default_database_lives_in_data_folder(self) -> None:
        self.assertEqual(DEFAULT_DB, ROOT / "data" / "bi_tools.db")
        self.assertEqual(DEFAULT_DB.parent.name, "data")


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "lineage.db"
        seed_database(self.path)

    def open(self) -> sqlite3.Connection:
        conn = connect(self.path)
        self.addCleanup(lambda: close_quietly(conn))
        return conn

    def test_search_filters(self) -> None:
        conn = self.open()
        rows = search(conn, "Sales")
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            {row["node_type"] for row in rows},
            {"Report", "SemanticModel", "Dataflow", "Dashboard", "Datasource"},
        )
        workspace_rows = search(conn, "Sales", "Sales Workspace")
        self.assertEqual(len(workspace_rows), 4)
        reports = search(conn, "", "", "Report")
        self.assertEqual([row["name"] for row in reports], ["Sales Report"])
        self.assertEqual(search(conn, "rep-1")[0]["node_id"], "rep-1")
        self.assertEqual(search(conn, "tidak-ada"), [])

    def test_lineage_directions(self) -> None:
        conn = self.open()
        downstream = lineage(conn, "sql-1", "downstream")
        self.assertIsNotNone(downstream)
        assert downstream is not None
        depths = {node["name"]: node["depth"] for node in downstream["nodes"]}
        self.assertEqual(
            depths,
            {"Sales Model": 1, "Sales Report": 2, "Sales Dashboard": 3},
        )
        relations = {node["name"]: node["edge_type"] for node in downstream["nodes"]}
        self.assertEqual(relations["Sales Model"], "feeds")
        self.assertEqual(relations["Sales Report"], "uses_dataset")
        self.assertEqual(relations["Sales Dashboard"], "pinned_to")
        self.assertNotIn("Sales Workspace", depths)

        upstream = lineage(conn, "rep-1", "upstream")
        assert upstream is not None
        depths = {node["name"]: node["depth"] for node in upstream["nodes"]}
        self.assertEqual(depths["Sales Model"], 1)
        self.assertEqual(depths["Sql: srv / SalesDB"], 2)
        self.assertEqual(depths["Sales Dataflow"], 2)
        self.assertEqual(depths["SharePoint: https://contoso.sharepoint.com/sites/sales"], 3)

        limited = lineage(conn, "sql-1", "downstream", max_depth=1)
        assert limited is not None
        self.assertEqual([node["name"] for node in limited["nodes"]], ["Sales Model"])

    def test_stats_and_diagnostics(self) -> None:
        conn = self.open()
        data = stats(conn)
        counts = {item["node_type"]: item["n"] for item in data["types"]}
        self.assertEqual(counts["Workspace"], 1)
        self.assertEqual(counts["Report"], 1)
        self.assertEqual(data["last_scan"], "2026-01-01T00:00:00.0000000Z")
        self.assertEqual(active_counts(conn), (7, 9))
        report = diagnostics(conn)
        edges = {row["edge_type"]: row for row in report["edges"]}
        self.assertEqual(edges["feeds"]["total"], 3)
        self.assertEqual(edges["uses_dataset"]["source_missing"], 0)
        self.assertEqual(report["unresolved_feed_sources"], 0)
        self.assertEqual(len(report["scans"]), 1)
        self.assertEqual(report["scans"][0]["status"], "Succeeded")

        conn.execute(
            "INSERT INTO edges VALUES ('ghost','rep-1','feeds',1,'scan-1','scan-1')"
        )
        conn.commit()
        report = diagnostics(conn)
        self.assertEqual(report["unresolved_feed_sources"], 1)
        self.assertTrue(
            any(row["node_id"] == "ghost" for row in report["missing_samples"])
        )

    def test_rescan_deactivates_removed_items(self) -> None:
        conn = self.open()
        second = {
            "workspaces": [
                {
                    "id": "ws-1",
                    "name": "Sales Workspace",
                    "datasets": [{"id": "ds-1", "name": "Sales Model"}],
                }
            ]
        }
        nodes, edges, datasources = transform(second)
        save(conn, "scan-2", ["ws-1"], nodes, edges, datasources)
        self.assertEqual(search(conn, "Sales Report"), [])
        self.assertEqual(search(conn, "", "", "Report"), [])
        self.assertEqual(active_counts(conn), (4, 1))
        self.assertEqual(search(conn, "Sales Model")[0]["node_id"], "ds-1")

    def test_datasource_details_merge(self) -> None:
        conn = self.open()
        second = {
            "workspaces": [
                {
                    "id": "ws-1",
                    "name": "Sales Workspace",
                    "datasets": [
                        {
                            "id": "ds-1",
                            "name": "Sales Model",
                            "datasourceUsages": [{"datasourceInstanceId": "sql-1"}],
                        }
                    ],
                    "datasourceInstances": [
                        {
                            "datasourceId": "sql-1",
                            "datasourceType": "Sql",
                            "connectionDetails": {"server": "srv2"},
                        }
                    ],
                }
            ]
        }
        nodes, edges, datasources = transform(second)
        save(conn, "scan-3", ["ws-1"], nodes, edges, datasources)
        row = conn.execute(
            "SELECT server, database_name, connection_details_json "
            "FROM datasource_detail WHERE node_id='sql-1'"
        ).fetchone()
        assert row is not None
        self.assertEqual(row["server"], "srv2")
        self.assertEqual(row["database_name"], "SalesDB")
        self.assertEqual(json.loads(row["connection_details_json"])["database"], "SalesDB")
        name = conn.execute(
            "SELECT name FROM nodes WHERE node_id='sql-1'"
        ).fetchone()["name"]
        self.assertEqual(name, "Sql: srv2 / SalesDB")

    def test_open_read_only_rejects_missing_or_invalid_database(self) -> None:
        with self.assertRaises(ExtractionError):
            open_read_only(Path(self._tmp.name) / "tidak-ada.db")
        broken = Path(self._tmp.name) / "broken.db"
        broken.write_text("bukan sqlite", encoding="utf-8")
        with self.assertRaises(ExtractionError):
            open_read_only(broken)


class LayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "lineage.db"
        seed_database(self.path)
        conn = connect(self.path)
        self.addCleanup(lambda: close_quietly(conn))
        self.upstream = lineage(conn, "rep-1", "upstream")
        self.downstream = lineage(conn, "rep-1", "downstream")

    def test_two_way_columns_and_edges(self) -> None:
        graph = build_graph(downstream=self.downstream, upstream=self.upstream)
        self.assertEqual(graph.root.node_id, "rep-1")
        self.assertEqual((graph.root.column, graph.root.row, graph.root.side), (0, 0.0, "root"))
        columns = {node.name: node.column for node in graph.nodes}
        self.assertEqual(columns["Sales Dashboard"], 1)
        self.assertEqual(columns["Sales Model"], -1)
        self.assertEqual(columns["Sales Dataflow"], -2)
        self.assertEqual(columns["Sql: srv / SalesDB"], -2)
        self.assertEqual(
            columns["SharePoint: https://contoso.sharepoint.com/sites/sales"], -3
        )
        self.assertEqual(len(graph.nodes), 6)
        self.assertEqual(len({node.node_id for node in graph.nodes}), 6)

        positions = {node.node_id: node for node in graph.nodes}
        for edge in graph.edges:
            self.assertLess(
                positions[edge.source_id].column,
                positions[edge.target_id].column,
            )
        relations = {edge.edge_type for edge in graph.edges}
        self.assertEqual(relations, {"feeds", "uses_dataset", "pinned_to"})

        same_column = sorted(
            node.row for node in graph.nodes if node.column == -2
        )
        self.assertEqual(same_column, [-0.5, 0.5])
        self.assertEqual(graph.truncated, 0)
        self.assertEqual(graph.columns, 4)

    def test_duplicate_nodes_are_merged_once(self) -> None:
        graph = build_graph(downstream=self.upstream, upstream=self.upstream)
        self.assertEqual(len(graph.nodes), 5)
        self.assertEqual(len({node.node_id for node in graph.nodes}), 5)
        self.assertEqual(graph.root.node_id, "rep-1")
        self.assertEqual(graph.truncated, 0)

    def test_node_limit_keeps_nearest_and_reports_truncation(self) -> None:
        graph = build_graph(
            downstream=self.downstream,
            upstream=self.upstream,
            max_nodes=3,
        )
        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(graph.truncated, 3)
        self.assertEqual(
            {node.column for node in graph.nodes},
            {0, -1, 1},
        )

    def test_requires_at_least_one_direction(self) -> None:
        with self.assertRaises(ValueError):
            build_graph()


class ConfigTest(unittest.TestCase):
    def test_from_values_and_validation(self) -> None:
        settings = ServicePrincipal.from_values(" t ", " c ", " s ")
        self.assertEqual(
            (settings.tenant_id, settings.client_id, settings.client_secret),
            ("t", "c", "s"),
        )
        self.assertTrue(settings.is_complete)
        empty = ServicePrincipal.from_values("", "c", "")
        self.assertEqual(empty.missing, ["TENANT_ID", "CLIENT_SECRET"])
        with self.assertRaises(ExtractionError):
            empty.validate()

    def test_from_env_file_and_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "TENANT_ID=file-tenant\n"
                "CLIENT_ID=file-client\n"
                "CLIENT_SECRET=file-secret\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                settings = ServicePrincipal.from_env(env_file)
            self.assertEqual(settings.tenant_id, "file-tenant")
            self.assertEqual(settings.client_secret, "file-secret")

            with patch.dict(
                os.environ,
                {"TENANT_ID": "shell-tenant"},
                clear=True,
            ):
                settings = ServicePrincipal.from_env(env_file)
            self.assertEqual(settings.tenant_id, "shell-tenant")
            self.assertEqual(settings.client_id, "file-client")


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: object = None,
        *,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        self.content = b"{}" if payload is not None else b""

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("bukan JSON")
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"request tak terduga: {method} {url}")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class RoutingSession:
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(url)
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response
        return FakeResponse(404, {}, text="not found")

    def close(self) -> None:
        pass


class FakeMsal:
    def __init__(self, token: str = "token-1", expires_in: int = 3600) -> None:
        self.token = token
        self.expires_in = expires_in
        self.calls = 0

    def acquire_token_for_client(self, scopes: list[str]) -> dict:
        self.calls += 1
        return {"access_token": self.token, "expires_in": self.expires_in}


def client_with(session: FakeSession, **kwargs: object) -> tuple[PowerBILineageClient, FakeMsal]:
    msal = FakeMsal()
    client = PowerBILineageClient(
        SETTINGS,
        session=session,
        msal_app=msal,
        sleep=lambda _seconds: None,
        **kwargs,
    )
    return client, msal


class ApiTest(unittest.TestCase):
    def test_token_is_cached_and_injected_session_not_closed(self) -> None:
        session = FakeSession(
            [FakeResponse(200, {"value": []}), FakeResponse(200, {"value": []})]
        )
        client, msal = client_with(session)
        self.assertEqual(client.member_workspaces(), [])
        self.assertEqual(client.member_workspaces(), [])
        self.assertEqual(msal.calls, 1)
        self.assertEqual(
            session.calls[0][2]["headers"],
            {"Authorization": "Bearer token-1"},
        )
        client.close()
        self.assertFalse(session.closed)

    def test_retry_after_429(self) -> None:
        session = FakeSession(
            [
                FakeResponse(429, headers={"Retry-After": "2"}, text="slow down"),
                FakeResponse(200, {"value": [{"id": "ws-1", "name": "WS"}]}),
            ]
        )
        sleeps: list[float] = []
        msal = FakeMsal()
        client = PowerBILineageClient(
            SETTINGS,
            session=session,
            msal_app=msal,
            sleep=sleeps.append,
        )
        self.assertEqual(client.member_workspaces(), [("ws-1", "WS")])
        self.assertEqual(sleeps, [2])
        self.assertEqual(msal.calls, 1)

    def test_http_error_carries_status_and_probe_fallback(self) -> None:
        client, _ = client_with(FakeSession([FakeResponse(403, text="Forbidden")]))
        with self.assertRaises(LineageApiError) as caught:
            client.member_workspaces()
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("izin service principal", str(caught.exception))

        client, _ = client_with(FakeSession([FakeResponse(403, text="Forbidden")]))
        self.assertFalse(client.probe_admin())

        client, _ = client_with(FakeSession([FakeResponse(500, text="Server error")]))
        with self.assertRaises(LineageApiError) as caught:
            client.probe_admin()
        self.assertEqual(caught.exception.status_code, 500)

    def test_scan_polls_until_succeeded(self) -> None:
        payload = {"workspaces": [{"id": "ws-1"}]}
        session = FakeSession(
            [
                FakeResponse(200, {"id": "scan-1"}),
                FakeResponse(200, {"status": "Running"}),
                FakeResponse(200, {"status": "Succeeded"}),
                FakeResponse(200, payload),
            ]
        )
        sleeps: list[float] = []
        client = PowerBILineageClient(
            SETTINGS,
            session=session,
            msal_app=FakeMsal(),
            sleep=sleeps.append,
        )
        scan_id, result = client.scan(["ws-1"])
        self.assertEqual(scan_id, "scan-1")
        self.assertEqual(result, payload)
        self.assertEqual(sleeps, [5])
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("admin/workspaces/getInfo"))
        self.assertEqual(kwargs["json"], {"workspaces": ["ws-1"]})
        self.assertEqual(kwargs["params"]["lineage"], "True")

    def test_scan_failed_status_raises(self) -> None:
        session = FakeSession(
            [
                FakeResponse(200, {"id": "scan-2"}),
                FakeResponse(200, {"status": "Failed"}),
            ]
        )
        client, _ = client_with(session)
        with self.assertRaises(ExtractionError):
            client.scan(["ws-1"])

    def test_member_scan_collects_items_and_datasources(self) -> None:
        routes = {
            "/groups/ws-1/datasets/ds-1/datasources": FakeResponse(
                200,
                {
                    "value": [
                        {
                            "datasourceType": "Sql",
                            "connectionDetails": {
                                "server": "srv",
                                "database": "SalesDB",
                            },
                        }
                    ]
                },
            ),
            "/groups/ws-1/dataflows/df-1/upstreamDataflows": FakeResponse(
                200, {"value": []}
            ),
            "/groups/ws-1/dataflows/df-1/datasources": FakeResponse(
                200, {"value": []}
            ),
            "/groups/ws-1/datasets": FakeResponse(
                200,
                {"value": [{"id": "ds-1", "name": "Sales Model"}]},
            ),
            "/groups/ws-1/dataflows": FakeResponse(
                200, {"value": [{"objectId": "df-1", "name": "Flow A"}]}
            ),
            "/groups/ws-1/dashboards": FakeResponse(200, {"value": []}),
            "/groups/ws-1/reports": FakeResponse(
                200,
                {"value": [{"id": "rep-1", "name": "Report A", "datasetId": "ds-1"}]},
            ),
            "/groups": FakeResponse(
                200, {"value": [{"id": "ws-1", "name": "Sales WS"}]}
            ),
        }
        session = RoutingSession(routes)
        client = PowerBILineageClient(
            SETTINGS, session=session, msal_app=FakeMsal(), sleep=lambda _s: None
        )
        self.assertEqual(client.member_workspaces(), [("ws-1", "Sales WS")])
        workspace = client.member_scan("ws-1", "Sales WS")
        self.assertEqual(workspace["id"], "ws-1")
        self.assertEqual(len(workspace["datasets"]), 1)
        self.assertEqual(len(workspace["datasets"][0]["datasourceUsages"]), 1)
        self.assertEqual(len(workspace["datasourceInstances"]), 1)

        nodes, edges, datasources = transform({"workspaces": [workspace]})
        types = {node[1] for node in nodes}
        self.assertTrue({"Workspace", "SemanticModel", "Report", "Dataflow", "Datasource"} <= types)
        edge_types = {edge[2] for edge in edges}
        self.assertTrue({"contains", "feeds", "uses_dataset"} <= edge_types)
        self.assertEqual(len(datasources), 1)
        self.assertEqual(datasources[0][2], "srv")
        self.assertEqual(datasources[0][3], "SalesDB")


class FakeLineageClient:
    def __init__(
        self,
        payload: dict | None = None,
        *,
        admin: bool = True,
        fail: str | None = None,
        scan_prefix: str = "scan",
    ) -> None:
        self.payload = payload or sample_scan()
        self.admin = admin
        self.fail = fail
        self.scan_prefix = scan_prefix
        self.modified_since: list[str | None] = []
        self.scan_calls: list[list[str]] = []
        self.member_calls: list[object] = []
        self.closed = False
        self._scan_number = 0

    def probe_admin(self) -> bool:
        return self.admin

    def modified_workspaces(self, modified_since: str | None = None) -> list[str]:
        if self.fail == "modified":
            raise RuntimeError("boom")
        self.modified_since.append(modified_since)
        return ["ws-1"]

    def scan(self, workspace_ids: list[str]) -> tuple[str, dict]:
        if self.fail == "scan":
            raise ExtractionError("scan gagal")
        self.scan_calls.append(list(workspace_ids))
        self._scan_number += 1
        return f"{self.scan_prefix}-{self._scan_number}", self.payload

    def member_workspaces(self) -> list[tuple[str, str]]:
        self.member_calls.append("list")
        return [("ws-1", "Sales Workspace")]

    def member_scan(self, workspace_id: str, workspace_name: str) -> dict:
        self.member_calls.append((workspace_id, workspace_name))
        return self.payload["workspaces"][0]

    def close(self) -> None:
        self.closed = True


class ScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "lineage.db"

    def run_scan(self, client: FakeLineageClient, **kwargs: object):
        return run_lineage_scan(
            self.db,
            SETTINGS,
            client_factory=lambda settings, log=None: client,
            **kwargs,
        )

    def scan_rows(self) -> list[dict]:
        conn = connect(self.db)
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT scan_id, mode, workspace_count, status FROM scan_run "
                    "ORDER BY started_at"
                )
            ]
        finally:
            close_quietly(conn)

    def test_admin_scan_saves_database_and_history(self) -> None:
        client = FakeLineageClient()
        result = self.run_scan(client, mode="admin")
        self.assertEqual(result.mode, "admin")
        self.assertEqual(result.workspace_count, 1)
        self.assertEqual(result.node_count, 7)
        self.assertEqual(result.edge_count, 9)
        self.assertEqual(result.unresolved_sources, 0)
        self.assertEqual(client.scan_calls, [["ws-1"]])
        self.assertEqual(client.modified_since, [None])
        self.assertTrue(client.closed)

        rows = self.scan_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mode"], "full")
        self.assertEqual(rows[0]["workspace_count"], 1)
        self.assertEqual(rows[0]["status"], "Succeeded")

    def test_incremental_and_full_scan_timestamps(self) -> None:
        first = FakeLineageClient(scan_prefix="first")
        first_result = self.run_scan(first, mode="admin")

        second = FakeLineageClient(scan_prefix="second")
        second_result = self.run_scan(second, mode="admin")
        self.assertEqual(second_result.mode, "admin")
        self.assertEqual(second.modified_since, [first_result.started_at])
        self.assertEqual(self.scan_rows()[-1]["mode"], "incremental")

        forced = FakeLineageClient(scan_prefix="forced")
        forced_result = self.run_scan(forced, mode="admin", full=True)
        self.assertEqual(forced_result.mode, "admin")
        self.assertEqual(forced.modified_since, [None])
        self.assertEqual(self.scan_rows()[-1]["mode"], "full")
        self.assertEqual(len(self.scan_rows()), 3)

    def test_auto_falls_back_to_member_scan(self) -> None:
        client = FakeLineageClient(admin=False)
        result = self.run_scan(client, mode="auto")
        self.assertEqual(result.mode, "member")
        self.assertEqual(result.workspace_count, 1)
        self.assertEqual(
            client.member_calls,
            ["list", ("ws-1", "Sales Workspace")],
        )
        self.assertEqual(client.scan_calls, [])
        rows = self.scan_rows()
        self.assertEqual(rows[-1]["mode"], "member")

    def test_failure_is_recorded_and_wrapped(self) -> None:
        client = FakeLineageClient(fail="modified")
        with self.assertRaises(ExtractionError) as caught:
            self.run_scan(client, mode="admin")
        self.assertIn("Scan lineage gagal", str(caught.exception))
        self.assertTrue(client.closed)
        rows = self.scan_rows()
        self.assertTrue(any(row["status"] == "Failed" for row in rows))

    def test_invalid_mode_and_missing_credentials(self) -> None:
        with self.assertRaises(ExtractionError):
            self.run_scan(FakeLineageClient(), mode="lain")
        with self.assertRaises(ExtractionError):
            run_lineage_scan(
                self.db,
                ServicePrincipal.from_values("", "", ""),
                mode="admin",
                client_factory=lambda settings, log=None: FakeLineageClient(),
            )

    def test_unwritable_database_is_wrapped(self) -> None:
        folder = Path(self._tmp.name) / "folder.db"
        folder.mkdir()
        with self.assertRaises(ExtractionError) as caught:
            run_lineage_scan(
                folder,
                SETTINGS,
                mode="admin",
                client_factory=lambda settings, log=None: FakeLineageClient(),
            )
        self.assertIn("Scan lineage gagal", str(caught.exception))


class ExportTest(unittest.TestCase):
    def test_csv_has_bom_headers_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "lineage.db"
            seed_database(db)
            conn = connect(db)
            try:
                result = lineage(conn, "sql-1", "downstream")
            finally:
                close_quietly(conn)
            assert result is not None
            target = Path(tmp) / "out" / "lineage.csv"
            written = write_lineage_csv(target, result)
            self.assertEqual(written, target)
            raw = target.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            text = raw.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            self.assertEqual(list(rows[0].keys()), CSV_FIELDS)
            self.assertEqual(len(rows), 3)
            report = next(row for row in rows if row["name"] == "Sales Report")
            self.assertEqual(report["depth"], "2")
            self.assertEqual(report["type"], "Report")
            self.assertEqual(
                report["path"], "Sql: srv / SalesDB > Sales Model > Sales Report"
            )


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "lineage.db"
        seed_database(self.db)

    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli_main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_stats_search_and_check(self) -> None:
        code, out, _ = self.run_cli(["--db", str(self.db), "--stats", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["last_scan"])

        code, out, _ = self.run_cli(
            ["--db", str(self.db), "--search", "Sales", "--json", "--limit", "10"]
        )
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual(len(rows), 6)

        code, out, _ = self.run_cli(["--db", str(self.db), "--check", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["unresolved_feed_sources"], 0)

    def test_impact_json_and_csv_export(self) -> None:
        target = Path(self._tmp.name) / "impact.csv"
        code, out, _ = self.run_cli(
            [
                "--db",
                str(self.db),
                "--impact",
                "sql-1",
                "--json",
                "--export-csv",
                str(target),
            ]
        )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["root"]["node_id"], "sql-1")
        self.assertEqual(len(data["nodes"]), 3)
        self.assertTrue(target.exists())
        self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))

        code, out, _ = self.run_cli(
            ["--db", str(self.db), "--upstream", "rep-1", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["direction"], "upstream")

    def test_scan_json_keeps_stdout_parseable(self) -> None:
        result = LineageScanResult(
            database=self.db,
            scan_id="scan-x",
            mode="admin",
            workspace_count=1,
            node_count=2,
            edge_count=1,
            unresolved_sources=0,
            started_at="2026-01-01T00:00:00.0000000Z",
            finished_at="2026-01-01T00:01:00.0000000Z",
            duration_seconds=1.25,
        )

        def fake_scan(database, settings, *, mode, full, log):
            log("progres scan")
            return result

        with patch.dict(
            os.environ,
            {"TENANT_ID": "t", "CLIENT_ID": "c", "CLIENT_SECRET": "s"},
            clear=False,
        ), patch("cli.lineage.run_lineage_scan", side_effect=fake_scan):
            code, out, err = self.run_cli(
                ["--db", str(self.db), "--scan", "--json"]
            )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["scan_id"], "scan-x")
        self.assertEqual(data["workspace_count"], 1)
        self.assertAlmostEqual(data["duration_seconds"], 1.25)
        self.assertIn("progres scan", err)

    def test_missing_credentials_and_missing_node(self) -> None:
        clean = {
            key: value
            for key, value in os.environ.items()
            if key not in {"TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"}
        }
        with patch.dict(os.environ, clean, clear=True):
            code, _, err = self.run_cli(
                [
                    "--db",
                    str(self.db),
                    "--scan",
                    "--env-file",
                    str(Path(self._tmp.name) / "missing.env"),
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("Kredensial", err)

        code, _, err = self.run_cli(["--db", str(self.db), "--impact", "tidak-ada"])
        self.assertEqual(code, 2)
        self.assertIn("tidak ditemukan", err)

        code, _, _ = self.run_cli(["--db", str(self.db)])
        self.assertEqual(code, 2)


@unittest.skipUnless(GUI_AVAILABLE, "PySide6 tidak tersedia")
class GuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from app.lineage_tab import LineageTab
        from app.settings_store import AppSettings

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "lineage.db"
        seed_database(self.db)
        self.settings = AppSettings(
            QSettings(
                str(Path(self._tmp.name) / "settings.ini"),
                QSettings.Format.IniFormat,
            )
        )
        self.settings.set_lineage_db(self.db)
        self.window = FakeWindow()
        self.tab = LineageTab(self.window, settings=self.settings)
        self.addCleanup(self.tab.close)

    def test_search_loads_root_and_directions(self) -> None:
        self.assertTrue(self.tab.search_button.isEnabled())

        self.tab.query.setText("Sales Report")
        self.tab.run_search()
        self.assertEqual(self.tab.results.rowCount(), 1)
        self.assertEqual(self.tab.vm.root["node_id"], "rep-1")
        self.assertEqual(self.tab.tree.topLevelItemCount(), 1)
        self.assertIn("1 item downstream", self.tab.lineage_status.text())

        self.tab.upstream_button.click()
        self.assertEqual(self.tab.vm.direction, "upstream")
        self.assertEqual(len(self.tab.vm.result["nodes"]), 4)
        self.assertIn("4 item upstream", self.tab.lineage_status.text())

        self.tab.downstream_button.click()
        self.assertEqual(self.tab.vm.direction, "downstream")
        self.assertEqual(len(self.tab.vm.result["nodes"]), 1)

        root_item = self.tab.tree.topLevelItem(0)
        child = root_item.child(0)
        self.assertIsNotNone(child)
        node = child.data(0, Qt.ItemDataRole.UserRole)
        self.assertEqual(node["node_id"], "dash-1")
        self.tab._open_tree_node(child, 0)
        self.assertEqual(self.tab.vm.root["node_id"], "dash-1")

    def test_visual_window_refreshes_and_drills_down(self) -> None:
        self.tab.query.setText("Sales Report")
        self.tab.run_search()
        self.assertTrue(self.tab.visual_button.isEnabled())

        self.tab._open_visual()
        window = self.tab._graph_window
        assert window is not None
        self.addCleanup(window.close)
        self.assertTrue(window.isVisible())
        self.assertEqual(len(window._nodes), 6)
        self.assertIn("6 node", window.status.text())
        self.assertIn("4 upstream", window.status.text())
        self.assertIn("Sales Report", window.windowTitle())

        before = window._graph
        self.tab.upstream_button.click()
        self.assertIs(window._graph, before)

        window._nodes["dash-1"].double_clicked.emit("dash-1")
        self.app.processEvents()
        self.assertEqual(self.tab.vm.root["node_id"], "dash-1")
        self.assertIsNotNone(window._graph)
        self.assertEqual(window._graph.root.node_id, "dash-1")

        self.tab.set_busy(True)
        self.assertFalse(self.tab.visual_button.isEnabled())
        window._nodes["rep-1"].double_clicked.emit("rep-1")
        self.app.processEvents()
        self.assertEqual(self.tab.vm.root["node_id"], "dash-1")
        self.tab.set_busy(False)
        self.assertTrue(self.tab.visual_button.isEnabled())

    def test_missing_database_disables_search(self) -> None:
        from app.lineage_tab import LineageTab
        from app.settings_store import AppSettings

        settings = AppSettings(
            QSettings(
                str(Path(self._tmp.name) / "lain.ini"),
                QSettings.Format.IniFormat,
            )
        )
        settings.set_lineage_db(Path(self._tmp.name) / "tidak-ada.db")
        tab = LineageTab(self.window, settings=settings)
        self.addCleanup(tab.close)

        self.assertFalse(tab.search_button.isEnabled())
        self.assertIn("Sinkronisasi data", tab.search_status.text())

    def test_busy_state_and_empty_search(self) -> None:
        self.tab.set_busy(True)
        self.assertFalse(self.tab.search_button.isEnabled())
        self.tab.set_busy(False)
        self.assertTrue(self.tab.search_button.isEnabled())

        self.tab.query.setText("tidak-ada")
        self.tab.run_search()
        self.assertEqual(self.tab.results.rowCount(), 0)
        self.assertIsNone(self.tab.vm.root)
        self.assertEqual(self.tab.search_status.text(), "Tidak ada hasil.")

        self.tab.query.setText("")
        self.tab.run_search()
        self.assertIn("Isi kata kunci", self.tab.search_status.text())


class FakeWindow:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.jobs: list[str] = []

    def log(self, message: str) -> None:
        self.messages.append(message)

    def open_settings_tab(self) -> None:
        self.messages.append("settings")

    def is_busy(self) -> bool:
        return False

    def start_job(self, title: str, job, on_success) -> None:
        self.jobs.append(title)


if __name__ == "__main__":
    unittest.main()

"""Uji presenter/endpoint Lineage (SQLite dipalsukan, tanpa network)."""

from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient  # noqa: E402

from core.errors import ExtractionError  # noqa: E402
from core.lineage_layout import LayoutEdge, LayoutGraph, LayoutNode  # noqa: E402
from server.app import create_app  # noqa: E402
from server.presenters import lineage as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402

ROOT = {
    "node_id": "report-1",
    "node_type": "Report",
    "name": "Report Uji",
    "workspace_name": "Workspace Uji",
    "owner": "owner@example.com",
    "last_modified_at": "2026-11-17T10:00:00",
}


def fake_result(direction: str = "upstream") -> dict:
    return {
        "root": ROOT,
        "nodes": [
            {
                **ROOT,
                "node_id": "model-1",
                "node_type": "SemanticModel",
                "name": "Model Uji",
                "depth": 1,
                "parent": "report-1",
                "edge_type": "uses_dataset",
            }
        ],
        "direction": direction,
        "max_depth": 3,
    }


def fake_graph() -> LayoutGraph:
    root = LayoutNode("report-1", "Report", "Report Uji", "Workspace Uji", 0, 0, 0.0, "root")
    child = LayoutNode(
        "model-1", "SemanticModel", "Model Uji", "Workspace Uji", 1, -1, 0.0, "upstream"
    )
    return LayoutGraph(
        root=root,
        nodes=(root, child),
        edges=(LayoutEdge("model-1", "report-1", "uses_dataset"),),
        truncated=0,
    )


class LineagePresenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_lineage_db(self.root / "lineage.db")

    def test_state_without_database(self) -> None:
        state = presenter.build_state(self.store)
        self.assertFalse(state["exists"])
        self.assertIn("Sinkronisasi", state["status"])
        self.assertEqual(state["node_types"], [])

    def test_search_requires_text(self) -> None:
        with patch.object(
            presenter, "database_summary"
        ) as summary:
            summary.return_value = type(
                "S", (), {"readable": True, "exists": True, "items": 0, "workspaces": 0,
                          "last_scan": "", "modified": "", "error": ""}
            )()
            data = presenter.search(self.store, "", "", "")
        self.assertEqual(data["results"], [])
        self.assertIn("kata kunci", data["message"])

    def test_search_results(self) -> None:
        rows = [{"node_id": "report-1", "name": "Report Uji", "node_type": "Report"}]
        with patch.object(presenter, "database_summary") as summary, patch.object(
            presenter, "search_nodes", return_value=rows
        ):
            summary.return_value = type(
                "S", (), {"readable": True, "exists": True, "items": 1, "workspaces": 1,
                          "last_scan": "", "modified": "", "error": ""}
            )()
            data = presenter.search(self.store, "Report", "", "Report")
        self.assertEqual(data["results"][0]["node_id"], "report-1")
        self.assertIn("1 hasil", data["message"])

    def test_node_payload(self) -> None:
        with patch.object(
            presenter, "two_way_lineage", return_value=(fake_result("downstream"), fake_result())
        ), patch.object(presenter, "build_graph", return_value=fake_graph()), patch.object(
            presenter, "node_detail", return_value=ROOT
        ):
            data = presenter.node_payload(self.store, "report-1", "upstream", 3)
        self.assertEqual(data["node"]["name"], "Report Uji")
        self.assertEqual(data["direction"], "upstream")
        self.assertEqual(data["upstream_count"], 1)
        self.assertEqual(data["downstream_count"], 1)
        self.assertEqual(data["graph"]["root"], "report-1")
        self.assertEqual(data["graph"]["nodes"][1]["type"], "SemanticModel")
        self.assertEqual(data["graph"]["edges"][0]["type"], "uses_dataset")

    def test_node_missing(self) -> None:
        with patch.object(presenter, "two_way_lineage", return_value=(None, None)):
            with self.assertRaises(ExtractionError):
                presenter.node_payload(self.store, "tidak-ada")

    def test_export_writes_csv(self) -> None:
        target = self.root / "Lineage_Report Uji.csv"
        target.write_text("a,b\n", encoding="utf-8-sig")
        with patch.object(
            presenter, "node_payload", return_value={"result": fake_result()}
        ), patch.object(presenter, "outputs_dir", return_value=self.root), patch.object(
            presenter, "export_csv", return_value=target
        ) as write:
            data = presenter.export(self.store, "report-1", "upstream", 3)
        self.assertEqual(data["path"], str(target))
        self.assertEqual(data["items"], 1)
        write.assert_called_once()

    def test_export_image_writes_svg_with_root_name(self) -> None:
        with patch.object(
            presenter, "node_detail", return_value=ROOT
        ), patch.object(presenter, "outputs_dir", return_value=self.root):
            data = presenter.export_lineage_image(
                self.store,
                {
                    "node_id": "report-1",
                    "format": "svg",
                    "data": '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                },
            )
        self.assertEqual(data["format"], "svg")
        self.assertEqual(Path(data["path"]).name, "Lineage_Report Uji.svg")
        self.assertTrue(Path(data["path"]).exists())

    def test_export_image_requires_node(self) -> None:
        with self.assertRaises(ExtractionError):
            presenter.export_lineage_image(
                self.store,
                {"format": "svg", "data": "<svg></svg>"},
            )

    def test_export_image_rejects_missing_node(self) -> None:
        with patch.object(presenter, "node_detail", return_value=None):
            with self.assertRaises(ExtractionError):
                presenter.export_lineage_image(
                    self.store,
                    {
                        "node_id": "tidak-ada",
                        "format": "svg",
                        "data": "<svg></svg>",
                    },
                )

    def test_export_image_rejects_script_payload(self) -> None:
        with patch.object(
            presenter, "node_detail", return_value=ROOT
        ), patch.object(presenter, "outputs_dir", return_value=self.root):
            with self.assertRaises(ExtractionError):
                presenter.export_lineage_image(
                    self.store,
                    {
                        "node_id": "report-1",
                        "format": "svg",
                        "data": "<svg><script>alert(1)</script></svg>",
                    },
                )


class LineageEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        web = self.root / "web"
        web.mkdir()
        (web / "index.html").write_text("ok", encoding="utf-8")
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_lineage_db(self.root / "lineage.db")
        self.app = create_app(settings_store=self.store, web_root=web)
        self.client = TestClient(self.app)

    def test_state(self) -> None:
        response = self.client.get("/api/lineage/state")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["exists"])

    def test_search_endpoint(self) -> None:
        with patch.object(
            presenter, "search", return_value={"results": [], "message": "0 hasil"}
        ):
            response = self.client.get("/api/lineage/search", params={"q": "report"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "0 hasil")

    def test_node_endpoint(self) -> None:
        with patch.object(
            presenter, "node_payload", return_value={"node": ROOT, "graph": {}}
        ):
            response = self.client.get(
                "/api/lineage/node/report-1",
                params={"direction": "upstream", "depth": 3},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["node"]["node_id"], "report-1")

    def test_export_endpoint(self) -> None:
        with patch.object(
            presenter, "export", return_value={"path": "C:/lineage.csv", "size": 2}
        ):
            response = self.client.post(
                "/api/lineage/export",
                json={"node_id": "report-1", "direction": "upstream", "depth": 3},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "C:/lineage.csv")

    def test_image_endpoint(self) -> None:
        with patch.object(
            presenter,
            "export_lineage_image",
            return_value={"path": "C:/side.svg", "size": 10, "format": "svg"},
        ) as handler:
            response = self.client.post(
                "/api/lineage/image",
                json={"node_id": "report-1", "format": "svg", "data": "<svg></svg>"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["format"], "svg")
        handler.assert_called_once()
        self.assertEqual(handler.call_args.args[1]["node_id"], "report-1")

    def test_image_endpoint_returns_400_for_invalid_payload(self) -> None:
        with patch.object(
            presenter,
            "export_lineage_image",
            side_effect=ExtractionError("Format gambar harus svg atau png."),
        ):
            response = self.client.post(
                "/api/lineage/image", json={"node_id": "report-1", "format": "gif"}
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("svg atau png", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

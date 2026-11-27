"""Uji upload SharePoint (Graph) dan pemetaan error tanpa network."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from sync.flow import SyncOptions, _upload_snapshot
from sync.graph import GraphUploader, SharePointTarget

TARGET = SharePointTarget.from_values(
    "astrainternational.sharepoint.com",
    "/teams/BIDataRepository",
    "Documents",
    "BI Tools/Snapshot",
)
PRINCIPAL = ServicePrincipal.from_values("tenant", "client", "secret")


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self.headers: dict[str, str] = {}
        self.text = json.dumps(body) if body is not None else ""
        self.content = self.text.encode("utf-8")

    def json(self) -> dict:
        if self._body is None:
            raise ValueError("body kosong")
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((method, url, dict(kwargs)))
        if not self.responses:
            raise AssertionError(f"request tak terduga: {method} {url}")
        return self.responses.pop(0)

    def close(self) -> None:
        pass


class FakeMsal:
    def acquire_token_for_client(self, scopes: list[str]) -> dict:
        return {"access_token": "graph-token", "expires_in": 3600}


def uploader(session: FakeSession, **kwargs: object) -> GraphUploader:
    return GraphUploader(
        PRINCIPAL,
        TARGET,
        session=session,
        msal_app=FakeMsal(),
        sleep=lambda _seconds: None,
        **kwargs,
    )


def site_response() -> FakeResponse:
    return FakeResponse(
        200,
        {
            "id": "site-1",
            "displayName": "BI Data Repository",
            "webUrl": "https://astrainternational.sharepoint.com/teams/BIDataRepository",
        },
    )


def drive_response() -> FakeResponse:
    return FakeResponse(
        200,
        {
            "value": [
                {"id": "drive-1", "name": "Style Library", "webUrl": "https://x/style"},
                {"id": "drive-2", "name": "Documents", "webUrl": "https://x/docs"},
            ]
        },
    )


class TargetTests(unittest.TestCase):
    def test_normalizes_url_and_folder(self) -> None:
        target = SharePointTarget.from_values(
            "https://astrainternational.sharepoint.com/",
            "https://astrainternational.sharepoint.com/teams/BIDataRepository",
            "Documents",
            "/BI Tools\\Snapshot/",
        )
        self.assertEqual(target.hostname, "astrainternational.sharepoint.com")
        self.assertEqual(target.site_path, "teams/BIDataRepository")
        self.assertEqual(target.folder, "BI Tools/Snapshot")
        self.assertIn("Documents", target.label)

    def test_requires_host_and_site(self) -> None:
        with self.assertRaises(ExtractionError):
            SharePointTarget.from_values("", "/teams/x")
        with self.assertRaises(ExtractionError):
            SharePointTarget.from_values("contoso.sharepoint.com", "")

    def test_upload_requires_target(self) -> None:
        options = SyncOptions(
            database=Path("a.db"), snapshot=Path("b.db"), upload=True
        )
        with self.assertRaises(ExtractionError):
            options.validate()


class CheckTests(unittest.TestCase):
    def test_check_lists_files_and_resolves_library(self) -> None:
        session = FakeSession(
            [
                site_response(),
                drive_response(),
                FakeResponse(
                    200,
                    {
                        "value": [
                            {
                                "name": "bi_tools_snapshot.db",
                                "size": 37494784,
                                "lastModifiedDateTime": "2026-11-25T05:00:00Z",
                            }
                        ]
                    },
                ),
            ]
        )
        data = uploader(session).check()
        self.assertEqual(data["site"], "BI Data Repository")
        self.assertEqual(data["library"], "Documents")
        self.assertEqual(data["path"], "BI%20Tools/Snapshot")
        self.assertEqual(data["files"][0]["name"], "bi_tools_snapshot.db")
        self.assertEqual(session.calls[0][1].split("v1.0")[-1], "/sites/astrainternational.sharepoint.com:/teams/BIDataRepository")
        self.assertIn("/drives/drive-2/root:/BI%20Tools/Snapshot:/children", session.calls[2][1])

    def test_missing_library_is_reported(self) -> None:
        session = FakeSession([site_response(), drive_response()])
        target = SharePointTarget.from_values(
            "astrainternational.sharepoint.com",
            "/teams/BIDataRepository",
            "Laporan",
        )
        client = GraphUploader(
            PRINCIPAL,
            target,
            session=session,
            msal_app=FakeMsal(),
            sleep=lambda _seconds: None,
        )
        with self.assertRaises(ExtractionError) as ctx:
            client.drive()
        self.assertIn("not found", str(ctx.exception))


class UploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_simple_upload_creates_nested_folder(self) -> None:
        source = self.root / "bi_tools_snapshot.db"
        source.write_bytes(b"sqlite-bytes")
        session = FakeSession(
            [
                site_response(),
                drive_response(),
                FakeResponse(201, {"name": "BI Tools"}),
                FakeResponse(201, {"name": "Snapshot"}),
                FakeResponse(
                    201,
                    {
                        "name": "bi_tools_snapshot.db",
                        "size": 12,
                        "webUrl": "https://x/docs/bi_tools_snapshot.db",
                    },
                ),
            ]
        )
        info = uploader(session).upload(source)
        self.assertEqual(info["name"], "bi_tools_snapshot.db")
        self.assertEqual(info["size"], 12)
        self.assertTrue(info["webUrl"].endswith("bi_tools_snapshot.db"))
        self.assertEqual(session.calls[2][1].split("v1.0")[-1], "/drives/drive-2/root/children")
        self.assertEqual(
            session.calls[3][1].split("v1.0")[-1],
            "/drives/drive-2/root:/BI%20Tools:/children",
        )
        self.assertIn("/root:/BI%20Tools/Snapshot/bi_tools_snapshot.db:/content", session.calls[4][1])
        self.assertEqual(session.calls[4][2]["data"], b"sqlite-bytes")
        self.assertEqual(
            session.calls[4][2]["headers"]["Content-Type"], "application/octet-stream"
        )

    def test_upload_session_splits_chunks(self) -> None:
        source = self.root / "bi_tools_snapshot.db"
        source.write_bytes(b"0123456789")
        session = FakeSession(
            [
                site_response(),
                drive_response(),
                FakeResponse(201, {"name": "BI Tools"}),
                FakeResponse(201, {"name": "Snapshot"}),
                FakeResponse(200, {"uploadUrl": "https://upload.example/session-1"}),
                FakeResponse(200, {}),
                FakeResponse(202, {"nextExpectedRanges": ["8-"]}),
                FakeResponse(
                    201,
                    {
                        "name": "bi_tools_snapshot.db",
                        "size": 10,
                        "webUrl": "https://x/docs/bi_tools_snapshot.db",
                    },
                ),
            ]
        )
        info = uploader(session, chunk_size=4, simple_limit=1).upload(source)
        self.assertEqual(info["size"], 10)
        chunk_calls = [call for call in session.calls if call[1] == "https://upload.example/session-1"]
        self.assertEqual(len(chunk_calls), 3)
        self.assertEqual(
            [call[2]["headers"]["Content-Range"] for call in chunk_calls],
            ["bytes 0-3/10", "bytes 4-7/10", "bytes 8-9/10"],
        )
        self.assertEqual(b"".join(call[2]["data"] for call in chunk_calls), b"0123456789")

    def test_forbidden_mentions_graph_permission(self) -> None:
        session = FakeSession([FakeResponse(403, {"error": {"code": "accessDenied"}})])
        with self.assertRaises(ExtractionError) as ctx:
            uploader(session).site()
        message = str(ctx.exception)
        self.assertIn("Sites.Selected", message)
        self.assertIn("granted", message)


class FlowUploadTests(unittest.TestCase):
    def test_upload_snapshot_sends_database_then_checksum(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        snapshot = root / "bi_tools_snapshot.db"
        snapshot.write_bytes(b"db")
        checksum = root / "bi_tools_snapshot.db.sha256"
        checksum.write_text("abc\n", encoding="ascii")
        uploaded: list[str] = []

        class FakeUploader:
            def __init__(self, principal, target, log=None) -> None:
                self.target = target

            def __enter__(self):
                return self

            def __exit__(self, *exc_info: object) -> None:
                return None

            def upload(self, path: Path) -> dict:
                uploaded.append(Path(path).name)
                return {"name": Path(path).name, "size": 2, "webUrl": ""}

        with patch("sync.flow.GraphUploader", FakeUploader):
            result = _upload_snapshot(
                TARGET,
                {"path": str(snapshot)},
                PRINCIPAL,
                lambda _message: None,
            )
        self.assertEqual(
            uploaded, ["bi_tools_snapshot.db", "bi_tools_snapshot.db.sha256"]
        )
        self.assertEqual(result["target"], TARGET.label)
        self.assertEqual(len(result["files"]), 2)


if __name__ == "__main__":
    unittest.main()

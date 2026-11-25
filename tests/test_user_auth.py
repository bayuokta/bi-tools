"""Uji autentikasi akun 365, katalog report, dan snapshot bersama."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.auth import EntraTokens, ServicePrincipal, UserSession, reset_user_session, user_session
from core.errors import ExtractionError
from core.lineage_store import connect, initialize
from core.report_catalog import catalog_reports, save_report_catalog
from core.usage_service import discover_reports
from core.snapshot import (
    prepare_local_snapshot,
    publish_snapshot,
    read_meta,
    SCHEMA_VERSION,
)
from core.tom_client import build_connection_string
from core.xmla_client import interactive_connection_string
from server.settings_store import SettingsStore


class _Access:
    token = "header.payload.signature"
    expires_on = int(time.time()) + 3600


class _Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str) -> _Access:
        self.scopes.append(scope)
        return _Access()


class UserSessionTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_user_session()

    def test_sign_in_and_cache_tokens(self) -> None:
        session = UserSession()
        fake = _Credential()
        session._credential = fake
        session.sign_in()
        self.assertTrue(session.signed_in)
        self.assertTrue(session.is_complete)
        self.assertEqual(session.missing, [])
        self.assertEqual(len(fake.scopes), 2)
        first = session.get("scope-a")
        second = session.get("scope-a")
        self.assertIs(first, second)
        session.sign_out()
        self.assertFalse(session.signed_in)

    def test_not_signed_in_raises(self) -> None:
        session = UserSession()
        with self.assertRaises(ExtractionError):
            session.validate()
        self.assertEqual(session.missing, ["sign-in"])

    def test_configure_tenant_resets_session(self) -> None:
        session = UserSession()
        session._credential = _Credential()
        session.sign_in()
        session.configure("other-tenant")
        self.assertFalse(session.signed_in)
        self.assertEqual(session.tenant_id, "other-tenant")

    def test_entra_tokens_delegates_to_user_session(self) -> None:
        session = UserSession()
        session._credential = _Credential()
        session.sign_in()
        tokens = EntraTokens(session)
        self.assertEqual(tokens.get("scope-x").value, _Access.token)
        self.assertEqual(tokens.provider("scope-x").get_token(), _Access.token)

    def test_service_principal_still_uses_client_credentials(self) -> None:
        principal = ServicePrincipal.from_values("t", "c", "s")
        tokens = EntraTokens(principal)
        self.assertIsNone(tokens._user)


class InteractiveConnectionTests(unittest.TestCase):
    def test_adomd_connection_uses_msolap_login(self) -> None:
        text = interactive_connection_string(
            "Data Source=powerbi://api.powerbi.com/v1.0/myorg/WS"
        )
        self.assertIn("Interactive Login=Always", text)
        self.assertIn("Identity Mode=Connection", text)
        self.assertNotIn("Password=", text)
        self.assertNotIn("AccessToken", text)

    def test_local_connection_is_unchanged(self) -> None:
        value = "Data Source=localhost:1234"
        self.assertEqual(interactive_connection_string(value), value)

    def test_tom_connection_uses_reuse_login(self) -> None:
        text = build_connection_string(
            "powerbi://api.powerbi.com/v1.0/myorg/WS",
            "Model",
            interactive=True,
        )
        self.assertIn("Interactive Login=Always", text)
        self.assertIn("Identity Mode=Connection", text)
        self.assertNotIn("Password=", text)
        self.assertIn("Initial Catalog=Model", text)
        self.assertNotIn("Provider=MSOLAP", text)


class ReportCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.db = self.root / "katalog.db"
        self.conn = connect(self.db)
        initialize(self.conn)
        self.conn.execute(
            "INSERT INTO workspace(workspace_id,name,state,type,is_active) "
            "VALUES('ws','Workspace','Active','Workspace',1)"
        )
        self.conn.execute(
            "INSERT INTO workspace(workspace_id,name,state,type,is_active) "
            "VALUES('personal','PersonalWorkspace x','Active','PersonalGroup',1)"
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_save_and_read_catalog(self) -> None:
        rows = [
            {
                "id": "r1",
                "workspaceId": "ws",
                "datasetId": "ds",
                "name": "Report 1",
                "reportType": "PowerBIReport",
                "format": "PBIR",
                "modifiedDateTime": "2026-11-01",
            },
            {
                "id": "r2",
                "workspaceId": "personal",
                "datasetId": "ds",
                "name": "Personal",
                "reportType": "PowerBIReport",
                "format": "PBIR",
            },
            {
                "id": "r3",
                "workspaceId": "ws",
                "datasetId": "ds",
                "name": "[App] Report 1",
                "reportType": "PowerBIReport",
                "format": "PBIR",
            },
            {
                "id": "r4",
                "workspaceId": "ws",
                "datasetId": "ds",
                "name": "Paginated",
                "reportType": "PaginatedReport",
            },
        ]
        self.assertEqual(save_report_catalog(self.conn, rows), 4)
        found = {row["report_id"]: row for row in catalog_reports(self.db, "ds")}
        self.assertEqual(set(found), {"r1", "r2", "r3", "r4"})
        self.assertEqual(found["r1"]["report_format"], "PBIR")
        self.assertEqual(found["r2"]["is_personal"], 1)
        self.assertEqual(found["r3"]["is_app"], 1)
        self.assertEqual(found["r4"]["is_supported"], 0)

    def test_full_sync_deactivates_missing_reports(self) -> None:
        save_report_catalog(self.conn, [{"id": "old", "workspaceId": "ws", "datasetId": "ds"}])
        save_report_catalog(self.conn, [{"id": "new", "workspaceId": "ws", "datasetId": "ds"}])
        found = {row["report_id"] for row in catalog_reports(self.db, "ds")}
        self.assertEqual(found, {"new"})


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.db = self.root / "work.db"
        conn = connect(self.db)
        initialize(conn)
        conn.execute(
            "INSERT INTO workspace(workspace_id,name,state,type,is_active) "
            "VALUES('ws','Workspace','Active','Workspace',1)"
        )
        conn.commit()
        conn.close()

    def test_publish_and_prepare_snapshot(self) -> None:
        target = self.root / "shared.db"
        result = publish_snapshot(self.db, target)
        self.assertGreater(result["size"], 0)
        self.assertTrue(target.exists())
        self.assertEqual(read_meta(target)["schema_version"], str(SCHEMA_VERSION))
        self.assertTrue(Path(str(target) + ".sha256").exists())
        local = self.root / "local.db"
        prepared = prepare_local_snapshot(target, local)
        self.assertTrue(prepared["updated"])
        self.assertTrue(local.exists())

    def test_checksum_mismatch_is_rejected(self) -> None:
        target = self.root / "shared.db"
        publish_snapshot(self.db, target)
        Path(str(target) + ".sha256").write_text("deadbeef\n", encoding="ascii")
        with self.assertRaises(ExtractionError):
            prepare_local_snapshot(target, self.root / "local.db")

    def test_newer_schema_is_rejected(self) -> None:
        target = self.root / "shared.db"
        publish_snapshot(self.db, target, extra_meta={"schema_version": "999"})
        with self.assertRaises(ExtractionError):
            prepare_local_snapshot(target, self.root / "local.db")


class AuthSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        reset_user_session()

    def tearDown(self) -> None:
        reset_user_session()

    def test_default_mode_is_service(self) -> None:
        store = SettingsStore(self.root / "settings.json", registry_reader=lambda: {})
        self.assertEqual(store.auth_mode(), "service")
        self.assertIsInstance(store.auth(), ServicePrincipal)

    def test_user_mode_returns_session(self) -> None:
        store = SettingsStore(self.root / "settings.json", registry_reader=lambda: {})
        store.set_auth_mode("user")
        store.set("auth/tenant_id", "tenant")
        self.assertIs(store.auth(), user_session())
        self.assertEqual(user_session().tenant_id, "tenant")

    def test_shared_db_settings(self) -> None:
        store = SettingsStore(self.root / "settings.json", registry_reader=lambda: {})
        store.set_shared_db_source(str(self.root / "share" / "snap.db"))
        store.set_shared_db_local(str(self.root / "local.db"))
        store.set_shared_db_auto(False)
        self.assertTrue(store.shared_db_source().endswith("snap.db"))
        self.assertTrue(store.shared_db_local().endswith("local.db"))
        self.assertFalse(store.shared_db_auto())


class CatalogDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.db = self.root / "shared.db"
        conn = connect(self.db)
        initialize(conn)
        conn.execute(
            "INSERT INTO workspace(workspace_id,name,state,type,is_active) "
            "VALUES('ws','Workspace','Active','Workspace',1)"
        )
        conn.commit()
        save_report_catalog(
            conn,
            [
                {
                    "id": "catalog-1",
                    "workspaceId": "ws",
                    "datasetId": "ds",
                    "name": "Catalog report",
                    "reportType": "PowerBIReport",
                    "format": "PBIR",
                    "modifiedDateTime": "2026-11-01",
                }
            ],
        )
        conn.close()

    def test_user_mode_reads_catalog_without_member_access(self) -> None:
        from core.api.transport import ApiError

        class _Client:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def reports_in_group(self, _workspace: str) -> list[dict[str, object]]:
                raise ApiError("denied", status_code=403)

            def close(self) -> None:
                pass

        principal = UserSession()
        principal.signed_in = True
        with patch("core.usage_service.PowerBILineageClient", _Client):
            entries, method, notes = discover_reports(
                principal,
                dataset_id="ds",
                workspace_id="ws",
                database=self.db,
                use_admin=False,
            )
        self.assertEqual([entry.report_id for entry in entries], ["catalog-1"])
        self.assertEqual(method, "catalog")
        self.assertTrue(any("katalog" in note for note in notes))


if __name__ == "__main__":
    unittest.main()

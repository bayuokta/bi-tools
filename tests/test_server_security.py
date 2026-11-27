"""Uji penjaga token/Host/Origin server lokal."""

from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app
from server.security import COOKIE_NAME
from server.settings_store import SettingsStore


def build_client(token: str = "token-uji") -> TestClient:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    web = root / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>uji</h1>", encoding="utf-8")
    store = SettingsStore(root / "settings.json", registry_reader=lambda: {})
    app = create_app(
        settings_store=store,
        token=token,
        allowed_hosts=["testserver"],
        allowed_origins=["http://testserver"],
        web_root=web,
    )
    client = TestClient(app)
    client._tmp = tmp  # type: ignore[attr-defined]
    return client


class LocalGuardTests(unittest.TestCase):
    def test_health_is_open(self) -> None:
        client = build_client()
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_api_requires_token(self) -> None:
        client = build_client()
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        self.assertEqual(client.get("/api/settings").status_code, 401)

    def test_bootstrap_sets_cookie_and_redirects(self) -> None:
        client = build_client("rahasia")
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        response = client.get("/?t=rahasia", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        cookie = response.headers["set-cookie"]
        self.assertIn(COOKIE_NAME, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(client.get("/api/settings").status_code, 200)

    def test_wrong_token_is_rejected(self) -> None:
        client = build_client("rahasia")
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        response = client.get("/?t=salah", follow_redirects=False)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Unknown server session", response.text)

    def test_foreign_host_is_rejected(self) -> None:
        client = build_client()
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        response = client.get("/api/settings", headers={"host": "evil.example"})
        self.assertEqual(response.status_code, 400)

    def test_foreign_origin_is_rejected_for_writes(self) -> None:
        client = build_client()
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        response = client.post(
            "/api/system/shutdown", headers={"origin": "http://evil.example"}
        )
        self.assertEqual(response.status_code, 403)

    def test_same_origin_is_allowed(self) -> None:
        client = build_client()
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        client.get("/?t=token-uji", follow_redirects=False)
        response = client.post(
            "/api/system/shutdown", headers={"origin": "http://testserver"}
        )
        self.assertEqual(response.status_code, 200)

    def test_static_asset_requires_cookie(self) -> None:
        client = build_client()
        self.addCleanup(client._tmp.cleanup)  # type: ignore[attr-defined]
        self.assertEqual(client.get("/index.html").status_code, 401)
        client.get("/?t=token-uji", follow_redirects=False)
        self.assertEqual(client.get("/index.html").status_code, 200)


if __name__ == "__main__":
    unittest.main()

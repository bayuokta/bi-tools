"""Uji token XMLA: satu service principal untuk REST dan ADOMD (tanpa .NET)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.auth import POWERBI_SCOPE
from core.xmla_client import (
    attach_token,
    normalize_powerbi_endpoint,
    open_client,
)

ENDPOINT = "powerbi://api.powerbi.com/v1.0/myorg/My WS"
NORMALIZED = 'Data Source="powerbi://api.powerbi.com/v1.0/myorg/My%20WS?readonly"'


class NormalizeEndpointTests(unittest.TestCase):
    def test_url_workspace_is_encoded_and_readonly_added(self) -> None:
        self.assertEqual(normalize_powerbi_endpoint(ENDPOINT), NORMALIZED)

    def test_existing_readonly_is_kept_once(self) -> None:
        value = "powerbi://api.powerbi.com/v1.0/myorg/My%20WS?readonly"
        result = normalize_powerbi_endpoint(value)
        self.assertEqual(result.count("readonly"), 1)
        self.assertTrue(result.startswith('Data Source="'))
        self.assertIn("My%20WS", result)

    def test_readwrite_is_not_overridden(self) -> None:
        value = "powerbi://api.powerbi.com/v1.0/myorg/My%20WS?readwrite"
        self.assertIn("readwrite", normalize_powerbi_endpoint(value))
        self.assertNotIn("readonly", normalize_powerbi_endpoint(value))

    def test_local_endpoint_and_connection_string_are_untouched(self) -> None:
        self.assertEqual(
            normalize_powerbi_endpoint("localhost:51249"), "localhost:51249"
        )
        full = 'Data Source="powerbi://api.powerbi.com/v1.0/myorg/X";Initial Catalog="Y"'
        self.assertEqual(normalize_powerbi_endpoint(full), full)


class FakeTokens:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def get(self, scope: str = POWERBI_SCOPE, *, force: bool = False):
        self.calls.append((scope, force))
        token = "tok-2" if force else "tok-1"
        expires_on = 2000 if force else 1000
        return SimpleNamespace(value=token, expires_on=expires_on)


class FakeAccessToken:
    def __init__(self, value: str, expires_on: int) -> None:
        self.value = value
        self.expires_on = expires_on


class AttachTokenTests(unittest.TestCase):
    def _attach(self) -> tuple[SimpleNamespace, FakeTokens]:
        tokens = FakeTokens()
        connection = SimpleNamespace()
        attach_token(
            connection,
            tokens,
            access_token_cls=FakeAccessToken,
            wrap_expired=lambda function: function,
            offset_factory=lambda seconds: seconds,
        )
        return connection, tokens

    def test_token_and_expiry_are_set(self) -> None:
        connection, tokens = self._attach()
        self.assertEqual(connection.AccessToken.value, "tok-1")
        self.assertEqual(connection.AccessToken.expires_on, 1000)
        self.assertEqual(tokens.calls, [(POWERBI_SCOPE, False)])

    def test_expiry_callback_refreshes_with_force(self) -> None:
        connection, tokens = self._attach()
        refreshed = connection.OnAccessTokenExpired(connection.AccessToken)
        self.assertEqual(refreshed.value, "tok-2")
        self.assertEqual(refreshed.expires_on, 2000)
        self.assertEqual(
            tokens.calls, [(POWERBI_SCOPE, False), (POWERBI_SCOPE, True)]
        )

    def test_none_tokens_is_a_no_op(self) -> None:
        connection = SimpleNamespace()
        attach_token(connection, None)
        self.assertFalse(hasattr(connection, "AccessToken"))


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def run_open(tokens, *, names=None, **kwargs):
    calls: list[tuple[str, dict]] = []
    catalogs = names or [kwargs.get("catalog") or "Model"]

    def fake_connect(connection_string: str, dll_path=None, **extra):
        calls.append((connection_string, extra))
        return FakeClient()

    with patch("core.xmla_client._connect", side_effect=fake_connect), patch(
        "core.xmla_client.list_catalogs",
        return_value=[{"name": name} for name in catalogs],
    ):
        client = open_client(tokens=tokens, **kwargs)
    return client, calls


class OpenClientTokenTests(unittest.TestCase):
    def test_cloud_endpoint_receives_token_and_catalog(self) -> None:
        tokens = FakeTokens()
        client, calls = run_open(tokens, endpoint=ENDPOINT, catalog="Model")
        self.assertEqual(calls[0][0], NORMALIZED)
        self.assertIs(calls[0][1].get("tokens"), tokens)
        self.assertTrue(calls[1][0].endswith(';Initial Catalog="Model"'))
        self.assertEqual(client.catalog, "Model")

    def test_local_endpoint_is_not_treated_as_cloud(self) -> None:
        from core.xmla_client import _is_cloud

        self.assertFalse(_is_cloud("Data Source=localhost:111"))
        self.assertTrue(_is_cloud(NORMALIZED))
        _, calls = run_open(FakeTokens(), port=111)
        self.assertEqual(calls[0][0], "Data Source=localhost:111")

    def test_existing_catalog_in_connection_string_is_not_duplicated(self) -> None:
        full = (
            'Data Source="powerbi://api.powerbi.com/v1.0/myorg/X";'
            'Initial Catalog="Sudah"'
        )
        client, calls = run_open(
            FakeTokens(), endpoint=full, catalog=None, names=["Sudah"]
        )
        self.assertEqual(calls[0][0], full)
        self.assertEqual(calls[1][0], full)
        self.assertEqual(calls[1][0].lower().count("initial catalog="), 1)
        self.assertEqual(client.catalog, "Sudah")

    def test_connection_catalog_parser(self) -> None:
        from core.xmla_client import connection_catalog

        self.assertEqual(
            connection_catalog('Data Source="x";Initial Catalog="Model A"'),
            "Model A",
        )
        self.assertEqual(connection_catalog("Data Source=localhost:1"), "")


class CatalogQuotingTests(unittest.TestCase):
    def test_catalog_with_quotes_is_escaped(self) -> None:
        name = 'Model "A"'
        _, calls = run_open(FakeTokens(), endpoint=ENDPOINT, catalog=name, names=[name])
        self.assertIn('Initial Catalog="Model ""A"""', calls[1][0])


if __name__ == "__main__":
    unittest.main()

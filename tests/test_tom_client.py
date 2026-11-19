"""Uji klien TOM/TMSL tanpa .NET atau jaringan."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from core.errors import ExtractionError
from core.tom_client import (
    PartitionInfo,
    build_connection_string,
    build_refresh_tmsl,
    connect_server,
    execute_refresh,
    list_partitions,
    normalize_refresh_type,
    parse_partition_range,
    validate_refresh_targets,
)
from core.xmla_client import readwrite_endpoint


class FakeResult:
    def __init__(self, contains_errors: bool = False) -> None:
        self.ContainsErrors = contains_errors

    def __str__(self) -> str:
        return "refresh error"


class FakeServer:
    def __init__(self, contains_errors: bool = False) -> None:
        self.xmla = ""
        self.contains_errors = contains_errors

    def Execute(self, xmla: str) -> FakeResult:  # noqa: N802 - mirrors TOM
        self.xmla = xmla
        return FakeResult(self.contains_errors)


class FakeToken:
    value = "access-token"
    expires_on = 1234567890


class FakeTokens:
    def __init__(self) -> None:
        self.forced = False

    def get(self, _scope: str, *, force: bool = False) -> FakeToken:
        self.forced = force or self.forced
        return FakeToken()


class FakeAccessToken:
    def __init__(self, token: str, expiration: object, context: object) -> None:
        self.token = token
        self.expiration = expiration
        self.context = context


class FakeConnectedServer:
    def __init__(self) -> None:
        self.AccessToken = None
        self.OnAccessTokenExpired = None
        self.connection_string = ""
        self.disposed = False

    def Connect(self, connection_string: str) -> None:  # noqa: N802 - mirrors TOM
        self.connection_string = connection_string

    def Dispose(self) -> None:  # noqa: N802 - mirrors TOM
        self.disposed = True


class TomClientTests(unittest.TestCase):
    def test_refresh_types_are_normalized(self) -> None:
        self.assertEqual(normalize_refresh_type("DataOnly"), "dataOnly")
        self.assertEqual(normalize_refresh_type("clear-values"), "clearValues")
        self.assertEqual(normalize_refresh_type("DEFRAGMENT"), "defragment")
        with self.assertRaises(ExtractionError):
            normalize_refresh_type("sideways")

    def test_readwrite_endpoint_strips_readonly(self) -> None:
        value = "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO?readonly"
        self.assertEqual(
            readwrite_endpoint(value),
            "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO",
        )
        self.assertEqual(
            readwrite_endpoint("powerbi://api.powerbi.com/v1.0/myorg/X"),
            "powerbi://api.powerbi.com/v1.0/myorg/X",
        )

    def test_connection_string_has_no_token(self) -> None:
        connection = build_connection_string(
            "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO?readonly",
            'Model "Uji"',
        )
        self.assertIn("Provider=MSOLAP", connection)
        self.assertIn('Initial Catalog="Model ""Uji"""', connection)
        self.assertNotIn("readonly", connection.lower())
        self.assertNotIn("password", connection.lower())

    def test_connect_server_attaches_access_token_and_disposes(self) -> None:
        tokens = FakeTokens()
        with connect_server(
            "powerbi://api.powerbi.com/v1.0/myorg/Contoh",
            "Model",
            tokens,
            server_cls=FakeConnectedServer,
            access_token_cls=FakeAccessToken,
            offset_factory=lambda value: value,
            wrap_expired=lambda function: function,
        ) as server:
            self.assertIsInstance(server.AccessToken, FakeAccessToken)
            self.assertEqual(server.AccessToken.token, "access-token")
            self.assertEqual(server.AccessToken.expiration, 1234567890)
            self.assertIn("Initial Catalog=\"Model\"", server.connection_string)
            self.assertTrue(callable(server.OnAccessTokenExpired))
        self.assertTrue(server.disposed)

    def test_build_refresh_tmsl_multiple_partitions(self) -> None:
        tmsl = build_refresh_tmsl(
            "Model",
            [("Fact", "P1"), {"table": "Fact", "partition": "P2"}],
            "dataOnly",
        )
        payload = json.loads(tmsl)
        self.assertEqual(payload["refresh"]["type"], "dataOnly")
        self.assertEqual(
            payload["refresh"]["objects"],
            [
                {"database": "Model", "table": "Fact", "partition": "P1"},
                {"database": "Model", "table": "Fact", "partition": "P2"},
            ],
        )

    def test_defragment_uses_table_objects_once(self) -> None:
        tmsl = build_refresh_tmsl(
            "Model", [("Fact", "P1"), ("Fact", "P2"), ("Dim", "P1")], "defragment"
        )
        payload = json.loads(tmsl)
        self.assertEqual(
            payload["refresh"]["objects"],
            [
                {"database": "Model", "table": "Fact"},
                {"database": "Model", "table": "Dim"},
            ],
        )

    def test_add_rejects_calculated_partition(self) -> None:
        calculated = PartitionInfo(
            table="Calc",
            name="P",
            state="Ready",
            mode="Import",
            data_view="Full",
            source_type="CalculatedPartitionSource",
            expression="",
            description="",
            modified_time="",
            refreshed_time="",
            is_calculated=True,
        )
        with self.assertRaises(ExtractionError):
            validate_refresh_targets("add", [calculated])

    def test_execute_refresh_escapes_xml_and_checks_errors(self) -> None:
        server = FakeServer()
        execute_refresh(server, '{"refresh": "A & B < C"}')
        self.assertIn("A &amp; B &lt; C", server.xmla)
        with self.assertRaises(ExtractionError):
            execute_refresh(FakeServer(contains_errors=True), "{}")

    def test_parse_partition_range_from_m_and_name(self) -> None:
        m = parse_partition_range(
            "Fact",
            "Table.SelectRows(x, each [D] >= #datetime(2024,1,1,0,0,0) "
            "and [D] < #datetime(2024,2,1,0,0,0))",
        )
        self.assertEqual((m.start, m.end, m.source), ("2024-01-01", "2024-02-01", "M"))
        name = parse_partition_range("Fact 2025-01-01..2025-02-01", "")
        self.assertEqual((name.start, name.end, name.source), ("2025-01-01", "2025-02-01", "name"))
        month = parse_partition_range("Fact 2025-01", "")
        self.assertEqual(month.label, "from 2025-01")
        self.assertEqual(parse_partition_range("Fact", "").label, "")

    def test_list_partitions_reads_metadata(self) -> None:
        source = SimpleNamespace(
            Expression="Table.SelectRows(x, each [D] >= RangeStart and [D] < RangeEnd)",
            GetType=lambda: SimpleNamespace(Name="MPartitionSource"),
        )
        partition = SimpleNamespace(
            Name="Fact 2025",
            State="Ready",
            Mode="Import",
            DataView="Full",
            Source=source,
            Description="",
            ModifiedTime="2026-01-01 00:00:00",
            RefreshedTime="2026-01-02 03:04:05",
        )
        table = SimpleNamespace(Name="Fact", Partitions=[partition])
        database = SimpleNamespace(Model=SimpleNamespace(Tables=[table]))
        server = SimpleNamespace(Databases=SimpleNamespace(GetByName=lambda _name: database))

        rows = list_partitions(server, "Model")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].table, "Fact")
        self.assertEqual(rows[0].source_type, "MPartitionSource")
        self.assertFalse(rows[0].is_calculated)
        self.assertEqual(rows[0].refreshed_time, "2026-01-02 03:04:05")

    def test_list_partitions_reports_missing_dataset(self) -> None:
        class Databases:
            def GetByName(self, _name: str) -> object:
                raise RuntimeError("missing")

            def __iter__(self):
                return iter([SimpleNamespace(Name="Model Lain")])

        with self.assertRaises(ExtractionError) as ctx:
            list_partitions(SimpleNamespace(Databases=Databases()), "Model")
        self.assertIn("Model Lain", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

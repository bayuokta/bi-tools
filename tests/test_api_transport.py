"""Uji lapisan transport REST bersama (tanpa network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.api import ApiError, Transport


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object = None,
        *,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        if payload is not None:
            self.content = b"{}"
        else:
            self.content = text.encode("utf-8") if text else b""

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("bukan JSON")
        return self._payload


class FakeSession:
    """Session tiruan dengan signature ketat seperti ``requests.Session``."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        timeout: float = 0,
        **kwargs: object,
    ) -> FakeResponse:
        self.calls.append(
            (method, url, {"headers": dict(headers or {}), "timeout": timeout, **kwargs})
        )
        if not self.responses:
            raise AssertionError(f"request tak terduga: {method} {url}")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class DummyTokens:
    def __init__(self, token: str = "secret-token") -> None:
        self.token = token
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return self.token


def make_transport(
    responses: list[FakeResponse],
    sleeps: list[float],
    **kwargs: object,
) -> tuple[Transport, FakeSession, DummyTokens]:
    session = FakeSession(responses)
    tokens = DummyTokens()
    transport = Transport(
        tokens,
        "https://api.example.test/v1",
        session=session,
        sleep=sleeps.append,
        **kwargs,
    )
    return transport, session, tokens


class RequestTests(unittest.TestCase):
    def test_token_is_sent_and_empty_kwargs_are_omitted(self) -> None:
        transport, session, _ = make_transport(
            [FakeResponse(200, {"ok": True})], []
        )
        self.assertEqual(transport.json("GET", "items"), {"ok": True})
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.example.test/v1/items")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertNotIn("params", kwargs)
        self.assertNotIn("json", kwargs)

    def test_429_honours_retry_after(self) -> None:
        sleeps: list[float] = []
        transport, _, _ = make_transport(
            [
                FakeResponse(429, headers={"Retry-After": "7"}, text="slow"),
                FakeResponse(200, {"ok": True}),
            ],
            sleeps,
        )
        self.assertEqual(transport.json("GET", "items"), {"ok": True})
        self.assertEqual(sleeps, [7])

    def test_server_error_uses_backoff(self) -> None:
        sleeps: list[float] = []
        transport, _, _ = make_transport(
            [
                FakeResponse(500, text="boom"),
                FakeResponse(503, text="later"),
                FakeResponse(200, {"ok": True}),
            ],
            sleeps,
        )
        self.assertEqual(transport.json("GET", "items"), {"ok": True})
        self.assertEqual(sleeps, [1, 2])

    def test_server_error_can_be_disabled(self) -> None:
        sleeps: list[float] = []
        transport, session, _ = make_transport(
            [FakeResponse(500, text="boom")], sleeps, retry_status=(429,)
        )
        with self.assertRaises(ApiError) as ctx:
            transport.json("GET", "items")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeps, [])

    def test_long_throttle_wait_fails_fast(self) -> None:
        # Power BI kadang meminta tunggu puluhan menit; jangan menggantung.
        sleeps: list[float] = []
        transport, session, _ = make_transport(
            [FakeResponse(429, headers={"Retry-After": "2400"}, text="throttled")],
            sleeps,
        )
        with self.assertRaises(ApiError) as ctx:
            transport.json("GET", "items")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("menit", str(ctx.exception))
        self.assertEqual(sleeps, [])
        self.assertEqual(len(session.calls), 1)

    def test_long_poll_delay_fails_fast(self) -> None:
        transport, _, _ = make_transport(
            [FakeResponse(202, headers={"Retry-After": "1800"})],
            [],
        )
        with self.assertRaises(ApiError) as ctx:
            transport.poll_status("operations/1")
        self.assertIn("menit", str(ctx.exception))

    def test_2xx_outside_allow_is_reported_with_hint(self) -> None:
        # Regresi: Scanner API menjawab 202; dulu hanya "gagal (HTTP 202)".
        transport, _, _ = make_transport(
            [FakeResponse(202, {"id": "job-1", "status": "NotStarted"}),],
            [],
        )
        with self.assertRaises(ApiError) as ctx:
            transport.json("POST", "admin/workspaces/getInfo")
        self.assertEqual(ctx.exception.status_code, 202)
        self.assertIn("tidak ada di daftar allow", str(ctx.exception))

    def test_202_is_accepted_when_allowed(self) -> None:
        transport, _, _ = make_transport(
            [FakeResponse(202, {"id": "job-1", "status": "NotStarted"})],
            [],
        )
        data = transport.json(
            "POST", "admin/workspaces/getInfo", allow=(200, 202)
        )
        self.assertEqual(data["id"], "job-1")

    def test_4xx_carries_status_code_and_request_id(self) -> None:
        transport, _, _ = make_transport(
            [
                FakeResponse(
                    403,
                    {"error": {"code": "Forbidden", "message": "no access"}},
                    headers={"x-ms-request-id": "req-123"},
                )
            ],
            [],
        )
        with self.assertRaises(ApiError) as ctx:
            transport.json("GET", "items")
        error = ctx.exception
        self.assertEqual(error.status_code, 403)
        self.assertEqual(error.code, "Forbidden")
        self.assertEqual(error.request_id, "req-123")
        self.assertIn("no access", str(error))
        self.assertIn("izin service principal", str(error))

    def test_token_never_appears_in_error_or_log(self) -> None:
        logs: list[str] = []
        transport, _, _ = make_transport(
            [FakeResponse(401, {"message": "unauthorized"})], [], log=logs.append
        )
        with self.assertRaises(ApiError) as ctx:
            transport.json("GET", "items")
        self.assertNotIn("secret-token", str(ctx.exception))
        self.assertFalse(any("secret-token" in line for line in logs))

    def test_absolute_url_is_not_prefixed(self) -> None:
        transport, session, _ = make_transport(
            [FakeResponse(200, {"ok": True})], []
        )
        transport.json("GET", "https://other.example/next")
        self.assertEqual(session.calls[0][1], "https://other.example/next")


class PollTests(unittest.TestCase):
    def test_poll_until_succeeded(self) -> None:
        sleeps: list[float] = []
        transport, _, _ = make_transport(
            [
                FakeResponse(202, headers={"Retry-After": "1"}),
                FakeResponse(200, {"status": "Running"}),
                FakeResponse(200, {"status": "Succeeded", "value": 1}),
            ],
            sleeps,
        )
        data = transport.poll_status(
            "https://api.example.test/v1/operations/1", initial_wait=1
        )
        self.assertEqual(data["value"], 1)
        # 1s dari POST, 1s dari respons 202, lalu 5s sebelum poll terakhir.
        self.assertEqual(sleeps, [1, 1, 5])

    def test_poll_ready_callback_stops_early(self) -> None:
        sleeps: list[float] = []
        transport, _, _ = make_transport(
            [FakeResponse(200, {"definition": {"parts": []}})], sleeps
        )
        data = transport.poll_status(
            "https://api.example.test/v1/operations/2",
            ready=lambda body: "definition" in body,
        )
        self.assertIn("definition", data)
        self.assertEqual(sleeps, [])

    def test_poll_failed_status_raises(self) -> None:
        transport, _, _ = make_transport(
            [FakeResponse(200, {"status": "Failed", "message": "gagal"})], []
        )
        with self.assertRaises(ApiError) as ctx:
            transport.poll_status("operations/3")
        self.assertIn("gagal", str(ctx.exception))

    def test_poll_timeout_is_reported(self) -> None:
        transport, _, _ = make_transport(
            [FakeResponse(200, {"status": "Running"})] * 3, []
        )
        with self.assertRaises(ApiError) as ctx:
            transport.poll_status("operations/4", max_polls=2)
        self.assertIn("Batas waktu", str(ctx.exception))


class PaginationTests(unittest.TestCase):
    def test_next_link_is_followed(self) -> None:
        transport, session, _ = make_transport(
            [
                FakeResponse(
                    200,
                    {
                        "value": [{"id": "a"}],
                        "@odata.nextLink": "https://api.example.test/v1/items?page=2",
                    },
                ),
                FakeResponse(200, {"value": [{"id": "b"}]}),
            ],
            [],
        )
        items = list(transport.pages("items"))
        self.assertEqual([item["id"] for item in items], ["a", "b"])
        self.assertEqual(
            session.calls[1][1], "https://api.example.test/v1/items?page=2"
        )


class LifecycleTests(unittest.TestCase):
    def test_injected_session_is_not_closed(self) -> None:
        transport, session, _ = make_transport([], [])
        transport.close()
        self.assertFalse(session.closed)

    def test_owned_session_is_closed(self) -> None:
        closed: list[bool] = []

        class OwnedSession(FakeSession):
            def close(self) -> None:
                closed.append(True)

        with patch(
            "core.api.transport.requests.Session", return_value=OwnedSession([])
        ):
            transport = Transport(DummyTokens(), "https://api.example.test")
            transport.close()
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()

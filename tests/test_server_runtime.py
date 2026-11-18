"""Uji runtime server: penanda state, port, dan kunci instance."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import runtime


class RuntimeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "server.json"
        patcher = patch.object(runtime, "state_file", return_value=self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_write_read_and_clear(self) -> None:
        runtime.write_state(port=8765, token="abc")
        payload = json.loads(self.state.read_text(encoding="utf-8"))

        self.assertEqual(payload["port"], 8765)
        self.assertEqual(payload["token"], "abc")
        self.assertEqual(runtime.read_state()["port"], 8765)

        runtime.clear_state()
        self.assertFalse(self.state.exists())
        self.assertIsNone(runtime.read_state())

    def test_health_missing_server(self) -> None:
        self.assertIsNone(runtime._health(1, timeout=0.05))

    def test_find_running_requires_health(self) -> None:
        runtime.write_state(port=1, token="abc")
        self.assertIsNone(runtime.find_running())

    def test_read_state_ignores_broken_json(self) -> None:
        self.state.write_text("{rusak", encoding="utf-8")
        self.assertIsNone(runtime.read_state())


class PortTests(unittest.TestCase):
    def test_default_host_is_loopback(self) -> None:
        from server import config

        self.assertEqual(config.DEFAULT_HOST, "127.0.0.1")

    def test_choose_port_skips_busy_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            busy = int(sock.getsockname()[1])
            chosen = runtime.choose_port(busy, 1)
        self.assertNotEqual(chosen, busy)
        self.assertGreater(chosen, 0)

    def test_choose_port_returns_preferred_when_free(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            free = int(sock.getsockname()[1])
        self.assertEqual(runtime.choose_port(free, 2), free)


class InstanceLockTests(unittest.TestCase):
    def test_second_acquire_is_rejected_until_release(self) -> None:
        first = runtime.InstanceLock("Local\\BIToolsTestMutex")
        second = runtime.InstanceLock("Local\\BIToolsTestMutex")
        self.addCleanup(first.release)
        self.addCleanup(second.release)

        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())


if __name__ == "__main__":
    unittest.main()

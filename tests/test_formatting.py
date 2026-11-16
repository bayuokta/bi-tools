"""Uji format teks status bersama (file dan kredensial)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.formatting import (
    ERROR_COLOR,
    OK_COLOR,
    WARN_COLOR,
    credential_status,
    duration_text,
    file_status,
)
from core.auth import ServicePrincipal


class FileStatusTests(unittest.TestCase):
    def test_missing_file_is_labelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = file_status(Path(tmp) / "Report_Metadata.xlsx")
        self.assertIn("Report_Metadata.xlsx", text)
        self.assertIn("belum dibuat", text)

    def test_existing_file_shows_name_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Report_Metadata.xlsx"
            path.write_text("x", encoding="utf-8")
            text = file_status(path)
        self.assertIn("Report_Metadata.xlsx", text)
        self.assertRegex(text, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


class CredentialStatusTests(unittest.TestCase):
    def test_complete_principal_is_green(self) -> None:
        principal = ServicePrincipal.from_values("tenant", "client", "secret")
        text, color = credential_status(principal)
        self.assertIn("lengkap", text)
        self.assertEqual(color, OK_COLOR)

    def test_incomplete_principal_lists_missing_fields(self) -> None:
        text, color = credential_status(ServicePrincipal.from_values("tenant", "", ""))
        self.assertIn("belum lengkap", text)
        self.assertIn("CLIENT_ID", text)
        self.assertIn("Pengaturan", text)
        self.assertEqual(color, WARN_COLOR)

    def test_error_color_is_distinct(self) -> None:
        self.assertNotIn(ERROR_COLOR, {OK_COLOR, WARN_COLOR})


class DurationTests(unittest.TestCase):
    def test_formats_one_decimal(self) -> None:
        self.assertEqual(duration_text(1.234), "1.2 detik")

    def test_invalid_value_is_dash(self) -> None:
        self.assertEqual(duration_text("x"), "-")


if __name__ == "__main__":
    unittest.main()

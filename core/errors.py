"""Exception yang ditampilkan ke pengguna (CLI dan GUI)."""

from __future__ import annotations


class ExtractionError(Exception):
    """Kesalahan yang bisa dijelaskan ke pengguna tanpa traceback."""

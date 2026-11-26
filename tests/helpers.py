"""Helper bersama untuk tes (identitas user tiruan)."""

from __future__ import annotations

from typing import Any

from core.auth import UserSession


def signed_in_user() -> UserSession:
    """Sesi user 365 yang sudah login, tanpa browser/token nyata."""
    session = UserSession()
    session.signed_in = True
    session.account = "tester@example.com"
    return session


def use_user(store: Any) -> UserSession:
    """Ganti ``store.auth`` dengan sesi user tiruan (tanpa service principal)."""
    session = signed_in_user()
    store.auth = lambda: session
    return session

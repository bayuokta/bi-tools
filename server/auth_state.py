"""Status dan aksi login akun 365 untuk antarmuka web."""

from __future__ import annotations

from typing import Any

from core.auth import UserSession, user_session
from . import settings as keys
from .settings_store import SettingsStore


def _user_status(store: SettingsStore, session: UserSession) -> dict[str, Any]:
    if session.signed_in:
        text = f"Login sebagai {session.account or 'akun 365'}."
        tone = "ok"
        if session.fabric_error:
            text += " Token Fabric belum tersedia."
            tone = "warn"
    else:
        text = (
            "Belum login. Klik Sign in untuk membuka browser dan memakai "
            "akun 365."
        )
        tone = "idle"
    return {
        "mode": "user",
        "tenant_id": session.tenant_id,
        "signed_in": session.signed_in,
        "account": session.account,
        "has_secret": False,
        "complete": session.signed_in,
        "missing": session.missing,
        "status": text,
        "tone": tone,
        "fabric_error": session.fabric_error,
    }


def status(store: SettingsStore) -> dict[str, Any]:
    if store.auth_mode() == "user":
        session = user_session()
        session.configure(store.get_str(keys.AUTH_TENANT_KEY, ""))
        return _user_status(store, session)
    principal = store.principal()
    from .presenters.formatting import credential_status

    text, tone = credential_status(principal)
    return {
        "mode": "service",
        "tenant_id": principal.tenant_id,
        "client_id": principal.client_id,
        "has_secret": bool(principal.client_secret),
        "complete": principal.is_complete,
        "missing": principal.missing,
        "status": text,
        "tone": tone,
        "account": "",
        "signed_in": principal.is_complete,
        "fabric_error": "",
    }


def sign_in(store: SettingsStore) -> dict[str, Any]:
    session = user_session()
    session.configure(store.get_str(keys.AUTH_TENANT_KEY, ""))
    session.sign_in()
    return status(store)


def sign_out(store: SettingsStore) -> dict[str, Any]:
    user_session().sign_out()
    return status(store)


def require_user(store: SettingsStore) -> UserSession:
    session = user_session()
    session.validate()
    return session


__all__ = ["status", "sign_in", "sign_out", "require_user"]

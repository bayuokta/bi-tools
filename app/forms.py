"""Pemetaan formulir TSD ke QSettings dalam satu tempat.

Sebelumnya ``TsdTab`` menulis 13 kunci ``tsd/*`` dua kali (muat dan simpan) dan
memetakan kunci ke widget secara manual. Dataclass :class:`TsdForm` memegang
nilai mentah formulir; widget tinggal mengisi/membaca field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.paths import OUTPUTS_DIR
from core.pbi_capture.assets import SCOPES as SHOT_SCOPES
from core.report import MODEL_WORKBOOK_NAME, OUT_FILE

from .settings import (
    SETTINGS_TSD_AUTO_INSTALL_KEY,
    SETTINGS_TSD_DECORATIVE_KEY,
    SETTINGS_TSD_DRAFT_KEY,
    SETTINGS_TSD_EXPAND_KEY,
    SETTINGS_TSD_MANUAL_KEY,
    SETTINGS_TSD_MODEL_KEY,
    SETTINGS_TSD_OUT_DIR_KEY,
    SETTINGS_TSD_REPORT_ID_KEY,
    SETTINGS_TSD_REPORT_KEY,
    SETTINGS_TSD_RLS_ROLES_KEY,
    SETTINGS_TSD_RLS_USER_KEY,
    SETTINGS_TSD_SHOT_SCOPE_KEY,
    SETTINGS_TSD_SHOT_SCALE_KEY,
    SETTINGS_TSD_SHOT_MOBILE_KEY,
    SETTINGS_TSD_SHOTS_KEY,
    SETTINGS_TSD_WORKSPACE_KEY,
)
from .settings_store import AppSettings


def _as_float(value: object, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def section(manual: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Ambil satu bagian sidecar manual sebagai dict baru (aman diedit)."""
    value = manual.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def text_value(value: Any) -> str:
    """Teks untuk field formulir; ``None`` menjadi string kosong."""
    return "" if value is None else str(value)


@dataclass
class TsdForm:
    """Nilai formulir Generate TSD yang disimpan antar sesi."""

    report_workbook: str = str(OUT_FILE)
    model_workbook: str = str(OUTPUTS_DIR / MODEL_WORKBOOK_NAME)
    manual_path: str = ""
    out_dir: str = str(OUTPUTS_DIR)
    draft: bool = True
    expand_all: bool = False
    screenshots: bool = False
    workspace_id: str = ""
    report_id: str = ""
    rls_username: str = ""
    rls_roles: str = ""
    shot_scope: str = "both"
    shot_scale: float = 1.0
    shot_mobile: bool = True
    include_decorative: bool = False
    auto_install_browser: bool = True

    @classmethod
    def load(cls, settings: AppSettings) -> "TsdForm":
        """Baca nilai tersimpan; RLS kosong memakai default tab Pengaturan."""

        def value(key: str, default: str = "") -> str:
            return settings.value(key, default, type=str) or default

        default_user, default_roles = settings.rls()
        scope = value(SETTINGS_TSD_SHOT_SCOPE_KEY, "both")
        if scope not in SHOT_SCOPES:
            scope = "both"
        return cls(
            report_workbook=value(SETTINGS_TSD_REPORT_KEY, str(OUT_FILE)),
            model_workbook=value(
                SETTINGS_TSD_MODEL_KEY, str(OUTPUTS_DIR / MODEL_WORKBOOK_NAME)
            ),
            manual_path=value(SETTINGS_TSD_MANUAL_KEY),
            out_dir=value(SETTINGS_TSD_OUT_DIR_KEY, str(OUTPUTS_DIR)),
            draft=settings.value(SETTINGS_TSD_DRAFT_KEY, True, type=bool),
            expand_all=settings.value(SETTINGS_TSD_EXPAND_KEY, False, type=bool),
            screenshots=settings.value(SETTINGS_TSD_SHOTS_KEY, False, type=bool),
            workspace_id=value(SETTINGS_TSD_WORKSPACE_KEY),
            report_id=value(SETTINGS_TSD_REPORT_ID_KEY),
            rls_username=value(SETTINGS_TSD_RLS_USER_KEY) or default_user,
            rls_roles=value(SETTINGS_TSD_RLS_ROLES_KEY) or ",".join(default_roles),
            shot_scope=scope,
            shot_scale=_as_float(
                settings.value(SETTINGS_TSD_SHOT_SCALE_KEY, 1.0)
            ),
            shot_mobile=settings.value(
                SETTINGS_TSD_SHOT_MOBILE_KEY, True, type=bool
            ),
            include_decorative=settings.value(
                SETTINGS_TSD_DECORATIVE_KEY, False, type=bool
            ),
            auto_install_browser=settings.value(
                SETTINGS_TSD_AUTO_INSTALL_KEY, True, type=bool
            ),
        )

    def save(self, settings: AppSettings) -> None:
        """Simpan nilai formulir; tidak menyentuh kunci lain."""
        settings.set_value(SETTINGS_TSD_REPORT_KEY, self.report_workbook)
        settings.set_value(SETTINGS_TSD_MODEL_KEY, self.model_workbook)
        settings.set_value(SETTINGS_TSD_MANUAL_KEY, self.manual_path)
        settings.set_value(SETTINGS_TSD_OUT_DIR_KEY, self.out_dir)
        settings.set_value(SETTINGS_TSD_DRAFT_KEY, bool(self.draft))
        settings.set_value(SETTINGS_TSD_EXPAND_KEY, bool(self.expand_all))
        settings.set_value(SETTINGS_TSD_SHOTS_KEY, bool(self.screenshots))
        self.save_selection(settings)
        settings.set_value(SETTINGS_TSD_RLS_USER_KEY, self.rls_username)
        settings.set_value(SETTINGS_TSD_RLS_ROLES_KEY, self.rls_roles)
        settings.set_value(SETTINGS_TSD_SHOT_SCOPE_KEY, self.shot_scope or "both")
        settings.set_value(SETTINGS_TSD_SHOT_SCALE_KEY, float(self.shot_scale))
        settings.set_value(SETTINGS_TSD_SHOT_MOBILE_KEY, bool(self.shot_mobile))
        settings.set_value(
            SETTINGS_TSD_DECORATIVE_KEY, bool(self.include_decorative)
        )
        settings.set_value(
            SETTINGS_TSD_AUTO_INSTALL_KEY, bool(self.auto_install_browser)
        )

    def save_selection(self, settings: AppSettings) -> None:
        """Simpan pilihan workspace/report saja (bertahan tanpa Generate)."""
        settings.set_value(SETTINGS_TSD_WORKSPACE_KEY, self.workspace_id)
        settings.set_value(SETTINGS_TSD_REPORT_ID_KEY, self.report_id)

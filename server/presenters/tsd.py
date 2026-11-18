"""Presenter Generate TSD untuk web (port dari ``app/viewmodels/tsd.py``)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from core.auth import DeferredTokenProvider, EntraTokens, powerbi_provider
from core.errors import ExtractionError
from core.paths import outputs_dir
from core.pbi_capture import (
    CaptureOptions,
    cache_dir,
    capture_report,
    load_screenshot_set,
)
from core.pbi_capture.assets import SCOPES
from core.pbi_capture.credentials import split_roles
from core.requests import CaptureRequest, TsdRequest
from core.report import MODEL_WORKBOOK_NAME, OUT_FILE
from core.tsd import (
    TEMPLATE_PATH,
    load_manual,
    output_file_name,
    run_tsd,
    write_manual,
)

from .. import settings as keys
from ..settings_store import SettingsStore
from .formatting import file_status

SCOPE_LABELS = {"both": "Page + visual", "pages": "Page saja", "visuals": "Visual saja"}
SCALE_LABELS = {1.0: "1x (file ringkas)", 2.0: "2x (lebih tajam)", 3.0: "3x (maksimal)"}
BOOL_KEYS = (
    "draft",
    "expand_all",
    "screenshots",
    "shot_mobile",
    "include_decorative",
    "auto_install_browser",
    "debug",
)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _file_or_empty(text: str, empty: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return {
            "path": "",
            "name": "",
            "exists": False,
            "size": 0,
            "modified": "",
            "text": empty,
        }
    return file_status(Path(value).expanduser())


def _default_workbook(default_dir: Path, name: str) -> str:
    candidate = default_dir / name
    if candidate.exists():
        return str(candidate)
    fallback = Path(OUT_FILE).parent / name
    if fallback.exists():
        return str(fallback)
    return str(candidate)


def defaults(store: SettingsStore) -> dict[str, Any]:
    """Nilai awal formulir TSD dari preferensi 0.3.x/0.4.x."""
    out_dir = store.get_str(keys.SETTINGS_TSD_OUT_DIR_KEY) or str(outputs_dir())
    username, roles = store.rls()
    scope = store.get_str(keys.SETTINGS_TSD_SHOT_SCOPE_KEY, "both")
    if scope not in SCOPES:
        scope = "both"
    scale = _float(store.get(keys.SETTINGS_TSD_SHOT_SCALE_KEY, 1.0), 1.0)
    return {
        "report_workbook": store.get_str(keys.SETTINGS_TSD_REPORT_KEY)
        or _default_workbook(outputs_dir(), OUT_FILE.name),
        "model_workbook": store.get_str(keys.SETTINGS_TSD_MODEL_KEY)
        or _default_workbook(outputs_dir(), MODEL_WORKBOOK_NAME),
        "template_path": str(TEMPLATE_PATH),
        "manual_path": store.get_str(keys.SETTINGS_TSD_MANUAL_KEY),
        "out_dir": out_dir,
        "out_name": "",
        "report_name": "",
        "report_id": "",
        "generated_at": "",
        "draft": store.get_bool(keys.SETTINGS_TSD_DRAFT_KEY, True),
        "expand_all": store.get_bool(keys.SETTINGS_TSD_EXPAND_KEY, False),
        "screenshots": store.get_bool(keys.SETTINGS_TSD_SHOTS_KEY, False),
        "workspace_id": "",
        "rls_username": store.get_str(keys.SETTINGS_TSD_RLS_USER_KEY)
        or username,
        "rls_roles": store.get_str(keys.SETTINGS_TSD_RLS_ROLES_KEY)
        or ",".join(roles),
        "shot_scope": scope,
        "shot_scale": scale,
        "shot_mobile": store.get_bool(keys.SETTINGS_TSD_SHOT_MOBILE_KEY, True),
        "include_decorative": store.get_bool(
            keys.SETTINGS_TSD_DECORATIVE_KEY, False
        ),
        "auto_install_browser": store.get_bool(
            keys.SETTINGS_TSD_AUTO_INSTALL_KEY, True
        ),
        "debug": False,
        "manual": {},
    }


def normalize(store: SettingsStore, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Gabungkan preferensi tersimpan dengan input formulir web."""
    data = defaults(store)
    incoming = dict(payload or {})
    for key, value in incoming.items():
        if key in {"manual"}:
            data[key] = value if isinstance(value, Mapping) else {}
            continue
        if key in BOOL_KEYS:
            data[key] = bool(value)
        elif key in {"shot_scale"}:
            data[key] = _float(value, data["shot_scale"])
        elif value is not None:
            data[key] = str(value).strip()
    if data["shot_scope"] not in SCOPES:
        data["shot_scope"] = "both"
    if data["shot_scale"] not in SCALE_LABELS:
        data["shot_scale"] = 1.0 if data["shot_scale"] < 2 else 2.0
    if data["rls_username"] or data["rls_roles"]:
        data["rls_roles"] = ",".join(split_roles(data["rls_roles"]))
    return data


def paths_for(data: Mapping[str, Any]) -> dict[str, Any]:
    """Path output, sidecar, dan cache screenshot dari nilai formulir."""
    out_dir = Path(str(data.get("out_dir") or outputs_dir())).expanduser()
    if not out_dir.is_absolute():
        raise ExtractionError("Folder output TSD harus absolut.")
    report_name = str(data.get("report_name") or "").strip()
    report_id = str(data.get("report_id") or "").strip()
    suggested = output_file_name(report_name or "Report", report_id)
    out_name = str(data.get("out_name") or "").strip() or suggested
    out_file = out_dir / out_name
    manual_path = str(data.get("manual_path") or "").strip()
    manual_file = (
        Path(manual_path).expanduser()
        if manual_path
        else out_file.with_suffix(".json")
    )
    assets = cache_dir(out_file.parent, report_name or "Report", report_id)
    return {
        "out_dir": out_dir,
        "out_name": out_name,
        "suggested_name": suggested,
        "out_name_auto": not str(data.get("out_name") or "").strip(),
        "out_file": out_file,
        "manual_file": manual_file,
        "assets_dir": assets,
    }


def _rls(store: SettingsStore, data: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    username = str(data.get("rls_username") or "").strip()
    roles = str(data.get("rls_roles") or "").strip()
    if not username and not roles:
        default_user, default_roles = store.rls()
        return default_user, tuple(default_roles)
    return username, split_roles(roles)


def _token_provider(store: SettingsStore) -> DeferredTokenProvider:
    return DeferredTokenProvider(
        lambda: powerbi_provider(EntraTokens(store.principal()))
    )


def build_capture_options(
    store: SettingsStore,
    data: Mapping[str, Any],
    *,
    refresh: bool = False,
) -> CaptureOptions:
    workspace = str(data.get("workspace_id") or "").strip()
    report_id = str(data.get("report_id") or "").strip()
    if not workspace or not report_id:
        raise ExtractionError(
            "Pilih workspace dan report Power BI Service untuk screenshot."
        )
    username, roles = _rls(store, data)
    report_text = str(data.get("report_workbook") or "").strip()
    paths = paths_for(data)
    request = CaptureRequest(
        workspace_id=workspace,
        report_id=report_id,
        rls_username=username,
        rls_roles=roles,
        scope=str(data.get("shot_scope") or "both"),
        scale=_float(data.get("shot_scale"), 1.0),
        mobile=bool(data.get("shot_mobile", True)),
        headless=not bool(data.get("debug")),
        output_root=paths["assets_dir"],
        refresh=refresh,
        include_decorative=bool(data.get("include_decorative")),
        hints_workbook=Path(report_text).expanduser() if report_text else None,
        auto_install_browser=bool(data.get("auto_install_browser", True)),
    )
    return request.to_options(_token_provider(store))


def build_request(
    store: SettingsStore,
    data: Mapping[str, Any],
    *,
    refresh: bool = False,
) -> tuple[TsdRequest, CaptureOptions | None, dict[str, Any]]:
    """Susun ``TsdRequest``; validasi ringan sebelum job dimulai."""
    report_text = str(data.get("report_workbook") or "").strip()
    if not report_text:
        raise ExtractionError("Pilih workbook Report_Metadata.xlsx.")
    report_path = Path(report_text).expanduser()
    if not report_path.exists():
        raise ExtractionError(f"Workbook report tidak ditemukan: {report_path}")
    if report_path.suffix.lower() != ".xlsx":
        raise ExtractionError(f"Workbook report harus .xlsx: {report_path}")

    model_path: Path | None = None
    model_text = str(data.get("model_workbook") or "").strip()
    if model_text:
        candidate = Path(model_text).expanduser()
        if candidate.exists():
            model_path = candidate

    template_text = str(data.get("template_path") or "").strip()
    template = Path(template_text).expanduser() if template_text else TEMPLATE_PATH
    if not template.exists():
        raise ExtractionError(f"Template TSD tidak ditemukan: {template}")

    paths = paths_for(data)
    merged = dict(data.get("manual") or {})
    report_name = str(data.get("report_name") or "").strip()
    if report_name:
        report_section = merged.get("report")
        report_section = dict(report_section) if isinstance(report_section, Mapping) else {}
        report_section["name"] = report_name
        merged["report"] = report_section

    capture = None
    if bool(data.get("screenshots")):
        capture = build_capture_options(store, data, refresh=refresh)

    request = TsdRequest(
        report_workbook=report_path,
        model_workbook=model_path,
        out_file=paths["out_file"],
        manual_path=paths["manual_file"],
        manual=merged,
        report_name=report_name,
        report_id=str(data.get("report_id") or "").strip(),
        draft=bool(data.get("draft", True)),
        expand_all=bool(data.get("expand_all")),
        generated_at=str(data.get("generated_at") or "").strip() or None,
        template_path=template,
        include_decorative=bool(data.get("include_decorative")),
    )
    return request, capture, paths


def save_preferences(store: SettingsStore, data: Mapping[str, Any]) -> None:
    """Simpan preferensi TSD (bukan pilihan workspace/report sesi)."""
    store.update(
        {
            keys.SETTINGS_TSD_REPORT_KEY: str(data.get("report_workbook") or ""),
            keys.SETTINGS_TSD_MODEL_KEY: str(data.get("model_workbook") or ""),
            keys.SETTINGS_TSD_MANUAL_KEY: str(data.get("manual_path") or ""),
            keys.SETTINGS_TSD_OUT_DIR_KEY: str(data.get("out_dir") or ""),
            keys.SETTINGS_TSD_DRAFT_KEY: bool(data.get("draft", True)),
            keys.SETTINGS_TSD_EXPAND_KEY: bool(data.get("expand_all")),
            keys.SETTINGS_TSD_SHOTS_KEY: bool(data.get("screenshots")),
            keys.SETTINGS_TSD_RLS_USER_KEY: str(data.get("rls_username") or ""),
            keys.SETTINGS_TSD_RLS_ROLES_KEY: str(data.get("rls_roles") or ""),
            keys.SETTINGS_TSD_SHOT_SCOPE_KEY: str(data.get("shot_scope") or "both"),
            keys.SETTINGS_TSD_SHOT_SCALE_KEY: _float(data.get("shot_scale"), 1.0),
            keys.SETTINGS_TSD_SHOT_MOBILE_KEY: bool(data.get("shot_mobile", True)),
            keys.SETTINGS_TSD_DECORATIVE_KEY: bool(data.get("include_decorative")),
            keys.SETTINGS_TSD_AUTO_INSTALL_KEY: bool(
                data.get("auto_install_browser", True)
            ),
        }
    )


def build_state(
    store: SettingsStore, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Nilai formulir + status berkas untuk halaman TSD."""
    data = normalize(store, payload)
    paths = paths_for(data)
    report = _file_or_empty(str(data.get("report_workbook") or ""), "Belum dipilih")
    model = _file_or_empty(str(data.get("model_workbook") or ""), "Tidak dipakai")
    template_path = Path(str(data.get("template_path") or TEMPLATE_PATH)).expanduser()
    template = file_status(template_path)
    manual = file_status(paths["manual_file"])
    output = file_status(paths["out_file"])
    cached = None
    try:
        cached = load_screenshot_set(paths["assets_dir"])
    except Exception:  # noqa: BLE001 - cache rusak hanya berarti belum siap
        cached = None
    screenshots_ready = (not data["screenshots"]) or (
        bool(data["workspace_id"]) and bool(data["report_id"])
    )
    can_run = (
        bool(report["exists"])
        and bool(str(data.get("out_dir") or "").strip())
        and screenshots_ready
        and bool(template["exists"])
    )
    return {
        "form": {key: value for key, value in data.items() if key != "manual"},
        "paths": {
            "out_dir": str(paths["out_dir"]),
            "out_file": str(paths["out_file"]),
            "out_name": paths["out_name"],
            "suggested_name": paths["suggested_name"],
            "manual_path": str(paths["manual_file"]),
            "assets_dir": str(paths["assets_dir"]),
        },
        "status": {
            "report": report,
            "model": model,
            "template": template,
            "manual": manual,
            "output": output,
            "cache": {
                "path": str(paths["assets_dir"]),
                "exists": cached is not None,
                "summary": cached.summary() if cached is not None else "Belum ada cache",
                "pages": cached.page_count if cached is not None else 0,
                "visuals": cached.visual_count if cached is not None else 0,
                "mobile": cached.mobile_count if cached is not None else 0,
            },
        },
        "can_run": can_run,
        "screenshots_ready": screenshots_ready,
        "checklist": {
            "report": bool(report["exists"]),
            "model": bool(model["exists"]),
            "template": bool(template["exists"]),
            "manual": bool(manual["exists"]),
        },
        "credentials_missing": store.principal().missing,
        "scopes": [
            {"value": key, "label": SCOPE_LABELS[key]} for key in ("both", "pages", "visuals")
        ],
        "scales": [
            {"value": str(value), "label": label} for value, label in SCALE_LABELS.items()
        ],
    }


def run_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    data = normalize(store, payload)
    request, capture, paths = build_request(store, data)
    paths["out_dir"].mkdir(parents=True, exist_ok=True)
    result = run_tsd(**request.to_run_kwargs(), capture=capture, log=log)
    save_preferences(store, data)
    summary = {
        key: (str(value) if isinstance(value, Path) else value)
        for key, value in result.items()
    }
    summary["state"] = build_state(store, {**data, "manual": payload.get("manual") or {}})
    return summary


def capture_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    data = normalize(store, payload)
    options = build_capture_options(store, data, refresh=True)
    result = capture_report(options, log=log)
    save_preferences(store, data)
    return {
        "root": str(result.root),
        "pages": result.page_count,
        "visuals": result.visual_count,
        "mobile": result.mobile_count,
        "missing": len(result.missing),
        "warnings": list(result.warnings),
        "captured_at": result.captured_at,
    }


def clear_cache(
    store: SettingsStore, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    data = normalize(store, payload)
    paths = paths_for(data)
    folder = paths["assets_dir"]
    if not folder.exists():
        return {"removed": False, "path": str(folder), "message": "Cache belum ada."}
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        raise ExtractionError(f"Cache tidak bisa dihapus: {exc}") from exc
    return {
        "removed": True,
        "path": str(folder),
        "state": build_state(store, payload),
    }


def manual_state(
    store: SettingsStore, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    data = normalize(store, payload)
    path = paths_for(data)["manual_file"]
    if not path.exists():
        return {"path": str(path), "exists": False, "data": {}}
    return {"path": str(path), "exists": True, "data": load_manual(path)}


def save_manual_file(
    store: SettingsStore, path_text: str, data: Mapping[str, Any]
) -> dict[str, Any]:
    text = str(path_text or "").strip().strip('"')
    if not text:
        raise ExtractionError("Path sidecar JSON belum ditentukan.")
    path = Path(text).expanduser()
    if path.suffix.lower() != ".json":
        raise ExtractionError("Sidecar manual harus file .json.")
    if not isinstance(data, Mapping):
        raise ExtractionError("Isi sidecar manual harus objek JSON.")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_manual(path, data)
    return {"path": str(path), "exists": True, "data": dict(data)}


def preview_path(
    store: SettingsStore, path_text: str, payload: Mapping[str, Any] | None = None
) -> Path:
    text = str(path_text or "").strip().strip('"')
    if not text:
        raise ExtractionError("File HTML TSD belum ditentukan.")
    path = Path(text).expanduser().resolve()
    if not path.exists() or path.suffix.lower() not in {".html", ".htm"}:
        raise ExtractionError(f"File HTML TSD tidak ditemukan: {path}")
    data = normalize(store, payload)
    allowed = {
        outputs_dir().resolve(),
        Path(OUT_FILE).parent.resolve(),
        paths_for(data)["out_dir"].resolve(),
    }
    if not any(path.is_relative_to(base) for base in allowed):
        raise ExtractionError("Preview hanya untuk file HTML di folder output.")
    return path

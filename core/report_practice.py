"""Evaluasi rule report PBI Inspector per report.

Sumber katalog: ``rules/PBIInspector-rules.json`` (salinan
``PBI-Inspector/Rules/Base-rules.json``). Setiap rule dievaluasi sekali per
report; skor = 10 x rule lulus (maksimum 100 karena rule yang ``disabled``
dilewati). Label: ``Ok`` bila semua lulus, ``Warning`` bila hanya warning yang
gagal, ``Critical`` bila rule dengan log type ``error`` gagal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .fabric_api import PBIR, ReportDefinition
from .paths import RULES_DIR

RULE_FILE = "PBIInspector-rules.json"
SCORE_PER_RULE = 10
HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b")
EXCLUDED_VISUAL_TYPES = {"shape", "slicer", "actionButton", "textbox"}
TOOLTIP_PAGE_TYPES = {"tooltip", "drillthrough", "1", "2"}


@dataclass(frozen=True)
class PracticeRule:
    id: str
    name: str
    log_type: str
    description: str = ""

    @property
    def severity(self) -> str:
        return "error" if self.log_type.casefold() == "error" else "warning"


@dataclass
class PracticeResult:
    rule: PracticeRule
    failed: int = 0
    objects: list[str] = field(default_factory=list)
    evaluated: bool = True
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.failed == 0

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.rule.id,
            "name": self.rule.name,
            "log_type": self.rule.log_type,
            "passed": bool(self.passed),
            "failed": int(self.failed),
            "objects": list(self.objects[:20]),
            "evaluated": bool(self.evaluated),
            "reason": self.reason,
        }


def load_practice_rules(path: Path | str | None = None) -> list[PracticeRule]:
    """Baca rule aktif dari ``rules/PBIInspector-rules.json``."""
    target = Path(path) if path is not None else RULES_DIR / RULE_FILE
    raw = json.loads(target.read_text(encoding="utf-8-sig"))
    entries = raw.get("pbiEntries") if isinstance(raw, Mapping) else None
    if not entries:
        return []
    rules: list[PracticeRule] = []
    for item in entries[0].get("rules") or []:
        if not isinstance(item, Mapping) or item.get("disabled"):
            continue
        rule_id = str(item.get("id") or "").strip()
        if not rule_id:
            continue
        rules.append(
            PracticeRule(
                id=rule_id,
                name=str(item.get("name") or rule_id),
                log_type=str(item.get("logType") or "warning"),
                description=str(item.get("description") or ""),
            )
        )
    return rules


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, (dict, list)) else {}


def _parts(definition: ReportDefinition) -> dict[str, Any]:
    parts: dict[str, Any] = {}
    for part in definition.parts:
        try:
            parts[part.path] = json.loads(part.payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return parts


def _pbir_visuals(
    parts: Mapping[str, Any], page_ids: Iterable[str]
) -> list[dict[str, Any]]:
    visuals: list[dict[str, Any]] = []
    for page_id in page_ids:
        prefix = f"definition/pages/{page_id}/visuals/"
        for path in sorted(parts):
            if not path.startswith(prefix) or not path.endswith("/visual.json"):
                continue
            data = parts[path]
            if not isinstance(data, Mapping):
                continue
            visual_id = path[len(prefix) :].split("/")[0]
            group = data.get("visualGroup") if isinstance(data.get("visualGroup"), Mapping) else None
            visual = data.get("visual") if isinstance(data.get("visual"), Mapping) else None
            if group is None and visual is None:
                continue
            visual_type = (
                "visualGroup"
                if group is not None
                else str((visual or {}).get("visualType") or "")
            )
            title = visual_type
            if group is not None:
                title = str(group.get("displayName") or "visualGroup")
            query = (visual or {}).get("query") or {}
            fields: list[str] = []
            for role in (query.get("queryState") or {}).values():
                for projection in (role or {}).get("projections") or []:
                    if not isinstance(projection, Mapping):
                        continue
                    identifier = str(
                        projection.get("queryRef")
                        or json.dumps(projection.get("field") or {}, sort_keys=True)
                    )
                    if identifier not in fields:
                        fields.append(identifier)
            visuals.append(
                {
                    "id": visual_id,
                    "page": page_id,
                    "type": visual_type,
                    "title": title,
                    "is_group": group is not None,
                    "hidden": bool(data.get("isHidden")),
                    "parent": str(data.get("parentGroupName") or ""),
                    "fields": fields,
                    "filters": list(
                        ((data.get("filterConfig") or {}).get("filters") or [])
                    ),
                    "formatting": json.dumps(
                        {
                            "objects": (visual or {}).get("objects") or {},
                            "vcObjects": (visual or {}).get("visualContainerObjects") or {},
                        },
                        sort_keys=True,
                    ),
                    "show_all_roles": bool((visual or {}).get("showAllRoles")),
                }
            )
    return visuals


def _legacy_visuals(sections: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    visuals: list[dict[str, Any]] = []
    for section in sections:
        page_id = str(section.get("name") or "")
        for container in section.get("visualContainers") or []:
            config = _json(container.get("config"))
            if not isinstance(config, Mapping):
                continue
            visual = config.get("singleVisual") if isinstance(config.get("singleVisual"), Mapping) else None
            group = (
                config.get("singleVisualGroup")
                if isinstance(config.get("singleVisualGroup"), Mapping)
                else None
            )
            if visual is None and group is None:
                continue
            visual_id = str(config.get("name") or container.get("name") or "")
            query = (visual or {}).get("prototypeQuery") or {}
            fields = [
                str(item.get("Name") or json.dumps(item, sort_keys=True))
                for item in query.get("Select") or []
                if isinstance(item, Mapping)
            ]
            visuals.append(
                {
                    "id": visual_id,
                    "page": page_id,
                    "type": "visualGroup" if group is not None else str((visual or {}).get("visualType") or ""),
                    "title": str(
                        (group or {}).get("displayName")
                        or container.get("displayName")
                        or ""
                    ),
                    "is_group": group is not None,
                    "hidden": str(((visual or {}).get("display") or {}).get("mode") or "") == "hidden"
                    or bool(container.get("isHidden")),
                    "parent": str(config.get("parentGroupName") or ""),
                    "fields": fields,
                    "filters": list(container.get("filters") or []),
                    "formatting": json.dumps(
                        {
                            "objects": (visual or {}).get("objects") or {},
                            "vcObjects": (visual or {}).get("vcObjects") or {},
                        },
                        sort_keys=True,
                    ),
                    "show_all_roles": bool((visual or {}).get("showAllRoles")),
                }
            )
    return visuals


def _visible(visual: Mapping[str, Any]) -> bool:
    return not visual.get("hidden") and not visual.get("is_group")


def _page_hidden(page: Mapping[str, Any]) -> bool:
    visibility = str(page.get("visibility") or "")
    return bool(page.get("hidden")) or visibility.casefold() in {
        "hiddeninviewmode",
        "hidden",
        "1",
    }


def _normalize(
    definition: ReportDefinition,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    parts = _parts(definition)
    report = parts.get("definition/report.json") or parts.get("report.json") or {}
    custom = [
        str(item)
        for item in (
            report.get("publicCustomVisuals")
            or report.get("customVisuals")
            or []
        )
    ]
    if definition.report_format == PBIR:
        pages_meta = parts.get("definition/pages/pages.json") or {}
        page_ids = [
            str(item)
            for item in pages_meta.get("pageOrder") or []
            if str(item)
        ]
        pages: list[dict[str, Any]] = []
        for page_id in page_ids:
            page = parts.get(f"definition/pages/{page_id}/page.json") or {}
            pages.append(
                {
                    "id": page_id,
                    "name": str(page.get("displayName") or page_id),
                    "height": float(page.get("height") or 0),
                    "hidden": _page_hidden(page),
                    "type": str(page.get("type") or page.get("pageType") or ""),
                    "filters": list(
                        ((page.get("filterConfig") or {}).get("filters") or [])
                    ),
                }
            )
        return pages, _pbir_visuals(parts, page_ids), custom

    sections = [
        section
        for section in report.get("sections") or []
        if isinstance(section, Mapping)
    ]
    pages = []
    for section in sections:
        config = _json(section.get("config"))
        pages.append(
            {
                "id": str(section.get("name") or ""),
                "name": str(section.get("displayName") or section.get("name") or ""),
                "height": float(section.get("height") or config.get("height") or 0),
                "hidden": _page_hidden(
                    {
                        "hidden": bool(section.get("isHidden")),
                        "visibility": config.get("visibility")
                        if config.get("visibility") is not None
                        else section.get("visibility"),
                    }
                ),
                "type": str(config.get("type") or section.get("type") or ""),
                "filters": list(section.get("filters") or []),
            }
        )
    return pages, _legacy_visuals(sections), custom


def _filters_with_type(filters: Iterable[Any], kind: str) -> int:
    count = 0
    for item in filters:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "").casefold() == kind.casefold():
            count += 1
    return count


def _page_visuals(
    visuals: Iterable[Mapping[str, Any]], page_id: str
) -> list[Mapping[str, Any]]:
    return [item for item in visuals if str(item.get("page") or "") == page_id]


def _evaluate(
    rule: PracticeRule,
    pages: list[dict[str, Any]],
    visuals: list[dict[str, Any]],
    custom: list[str],
) -> PracticeResult:
    rule_id = rule.id
    if rule_id == "REMOVE_UNUSED_CUSTOM_VISUALS":
        used = {str(item.get("type") or "") for item in visuals if not item.get("is_group")}
        unused = [name for name in custom if name not in used]
        return PracticeResult(rule, failed=len(unused), objects=unused)

    if rule_id == "REDUCE_VISUALS_ON_PAGE":
        failing = []
        for page in pages:
            count = sum(
                1
                for item in _page_visuals(visuals, page["id"])
                if _visible(item)
                and str(item.get("type") or "") not in EXCLUDED_VISUAL_TYPES
            )
            if count > 20:
                failing.append(f"{page['name']} ({count})")
        return PracticeResult(rule, failed=len(failing), objects=failing)

    if rule_id == "REDUCE_OBJECTS_WITHIN_VISUALS":
        failing = [
            str(item.get("title") or item.get("id") or "")
            for item in visuals
            if not item.get("is_group") and len(item.get("fields") or []) > 6
        ]
        return PracticeResult(rule, failed=len(failing), objects=failing)

    if rule_id in {"REDUCE_TOPN_FILTERS", "REDUCE_ADVANCED_FILTERS"}:
        kind = "TopN" if rule_id == "REDUCE_TOPN_FILTERS" else "Advanced"
        failing = []
        for page in pages:
            count = sum(
                _filters_with_type(item.get("filters") or [], kind)
                for item in _page_visuals(visuals, page["id"])
            )
            if count > 4:
                failing.append(f"{page['name']} ({count})")
        return PracticeResult(rule, failed=len(failing), objects=failing)

    if rule_id == "REDUCE_PAGES":
        return PracticeResult(
            rule, failed=1 if len(pages) > 10 else 0, objects=[f"{len(pages)} pages"]
        )

    if rule_id == "AVOID_SHOW_ITEMS_WITH_NO_DATA":
        failing = [
            str(item.get("title") or item.get("id") or "")
            for item in visuals
            if item.get("show_all_roles")
        ]
        return PracticeResult(rule, failed=len(failing), objects=failing)

    if rule_id == "HIDE_TOOLTIP_DRILLTROUGH_PAGES":
        failing = [
            page["name"]
            for page in pages
            if str(page.get("type") or "").casefold() in TOOLTIP_PAGE_TYPES
            and not page.get("hidden")
        ]
        return PracticeResult(rule, failed=len(failing), objects=failing)

    if rule_id == "ENSURE_THEME_COLOURS":
        failing = [
            str(item.get("title") or item.get("id") or "")
            for item in visuals
            if not item.get("is_group")
            and str(item.get("type") or "") != "textbox"
            and HEX_COLOUR.search(str(item.get("formatting") or ""))
        ]
        return PracticeResult(rule, failed=len(failing), objects=failing)

    if rule_id == "ENSURE_PAGES_DO_NOT_SCROLL_VERTICALLY":
        failing = [
            f"{page['name']} ({int(page.get('height') or 0)})"
            for page in pages
            if float(page.get("height") or 0) > 720 and not page.get("hidden")
        ]
        return PracticeResult(rule, failed=len(failing), objects=failing)

    return PracticeResult(
        rule,
        failed=0,
        evaluated=False,
        reason="No evaluator for this PBI Inspector rule.",
    )


def build_report_practice(
    definition: ReportDefinition,
    *,
    rules: Iterable[PracticeRule] | None = None,
) -> dict[str, Any]:
    """Evaluasi rule PBI Inspector untuk satu report (skor per report)."""
    try:
        catalog = list(rules) if rules is not None else load_practice_rules()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "error": f"PBI Inspector rules could not be read: {exc}",
            "score": 0,
            "label": "",
            "passed": 0,
            "total": 0,
            "failed": 0,
            "rules": [],
        }
    try:
        pages, visuals, custom = _normalize(definition)
    except Exception as exc:  # noqa: BLE001 - report definition rusak
        return {
            "available": False,
            "error": f"Report practice could not be evaluated: {exc}",
            "score": 0,
            "label": "",
            "passed": 0,
            "total": 0,
            "failed": 0,
            "rules": [],
        }
    results = [_evaluate(rule, pages, visuals, custom) for rule in catalog]
    evaluated = [item for item in results if item.evaluated]
    passed = sum(1 for item in evaluated if item.passed)
    failed = [item for item in evaluated if not item.passed]
    score = SCORE_PER_RULE * passed
    if any(item.rule.severity == "error" for item in failed):
        label = "Critical"
    elif failed:
        label = "Warning"
    elif evaluated:
        label = "Ok"
    else:
        label = ""
    return {
        "available": True,
        "score": int(score),
        "label": label,
        "passed": int(passed),
        "total": len(evaluated),
        "failed": len(failed),
        "rules": [item.payload() for item in results],
    }


def report_practice_text(practice: Mapping[str, Any] | None) -> str:
    """Teks kolom ``Report_best_practices_score`` (mis. ``100 (Ok)``)."""
    if not practice or not practice.get("available"):
        return "-"
    score = practice.get("score")
    label = str(practice.get("label") or "")
    if score is None or not label:
        return "-"
    return f"{int(score)} ({label})"

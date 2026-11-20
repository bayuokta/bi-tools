"""Best Practice Analyzer untuk semantic model.

Katalog aturan berasal dari ``rules/BPARules.json`` (Microsoft/Tabular Editor).
Tidak semua aturan dapat dievaluasi tanpa Tabular Editor; aturan yang datanya
belum dikumpulkan tetap dilaporkan sebagai ``not_evaluated`` beserta alasannya.

Modul ini hanya membaca ``AnalysisResult``; tidak ada request XMLA/REST dan
tidak menulis berkas. Skor model memakai penskalaan logaritmik:

    skor aturan = round(severity × jumlah_objek × log10(N))

dengan ``N`` = jumlah objek model yang dianalisa. Skor total adalah jumlah
skor aturan, lalu dipetakan ke verdict.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .metadata_common import strip_dax_literals
from .model_health import UNUSED_STATUS
from .paths import RULES_DIR

RULE_FILE = "BPARules.json"

SEVERITY_LABELS = {1: "Low", 2: "Medium", 3: "High"}

REPORT_USAGE_RULES = {
    "UNNECESSARY_COLUMNS",
    "UNNECESSARY_MEASURES",
}

UNSUPPORTED_REASONS = {
    "DATA_COLUMNS_MUST_HAVE_A_SOURCE_COLUMN": (
        "SourceColumn sering kosong pada model Power BI/PBIP; tidak cukup andal."
    ),
    "SPLIT_DATE_AND_TIME": (
        "Butuh annotation DateTimeWithHourMinSec dari VertiPaq Analyzer."
    ),
    "ISAVAILABLEINMDX_FALSE_NONATTRIBUTE_COLUMNS": (
        "Pemakaian hierarki/variasi kolom belum dikumpulkan analisa ini."
    ),
    "SET_ISAVAILABLEINMDX_TO_TRUE_ON_NECESSARY_COLUMNS": (
        "Pemakaian hierarki/variasi kolom belum dikumpulkan analisa ini."
    ),
    "REDUCE_USAGE_OF_LONG-LENGTH_COLUMNS_WITH_HIGH_CARDINALITY": (
        "Butuh annotation LongLengthRowCount dari VertiPaq Analyzer."
    ),
    "LIMIT_ROW_LEVEL_SECURITY_(RLS)_LOGIC": (
        "Ekspresi RLS/role tidak dikumpulkan analisa ini."
    ),
    "AVOID_USING_MANY-TO-MANY_RELATIONSHIPS_ON_TABLES_USED_FOR_DYNAMIC_ROW_LEVEL_SECURITY": (
        "Ekspresi RLS/role tidak dikumpulkan analisa ini."
    ),
    "CHECK_IF_DYNAMIC_ROW_LEVEL_SECURITY_(RLS)_IS_NECESSARY": (
        "Ekspresi RLS/role tidak dikumpulkan analisa ini."
    ),
    "AVOID_THE_USERELATIONSHIP_FUNCTION_AND_RLS_AGAINST_THE_SAME_TABLE": (
        "Ekspresi RLS/role tidak dikumpulkan analisa ini."
    ),
    "MODEL_USING_DIRECT_QUERY_AND_NO_AGGREGATIONS": (
        "Metadata aggregation belum dikumpulkan analisa ini."
    ),
    "AVOID_STRUCTURED_DATA_SOURCES_WITH_PROVIDER_PARTITIONS": (
        "Metadata data source/provider partition belum dikumpulkan."
    ),
    "FIX_REFERENTIAL_INTEGRITY_VIOLATIONS": (
        "Butuh pemindaian data, bukan metadata model."
    ),
    "REMOVE_DATA_SOURCES_NOT_REFERENCED_BY_ANY_PARTITIONS": (
        "Metadata data source belum dikumpulkan analisa ini."
    ),
    "REMOVE_ROLES_WITH_NO_MEMBERS": (
        "Metadata role dan member belum dikumpulkan analisa ini."
    ),
    "PERSPECTIVES_WITH_NO_OBJECTS": (
        "Metadata perspective belum dikumpulkan analisa ini."
    ),
    "CALCULATION_GROUPS_WITH_NO_CALCULATION_ITEMS": (
        "Metadata calculation group/item belum dikumpulkan analisa ini."
    ),
    "PARTITION_NAME_SHOULD_MATCH_TABLE_NAME_FOR_SINGLE_PARTITION_TABLES": (
        "Nama partisi belum ada di hasil analisa."
    ),
}

TIME_INTELLIGENCE_RE = re.compile(
    r"(?i)\b("
    r"CLOSINGBALANCEMONTH|CLOSINGBALANCEQUARTER|CLOSINGBALANCEYEAR|"
    r"OPENINGBALANCEMONTH|OPENINGBALANCEQUARTER|OPENINGBALANCEYEAR|"
    r"DATEADD|DATESBETWEEN|DATESINPERIOD|DATESMTD|DATESQTD|DATESYTD|"
    r"ENDOFMONTH|ENDOFQUARTER|ENDOFYEAR|FIRSTDATE|FIRSTNONBLANK|"
    r"LASTDATE|LASTNONBLANK|NEXTDAY|NEXTMONTH|NEXTQUARTER|NEXTYEAR|"
    r"PARALLELPERIOD|PREVIOUSDAY|PREVIOUSMONTH|PREVIOUSQUARTER|PREVIOUSYEAR|"
    r"SAMEPERIODLASTYEAR|STARTOFMONTH|STARTOFQUARTER|STARTOFYEAR|"
    r"TOTALMTD|TOTALQTD|TOTALYTD"
    r")\s*\("
)

MONTH_TOKENS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
NUMERIC_TYPES = {"int64", "decimal", "double"}


@dataclass(frozen=True)
class BpaRule:
    """Satu aturan dari katalog BPARules.json."""

    id: str
    name: str
    category: str
    severity: int
    scope: str
    description: str
    expression: str
    fix_expression: str
    compatibility_level: Any = None

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABELS.get(self.severity, str(self.severity))


@dataclass
class Finding:
    """Satu objek yang melanggar aturan."""

    rule_id: str
    object: str
    table: str = ""
    name: str = ""
    kind: str = ""
    detail: str = ""
    size_bytes: int = 0
    target: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "object": self.object,
            "table": self.table,
            "name": self.name,
            "kind": self.kind,
            "detail": self.detail,
            "size_bytes": int(self.size_bytes or 0),
            "target": dict(self.target or {}),
        }


Evaluator = Callable[[Any, BpaRule], list[Finding]]


def load_rules(path: Path | str | None = None) -> list[BpaRule]:
    """Baca katalog aturan dari ``rules/BPARules.json``."""
    target = Path(path) if path is not None else RULES_DIR / RULE_FILE
    raw = json.loads(target.read_text(encoding="utf-8-sig"))
    rules: list[BpaRule] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        rule_id = str(item.get("ID") or "").strip()
        if not rule_id:
            continue
        try:
            severity = int(item.get("Severity") or 1)
        except (TypeError, ValueError):
            severity = 1
        rules.append(
            BpaRule(
                id=rule_id,
                name=str(item.get("Name") or rule_id),
                category=str(item.get("Category") or ""),
                severity=min(3, max(1, severity)),
                scope=str(item.get("Scope") or ""),
                description=str(item.get("Description") or ""),
                expression=str(item.get("Expression") or ""),
                fix_expression=str(item.get("FixExpression") or ""),
                compatibility_level=item.get("CompatibilityLevel"),
            )
        )
    return rules


def build_best_practice(
    result: Any, rules: Iterable[BpaRule] | None = None
) -> dict[str, Any]:
    """Evaluasi aturan model dan kembalikan payload siap serialisasi."""
    try:
        catalog = list(rules) if rules is not None else load_rules()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "error": f"Katalog best practice tidak bisa dibaca: {exc}",
            "rule_count": 0,
            "evaluated": 0,
            "not_evaluated": 0,
            "score": 0,
            "verdict": "",
            "verdict_key": "",
            "model_objects": 0,
            "log_scale": 0.0,
            "items": [],
            "rules": [],
        }

    model_objects = max(10, _model_objects(result))
    scale = math.log10(model_objects)
    usage_ok = bool(
        getattr(result, "reports_included", True)
        and getattr(result, "coverage_complete", False)
    )

    rule_rows: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for rule in catalog:
        evaluator = _EVALUATORS.get(rule.id)
        if evaluator is None:
            rule_rows.append(_rule_row(rule, "not_evaluated", 0, 0, UNSUPPORTED_REASONS.get(
                rule.id, "Aturan belum punya evaluator di tool ini."
            )))
            continue
        if rule.id in REPORT_USAGE_RULES and not usage_ok:
            rule_rows.append(_rule_row(
                rule,
                "needs_coverage",
                0,
                0,
                "Butuh cakupan report yang lengkap; jalankan analisa dengan report.",
            ))
            continue
        try:
            found = _unique_findings(evaluator(result, rule) or [])
        except Exception as exc:  # noqa: BLE001 - aturan tidak boleh mematikan analisa
            rule_rows.append(_rule_row(
                rule,
                "not_evaluated",
                0,
                0,
                f"Evaluator gagal: {str(exc).splitlines()[0]}",
            ))
            continue
        score = round(rule.severity * len(found) * scale)
        rule_rows.append(_rule_row(
            rule,
            "violation" if found else "pass",
            len(found),
            score,
            "",
        ))
        findings.extend(found)

    rule_rows.sort(key=_rule_sort_key)
    total = sum(int(row["score"]) for row in rule_rows)
    verdict, verdict_key = model_verdict(total)
    by_id = {rule.id: rule for rule in catalog}
    rows_by_id = {row["id"]: row for row in rule_rows}
    item_payloads: list[dict[str, Any]] = []
    for finding in findings:
        item = finding.payload()
        item["rule_score"] = int(rows_by_id[finding.rule_id]["score"])
        item["category"] = str(by_id[finding.rule_id].category)
        item["severity"] = int(by_id[finding.rule_id].severity)
        item["rule_name"] = str(by_id[finding.rule_id].name)
        item_payloads.append(item)

    evaluated = sum(1 for row in rule_rows if row["status"] in {"violation", "pass"})
    return {
        "available": True,
        "rule_count": len(rule_rows),
        "evaluated": evaluated,
        "not_evaluated": sum(
            1 for row in rule_rows if row["status"] not in {"violation", "pass"}
        ),
        "score": total,
        "verdict": verdict,
        "verdict_key": verdict_key,
        "model_objects": model_objects,
        "log_scale": round(scale, 4),
        "counts": {
            "violations": len(item_payloads),
            "rules": sum(1 for row in rule_rows if row["status"] == "violation"),
            "passed": sum(1 for row in rule_rows if row["status"] == "pass"),
        },
        "items": item_payloads,
        "rules": rule_rows,
    }


def model_verdict(score: int) -> tuple[str, str]:
    """Verdict model berdasarkan skor total."""
    if score < 50:
        return "Power BI Pro", "pro"
    if score <= 200:
        return "Good", "good"
    if score <= 400:
        return "Ok", "ok"
    if score <= 600:
        return "Poor", "poor"
    if score < 800:
        return "Awful", "awful"
    return "Power BI Criminal", "criminal"


# ---------------------------------------------------------------------------
# Helper model
# ---------------------------------------------------------------------------
def _model_objects(result: Any) -> int:
    return (
        len(getattr(result, "columns", []) or [])
        + len(getattr(result, "measures", []) or [])
        + len(getattr(getattr(result, "stats", None), "tables", []) or [])
        + len(getattr(result, "relationships", []) or [])
        + len(getattr(result, "m_queries", []) or [])
    )


def _columns(result: Any) -> list[Any]:
    return [
        analysis.column
        for analysis in (getattr(result, "columns", []) or [])
        if getattr(analysis, "column", None) is not None
    ]


def _measures(result: Any) -> list[Any]:
    return [
        analysis.measure
        for analysis in (getattr(result, "measures", []) or [])
        if getattr(analysis, "measure", None) is not None
    ]


def _tables(result: Any) -> list[Any]:
    return list(getattr(getattr(result, "stats", None), "tables", []) or [])


def _relationships(result: Any) -> list[Mapping[str, Any]]:
    return [
        row
        for row in (getattr(result, "relationships", []) or [])
        if isinstance(row, Mapping)
    ]


def _column_map(result: Any) -> dict[tuple[str, str], Any]:
    return {
        (str(getattr(column, "table", "")).casefold(), str(getattr(column, "column", "")).casefold()): column
        for column in _columns(result)
    }


def _table_map(result: Any) -> dict[str, Any]:
    return {
        str(getattr(table, "table", "")).casefold(): table
        for table in _tables(result)
    }


def _measure_names(result: Any) -> set[str]:
    return {str(getattr(measure, "measure", "")).casefold() for measure in _measures(result)}


def _is_numeric(data_type: str) -> bool:
    return str(data_type or "").casefold() in NUMERIC_TYPES


def _is_datetime(data_type: str) -> bool:
    return str(data_type or "").casefold() == "datetime"


def _visible_column(column: Any, tables: Mapping[str, Any] | None = None) -> bool:
    if bool(getattr(column, "is_hidden", False)):
        return False
    if tables is None:
        return True
    table = tables.get(str(getattr(column, "table", "")).casefold())
    return not bool(getattr(table, "is_hidden", False)) if table is not None else True


def _column_label(column: Any) -> str:
    return f"{getattr(column, 'table', '')}[{getattr(column, 'column', '')}]"


def _column_finding(rule: BpaRule, column: Any, detail: str = "") -> Finding:
    table = str(getattr(column, "table", "") or "")
    name = str(getattr(column, "column", "") or "")
    return Finding(
        rule_id=rule.id,
        object=_column_label(column),
        table=table,
        name=name,
        kind="column",
        detail=detail,
        size_bytes=int(getattr(column, "size_total_bytes", 0) or 0),
        target={"kind": "column", "table": table, "name": name},
    )


def _measure_finding(rule: BpaRule, measure: Any, detail: str = "") -> Finding:
    table = str(getattr(measure, "table", "") or "")
    name = str(getattr(measure, "measure", "") or "")
    return Finding(
        rule_id=rule.id,
        object=f"{table}[{name}]",
        table=table,
        name=name,
        kind="measure",
        detail=detail,
        target={"kind": "measure", "table": table, "name": name},
    )


def _table_finding(rule: BpaRule, table: Any, detail: str = "") -> Finding:
    name = str(getattr(table, "table", "") or "")
    return Finding(
        rule_id=rule.id,
        object=name,
        table=name,
        name=name,
        kind="table",
        detail=detail,
        size_bytes=int(getattr(table, "size_total_bytes", 0) or 0),
        target={"kind": "table", "table": name},
    )


def _relationship_label(relationship: Mapping[str, Any]) -> str:
    return (
        f"'{relationship.get('from_table') or ''}'"
        f"[{relationship.get('from_column') or ''}] -> "
        f"'{relationship.get('to_table') or ''}'"
        f"[{relationship.get('to_column') or ''}]"
    )


def _relationship_finding(rule: BpaRule, relationship: Mapping[str, Any], detail: str = "") -> Finding:
    label = _relationship_label(relationship)
    return Finding(
        rule_id=rule.id,
        object=label,
        kind="relationship",
        detail=detail,
        target={"kind": "relationship", "name": str(relationship.get("name") or "")},
    )


def _model_finding(rule: BpaRule, result: Any, detail: str = "") -> Finding:
    return Finding(
        rule_id=rule.id,
        object=str(getattr(result, "dataset_name", "") or "Model"),
        kind="model",
        detail=detail,
        target={"kind": "model"},
    )


def _rule_row(
    rule: BpaRule, status: str, count: int, score: int, reason: str
) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "category": rule.category,
        "severity": rule.severity,
        "severity_label": rule.severity_label,
        "scope": rule.scope,
        "description": rule.description,
        "expression": rule.expression,
        "fix_expression": rule.fix_expression,
        "status": status,
        "count": int(count),
        "score": int(score),
        "reason": reason,
    }


def _rule_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -int(row.get("score") or 0),
        -int(row.get("severity") or 0),
        str(row.get("category") or ""),
        str(row.get("name") or "").casefold(),
    )


def _unique_findings(items: Iterable[Finding]) -> list[Finding]:
    """Buang temuan ganda untuk objek + detail yang sama."""
    seen: set[tuple[str, str, str]] = set()
    result: list[Finding] = []
    for item in items:
        key = (item.rule_id, item.object, item.detail)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _dax_objects(result: Any) -> list[tuple[str, str, str]]:
    """Daftar (object, tabel, ekspresi) untuk measure + calculated column."""
    items: list[tuple[str, str, str]] = []
    for measure in _measures(result):
        expression = str(getattr(measure, "expression", "") or "")
        if expression:
            items.append(
                (
                    f"{getattr(measure, 'table', '')}[{getattr(measure, 'measure', '')}]",
                    str(getattr(measure, "table", "") or ""),
                    expression,
                )
            )
    for column in _columns(result):
        expression = str(getattr(column, "expression", "") or "")
        if expression and bool(getattr(column, "is_calculated", False)):
            items.append((_column_label(column), str(getattr(column, "table", "") or ""), expression))
    return items


# ---------------------------------------------------------------------------
# Evaluator: Performance
# ---------------------------------------------------------------------------
def _floating_point(result: Any, rule: BpaRule) -> list[Finding]:
    return [
        _column_finding(rule, column, str(getattr(column, "data_type", "")))
        for column in _columns(result)
        if str(getattr(column, "data_type", "")).casefold() == "double"
    ]


def _bi_directional_high_cardinality(result: Any, rule: BpaRule) -> list[Finding]:
    columns = _column_map(result)
    found: list[Finding] = []
    for relationship in _relationships(result):
        if str(relationship.get("cross_filtering") or "").casefold() != "bothdirections":
            continue
        for side, table_key, column_key in (
            ("from", "from_table", "from_column"),
            ("to", "to_table", "to_column"),
        ):
            column = columns.get(
                (
                    str(relationship.get(table_key) or "").casefold(),
                    str(relationship.get(column_key) or "").casefold(),
                )
            )
            if column is None:
                continue
            cardinality = int(getattr(column, "cardinality", 0) or 0)
            if cardinality > 100_000:
                found.append(
                    _column_finding(
                        rule,
                        column,
                        f"cardinality {cardinality:,} · relasi dua arah",
                    )
                )
    return found


def _large_table_partition(result: Any, rule: BpaRule) -> list[Finding]:
    return [
        _table_finding(rule, table, f"{int(getattr(table, 'rows', 0) or 0):,} baris")
        for table in _tables(result)
        if int(getattr(table, "rows", 0) or 0) > 25_000_000
        and int(getattr(table, "partition_count", 0) or 0) == 1
    ]


def _related_calculated_column(result: Any, rule: BpaRule) -> list[Finding]:
    pattern = re.compile(r"(?i)RELATED\s*\(")
    return [
        _column_finding(rule, column, "RELATED(")
        for column in _columns(result)
        if bool(getattr(column, "is_calculated", False))
        and pattern.search(str(getattr(column, "expression", "") or ""))
    ]


def _snowflake(result: Any, rule: BpaRule) -> list[Finding]:
    from_tables = {
        str(row.get("from_table") or "").casefold() for row in _relationships(result)
    }
    to_tables = {
        str(row.get("to_table") or "").casefold() for row in _relationships(result)
    }
    tables = _table_map(result)
    return [
        _table_finding(rule, table, "tabel menjadi sisi from dan to relasi")
        for key, table in tables.items()
        if key in from_tables and key in to_tables
    ]


def _date_table_missing(result: Any, rule: BpaRule) -> list[Finding]:
    columns_by_table: dict[str, list[Any]] = {}
    for column in _columns(result):
        columns_by_table.setdefault(str(getattr(column, "table", "")).casefold(), []).append(column)
    for table in _tables(result):
        if str(getattr(table, "data_category", "") or "").casefold() != "time":
            continue
        if any(
            bool(getattr(column, "is_key", False))
            and _is_datetime(getattr(column, "data_type", ""))
            for column in columns_by_table.get(str(getattr(table, "table", "")).casefold(), [])
        ):
            return []
    return [_model_finding(rule, result, "tidak ada tabel DataCategory=Time dengan key DateTime")]


def _date_table_not_marked(result: Any, rule: BpaRule) -> list[Finding]:
    columns_by_table: dict[str, list[Any]] = {}
    for column in _columns(result):
        columns_by_table.setdefault(str(getattr(column, "table", "")).casefold(), []).append(column)
    found: list[Finding] = []
    for table in _tables(result):
        name = str(getattr(table, "table", "") or "")
        upper = name.upper()
        if "DATE" not in upper and "CALENDAR" not in upper:
            continue
        has_key = any(
            bool(getattr(column, "is_key", False))
            and _is_datetime(getattr(column, "data_type", ""))
            for column in columns_by_table.get(name.casefold(), [])
        )
        if str(getattr(table, "data_category", "") or "").casefold() != "time" or not has_key:
            found.append(_table_finding(rule, table, "belum ditandai sebagai date table"))
    return found


def _auto_date_table(result: Any, rule: BpaRule) -> list[Finding]:
    prefixes = ("DateTableTemplate_", "LocalDateTable_")
    return [
        _table_finding(rule, table, "tabel tanggal otomatis")
        for table in _tables(result)
        if str(getattr(table, "table", "") or "").startswith(prefixes)
    ]


def _excessive_relationships(result: Any, rule: BpaRule) -> list[Finding]:
    relationships = _relationships(result)
    if not relationships:
        return []
    complex_count = sum(
        1
        for row in relationships
        if str(row.get("cross_filtering") or "").casefold() == "bothdirections"
        or (
            str(row.get("from_cardinality") or "").casefold() == "many"
            and str(row.get("to_cardinality") or "").casefold() == "many"
        )
    )
    if complex_count / len(relationships) > 0.3:
        return [
            _model_finding(
                rule,
                result,
                f"{complex_count} dari {len(relationships)} relasi kompleks",
            )
        ]
    return []


def _power_query_transformations(result: Any, rule: BpaRule) -> list[Finding]:
    markers = (
        "Table.Combine(",
        "Table.Join(",
        "Table.NestedJoin(",
        "Table.AddColumn(",
        "Table.Group(",
        "Table.Sort(",
        "Table.Pivot(",
        "Table.Unpivot(",
        "Table.UnpivotOtherColumns(",
        "Table.Distinct(",
        'Query="SELECT',
        "Value.NativeQuery",
        "OleDb.",
    )
    found: list[Finding] = []
    seen: set[str] = set()
    for item in getattr(result, "m_queries", []) or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("kind") or "") != "Tabel":
            continue
        name = str(item.get("name") or "")
        if not name or name.casefold() in seen:
            continue
        expression = str(item.get("expression") or "")
        if any(marker in expression for marker in markers):
            seen.add(name.casefold())
            table = _table_map(result).get(name.casefold())
            target = {"kind": "table", "table": name}
            found.append(
                Finding(
                    rule_id=rule.id,
                    object=name,
                    table=name,
                    name=name,
                    kind="table",
                    detail="transformasi Power Query",
                    size_bytes=int(getattr(table, "size_total_bytes", 0) or 0) if table else 0,
                    target=target,
                )
            )
    return found


def _unpivot_months(result: Any, rule: BpaRule) -> list[Finding]:
    months: dict[str, int] = {}
    for column in _columns(result):
        name = str(getattr(column, "column", "") or "").upper()
        if not _is_numeric(getattr(column, "data_type", "")):
            continue
        if any(token in name for token in MONTH_TOKENS):
            table = str(getattr(column, "table", "") or "")
            months[table] = months.get(table, 0) + 1
    tables = _table_map(result)
    return [
        _table_finding(rule, tables[table], "kolom bulan ter-pivot")
        for table, count in months.items()
        if count >= 3 and table.casefold() in tables
    ]


def _m2m_both_directions(result: Any, rule: BpaRule) -> list[Finding]:
    return [
        _relationship_finding(rule, row, "many-to-many dan bothDirections")
        for row in _relationships(result)
        if str(row.get("from_cardinality") or "").casefold() == "many"
        and str(row.get("to_cardinality") or "").casefold() == "many"
        and str(row.get("cross_filtering") or "").casefold() == "bothdirections"
    ]


def _calculated_tables(result: Any, rule: BpaRule) -> list[Finding]:
    return [
        _table_finding(rule, table, "calculated table")
        for table in _tables(result)
        if bool(getattr(table, "is_calculated_table", False))
    ]


def _redundant_columns(result: Any, rule: BpaRule) -> list[Finding]:
    columns = _columns(result)
    related = set()
    for row in _relationships(result):
        related.add(
            (
                str(row.get("from_table") or "").casefold(),
                str(row.get("from_column") or "").casefold(),
            )
        )
        related.add(
            (
                str(row.get("to_table") or "").casefold(),
                str(row.get("to_column") or "").casefold(),
            )
        )
    by_name: dict[str, list[Any]] = {}
    for column in columns:
        key = str(getattr(column, "column", "") or "").casefold()
        if key:
            by_name.setdefault(key, []).append(column)
    found: list[Finding] = []
    table_names = {str(getattr(column, "table", "") or "") for column in columns}
    for column in columns:
        table = str(getattr(column, "table", "") or "")
        name = str(getattr(column, "column", "") or "")
        if (table.casefold(), name.casefold()) in related:
            continue
        for other in by_name.get(name.casefold(), []):
            other_table = str(getattr(other, "table", "") or "")
            if other_table.casefold() == table.casefold() or other_table not in table_names:
                continue
            if other_table.casefold() in {
                str(row.get("from_table") or "").casefold()
                for row in _relationships(result)
                if str(row.get("to_table") or "").casefold() == table.casefold()
            }:
                found.append(_column_finding(rule, column, f"duplikat di {other_table}"))
                break
    return found


def _time_intelligence_direct_query(result: Any, rule: BpaRule) -> list[Finding]:
    if not any(
        "directquery" in str(getattr(table, "storage_mode", "") or "").casefold()
        for table in _tables(result)
    ):
        return []
    return [
        _measure_finding(rule, measure, "DirectQuery + time intelligence")
        for measure in _measures(result)
        if TIME_INTELLIGENCE_RE.search(str(getattr(measure, "expression", "") or ""))
    ]


def _many_calculated_columns(result: Any, rule: BpaRule) -> list[Finding]:
    count = sum(
        1 for column in _columns(result) if bool(getattr(column, "is_calculated", False))
    )
    if count > 5:
        return [_model_finding(rule, result, f"{count} calculated column")]
    return []


def _check_relationships(result: Any, rule: BpaRule) -> list[Finding]:
    return [
        _relationship_finding(rule, row, "perlu diverifikasi")
        for row in _relationships(result)
        if str(row.get("cross_filtering") or "").casefold() == "bothdirections"
        or (
            str(row.get("from_cardinality") or "").casefold() == "many"
            and str(row.get("to_cardinality") or "").casefold() == "many"
        )
    ]


# ---------------------------------------------------------------------------
# Evaluator: DAX
# ---------------------------------------------------------------------------
def _dax_columns_fully_qualified(result: Any, rule: BpaRule) -> list[Finding]:
    column_names = {
        str(getattr(column, "column", "") or "").casefold() for column in _columns(result)
    }
    pattern = re.compile(r"(?<![A-Za-z0-9_'\]])\[([^\]]+)\]")
    found: list[Finding] = []
    for label, _table, expression in _dax_objects(result):
        for match in pattern.finditer(strip_dax_literals(expression)):
            if match.group(1).casefold() in column_names:
                found.append(
                    Finding(
                        rule_id=rule.id,
                        object=label,
                        kind="expression",
                        detail=match.group(0),
                    )
                )
                break
    return found


def _dax_measures_unqualified(result: Any, rule: BpaRule) -> list[Finding]:
    measures = _measure_names(result)
    found: list[Finding] = []
    for label, _table, expression in _dax_objects(result):
        cleaned = strip_dax_literals(expression)
        for name in measures:
            pattern = re.compile(
                rf"(?:'[^']+'|[A-Za-z_][A-Za-z0-9_]*)\s*\[\s*{re.escape(name)}\s*\]",
                re.IGNORECASE,
            )
            if pattern.search(cleaned):
                found.append(
                    Finding(
                        rule_id=rule.id,
                        object=label,
                        kind="expression",
                        detail=f"referensi measure berkualifikasi: {name}",
                    )
                )
                break
    return found


def _duplicate_measures(result: Any, rule: BpaRule) -> list[Finding]:
    seen: dict[str, Any] = {}
    found: list[Finding] = []
    for measure in _measures(result):
        expression = re.sub(
            r"\s+", "", str(getattr(measure, "expression", "") or "")
        )
        if not expression:
            continue
        if expression in seen:
            found.append(
                _measure_finding(
                    rule,
                    measure,
                    f"definisi sama dengan {getattr(seen[expression], 'measure', '')}",
                )
            )
        else:
            seen[expression] = measure
    return found


def _regex_expression_rule(pattern: str, detail: str) -> Evaluator:
    compiled = re.compile(pattern, re.IGNORECASE)

    def evaluate(result: Any, rule: BpaRule) -> list[Finding]:
        found: list[Finding] = []
        for label, _table, expression in _dax_objects(result):
            if compiled.search(strip_dax_literals(expression)):
                found.append(
                    Finding(
                        rule_id=rule.id,
                        object=label,
                        kind="expression",
                        detail=detail,
                    )
                )
        return found

    return evaluate


def _direct_measure_reference(result: Any, rule: BpaRule) -> list[Finding]:
    names = {
        str(getattr(measure, "measure", "") or ""): measure
        for measure in _measures(result)
    }
    found: list[Finding] = []
    for measure in _measures(result):
        expression = str(getattr(measure, "expression", "") or "").strip()
        for name in names:
            if name and expression in {f"[{name}]", f"'{getattr(names[name], 'table', '')}'[{name}]"}:
                if measure is not names[name]:
                    found.append(
                        _measure_finding(rule, measure, f"hanya merujuk {name}")
                    )
                break
    return found


def _inactive_never_activated(result: Any, rule: BpaRule) -> list[Finding]:
    expressions = [expression for _label, _table, expression in _dax_objects(result)]
    found: list[Finding] = []
    for relationship in _relationships(result):
        if bool(relationship.get("is_active", True)):
            continue
        from_table = str(relationship.get("from_table") or "")
        from_column = str(relationship.get("from_column") or "")
        to_table = str(relationship.get("to_table") or "")
        to_column = str(relationship.get("to_column") or "")
        patterns = (
            rf"USERELATIONSHIP\s*\(\s*'?{re.escape(from_table)}'?\s*\[\s*{re.escape(from_column)}\s*\]",
            rf"USERELATIONSHIP\s*\(\s*'?{re.escape(to_table)}'?\s*\[\s*{re.escape(to_column)}\s*\]",
        )
        if not any(
            all(re.search(pattern, strip_dax_literals(expression), re.IGNORECASE) for pattern in patterns)
            for expression in expressions
        ):
            found.append(_relationship_finding(rule, relationship, "tidak pernah diaktifkan"))
    return found


# ---------------------------------------------------------------------------
# Evaluator: Error Prevention / Maintenance
# ---------------------------------------------------------------------------
def _empty_expressions(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for measure in _measures(result):
        if not str(getattr(measure, "expression", "") or "").strip():
            found.append(_measure_finding(rule, measure, "ekspresi kosong"))
    for column in _columns(result):
        if bool(getattr(column, "is_calculated", False)) and not str(
            getattr(column, "expression", "") or ""
        ).strip():
            found.append(_column_finding(rule, column, "ekspresi kosong"))
    return found


def _relationship_same_type(result: Any, rule: BpaRule) -> list[Finding]:
    columns = _column_map(result)
    found: list[Finding] = []
    for relationship in _relationships(result):
        from_column = columns.get(
            (
                str(relationship.get("from_table") or "").casefold(),
                str(relationship.get("from_column") or "").casefold(),
            )
        )
        to_column = columns.get(
            (
                str(relationship.get("to_table") or "").casefold(),
                str(relationship.get("to_column") or "").casefold(),
            )
        )
        if from_column is None or to_column is None:
            continue
        from_type = str(getattr(from_column, "data_type", "") or "")
        to_type = str(getattr(to_column, "data_type", "") or "")
        if from_type.casefold() != to_type.casefold():
            found.append(
                _relationship_finding(
                    rule, relationship, f"{from_type or '?'} vs {to_type or '?'}"
                )
            )
    return found


def _invalid_name_characters(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for table in _tables(result):
        if _has_control(str(getattr(table, "table", "") or "")):
            found.append(_table_finding(rule, table, "karakter kontrol"))
    for column in _columns(result):
        if _has_control(str(getattr(column, "column", "") or "")):
            found.append(_column_finding(rule, column, "karakter kontrol"))
    for measure in _measures(result):
        if _has_control(str(getattr(measure, "measure", "") or "")):
            found.append(_measure_finding(rule, measure, "karakter kontrol"))
    return found


def _invalid_description_characters(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for table in _tables(result):
        if _has_control(str(getattr(table, "description", "") or "")):
            found.append(_table_finding(rule, table, "karakter kontrol pada deskripsi"))
    for column in _columns(result):
        if _has_control(str(getattr(column, "description", "") or "")):
            found.append(_column_finding(rule, column, "karakter kontrol pada deskripsi"))
    for measure in _measures(result):
        if _has_control(str(getattr(measure, "description", "") or "")):
            found.append(_measure_finding(rule, measure, "karakter kontrol pada deskripsi"))
    return found


def _unnecessary_columns(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for analysis in getattr(result, "columns", []) or []:
        column = getattr(analysis, "column", None)
        if column is None:
            continue
        if str(getattr(analysis, "status", "") or "") != UNUSED_STATUS:
            continue
        if not bool(getattr(column, "is_hidden", False)):
            continue
        found.append(_column_finding(rule, column, "tersembunyi dan tanpa referensi"))
    return found


def _unnecessary_measures(result: Any, rule: BpaRule) -> list[Finding]:
    tables = _table_map(result)
    found: list[Finding] = []
    for analysis in getattr(result, "measures", []) or []:
        measure = getattr(analysis, "measure", None)
        if measure is None:
            continue
        if str(getattr(analysis, "status", "") or "") != UNUSED_STATUS:
            continue
        table = tables.get(str(getattr(measure, "table", "")).casefold())
        if not bool(getattr(measure, "is_hidden", False)) and not (
            table is not None and bool(getattr(table, "is_hidden", False))
        ):
            continue
        found.append(_measure_finding(rule, measure, "tersembunyi dan tanpa referensi"))
    return found


def _tables_without_relationship(result: Any, rule: BpaRule) -> list[Finding]:
    related = set()
    for relationship in _relationships(result):
        related.add(str(relationship.get("from_table") or "").casefold())
        related.add(str(relationship.get("to_table") or "").casefold())
    return [
        _table_finding(rule, table, "tanpa relasi")
        for table in _tables(result)
        if str(getattr(table, "table", "") or "").casefold() not in related
        and not bool(getattr(table, "is_calculation_group", False))
    ]


def _no_description(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    tables = _table_map(result)
    for table in _tables(result):
        if not bool(getattr(table, "is_hidden", False)) and not str(
            getattr(table, "description", "") or ""
        ).strip():
            found.append(_table_finding(rule, table, "tanpa deskripsi"))
    for column in _columns(result):
        if _visible_column(column, tables) and not str(
            getattr(column, "description", "") or ""
        ).strip():
            found.append(_column_finding(rule, column, "tanpa deskripsi"))
    for measure in _measures(result):
        table = tables.get(str(getattr(measure, "table", "")).casefold())
        if bool(getattr(measure, "is_hidden", False)) or (
            table is not None and bool(getattr(table, "is_hidden", False))
        ):
            continue
        if not str(getattr(measure, "description", "") or "").strip():
            found.append(_measure_finding(rule, measure, "tanpa deskripsi"))
    return found


# ---------------------------------------------------------------------------
# Evaluator: Naming / Formatting
# ---------------------------------------------------------------------------
def _special_chars(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for table in _tables(result):
        if _has_special(str(getattr(table, "table", "") or "")):
            found.append(_table_finding(rule, table, "karakter tab/newline"))
    for column in _columns(result):
        if _has_special(str(getattr(column, "column", "") or "")):
            found.append(_column_finding(rule, column, "karakter tab/newline"))
    for measure in _measures(result):
        if _has_special(str(getattr(measure, "measure", "") or "")):
            found.append(_measure_finding(rule, measure, "karakter tab/newline"))
    return found


def _trim_names(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for table in _tables(result):
        if _needs_trim(str(getattr(table, "table", "") or "")):
            found.append(_table_finding(rule, table, "spasi di awal/akhir"))
    for column in _columns(result):
        if _needs_trim(str(getattr(column, "column", "") or "")):
            found.append(_column_finding(rule, column, "spasi di awal/akhir"))
    for measure in _measures(result):
        if _needs_trim(str(getattr(measure, "measure", "") or "")):
            found.append(_measure_finding(rule, measure, "spasi di awal/akhir"))
    return found


def _first_letter_capital(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for table in _tables(result):
        if _lower_first(str(getattr(table, "table", "") or "")):
            found.append(_table_finding(rule, table))
    for measure in _measures(result):
        if _lower_first(str(getattr(measure, "measure", "") or "")):
            found.append(_measure_finding(rule, measure))
    for column in _columns(result):
        if bool(getattr(column, "is_calculated", False)) and _lower_first(
            str(getattr(column, "column", "") or "")
        ):
            found.append(_column_finding(rule, column))
    return found


def _flag_format(result: Any, rule: BpaRule) -> list[Finding]:
    tables = _table_map(result)
    found: list[Finding] = []
    for column in _columns(result):
        if not _visible_column(column, tables):
            continue
        name = str(getattr(column, "column", "") or "")
        data_type = str(getattr(column, "data_type", "") or "").casefold()
        if (name.startswith("Is") and data_type == "int64") or (
            name.endswith(" Flag") and data_type != "string"
        ):
            found.append(_column_finding(rule, column, name))
    return found


def _object_space_boundary(result: Any, rule: BpaRule) -> list[Finding]:
    return _trim_names(result, rule)


def _date_format(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for column in _columns(result):
        if "date" not in str(getattr(column, "column", "") or "").casefold():
            continue
        if not _is_datetime(getattr(column, "data_type", "")):
            continue
        if str(getattr(column, "format_string", "") or "") != "mm/dd/yyyy":
            found.append(
                _column_finding(rule, column, str(getattr(column, "format_string", "") or "(kosong)"))
            )
    return found


def _month_format(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for column in _columns(result):
        if "month" not in str(getattr(column, "column", "") or "").casefold():
            continue
        if not _is_datetime(getattr(column, "data_type", "")):
            continue
        if str(getattr(column, "format_string", "") or "") != "MMMM yyyy":
            found.append(
                _column_finding(rule, column, str(getattr(column, "format_string", "") or "(kosong)"))
            )
    return found


def _measure_format(result: Any, rule: BpaRule) -> list[Finding]:
    tables = _table_map(result)
    found: list[Finding] = []
    for measure in _measures(result):
        table = tables.get(str(getattr(measure, "table", "")).casefold())
        if bool(getattr(measure, "is_hidden", False)) or (
            table is not None and bool(getattr(table, "is_hidden", False))
        ):
            continue
        if not _is_numeric(getattr(measure, "data_type", "")):
            continue
        if not str(getattr(measure, "format_string", "") or "").strip():
            found.append(_measure_finding(rule, measure, "tanpa format string"))
    return found


def _numeric_summarize(result: Any, rule: BpaRule) -> list[Finding]:
    tables = _table_map(result)
    found: list[Finding] = []
    for column in _columns(result):
        if not _visible_column(column, tables) or not _is_numeric(
            getattr(column, "data_type", "")
        ):
            continue
        summarize = str(getattr(column, "summarize_by", "") or "").casefold()
        if summarize and summarize != "none":
            found.append(_column_finding(rule, column, summarize))
    return found


def _percentage_format(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for measure in _measures(result):
        value = str(getattr(measure, "format_string", "") or "")
        if "%" in value and value != "#,0.0%;-#,0.0%;#,0.0%":
            found.append(_measure_finding(rule, measure, value))
    return found


def _integer_format(result: Any, rule: BpaRule) -> list[Finding]:
    tables = _table_map(result)
    found: list[Finding] = []
    for measure in _measures(result):
        table = tables.get(str(getattr(measure, "table", "")).casefold())
        if bool(getattr(measure, "is_hidden", False)) or (
            table is not None and bool(getattr(table, "is_hidden", False))
        ):
            continue
        if str(getattr(measure, "data_type", "") or "").casefold() != "int64":
            continue
        value = str(getattr(measure, "format_string", "") or "")
        if "$" in value or "%" in value:
            continue
        if value not in {"#,0", "#,0.0"}:
            found.append(_measure_finding(rule, measure, value or "(kosong)"))
    return found


def _relationship_integer(result: Any, rule: BpaRule) -> list[Finding]:
    columns = _column_map(result)
    found: list[Finding] = []
    for relationship in _relationships(result):
        for table_key, column_key in (
            ("from_table", "from_column"),
            ("to_table", "to_column"),
        ):
            column = columns.get(
                (
                    str(relationship.get(table_key) or "").casefold(),
                    str(relationship.get(column_key) or "").casefold(),
                )
            )
            if column is None:
                continue
            if str(getattr(column, "data_type", "") or "").casefold() != "int64":
                found.append(
                    _column_finding(
                        rule,
                        column,
                        str(getattr(column, "data_type", "") or "?"),
                    )
                )
    return found


def _data_category(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for column in _columns(result):
        if str(getattr(column, "data_category", "") or "").strip():
            continue
        name = str(getattr(column, "column", "") or "").casefold()
        data_type = str(getattr(column, "data_type", "") or "").casefold()
        if (
            any(token in name for token in ("country", "continent", "city"))
            and data_type == "string"
        ) or (
            name in {"latitude", "longitude"} and data_type in {"decimal", "double"}
        ):
            found.append(_column_finding(rule, column, name))
    return found


def _hide_foreign_keys(result: Any, rule: BpaRule) -> list[Finding]:
    columns = _column_map(result)
    found: list[Finding] = []
    for relationship in _relationships(result):
        if str(relationship.get("from_cardinality") or "").casefold() != "many":
            continue
        column = columns.get(
            (
                str(relationship.get("from_table") or "").casefold(),
                str(relationship.get("from_column") or "").casefold(),
            )
        )
        if column is None or bool(getattr(column, "is_hidden", False)):
            continue
        found.append(_column_finding(rule, column, "foreign key terlihat"))
    return found


def _mark_primary_keys(result: Any, rule: BpaRule) -> list[Finding]:
    columns = _column_map(result)
    tables = _table_map(result)
    found: list[Finding] = []
    for relationship in _relationships(result):
        if str(relationship.get("to_cardinality") or "").casefold() != "one":
            continue
        column = columns.get(
            (
                str(relationship.get("to_table") or "").casefold(),
                str(relationship.get("to_column") or "").casefold(),
            )
        )
        if column is None or bool(getattr(column, "is_key", False)):
            continue
        table = tables.get(str(getattr(column, "table", "")).casefold())
        if table is not None and str(getattr(table, "data_category", "") or "").casefold() == "time":
            continue
        found.append(_column_finding(rule, column, "belum IsKey"))
    return found


def _hide_fact_columns(result: Any, rule: BpaRule) -> list[Finding]:
    patterns = re.compile(
        r"(?i)\b(COUNT|COUNTBLANK|COUNTROWS|SUM|SUMX|AVERAGE|AVERAGEX|MIN|MINX|MAX|MAXX)\s*\(\s*"
        r"'?([^'\[]+)'?\s*\[\s*([^\]]+)\s*\]\s*\)"
    )
    referenced: set[tuple[str, str]] = set()
    for _label, _table, expression in _dax_objects(result):
        for match in patterns.finditer(strip_dax_literals(expression)):
            referenced.add((match.group(2).strip().casefold(), match.group(3).strip().casefold()))
    tables = _table_map(result)
    found: list[Finding] = []
    for column in _columns(result):
        if not _visible_column(column, tables):
            continue
        key = (
            str(getattr(column, "table", "") or "").casefold(),
            str(getattr(column, "column", "") or "").casefold(),
        )
        if key in referenced:
            found.append(_column_finding(rule, column, "dipakai agregasi measure"))
    return found


def _month_string_sort(result: Any, rule: BpaRule) -> list[Finding]:
    found: list[Finding] = []
    for column in _columns(result):
        name = str(getattr(column, "column", "") or "").upper()
        if "MONTH" not in name or "MONTHS" in name:
            continue
        if str(getattr(column, "data_type", "") or "").casefold() != "string":
            continue
        if not str(getattr(column, "sort_by_column", "") or "").strip():
            found.append(_column_finding(rule, column, "tanpa Sort by column"))
    return found


# ---------------------------------------------------------------------------
# Helper text/karakter
# ---------------------------------------------------------------------------
def _has_control(text: str) -> bool:
    return any(ord(char) < 32 and not char.isspace() for char in text)


def _has_special(text: str) -> bool:
    return any(char in text for char in ("\t", "\n", "\r"))


def _needs_trim(text: str) -> bool:
    return text != text.strip() and bool(text.strip())


def _lower_first(text: str) -> bool:
    return bool(text) and text[0].isalpha() and text[0] != text[0].upper()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_EVALUATORS: dict[str, Evaluator] = {
    "AVOID_FLOATING_POINT_DATA_TYPES": _floating_point,
    "AVOID_BI-DIRECTIONAL_RELATIONSHIPS_AGAINST_HIGH-CARDINALITY_COLUMNS": _bi_directional_high_cardinality,
    "LARGE_TABLES_SHOULD_BE_PARTITIONED": _large_table_partition,
    "REDUCE_USAGE_OF_CALCULATED_COLUMNS_THAT_USE_THE_RELATED_FUNCTION": _related_calculated_column,
    "SNOWFLAKE_SCHEMA_ARCHITECTURE": _snowflake,
    "MODEL_SHOULD_HAVE_A_DATE_TABLE": _date_table_missing,
    "DATE/CALENDAR_TABLES_SHOULD_BE_MARKED_AS_A_DATE_TABLE": _date_table_not_marked,
    "REMOVE_AUTO-DATE_TABLE": _auto_date_table,
    "AVOID_EXCESSIVE_BI-DIRECTIONAL_OR_MANY-TO-MANY_RELATIONSHIPS": _excessive_relationships,
    "MINIMIZE_POWER_QUERY_TRANSFORMATIONS": _power_query_transformations,
    "UNPIVOT_PIVOTED_(MONTH)_DATA": _unpivot_months,
    "MANY-TO-MANY_RELATIONSHIPS_SHOULD_BE_SINGLE-DIRECTION": _m2m_both_directions,
    "REDUCE_USAGE_OF_CALCULATED_TABLES": _calculated_tables,
    "REMOVE_REDUNDANT_COLUMNS_IN_RELATED_TABLES": _redundant_columns,
    "MEASURES_USING_TIME_INTELLIGENCE_AND_MODEL_IS_USING_DIRECT_QUERY": _time_intelligence_direct_query,
    "REDUCE_NUMBER_OF_CALCULATED_COLUMNS": _many_calculated_columns,
    "CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID": _check_relationships,
    "DAX_COLUMNS_FULLY_QUALIFIED": _dax_columns_fully_qualified,
    "DAX_MEASURES_UNQUALIFIED": _dax_measures_unqualified,
    "AVOID_DUPLICATE_MEASURES": _duplicate_measures,
    "USE_THE_TREATAS_FUNCTION_INSTEAD_OF_INTERSECT": _regex_expression_rule(
        r"INTERSECT\s*\(", "INTERSECT("
    ),
    "USE_THE_DIVIDE_FUNCTION_FOR_DIVISION": _regex_expression_rule(
        r"(?:\]|\))\s*/(?!/)(?!\*)", "pembagian dengan /"
    ),
    "AVOID_USING_THE_IFERROR_FUNCTION": _regex_expression_rule(
        r"IFERROR\s*\(", "IFERROR("
    ),
    "MEASURES_SHOULD_NOT_BE_DIRECT_REFERENCES_OF_OTHER_MEASURES": _direct_measure_reference,
    "FILTER_COLUMN_VALUES": _regex_expression_rule(
        r"(?:CALCULATE|CALCULATETABLE)\s*\([^,]*,\s*FILTER\s*\(\s*'?[\w ]+'?\s*,"
        r"\s*'?[\w ]+'?\s*\[",
        "FILTER pada nilai kolom",
    ),
    "FILTER_MEASURE_VALUES_BY_COLUMNS": _regex_expression_rule(
        r"(?:CALCULATE|CALCULATETABLE)\s*\([^,]*,\s*FILTER\s*\(\s*'?[\w ]+'?\s*,\s*\[",
        "FILTER pada measure",
    ),
    "INACTIVE_RELATIONSHIPS_THAT_ARE_NEVER_ACTIVATED": _inactive_never_activated,
    "AVOID_USING_'1-(X/Y)'_SYNTAX": _regex_expression_rule(
        r"(?:\b\d+\s*[-+]\s*\(?\s*(?:SUM|DIVIDE)\s*\()", "1-(x/y)"
    ),
    "EVALUATEANDLOG_SHOULD_NOT_BE_USED_IN_PRODUCTION_MODELS": _regex_expression_rule(
        r"EVALUATEANDLOG\s*\(", "EVALUATEANDLOG("
    ),
    "EXPRESSION_RELIANT_OBJECTS_MUST_HAVE_AN_EXPRESSION": _empty_expressions,
    "RELATIONSHIP_COLUMNS_SAME_DATA_TYPE": _relationship_same_type,
    "AVOID_INVALID_NAME_CHARACTERS": _invalid_name_characters,
    "AVOID_INVALID_DESCRIPTION_CHARACTERS": _invalid_description_characters,
    "UNNECESSARY_COLUMNS": _unnecessary_columns,
    "UNNECESSARY_MEASURES": _unnecessary_measures,
    "ENSURE_TABLES_HAVE_RELATIONSHIPS": _tables_without_relationship,
    "OBJECTS_WITH_NO_DESCRIPTION": _no_description,
    "SPECIAL_CHARS_IN_OBJECT_NAMES": _special_chars,
    "TRIM_OBJECT_NAMES": _trim_names,
    "FIRST_LETTER_OF_OBJECTS_MUST_BE_CAPITALIZED": _first_letter_capital,
    "FORMAT_FLAG_COLUMNS_AS_YES/NO_VALUE_STRINGS": _flag_format,
    "OBJECTS_SHOULD_NOT_START_OR_END_WITH_A_SPACE": _object_space_boundary,
    "DATECOLUMN_FORMATSTRING": _date_format,
    "MONTHCOLUMN_FORMATSTRING": _month_format,
    "PROVIDE_FORMAT_STRING_FOR_MEASURES": _measure_format,
    "NUMERIC_COLUMN_SUMMARIZE_BY": _numeric_summarize,
    "PERCENTAGE_FORMATTING": _percentage_format,
    "INTEGER_FORMATTING": _integer_format,
    "RELATIONSHIP_COLUMNS_SHOULD_BE_OF_INTEGER_DATA_TYPE": _relationship_integer,
    "ADD_DATA_CATEGORY_FOR_COLUMNS": _data_category,
    "HIDE_FOREIGN_KEYS": _hide_foreign_keys,
    "MARK_PRIMARY_KEYS": _mark_primary_keys,
    "HIDE_FACT_TABLE_COLUMNS": _hide_fact_columns,
    "MONTH_(AS_A_STRING)_MUST_BE_SORTED": _month_string_sort,
}

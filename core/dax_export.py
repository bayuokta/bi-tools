"""Ekspor tab DAX expressions mengikuti template Measure Killer.

Satu baris per objek ber-ekspresi: measure, calculated column, calculated
table, field parameter table, dan user-defined function. ``Source_type`` selalu
``Semantic model``. ``Best_practices_violations`` bernilai 0 karena tool ini
belum punya rule best-practice per ekspresi DAX (template pembanding juga 0).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from .metadata_common import strip_dax_literals, write_sheet

DAX_RESULT_COLUMNS = [
    "Name",
    "Table",
    "Type",
    "Has_error",
    "Best_practices_violations",
    "Source",
    "Source_type",
    "Lineage_tag",
    "Display_folder",
    "Description",
    "Expression",
]

TYPE_FIELD_PARAMETER = "Field param. table"
TYPE_CALCULATED_TABLE = "Calculated Table"
TYPE_CALCULATED_COLUMN = "Calculated Column"
TYPE_MEASURE = "Measure"
TYPE_FUNCTION = "User-defined function"

_DIVISION = re.compile(r"(?:\]|\))\s*/(?!/)(?!\*)", re.IGNORECASE)


def _violations(expression: str) -> int:
    """Jumlah pelanggaran ekspresi DAX yang dihitung Measure Killer."""
    return 1 if _DIVISION.search(strip_dax_literals(expression or "")) else 0


def _field_parameter_tables(result: Any) -> set[str]:
    return {
        item.column.table.casefold()
        for item in (getattr(result, "columns", []) or [])
        if str(getattr(item.column, "column_type", "")).casefold()
        == "field parameter"
    }


def _row(
    *,
    name: str,
    table: str,
    type_label: str,
    has_error: Any,
    source: str,
    violations: int = 0,
    lineage_tag: str,
    display_folder: str,
    description: str,
    expression: str,
) -> dict[str, Any]:
    return {
        "Name": name,
        "Table": table,
        "Type": type_label,
        "Has_error": has_error,
        "Best_practices_violations": int(violations),
        "Source": source,
        "Source_type": "Semantic model",
        "Lineage_tag": lineage_tag,
        "Display_folder": display_folder,
        "Description": description,
        "Expression": expression,
    }


def build_dax_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 11 kolom template untuk semua objek ber-ekspresi."""
    source = str(getattr(result, "dataset_name", "") or "")
    rows: list[dict[str, Any]] = []

    for item in getattr(result, "functions", []) or []:
        function = item.function
        rows.append(
            _row(
                name=str(getattr(function, "name", "")),
                table="",
                type_label=TYPE_FUNCTION,
                has_error="N/A",
                source=source,
                lineage_tag=str(getattr(function, "lineage_tag", "") or ""),
                display_folder="",
                description=str(getattr(function, "description", "") or ""),
                expression=str(getattr(function, "expression", "") or ""),
            )
        )

    for item in getattr(result, "measures", []) or []:
        measure = item.measure
        rows.append(
            _row(
                name=str(getattr(measure, "measure", "")),
                table=str(getattr(measure, "table", "")),
                type_label=TYPE_MEASURE,
                has_error=bool(getattr(measure, "has_error", False)),
                violations=_violations(str(getattr(measure, "expression", "") or "")),
                source=source,
                lineage_tag=str(getattr(measure, "lineage_tag", "") or ""),
                display_folder=str(getattr(measure, "display_folder", "") or ""),
                description=str(getattr(measure, "description", "") or ""),
                expression=str(getattr(measure, "expression", "") or ""),
            )
        )

    for item in getattr(result, "columns", []) or []:
        column = item.column
        if not bool(getattr(column, "is_calculated", False)):
            continue
        rows.append(
            _row(
                name=str(getattr(column, "column", "")),
                table=str(getattr(column, "table", "")),
                type_label=TYPE_CALCULATED_COLUMN,
                has_error=bool(getattr(column, "has_error", False)),
                violations=_violations(str(getattr(column, "expression", "") or "")),
                source=source,
                lineage_tag=str(getattr(column, "lineage_tag", "") or ""),
                display_folder=str(getattr(column, "display_folder", "") or ""),
                description=str(getattr(column, "description", "") or ""),
                expression=str(getattr(column, "expression", "") or ""),
            )
        )

    field_parameters = _field_parameter_tables(result)
    for table in getattr(getattr(result, "stats", None), "tables", []) or []:
        if not bool(getattr(table, "is_calculated_table", False)):
            continue
        if bool(getattr(table, "is_calculation_group", False)):
            continue
        name = str(getattr(table, "table", ""))
        rows.append(
            _row(
                name=name,
                table="",
                type_label=(
                    TYPE_FIELD_PARAMETER
                    if name.casefold() in field_parameters
                    else TYPE_CALCULATED_TABLE
                ),
                has_error="N/A",
                source=source,
                lineage_tag=str(getattr(table, "lineage_tag", "") or ""),
                display_folder="",
                description=str(getattr(table, "description", "") or ""),
                expression=str(getattr(table, "expression", "") or ""),
            )
        )
    return rows


def write_dax_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet DAX expressions dengan 11 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_dax_rows(result), columns=DAX_RESULT_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "DAX expressions")
    return target

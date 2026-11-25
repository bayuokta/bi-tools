"""
Ekstraksi metadata semantic model Power BI via XMLA (ADOMD + DMV) -> Excel,
dilengkapi pemakaian objek di report.

Modul inti tanpa I/O terminal; dipakai oleh CLI dan GUI.
Sumber utama : instance Power BI Desktop lokal (auto-detect port) atau endpoint XMLA.
Sumber report: file .pbix (Report/definition di dalam arsip), hanya untuk kolom usage.
Output       : Semantic_Model_Metadata.xlsx
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import pandas as pd

from .errors import ExtractionError
from .m_lineage import apply_lineage, build_lineage, warnings_rows
from .metadata_common import (
    build_dependencies,
    fmt_pages,
    scan_report_usage,
    split_outside_quotes,
    write_sheet,
)
from .pbix import ROOT, display_path, extract_pbix_definition
from .xmla_client import XmlaError, label, open_client

DEFAULT_OUT = ROOT / "Semantic_Model_Metadata.xlsx"


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


# ---------------------------------------------------------------------------
# Enum dari Microsoft.AnalysisServices.Tabular (diverifikasi via reflection)
# ---------------------------------------------------------------------------
DATA_TYPE = {
    1: "automatic",
    2: "string",
    6: "int64",
    8: "double",
    9: "dateTime",
    10: "decimal",
    11: "boolean",
    17: "binary",
    19: "unknown",
    20: "variant",
}
AGGREGATE_FUNCTION = {
    1: "default",
    2: "none",
    3: "sum",
    4: "min",
    5: "max",
    6: "count",
    7: "average",
    8: "distinctCount",
}
COLUMN_TYPE = {1: "data", 2: "calculated", 3: "rowNumber", 4: "calculatedTableColumn"}
MODE_TYPE = {0: "Import", 1: "DirectQuery", 2: "Default", 3: "Push", 4: "Dual", 5: "DirectLake"}
OBJECT_STATE = {
    1: "ready",
    3: "noData",
    4: "calculationNeeded",
    5: "semanticError",
    6: "evaluationError",
    7: "dependencyError",
    8: "incomplete",
    10: "forceCalculationNeeded",
}
CROSS_FILTERING = {1: "oneDirection", 2: "bothDirections", 3: "automatic"}
SECURITY_FILTERING = {1: "oneDirection", 2: "bothDirections", 3: "none"}
CARDINALITY = {0: "none", 1: "one", 2: "many"}
JOIN_ON_DATE = {1: "dateAndTime", 2: "datePartOnly"}
MODEL_PERMISSION = {1: "none", 2: "read", 3: "readRefresh", 4: "refresh", 5: "administrator"}
ROLE_MEMBER_TYPE = {0: "User", 1: "Group", 2: "Unknown"}
METADATA_PERMISSION = {0: "default", 1: "none", 2: "read"}
PARTITION_SOURCE_TYPE = {
    1: "query",
    2: "calculated",
    3: "none",
    4: "m",
    5: "entity",
    6: "policyRange",
    7: "calculationGroup",
    8: "inferred",
    9: "parquet",
}
IMPERSONATION_MODE = {
    1: "default",
    2: "impersonateAccount",
    3: "impersonateAnonymous",
    4: "impersonateCurrentUser",
    5: "impersonateServiceAccount",
    6: "impersonateUnattendedAccount",
}
DATA_SOURCE_TYPE = {1: "provider", 2: "structured"}
POWERBI_DATASOURCE_VERSION = {0: "powerBI_V1", 1: "powerBI_V2", 2: "powerBI_V3"}
VALUE_FILTER_BEHAVIOR = {0: "automatic", 1: "independent", 2: "coalesced"}
DIRECTLAKE_BEHAVIOR = {0: "automatic", 1: "directLakeOnly", 2: "directQueryOnly"}
DATA_VIEW = {0: "full", 1: "sample", 3: "default"}
REFRESH_POLICY_TYPE = {0: "basic"}
REFRESH_POLICY_MODE = {0: "import", 1: "hybrid"}
REFRESH_GRANULARITY = {-1: "invalid", 0: "day", 1: "month", 2: "quarter", 3: "year"}
OBJECT_TYPE = {
    0: "null",
    1: "model",
    2: "dataSource",
    3: "table",
    4: "column",
    5: "attributeHierarchy",
    6: "partition",
    7: "relationship",
    8: "measure",
    9: "hierarchy",
    10: "level",
    11: "annotation",
    12: "kpi",
    13: "culture",
    14: "objectTranslation",
    15: "linguisticMetadata",
    29: "perspective",
    30: "perspectiveTable",
    31: "perspectiveColumn",
    32: "perspectiveHierarchy",
    33: "perspectiveMeasure",
    34: "role",
    35: "roleMembership",
    36: "tablePermission",
    37: "variation",
    38: "set",
    39: "perspectiveSet",
    40: "extendedProperty",
    41: "expression",
    42: "columnPermission",
    43: "detailRowsDefinition",
    44: "relatedColumnDetails",
    45: "groupByColumn",
    46: "calculationGroup",
    47: "calculationItem",
    48: "alternateOf",
    49: "refreshPolicy",
    50: "formatStringDefinition",
    51: "queryGroup",
    52: "analyticsAIMetadata",
    53: "changedProperty",
}

DMVS = [
    "TMSCHEMA_MODEL",
    "TMSCHEMA_TABLES",
    "TMSCHEMA_COLUMNS",
    "TMSCHEMA_MEASURES",
    "TMSCHEMA_PARTITIONS",
    "TMSCHEMA_EXPRESSIONS",
    "TMSCHEMA_RELATIONSHIPS",
    "TMSCHEMA_ROLES",
    "TMSCHEMA_ROLE_MEMBERSHIPS",
    "TMSCHEMA_TABLE_PERMISSIONS",
    "TMSCHEMA_COLUMN_PERMISSIONS",
    "TMSCHEMA_REFRESH_POLICIES",
    "TMSCHEMA_ANNOTATIONS",
    "TMSCHEMA_QUERY_GROUPS",
    "TMSCHEMA_CULTURES",
    "TMSCHEMA_LINGUISTIC_METADATA",
    "TMSCHEMA_OBJECT_TRANSLATIONS",
    "TMSCHEMA_DATA_SOURCES",
    "TMSCHEMA_HIERARCHIES",
    "TMSCHEMA_LEVELS",
    "TMSCHEMA_CALCULATION_GROUPS",
    "TMSCHEMA_CALCULATION_ITEMS",
    "TMSCHEMA_PERSPECTIVES",
    "TMSCHEMA_KPIS",
]

META_RE = re.compile(r"\s+meta\s*\[(?P<meta>.*)\]\s*$", re.S)

CONNECTORS = [
    "Sql.Database",
    "Sql.Databases",
    "AzureSynapseAnalytics.Database",
    "AzureSql.Database",
    "AnalysisServices.Database",
    "AnalysisServices.Databases",
    "OData.Feed",
    "Web.Contents",
    "Web.Page",
    "Excel.Workbook",
    "Excel.CurrentWorkbook",
    "Csv.Document",
    "Json.Document",
    "Xml.Tables",
    "File.Contents",
    "SharePoint.Files",
    "SharePoint.Contents",
    "SharePoint.Tables",
    "Folder.Files",
    "AzureStorage.Blobs",
    "AzureStorage.DataLake",
    "Hdfs.Files",
    "Hadoop.Files",
    "Fabric.Dataflows",
    "Fabric.Datasets",
    "PowerBI.Dataflows",
    "PowerPlatform.Dataflows",
    "PowerPlatform.Datasets",
    "UsageMetricsDataConnector.GetMetricsData",
    "Dataverse.Contents",
    "CommonDataService.Database",
    "Snowflake.Databases",
    "Oracle.Database",
    "PostgreSQL.Database",
    "MySQL.Database",
    "Teradata.Database",
    "GoogleBigQuery.Database",
    "GoogleBigQueryAad.Database",
    "GoogleSheets.Contents",
    "DB2.Database",
    "SapHana.Database",
    "SapBusinessWarehouse.Cubes",
    "Sybase.Database",
    "Informix.Database",
    "Odbc.Query",
    "Odbc.DataSource",
    "Parquet.Document",
    "Pdf.Tables",
    "Pdf.Data",
    "Web.BrowserContents",
    "Html.Table",
    "Html.BrowserContents",
]
CONNECTORS.sort(key=len, reverse=True)


# ---------------------------------------------------------------------------
# Helper umum
# ---------------------------------------------------------------------------
def fmt_dt(value: Any, never_below: int = 1900) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M:%S")
    else:
        try:
            text = value.ToString("yyyy-MM-dd HH:mm:ss")
        except Exception:  # noqa: BLE001
            text = str(value)
    try:
        if int(text[:4]) < never_below:
            return ""
    except (ValueError, TypeError):
        pass
    return text


def decode_filetime(value: Any) -> str:
    """__LastRPTime disimpan sebagai FILETIME (100 ns sejak 1601-01-01)."""
    try:
        ticks = int(value)
    except (TypeError, ValueError):
        return ""
    if ticks <= 0:
        return ""
    try:
        stamp = datetime(1601, 1, 1) + timedelta(microseconds=ticks / 10)
    except (OverflowError, ValueError):
        return ""
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def parse_data_access(text: Any) -> str:
    if not text:
        return ""
    try:
        data = json.loads(str(text))
    except json.JSONDecodeError:
        return str(text)
    return ", ".join(str(key) for key, value in data.items() if value)


def annotations_text(pairs: list[tuple[str, str]]) -> str:
    return "; ".join(f"{key} = {value}" for key, value in pairs)


def parse_meta(meta: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in split_outside_quotes(meta):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = value.strip().strip('"')
    return out


def cell(value: Any) -> Any:
    """Pastikan nilai bisa ditulis openpyxl (hindari tipe .NET)."""
    if value is None:
        return ""
    if isinstance(value, (str, bool, int, float, datetime)):
        return value
    if isinstance(value, (list, tuple, dict, set)):
        return str(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{column: cell(row.get(column, "")) for column in columns} for row in rows],
        columns=columns,
    )


def clean_expr(value: Any) -> str:
    """Rapikan teks DAX/M dari DMV: samakan newline, buang newline di ujung."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n")


def m_arg(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('""', '"')
    return text


def extract_connector(query: str) -> tuple[str, list[str]]:
    """Cari connector M pertama beserta argumennya (tanda kurung seimbang)."""
    if not query:
        return "", []
    for name in CONNECTORS:
        pattern = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"\s*\(")
        match = pattern.search(query)
        if not match:
            continue
        start = match.end()
        depth = 1
        in_quote = False
        index = start
        while index < len(query) and depth > 0:
            char = query[index]
            if char == '"':
                if in_quote and index + 1 < len(query) and query[index + 1] == '"':
                    index += 2
                    continue
                in_quote = not in_quote
            elif not in_quote:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        break
            index += 1
        return name, split_outside_quotes(query[start:index])
    return "", []


def connector_endpoint(connector: str, args: list[str], query: str) -> tuple[str, str]:
    server, database = "", ""
    if connector in {
        "Sql.Database",
        "AzureSynapseAnalytics.Database",
        "AzureSql.Database",
        "AnalysisServices.Database",
        "Oracle.Database",
        "PostgreSQL.Database",
        "MySQL.Database",
        "Snowflake.Databases",
        "Teradata.Database",
        "DB2.Database",
        "SapHana.Database",
        "Sybase.Database",
        "Informix.Database",
    }:
        server = m_arg(args[0]) if args else ""
        database = m_arg(args[1]) if len(args) > 1 else ""
    elif connector in {"Web.Contents", "Web.Page", "OData.Feed"}:
        url = m_arg(args[0]) if args else ""
        parsed = urlparse(url)
        server = parsed.netloc or url
        database = parsed.path
    elif connector == "Excel.Workbook":
        match = re.search(r'File\.Contents\("([^"]+)"\)', query)
        server = match.group(1) if match else (m_arg(args[0]) if args else "")
    elif connector in {"SharePoint.Files", "SharePoint.Contents", "SharePoint.Tables", "Folder.Files"}:
        server = m_arg(args[0]) if args else ""
    elif connector in {"AzureStorage.Blobs", "AzureStorage.DataLake", "Hdfs.Files", "Hadoop.Files"}:
        server = m_arg(args[0]) if args else ""
    else:
        server = m_arg(args[0]) if args else ""
    return server, database


# ---------------------------------------------------------------------------
# Model live
# ---------------------------------------------------------------------------
class LiveModel:
    def __init__(self, client):
        self.client = client
        self.endpoint = client.endpoint
        self.catalog = client.catalog
        self.server_version = client.server_version
        self.catalog_info = client.catalog_info or {}
        self.notes: list[str] = []
        self.raw: dict[str, list[dict[str, Any]]] = {}
        for dmv in DMVS:
            try:
                self.raw[dmv] = client.query(dmv)
            except Exception as exc:  # noqa: BLE001
                self.raw[dmv] = []
                self.notes.append(f"{dmv}: {str(exc).splitlines()[0]}")

        self.model_row: dict[str, Any] = (self.raw["TMSCHEMA_MODEL"] or [{}])[0]
        self.table_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_TABLES"]}
        self.table_name = {key: row["Name"] for key, row in self.table_by_id.items()}

        self.column_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_COLUMNS"]}
        self.column_name: dict[int, tuple[str, str]] = {}
        for key, row in self.column_by_id.items():
            name = row.get("ExplicitName") or row.get("InferredName") or ""
            self.column_name[key] = (self.table_name.get(int(row["TableID"]), ""), str(name))

        self.measure_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_MEASURES"]}
        self.measure_name = {
            key: (self.table_name.get(int(row["TableID"]), ""), row["Name"])
            for key, row in self.measure_by_id.items()
        }

        self.relationship_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_RELATIONSHIPS"]}
        self.role_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_ROLES"]}
        self.expression_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_EXPRESSIONS"]}
        self.partition_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_PARTITIONS"]}
        self.query_group_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_QUERY_GROUPS"]}
        self.hierarchy_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_HIERARCHIES"]}
        self.calc_group_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_CALCULATION_GROUPS"]}
        self.culture_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_CULTURES"]}
        self.data_source_by_id = {int(row["ID"]): row for row in self.raw["TMSCHEMA_DATA_SOURCES"]}
        self.table_permission_by_id = {
            int(row["ID"]): row for row in self.raw["TMSCHEMA_TABLE_PERMISSIONS"]
        }

        self.annotations: dict[tuple[int, int], list[tuple[str, str]]] = defaultdict(list)
        for row in self.raw["TMSCHEMA_ANNOTATIONS"]:
            self.annotations[(int(row["ObjectType"]), int(row["ObjectID"]))].append(
                (str(row["Name"]), str(row["Value"] or ""))
            )

        self.linguistic = {
            int(row["CultureID"]): row for row in self.raw["TMSCHEMA_LINGUISTIC_METADATA"]
        }

    def ann(self, object_type: int, object_id: int) -> str:
        return annotations_text(self.annotations.get((object_type, object_id), []))

    def object_label(self, object_type: int, object_id: int) -> str:
        kind = OBJECT_TYPE.get(object_type, f"objectType_{object_type}")
        if kind == "table":
            return self.table_name.get(object_id, str(object_id))
        if kind == "column":
            table, column = self.column_name.get(object_id, ("", ""))
            return f"{table}[{column}]" if table else column
        if kind == "measure":
            table, measure = self.measure_name.get(object_id, ("", ""))
            return f"{table}[{measure}]" if table else measure
        if kind == "expression":
            row = self.expression_by_id.get(object_id)
            return str(row["Name"]) if row else str(object_id)
        if kind == "role":
            row = self.role_by_id.get(object_id)
            return str(row["Name"]) if row else str(object_id)
        if kind == "partition":
            row = self.partition_by_id.get(object_id)
            if row:
                return f"{self.table_name.get(int(row['TableID']), '')}[{row['Name']}]"
            return str(object_id)
        if kind == "queryGroup":
            row = self.query_group_by_id.get(object_id)
            return str(row["Folder"]) if row else str(object_id)
        if kind == "hierarchy":
            row = self.hierarchy_by_id.get(object_id)
            return str(row["Name"]) if row else str(object_id)
        if kind == "model":
            return str(self.model_row.get("Name") or "Model")
        if kind == "relationship":
            row = self.relationship_by_id.get(object_id)
            return str(row.get("Name") or object_id) if row else str(object_id)
        return str(object_id)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_tables(model: LiveModel) -> list[dict[str, Any]]:
    partitions_by_table: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in model.raw["TMSCHEMA_PARTITIONS"]:
        partitions_by_table[int(row["TableID"])].append(row)

    refresh_by_table = {int(row["TableID"]): row for row in model.raw["TMSCHEMA_REFRESH_POLICIES"]}
    column_counts: dict[int, int] = defaultdict(int)
    for row in model.raw["TMSCHEMA_COLUMNS"]:
        if int(row.get("Type") or 0) == 3:
            continue
        column_counts[int(row["TableID"])] += 1
    measure_counts: dict[int, int] = defaultdict(int)
    for row in model.raw["TMSCHEMA_MEASURES"]:
        measure_counts[int(row["TableID"])] += 1

    rows: list[dict[str, Any]] = []
    for table_id, table in model.table_by_id.items():
        partitions = partitions_by_table.get(table_id, [])
        modes = {label(part.get("Mode"), MODE_TYPE, "mode") for part in partitions if part.get("Mode") is not None}
        query_group = ""
        for part in partitions:
            if part.get("QueryGroupID") is not None:
                group = model.query_group_by_id.get(int(part["QueryGroupID"]))
                query_group = str(group["Folder"]) if group else ""
                break
        rows.append(
            {
                "table": table["Name"],
                "is_hidden": bool(table.get("IsHidden")),
                "storage_mode": ", ".join(sorted(mode for mode in modes if mode)),
                "partition_count": len(partitions),
                "column_count": column_counts.get(table_id, 0),
                "measure_count": measure_counts.get(table_id, 0),
                "query_group": query_group,
                "refresh_policy": "Yes" if table_id in refresh_by_table else "No",
                "is_calculation_group": table.get("CalculationGroupID") is not None,
                "is_calculated_table": any(
                    label(part.get("Type"), PARTITION_SOURCE_TYPE, "sourceType")
                    == "calculated"
                    for part in partitions
                ),
                "lineage_tag": str(table.get("LineageTag") or ""),
                "description": str(table.get("Description") or ""),
                "data_category": str(table.get("DataCategory") or ""),
                "annotations": model.ann(3, table_id),
            }
        )
    return rows


def build_columns(model: LiveModel) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    excluded = 0
    for column_id, column in model.column_by_id.items():
        column_type = int(column.get("Type") or 0)
        if column_type == 3:
            excluded += 1
            continue
        table = model.table_name.get(int(column["TableID"]), "")
        name = str(column.get("ExplicitName") or column.get("InferredName") or "")
        sort_id = column.get("SortByColumnID")
        sort_by = ""
        if sort_id is not None:
            sort_by = model.column_name.get(int(sort_id), ("", ""))[1]
        expression = clean_expr(column.get("Expression"))
        rows.append(
            {
                "table": table,
                "column": name,
                "column_type": label(column_type, COLUMN_TYPE, "columnType"),
                "data_type": label(column.get("ExplicitDataType") or column.get("InferredDataType"), DATA_TYPE, "dataType"),
                "format_string": str(column.get("FormatString") or ""),
                "summarize_by": label(column.get("SummarizeBy"), AGGREGATE_FUNCTION, "summarizeBy"),
                "sort_by_column": sort_by,
                "source_column": str(column.get("SourceColumn") or ""),
                "data_category": str(column.get("DataCategory") or ""),
                "is_key": bool(column.get("IsKey")),
                "is_available_in_mdx": bool(column.get("IsAvailableInMDX")),
                "is_hidden": bool(column.get("IsHidden")),
                "display_folder": str(column.get("DisplayFolder") or ""),
                "description": str(column.get("Description") or ""),
                "is_calculated": column_type == 2,
                "expression": expression,
                "expression_lines": len(expression.splitlines()) if expression else 0,
                "lineage_tag": str(column.get("LineageTag") or ""),
                "annotations": model.ann(4, column_id),
            }
        )

    # ------------------------------------------------------------------
    # Lineage kolom dari query M (bukan dari SourceColumn engine)
    # ------------------------------------------------------------------
    query_by_table: dict[str, str] = {}
    for part in model.raw["TMSCHEMA_PARTITIONS"]:
        table_name = model.table_name.get(int(part["TableID"]), "")
        query = clean_expr(part.get("QueryDefinition"))
        if query and table_name not in query_by_table:
            query_by_table[table_name] = query

    rows_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_table[row["table"]].append(row)

    lineage_warnings: list[Any] = []
    for table_name, table_rows in rows_by_table.items():
        result = build_lineage(query_by_table.get(table_name, ""))
        calculated = {row["column"] for row in table_rows if row["is_calculated"]}
        lineage_warnings.extend(apply_lineage(table_rows, result, calculated))

    return rows, excluded, warnings_rows(lineage_warnings)


def build_measures(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for measure_id, measure in model.measure_by_id.items():
        expression = clean_expr(measure.get("Expression"))
        rows.append(
            {
                "table": model.table_name.get(int(measure["TableID"]), ""),
                "measure": str(measure["Name"]),
                "data_type": label(
                    measure.get("DataType"), DATA_TYPE, "dataType"
                ),
                "expression": expression,
                "expression_lines": len(expression.splitlines()) if expression else 0,
                "format_string": str(measure.get("FormatString") or ""),
                "is_hidden": bool(measure.get("IsHidden")),
                "display_folder": str(measure.get("DisplayFolder") or ""),
                "description": str(measure.get("Description") or ""),
                "error_message": str(measure.get("ErrorMessage") or ""),
                "lineage_tag": str(measure.get("LineageTag") or ""),
                "annotations": model.ann(8, measure_id),
            }
        )
    return rows


def build_partitions(model: LiveModel) -> list[dict[str, Any]]:
    refresh_by_table = {int(row["TableID"]): row for row in model.raw["TMSCHEMA_REFRESH_POLICIES"]}
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_PARTITIONS"]:
        table_id = int(row["TableID"])
        policy = refresh_by_table.get(table_id, {})
        group = model.query_group_by_id.get(int(row["QueryGroupID"])) if row.get("QueryGroupID") is not None else None
        data_source = model.data_source_by_id.get(int(row["DataSourceID"])) if row.get("DataSourceID") is not None else None
        rows.append(
            {
                "table": model.table_name.get(table_id, ""),
                "partition": str(row["Name"]),
                "mode": label(row.get("Mode"), MODE_TYPE, "mode"),
                "query_group": str(group["Folder"]) if group else "",
                "source_type": label(row.get("Type"), PARTITION_SOURCE_TYPE, "sourceType"),
                "source": clean_expr(row.get("QueryDefinition")),
                "refresh_policy_type": label(policy.get("PolicyType"), REFRESH_POLICY_TYPE, "policyType"),
                "refresh_policy_mode": label(policy.get("Mode"), REFRESH_POLICY_MODE, "refreshMode"),
                "rolling_window_granularity": label(
                    policy.get("RollingWindowGranularity"), REFRESH_GRANULARITY, "granularity"
                ),
                "rolling_window_periods": policy.get("RollingWindowPeriods")
                if policy.get("RollingWindowPeriods") is not None
                else "",
                "incremental_granularity": label(
                    policy.get("IncrementalGranularity"), REFRESH_GRANULARITY, "granularity"
                ),
                "incremental_periods": policy.get("IncrementalPeriods")
                if policy.get("IncrementalPeriods") is not None
                else "",
                "incremental_periods_offset": policy.get("IncrementalPeriodsOffset")
                if policy.get("IncrementalPeriodsOffset") is not None
                else "",
                "source_expression": clean_expr(policy.get("SourceExpression")),
                "polling_expression": clean_expr(policy.get("PollingExpression")),
                "state": label(row.get("State"), OBJECT_STATE, "state"),
                "refreshed_time": fmt_dt(row.get("RefreshedTime")),
                "data_source": str(data_source["Name"]) if data_source else "",
                "annotations": model.ann(6, int(row["ID"])),
            }
        )
    return rows


def build_expressions(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for expression_id, row in model.expression_by_id.items():
        raw = clean_expr(row.get("Expression"))
        match = META_RE.search(raw)
        meta = parse_meta(match.group("meta")) if match else {}
        body = raw[: match.start()].strip() if match else raw.strip()
        is_parameter = meta.get("IsParameterQuery", "false").strip().lower() in {"true", "1"}
        value = body
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('""', '"')
        group = model.query_group_by_id.get(int(row["QueryGroupID"])) if row.get("QueryGroupID") is not None else None
        rows.append(
            {
                "name": str(row["Name"]),
                "kind": "Parameter" if is_parameter else "Expression",
                "data_type": meta.get("Type", ""),
                "is_required": meta.get("IsParameterQueryRequired", "false").strip().lower() in {"true", "1"},
                "query_group": str(group["Folder"]) if group else "",
                "value": value,
                "expression": body,
                "annotations": model.ann(41, expression_id),
                "lineage_tag": str(row.get("LineageTag") or ""),
            }
        )
    return rows


def relationship_is_auto(name: str) -> bool:
    """Relasi buatan Power BI biasanya bernama ``AutoDetected_<guid>`` atau GUID."""
    value = str(name or "").strip()
    if not value:
        return False
    if value.casefold().startswith("autodetected_"):
        return True
    return bool(
        re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            value,
            re.IGNORECASE,
        )
    )


def build_relationships(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_RELATIONSHIPS"]:
        from_table, from_column = model.column_name.get(int(row["FromColumnID"]), ("", ""))
        to_table, to_column = model.column_name.get(int(row["ToColumnID"]), ("", ""))
        if not from_table:
            from_table = model.table_name.get(int(row["FromTableID"]), "")
        if not to_table:
            to_table = model.table_name.get(int(row["ToTableID"]), "")
        name = str(row.get("Name") or f"{from_table}[{from_column}] -> {to_table}[{to_column}]")
        rows.append(
            {
                "name": name,
                "is_auto": relationship_is_auto(name),
                "from_table": from_table,
                "from_column": from_column,
                "to_table": to_table,
                "to_column": to_column,
                "cross_filtering": label(row.get("CrossFilteringBehavior"), CROSS_FILTERING, "crossFiltering"),
                "security_filtering": label(
                    row.get("SecurityFilteringBehavior"), SECURITY_FILTERING, "securityFiltering"
                ),
                "is_active": bool(row.get("IsActive")),
                "join_on_date_behavior": label(row.get("JoinOnDateBehavior"), JOIN_ON_DATE, "joinOnDate"),
                "from_cardinality": label(row.get("FromCardinality"), CARDINALITY, "cardinality"),
                "to_cardinality": label(row.get("ToCardinality"), CARDINALITY, "cardinality"),
                "lineage_tag": "",
            }
        )
    return rows


def read_model_metadata(model: LiveModel) -> dict[str, list[dict[str, Any]]]:
    """Metadata model untuk analisa dan halaman Partisi (tanpa koneksi baru).

    Semua bagian memakai helper ``build_*`` yang sudah membaca TMSCHEMA, jadi
    pemanggil tidak perlu membuka XMLA dua kali. Hasilnya berupa list of dict
    siap diserialisasi ke JSON/SQLite.
    """
    return {
        "tables": build_tables(model),
        "relationships": build_relationships(model),
        "partitions": build_partitions(model),
        "expressions": build_expressions(model),
        "roles": build_role_details(model),
    }


def build_roles(model: LiveModel) -> tuple[list[dict[str, Any]], int]:
    permissions_by_role: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in model.raw["TMSCHEMA_TABLE_PERMISSIONS"]:
        permissions_by_role[int(row["RoleID"])].append(row)

    column_permissions = model.raw["TMSCHEMA_COLUMN_PERMISSIONS"]
    ols_permissions = {int(row["TablePermissionID"]) for row in column_permissions}

    rows: list[dict[str, Any]] = []
    for role_id, role in model.role_by_id.items():
        permissions = permissions_by_role.get(role_id, [])
        if not permissions:
            rows.append(
                {
                    "role": str(role["Name"]),
                    "model_permission": label(role.get("ModelPermission"), MODEL_PERMISSION, "permission"),
                    "table": "",
                    "table_permission_expression": "",
                    "has_ols": False,
                    "note": "Tidak ada tablePermission",
                }
            )
            continue
        for permission in permissions:
            rows.append(
                {
                    "role": str(role["Name"]),
                    "model_permission": label(role.get("ModelPermission"), MODEL_PERMISSION, "permission"),
                    "table": model.table_name.get(int(permission["TableID"]), ""),
                    "table_permission_expression": str(permission.get("FilterExpression") or ""),
                    "has_ols": int(permission["ID"]) in ols_permissions,
                    "note": "",
                }
            )
    return rows, len(column_permissions)


def build_role_details(model: LiveModel) -> list[dict[str, Any]]:
    """Role lengkap dengan member dan table permission (RLS/OLS).

    Dipakai tab Roles di halaman Analisa dan halaman Compare (read-only).
    ``TMSCHEMA_ROLE_MEMBERSHIPS`` tidak tersedia di semua engine lama; bagian
    member dibiarkan kosong tanpa mengarang data.
    """
    members_by_role: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in model.raw.get("TMSCHEMA_ROLE_MEMBERSHIPS", []):
        role_id = int(row.get("RoleID") or 0)
        members_by_role[role_id].append(
            {
                "name": str(
                    row.get("MemberName") or row.get("Name") or ""
                ),
                "member_id": str(row.get("MemberID") or ""),
                "member_type": label(
                    row.get("MemberType"), ROLE_MEMBER_TYPE, "memberType"
                ),
                "member_type_id": row.get("MemberType"),
                "provider": str(
                    row.get("IdentityProvider") or row.get("Provider") or ""
                ),
                "modified": fmt_dt(row.get("ModifiedTime")),
            }
        )

    permissions_by_role: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in model.raw.get("TMSCHEMA_TABLE_PERMISSIONS", []):
        permissions_by_role[int(row["RoleID"])].append(row)
    column_permissions = model.raw.get("TMSCHEMA_COLUMN_PERMISSIONS", [])
    ols_permissions = {int(row["TablePermissionID"]) for row in column_permissions}

    rows: list[dict[str, Any]] = []
    for role_id, role in model.role_by_id.items():
        permissions = [
            {
                "table": model.table_name.get(int(permission["TableID"]), ""),
                "expression": str(permission.get("FilterExpression") or ""),
                "has_ols": int(permission["ID"]) in ols_permissions,
            }
            for permission in permissions_by_role.get(role_id, [])
        ]
        members = sorted(
            members_by_role.get(role_id, []),
            key=lambda item: (item["name"].casefold(), item["member_id"]),
        )
        rows.append(
            {
                "id": role_id,
                "name": str(role["Name"]),
                "model_permission": label(
                    role.get("ModelPermission"), MODEL_PERMISSION, "permission"
                ),
                "description": str(role.get("Description") or ""),
                "modified": fmt_dt(role.get("ModifiedTime")),
                "members": members,
                "permissions": permissions,
            }
        )
    rows.sort(key=lambda item: item["name"].casefold())
    return rows


def query_order(model: LiveModel) -> list[str]:
    """Urutan objek di pane Power Query (annotation model PBI_QueryOrder)."""
    model_id = int(model.model_row.get("ID") or 1)
    for name, value in model.annotations.get((1, model_id), []):
        if name != "PBI_QueryOrder":
            continue
        try:
            order = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in order]
    return []


def build_query_groups(model: LiveModel) -> list[dict[str, Any]]:
    order_by_group: dict[int, str] = {}
    for row in model.raw["TMSCHEMA_ANNOTATIONS"]:
        if int(row["ObjectType"]) == 51 and str(row["Name"]) == "PBI_QueryGroupOrder":
            order_by_group[int(row["ObjectID"])] = str(row["Value"] or "")

    pq_order = query_order(model)
    rank = {name: index for index, name in enumerate(pq_order)}

    members: dict[int, list[tuple[int, str, str]]] = defaultdict(list)
    seen_tables: set[tuple[int, str]] = set()
    for partition in model.raw["TMSCHEMA_PARTITIONS"]:
        if partition.get("QueryGroupID") is None:
            continue
        group_id = int(partition["QueryGroupID"])
        table = model.table_name.get(int(partition["TableID"]), "")
        key = (group_id, table)
        if key not in seen_tables:
            seen_tables.add(key)
            members[group_id].append((rank.get(table, 10**6), "table", table))
    for expression in model.raw["TMSCHEMA_EXPRESSIONS"]:
        if expression.get("QueryGroupID") is None:
            continue
        name = str(expression["Name"])
        members[int(expression["QueryGroupID"])].append((rank.get(name, 10**6), "expression", name))

    rows: list[dict[str, Any]] = []
    for group_id, group in model.query_group_by_id.items():
        ordered = sorted(members.get(group_id, []), key=lambda item: (item[0], item[2].lower()))
        rows.append(
            {
                "query_group": str(group["Folder"]),
                "order": order_by_group.get(group_id, ""),
                "members": " | ".join(f"{kind}: {name}" for _, kind, name in ordered),
            }
        )
    return rows


def build_cultures(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for culture_id, culture in model.culture_by_id.items():
        linguistic = model.linguistic.get(culture_id)
        if not linguistic:
            continue
        try:
            data = json.loads(str(linguistic.get("Content") or "{}"))
        except json.JSONDecodeError:
            continue
        for entity, content in (data.get("Entities") or {}).items():
            terms = content.get("Terms") or []
            names: list[str] = []
            for term in terms:
                for key in term:
                    if key not in {"State", "Weight", "ID"}:
                        names.append(key)
            rows.append(
                {
                    "culture": str(culture["Name"]),
                    "language": data.get("Language", ""),
                    "version": data.get("Version", ""),
                    "entity": entity,
                    "term_count": len(terms),
                    "sample_terms": ", ".join(names[:8]),
                    "state": content.get("State", ""),
                }
            )
    return rows


def build_data_sources(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_DATA_SOURCES"]:
        rows.append(
            {
                "source_kind": "model data source",
                "name": str(row.get("Name") or ""),
                "connector": label(row.get("Type"), DATA_SOURCE_TYPE, "dataSourceType"),
                "server": "",
                "database": "",
                "table": "",
                "partition": "",
                "mode": "",
                "query_group": "",
                "impersonation": label(row.get("ImpersonationMode"), IMPERSONATION_MODE, "impersonation"),
                "connection_string": str(row.get("ConnectionString") or ""),
                "note": str(row.get("Description") or ""),
            }
        )

    for row in model.raw["TMSCHEMA_PARTITIONS"]:
        query = clean_expr(row.get("QueryDefinition"))
        connector, args = extract_connector(query)
        server, database = connector_endpoint(connector, args, query)
        group = model.query_group_by_id.get(int(row["QueryGroupID"])) if row.get("QueryGroupID") is not None else None
        note = ""

        workspace = re.search(r'workspaceId\s*=\s*"([^"]+)"', query)
        dataflow = re.search(r'dataflowId\s*=\s*"([^"]+)"', query)
        entity = re.search(r'entity\s*=\s*"([^"]+)"', query)
        if connector in {"PowerPlatform.Dataflows", "Fabric.Dataflows"}:
            server = workspace.group(1) if workspace else ""
            database = dataflow.group(1) if dataflow else ""
            note = "Dataflow" + (f" entity={entity.group(1)}" if entity else "")
        elif "Table.FromRows(" in query or "Binary.FromText(" in query:
            connector = "(inline table)"
            server, database = "", ""
            note = "Tabel inline di M (Binary.FromText) - tidak ada sumber eksternal"
        elif not connector and query:
            note = "Connector tidak dikenali (query inline / custom)"
        else:
            literal = [arg for arg in args if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"']
            if args and len(literal) != len(args):
                dynamic = [arg for arg in args if arg not in literal]
                note = "Argumen memakai parameter/ekspresi: " + ", ".join(dynamic)[:200]
                if not (args and args[0] in literal):
                    server, database = "", ""
        rows.append(
            {
                "source_kind": "partition query",
                "name": "",
                "connector": connector or ("(inline)" if query else ""),
                "server": server,
                "database": database,
                "table": model.table_name.get(int(row["TableID"]), ""),
                "partition": str(row["Name"]),
                "mode": label(row.get("Mode"), MODE_TYPE, "mode"),
                "query_group": str(group["Folder"]) if group else "",
                "impersonation": "",
                "connection_string": "",
                "note": note,
            }
        )
    return rows


def build_partition_state(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_PARTITIONS"]:
        group = model.query_group_by_id.get(int(row["QueryGroupID"])) if row.get("QueryGroupID") is not None else None
        data_source = model.data_source_by_id.get(int(row["DataSourceID"])) if row.get("DataSourceID") is not None else None
        rows.append(
            {
                "table": model.table_name.get(int(row["TableID"]), ""),
                "partition": str(row["Name"]),
                "mode": label(row.get("Mode"), MODE_TYPE, "mode"),
                "state": label(row.get("State"), OBJECT_STATE, "state"),
                "refreshed_time": fmt_dt(row.get("RefreshedTime")),
                "modified_time": fmt_dt(row.get("ModifiedTime")),
                "range_start": fmt_dt(row.get("RangeStart")),
                "range_end": fmt_dt(row.get("RangeEnd")),
                "range_granularity": label(row.get("RangeGranularity"), REFRESH_GRANULARITY, "granularity"),
                "query_group": str(group["Folder"]) if group else "",
                "data_source": str(data_source["Name"]) if data_source else "",
                "query_definition_length": len(clean_expr(row.get("QueryDefinition"))),
                "error_message": str(row.get("ErrorMessage") or ""),
            }
        )
    return rows


def build_translations(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_OBJECT_TRANSLATIONS"]:
        culture = model.culture_by_id.get(int(row["CultureID"]))
        object_type = int(row["ObjectType"])
        rows.append(
            {
                "culture": str(culture["Name"]) if culture else str(row["CultureID"]),
                "object_type": OBJECT_TYPE.get(object_type, f"objectType_{object_type}"),
                "object_name": model.object_label(object_type, int(row["ObjectID"])),
                "property": str(row.get("Property") or ""),
                "value": str(row.get("Value") or ""),
                "altered": bool(row.get("Altered")),
            }
        )
    return rows


def build_hierarchies(model: LiveModel) -> list[dict[str, Any]]:
    levels_by_hierarchy: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in model.raw["TMSCHEMA_LEVELS"]:
        levels_by_hierarchy[int(row["HierarchyID"])].append(row)

    rows: list[dict[str, Any]] = []
    for hierarchy_id, hierarchy in model.hierarchy_by_id.items():
        levels = sorted(
            levels_by_hierarchy.get(hierarchy_id, []),
            key=lambda item: int(item.get("Ordinal") or 0),
        )
        level_text = " > ".join(
            f"{level['Name']} ({model.column_name.get(int(level['ColumnID']), ('', ''))[1]})"
            for level in levels
        )
        rows.append(
            {
                "table": model.table_name.get(int(hierarchy["TableID"]), ""),
                "hierarchy": str(hierarchy["Name"]),
                "is_hidden": bool(hierarchy.get("IsHidden")),
                "display_folder": str(hierarchy.get("DisplayFolder") or ""),
                "description": str(hierarchy.get("Description") or ""),
                "level_count": len(levels),
                "levels": level_text,
                "lineage_tag": str(hierarchy.get("LineageTag") or ""),
            }
        )
    return rows


def build_calculation_groups(model: LiveModel) -> list[dict[str, Any]]:
    items_by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in model.raw["TMSCHEMA_CALCULATION_ITEMS"]:
        items_by_group[int(row["CalculationGroupID"])].append(row)

    rows: list[dict[str, Any]] = []
    for group_id, group in model.calc_group_by_id.items():
        items = sorted(items_by_group.get(group_id, []), key=lambda item: int(item.get("Ordinal") or 0))
        item_text = " | ".join(
            f"{item['Name']}: {str(item.get('Expression') or '').strip()}" for item in items
        )
        rows.append(
            {
                "table": model.table_name.get(int(group["TableID"]), ""),
                "calculation_group": model.table_name.get(int(group["TableID"]), ""),
                "precedence": group.get("Precedence") or "",
                "item_count": len(items),
                "items": item_text,
                "description": str(group.get("Description") or ""),
            }
        )
    return rows


def build_perspectives(model: LiveModel) -> list[dict[str, Any]]:
    return [
        {
            "perspective": str(row["Name"]),
            "description": str(row.get("Description") or ""),
            "modified_time": fmt_dt(row.get("ModifiedTime")),
        }
        for row in model.raw["TMSCHEMA_PERSPECTIVES"]
    ]


def build_kpis(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_KPIS"]:
        table, measure = model.measure_name.get(int(row["MeasureID"]), ("", ""))
        rows.append(
            {
                "table": table,
                "measure": measure,
                "target_description": str(row.get("TargetDescription") or ""),
                "target_expression": str(row.get("TargetExpression") or ""),
                "target_format_string": str(row.get("TargetFormatString") or ""),
                "status_description": str(row.get("StatusDescription") or ""),
                "status_expression": str(row.get("StatusExpression") or ""),
                "status_graphic": str(row.get("StatusGraphic") or ""),
                "trend_description": str(row.get("TrendDescription") or ""),
                "trend_expression": str(row.get("TrendExpression") or ""),
                "trend_graphic": str(row.get("TrendGraphic") or ""),
            }
        )
    return rows


def build_ols(model: LiveModel) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in model.raw["TMSCHEMA_COLUMN_PERMISSIONS"]:
        permission = model.table_permission_by_id.get(int(row["TablePermissionID"]))
        role = model.role_by_id.get(int(permission["RoleID"])) if permission else None
        table = model.table_name.get(int(permission["TableID"]), "") if permission else ""
        column = model.column_name.get(int(row["ColumnID"]), ("", ""))[1]
        rows.append(
            {
                "role": str(role["Name"]) if role else "",
                "table": table,
                "column": column,
                "metadata_permission": label(row.get("MetadataPermission"), METADATA_PERMISSION, "permission"),
                "table_permission_expression": str(permission.get("FilterExpression") or "") if permission else "",
            }
        )
    return rows


def build_unsupported(model: LiveModel, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calculated_columns = sum(1 for column in columns if column["is_calculated"])
    calculated_tables = sum(
        1
        for row in model.raw["TMSCHEMA_PARTITIONS"]
        if int(row.get("Type") or 0) in {2, 7}
    )
    detail_rows = sum(
        1
        for row in model.raw["TMSCHEMA_TABLES"]
        if row.get("DefaultDetailRowsDefinitionID") is not None
    ) + sum(
        1
        for row in model.raw["TMSCHEMA_MEASURES"]
        if row.get("DetailRowsDefinitionID") is not None
    )
    items = [
        ("Calculation group", len(model.raw["TMSCHEMA_CALCULATION_GROUPS"]), "Tabel calculation group."),
        (
            "User-defined function (DAX UDF)",
            None,
            "DMV TMSCHEMA_FUNCTIONS tidak tersedia di engine ini; tidak bisa dihitung via XMLA.",
        ),
        ("Hierarchy", len(model.raw["TMSCHEMA_HIERARCHIES"]), "Hierarchy eksplisit di tabel."),
        ("Perspective", len(model.raw["TMSCHEMA_PERSPECTIVES"]), "Perspective untuk expose subset objek."),
        (
            "OLS column permission",
            len(model.raw["TMSCHEMA_COLUMN_PERMISSIONS"]),
            "Object level security per kolom di role.",
        ),
        ("KPI", len(model.raw["TMSCHEMA_KPIS"]), "Definisi KPI pada measure."),
        ("Calculated column", calculated_columns, "Kolom kalkulasi DAX (Column.Type = calculated)."),
        ("Calculated table", calculated_tables, "Partisi bertipe calculated / calculationGroup."),
        ("Detail rows definition", detail_rows, "Definisi drill-through detail rows."),
    ]
    rows: list[dict[str, Any]] = []
    for name, count, note in items:
        if count is None:
            status = "Not supported by engine"
            count_text = ""
        else:
            status = "Present" if count else "Not present"
            count_text = count
        rows.append({"object_class": name, "count": count_text, "status": status, "note": note})
    return rows


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def resolve_report_pbix(report: Path | None, no_report: bool) -> Path | None:
    """Validasi file .pbix sumber usage. None bila report dilewati."""
    if no_report:
        return None
    if report is None:
        raise ExtractionError(
            "File .pbix wajib ditentukan (--report) atau lewati dengan --no-report."
        )
    pbix = report.resolve()
    if not pbix.exists():
        raise ExtractionError(
            f"File .pbix tidak ditemukan: {display_path(pbix)}. Pilih file .pbix sumber."
        )
    if pbix.is_dir() or pbix.suffix.lower() != ".pbix":
        raise ExtractionError(
            f"Sumber report harus file .pbix, bukan folder: {pbix}. "
            "Dukungan folder PBIR sudah dihapus."
        )
    return pbix


def _resolve_report_usage(
    report_definition: Path | None,
    pbix: Path | None,
    no_report: bool,
    report_label: str = "",
) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    str,
    bool,
]:
    """Sumber pemakaian report: folder definition PBIR, file .pbix, atau dilewati."""
    if no_report:
        return {}, {}, "Tidak tersedia (--no-report).", False
    if report_definition is not None:
        report_def = Path(report_definition)
        if not (report_def / "pages" / "pages.json").exists() or not (
            report_def / "report.json"
        ).exists():
            raise ExtractionError(
                f"Folder report definition tidak lengkap: {display_path(report_def)}. "
                "Dibutuhkan pages/pages.json dan report.json."
            )
        measures, columns = scan_report_usage(report_def)
        label = report_label or f"definition {display_path(report_def)}"
        return measures, columns, label, True
    if pbix is not None:
        with tempfile.TemporaryDirectory(prefix="model_report_") as temporary:
            report_def = extract_pbix_definition(pbix, Path(temporary))
            measures, columns = scan_report_usage(report_def)
        return (
            measures,
            columns,
            f"pbix {display_path(pbix)} (Report/definition)",
            True,
        )
    return {}, {}, "Tidak tersedia (report tidak dipilih).", False


def run_model(
    endpoint: str | None = None,
    catalog: str | None = None,
    port: int | None = None,
    report: Path | None = None,
    no_report: bool = False,
    report_definition: Path | None = None,
    report_label: str = "",
    out_file: Path | None = None,
    tokens: Any | None = None,
    interactive: bool | None = None,
    log: Callable[[str], None] = _silent,
) -> dict[str, Any]:
    """Ekstrak metadata model via XMLA; usage opsional dari .pbix atau folder PBIR.

    ``report_definition`` dipakai untuk sumber report Power BI Service yang sudah
    diekstrak ke folder PBIR (tanpa file .pbix). ``no_report`` selalu menang.
    ``tokens`` (:class:`core.auth.EntraTokens`) dipakai untuk endpoint XMLA
    Power BI; instance Desktop lokal mengabaikannya.
    """
    out_file = out_file or DEFAULT_OUT
    if no_report or report_definition is not None:
        pbix = None
    else:
        pbix = resolve_report_pbix(report, False)

    report_measures, report_columns, report_source, report_available = (
        _resolve_report_usage(report_definition, pbix, no_report, report_label)
    )

    try:
        client = open_client(
            endpoint=endpoint,
            catalog=catalog,
            port=port,
            tokens=tokens,
            interactive=(
                bool(getattr(getattr(tokens, "principal", None), "interactive_xmla", False))
                if interactive is None
                else interactive
            ),
        )
    except XmlaError as exc:
        raise ExtractionError(str(exc)) from exc

    try:
        model = LiveModel(client)
        endpoint, catalog = model.endpoint, model.catalog
        server_version = model.server_version
        catalog_info = dict(model.catalog_info)
        notes = list(model.notes)

        tables = build_tables(model)
        columns, internal_columns, lineage_warning_rows = build_columns(model)
        measures = build_measures(model)
        partitions = build_partitions(model)
        expressions = build_expressions(model)
        relationships = build_relationships(model)
        roles, ols_count = build_roles(model)
        query_groups = build_query_groups(model)
        cultures = build_cultures(model)
        data_sources = build_data_sources(model)
        partition_state = build_partition_state(model)
        translations = build_translations(model)
        hierarchies = build_hierarchies(model)
        calculation_groups = build_calculation_groups(model)
        perspectives = build_perspectives(model)
        kpis = build_kpis(model)
        ols = build_ols(model)
        unsupported = build_unsupported(model, columns)
        model_row = dict(model.model_row)
    finally:
        client.close()

    dependencies = build_dependencies(measures, columns, tables)

    for measure in measures:
        usage = report_measures.get(measure["measure"])
        measure["report_usage_count"] = len(usage["visuals"]) if usage else 0
        measure["report_pages"] = fmt_pages(usage["pages"]) if usage else ""
    for column in columns:
        usage = report_columns.get((column["table"], column["column"]))
        column["report_usage_count"] = len(usage["visuals"]) if usage else 0
        column["report_pages"] = fmt_pages(usage["pages"]) if usage else ""
        column["report_aggregations"] = (
            ", ".join(sorted(usage.get("aggregations") or ())) if usage else ""
        )

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    model_annotations = model.annotations.get((1, int(model_row.get("ID") or 1)), [])
    last_refresh = next((value for key, value in model_annotations if key == "__LastRPTime"), "")

    overview_rows: list[tuple[str, Any]] = [
        ("Extraction source", "XMLA (ADOMD) - live dari engine"),
        ("Endpoint", endpoint),
        ("Catalog", catalog),
        ("Server version", server_version),
        ("Compatibility level", catalog_info.get("compatibility_level", "")),
        ("Catalog version", catalog_info.get("version", "")),
        ("Catalog last modified", fmt_dt(catalog_info.get("date_modified"))),
        ("Model name", model_row.get("Name", "")),
        ("Model description", model_row.get("Description", "") or ""),
        ("Culture", model_row.get("Culture", "")),
        ("Collation", model_row.get("Collation", "") or ""),
        ("Storage location", model_row.get("StorageLocation", "") or ""),
        ("Default mode", label(model_row.get("DefaultMode"), MODE_TYPE, "mode")),
        ("Default data view", label(model_row.get("DefaultDataView"), DATA_VIEW, "dataView")),
        ("Model version", model_row.get("Version", "")),
        ("Default Power BI data source version", label(
            model_row.get("DefaultPowerBIDataSourceVersion"), POWERBI_DATASOURCE_VERSION, "version"
        )),
        ("Source query culture", model_row.get("SourceQueryCulture", "")),
        ("Value filter behavior", label(model_row.get("ValueFilterBehavior"), VALUE_FILTER_BEHAVIOR, "behavior")),
        ("Discourage implicit measures", bool(model_row.get("DiscourageImplicitMeasures"))),
        ("Data access options", parse_data_access(model_row.get("DataAccessOptions"))),
        ("Max parallelism per refresh", model_row.get("MaxParallelismPerRefresh", "")),
        ("Max parallelism per query", model_row.get("MaxParallelismPerQuery", "")),
        ("DirectLake behavior", label(model_row.get("DirectLakeBehavior"), DIRECTLAKE_BEHAVIOR, "behavior")),
        ("Tables", len(tables)),
        ("Hidden tables", sum(1 for table in tables if table["is_hidden"])),
        ("Columns (model)", len(columns)),
        ("Internal columns excluded", internal_columns),
        ("Calculated columns", sum(1 for column in columns if column["is_calculated"])),
        ("Hidden columns", sum(1 for column in columns if column["is_hidden"])),
        ("Measures", len(measures)),
        ("Hidden measures", sum(1 for measure in measures if measure["is_hidden"])),
        ("Partitions", len(partitions)),
        ("Expressions / parameters", len(expressions)),
        ("Relationships", len(relationships)),
        ("Roles (RLS)", len({role["role"] for role in roles})),
        ("Table permissions", sum(1 for role in roles if role["table"])),
        ("OLS column permissions", ols_count),
        ("Query groups", len(query_groups)),
        ("Cultures", len({culture["culture"] for culture in cultures})),
        ("Model annotations", len(model_annotations)),
        ("Object annotations", len(model.raw["TMSCHEMA_ANNOTATIONS"])),
        ("Hierarchies", len(hierarchies)),
        ("Calculation groups", len(calculation_groups)),
        ("Perspectives", len(perspectives)),
        ("KPIs", len(kpis)),
        ("Data sources (declared)", len(model.raw["TMSCHEMA_DATA_SOURCES"])),
        ("Incremental refresh tables", sum(1 for table in tables if table["refresh_policy"] == "Yes")),
        ("DirectQuery tables", sum(1 for table in tables if "DirectQuery" in table["storage_mode"])),
        ("Last refresh (__LastRPTime, decoded)", decode_filetime(last_refresh)),
        ("Extracted at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    overview_rows += [(f"annotation {key}", value) for key, value in model_annotations]
    overview_rows += [(f"note: {note}", "") for note in notes]
    overview_df = frame([{"property": key, "value": value} for key, value in overview_rows], ["property", "value"])

    # ------------------------------------------------------------------
    # Model vs report
    # ------------------------------------------------------------------
    cross_rows: list[dict[str, Any]] = []
    for measure in measures:
        cross_rows.append(
            {
                "object_type": "Measure",
                "table": measure["table"],
                "object": measure["measure"],
                "direct_visual_usage": measure["report_usage_count"],
                "report_pages": measure["report_pages"],
                "note": ""
                if measure["report_usage_count"]
                else ("Tidak dipakai langsung oleh visual" if report_available else "Report tidak tersedia"),
            }
        )
    for column in columns:
        aggregations = column.get("report_aggregations") or ""
        if column["report_usage_count"]:
            note = f"Dipakai visual lewat agregasi: {aggregations}" if aggregations else ""
        else:
            note = "Tidak dipakai langsung oleh visual" if report_available else "Report tidak tersedia"
        cross_rows.append(
            {
                "object_type": "Column",
                "table": column["table"],
                "object": column["column"],
                "direct_visual_usage": column["report_usage_count"],
                "report_pages": column["report_pages"],
                "note": note,
            }
        )
    model_measure_names = {measure["measure"] for measure in measures}
    model_columns = {(column["table"], column["column"]) for column in columns}
    for name, usage in report_measures.items():
        if name not in model_measure_names:
            cross_rows.append(
                {
                    "object_type": "Measure",
                    "table": "",
                    "object": name,
                    "direct_visual_usage": len(usage["visuals"]),
                    "report_pages": fmt_pages(usage["pages"]),
                    "note": "Dipakai report tapi TIDAK ADA di model",
                }
            )
    for (table, name), usage in report_columns.items():
        if (table, name) not in model_columns:
            cross_rows.append(
                {
                    "object_type": "Column",
                    "table": table,
                    "object": name,
                    "direct_visual_usage": len(usage["visuals"]),
                    "report_pages": fmt_pages(usage["pages"]),
                    "note": "Dipakai report tapi TIDAK ADA di model",
                }
            )

    # ------------------------------------------------------------------
    # Lineage & annotations
    # ------------------------------------------------------------------
    lineage_rows: list[dict[str, Any]] = []
    for key, value in model_annotations:
        lineage_rows.append(
            {
                "scope": "Model",
                "object_type": "Model",
                "object_name": str(model_row.get("Name") or ""),
                "lineage_tag": "",
                "annotation_key": key,
                "annotation_value": value,
            }
        )
    for table in tables:
        lineage_rows.append(
            {
                "scope": "Model",
                "object_type": "Table",
                "object_name": table["table"],
                "lineage_tag": table["lineage_tag"],
                "annotation_key": "",
                "annotation_value": table["annotations"],
            }
        )
    for column in columns:
        lineage_rows.append(
            {
                "scope": "Model",
                "object_type": "Column",
                "object_name": f"{column['table']}.{column['column']}",
                "lineage_tag": column["lineage_tag"],
                "annotation_key": "",
                "annotation_value": column["annotations"],
            }
        )
    for measure in measures:
        lineage_rows.append(
            {
                "scope": "Model",
                "object_type": "Measure",
                "object_name": f"{measure['table']}.{measure['measure']}",
                "lineage_tag": measure["lineage_tag"],
                "annotation_key": "",
                "annotation_value": measure["annotations"],
            }
        )
    for expression in expressions:
        lineage_rows.append(
            {
                "scope": "Model",
                "object_type": "Expression",
                "object_name": expression["name"],
                "lineage_tag": expression["lineage_tag"],
                "annotation_key": "",
                "annotation_value": expression["annotations"],
            }
        )
    for relationship in relationships:
        lineage_rows.append(
            {
                "scope": "Model",
                "object_type": "Relationship",
                "object_name": relationship["name"],
                "lineage_tag": "",
                "annotation_key": "",
                "annotation_value": "",
            }
        )

    # ------------------------------------------------------------------
    # README
    # ------------------------------------------------------------------
    readme_rows = [
        ("Tujuan", "Dokumentasi metadata semantic model via XMLA (ADOMD) beserta pemakaian objek di report."),
        ("Sumber model", f"XMLA live - endpoint {endpoint}, catalog {catalog}."),
        ("Sumber report", report_source),
        ("01_Model_Overview", "Properti model, compatibility level, jumlah objek, dan annotation."),
        ("02_Tables", "Daftar tabel: storage mode, partisi/kolom/measure, query group, refresh policy."),
        (
            "03_Columns",
            "Metadata kolom: tipe, format, summarizeBy, sortByColumn, hidden, DAX kolom kalkulasi, "
            "dan lineage kolom asli hasil parsing query M (engine_source_column = SourceColumn dari engine).",
        ),
        ("04_Measures", "Measure + DAX lengkap (multi-baris) + jumlah pemakaian langsung di report."),
        ("05_Partitions", "Partisi: mode, query group, query M lengkap, refresh policy (rolling/incremental, polling), state."),
        ("06_Expressions_Params", "Power Query expression & parameter."),
        ("07_Relationships", "Relasi antar tabel: kolom, cross/security filter, kardinalitas, status aktif."),
        ("08_Roles_RLS", "Role dan ekspresi table permission (row level security)."),
        ("09_Query_Groups", "Query group beserta urutan dan anggotanya."),
        ("10_Cultures", "Culture dan ringkasan linguistic metadata (sinonim Q&A otomatis)."),
        ("11_DAX_Dependencies", "Referensi antar measure/kolom hasil parsing DAX, dengan depth."),
        ("12_Model_vs_Report", "Silang objek model vs pemakaian langsung di report."),
        ("13_Lineage_Annotations", "lineageTag dan annotation objek model."),
        ("14_Unsupported_Objects", "Objek lanjutan yang diperiksa keberadaannya."),
        ("15_Data_Sources", "Sumber data: data source model + connector dari query M (termasuk workspaceId/dataflowId dan tabel inline)."),
        ("16_Partition_State", "State partisi live: ready/error, refreshed time, range incremental."),
        ("17_Translations", "Terjemahan caption/description per culture (object translations)."),
        ("18_Hierarchies", "Hierarchy eksplisit beserta level dan kolomnya."),
        ("19_Calculation_Groups", "Calculation group beserta item dan ekspresinya."),
        ("20_Perspectives", "Perspective yang didefinisikan di model."),
        ("21_KPIs", "KPI pada measure: target, status, trend."),
        ("22_OLS", "Object level security per kolom."),
        (
            "23_M_Lineage_Warnings",
            "Peringatan lineage M: rename dinamis, rename kolom yang tidak ada, konflik nama, "
            "atau kolom yang tidak bisa dipastikan asalnya.",
        ),
        ("Catatan DAX/M", "Teks DAX & M disimpan utuh dalam satu sel. Lihat lewat formula bar."),
        ("Catatan usage", "direct_visual_usage = jumlah visual yang memakai objek langsung, bukan pemakaian di measure lain."),
        ("Catatan enum", "Nilai enum diterjemahkan memakai enum resmi Microsoft.AnalysisServices.Tabular."),
        (
            "Catatan kolom internal",
            "Kolom internal engine (RowNumber-*, Type=rowNumber) tidak dihitung sebagai kolom model; jumlahnya ada di 01_Model_Overview.",
        ),
        ("Batasan XMLA", "Butuh endpoint hidup. Member RLS, riwayat refresh lengkap, sensitivity label, dan detail gateway hanya ada di service."),
        ("Dibuat", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]

    # ------------------------------------------------------------------
    # Sheets
    # ------------------------------------------------------------------
    sheets: list[tuple[str, pd.DataFrame, dict[str, int] | None]] = [
        (
            "00_README",
            frame([{"Bagian": key, "Penjelasan": value} for key, value in readme_rows], ["Bagian", "Penjelasan"]),
            {"Bagian": 26, "Penjelasan": 100},
        ),
        ("01_Model_Overview", overview_df, {"property": 44, "value": 95}),
        (
            "02_Tables",
            frame(
                tables,
                [
                    "table",
                    "is_hidden",
                    "storage_mode",
                    "partition_count",
                    "column_count",
                    "measure_count",
                    "query_group",
                    "refresh_policy",
                    "is_calculation_group",
                    "lineage_tag",
                    "description",
                ],
            ),
            {"table": 36, "storage_mode": 14, "query_group": 18, "lineage_tag": 38, "description": 40},
        ),
        (
            "03_Columns",
            frame(
                columns,
                [
                    "table",
                    "column",
                    "column_type",
                    "data_type",
                    "format_string",
                    "summarize_by",
                    "sort_by_column",
                    "engine_source_column",
                    "source_column",
                    "m_source_object",
                    "m_source_column",
                    "m_source_origin",
                    "m_source_columns_used",
                    "m_transform_chain",
                    "m_lineage_status",
                    "m_lineage_confidence",
                    "is_hidden",
                    "display_folder",
                    "description",
                    "is_calculated",
                    "expression",
                    "expression_lines",
                    "lineage_tag",
                    "annotations",
                ],
            ),
            {
                "table": 34,
                "column": 46,
                "column_type": 14,
                "data_type": 12,
                "format_string": 20,
                "summarize_by": 14,
                "sort_by_column": 24,
                "engine_source_column": 26,
                "source_column": 30,
                "m_source_object": 30,
                "m_source_column": 30,
                "m_source_origin": 14,
                "m_source_columns_used": 42,
                "m_transform_chain": 52,
                "m_lineage_status": 18,
                "m_lineage_confidence": 14,
                "is_calculated": 12,
                "expression": 80,
                "lineage_tag": 38,
                "annotations": 45,
            },
        ),
        (
            "04_Measures",
            frame(
                measures,
                [
                    "table",
                    "measure",
                    "expression",
                    "expression_lines",
                    "format_string",
                    "is_hidden",
                    "display_folder",
                    "description",
                    "lineage_tag",
                    "report_usage_count",
                    "report_pages",
                    "annotations",
                ],
            ),
            {
                "table": 30,
                "measure": 44,
                "expression": 100,
                "expression_lines": 12,
                "format_string": 18,
                "lineage_tag": 38,
                "report_pages": 60,
                "annotations": 40,
            },
        ),
        (
            "05_Partitions",
            frame(
                partitions,
                [
                    "table",
                    "partition",
                    "mode",
                    "query_group",
                    "source_type",
                    "source",
                    "refresh_policy_type",
                    "refresh_policy_mode",
                    "rolling_window_granularity",
                    "rolling_window_periods",
                    "incremental_granularity",
                    "incremental_periods",
                    "incremental_periods_offset",
                    "source_expression",
                    "polling_expression",
                    "state",
                    "refreshed_time",
                    "data_source",
                    "annotations",
                ],
            ),
            {
                "table": 32,
                "partition": 34,
                "mode": 14,
                "query_group": 18,
                "source_type": 12,
                "source": 100,
                "source_expression": 100,
                "polling_expression": 80,
                "annotations": 40,
            },
        ),
        (
            "06_Expressions_Params",
            frame(
                expressions,
                [
                    "name",
                    "kind",
                    "data_type",
                    "is_required",
                    "query_group",
                    "value",
                    "expression",
                    "annotations",
                    "lineage_tag",
                ],
            ),
            {"name": 24, "kind": 14, "data_type": 12, "query_group": 18, "value": 60, "expression": 80, "lineage_tag": 38},
        ),
        (
            "07_Relationships",
            frame(
                relationships,
                [
                    "name",
                    "from_table",
                    "from_column",
                    "to_table",
                    "to_column",
                    "cross_filtering",
                    "security_filtering",
                    "is_active",
                    "join_on_date_behavior",
                    "from_cardinality",
                    "to_cardinality",
                    "lineage_tag",
                ],
            ),
            {"name": 44, "from_table": 30, "from_column": 34, "to_table": 30, "to_column": 34, "lineage_tag": 38},
        ),
        (
            "08_Roles_RLS",
            frame(roles, ["role", "model_permission", "table", "table_permission_expression", "has_ols", "note"]),
            {"role": 22, "model_permission": 16, "table": 32, "table_permission_expression": 80, "note": 30},
        ),
        (
            "09_Query_Groups",
            frame(query_groups, ["query_group", "order", "members"]),
            {"query_group": 24, "order": 10, "members": 90},
        ),
        (
            "10_Cultures",
            frame(cultures, ["culture", "language", "version", "entity", "term_count", "sample_terms", "state"]),
            {"entity": 60, "sample_terms": 60},
        ),
        (
            "11_DAX_Dependencies",
            frame(
                dependencies,
                [
                    "measure",
                    "measure_table",
                    "referenced_type",
                    "referenced_table",
                    "referenced_object",
                    "depth",
                    "resolved_in_model",
                ],
            ),
            {"measure": 44, "measure_table": 24, "referenced_type": 16, "referenced_table": 28, "referenced_object": 46},
        ),
        (
            "12_Model_vs_Report",
            frame(
                cross_rows,
                ["object_type", "table", "object", "direct_visual_usage", "report_pages", "note"],
            ),
            {"object_type": 14, "table": 32, "object": 50, "report_pages": 70, "note": 60},
        ),
        (
            "13_Lineage_Annotations",
            frame(
                lineage_rows,
                ["scope", "object_type", "object_name", "lineage_tag", "annotation_key", "annotation_value"],
            ),
            {"object_type": 16, "object_name": 60, "lineage_tag": 38, "annotation_key": 34, "annotation_value": 70},
        ),
        (
            "14_Unsupported_Objects",
            frame(unsupported, ["object_class", "count", "status", "note"]),
            {"object_class": 34, "note": 60},
        ),
        (
            "15_Data_Sources",
            frame(
                data_sources,
                [
                    "source_kind",
                    "name",
                    "connector",
                    "server",
                    "database",
                    "table",
                    "partition",
                    "mode",
                    "query_group",
                    "impersonation",
                    "connection_string",
                    "note",
                ],
            ),
            {"source_kind": 18, "name": 28, "connector": 30, "server": 50, "database": 40, "table": 32, "partition": 30, "connection_string": 70, "note": 50},
        ),
        (
            "16_Partition_State",
            frame(
                partition_state,
                [
                    "table",
                    "partition",
                    "mode",
                    "state",
                    "refreshed_time",
                    "modified_time",
                    "range_start",
                    "range_end",
                    "range_granularity",
                    "query_group",
                    "data_source",
                    "query_definition_length",
                    "error_message",
                ],
            ),
            {"table": 32, "partition": 30, "refreshed_time": 20, "modified_time": 20, "error_message": 50},
        ),
        (
            "17_Translations",
            frame(translations, ["culture", "object_type", "object_name", "property", "value", "altered"]),
            {"object_type": 18, "object_name": 50, "property": 20, "value": 60},
        ),
        (
            "18_Hierarchies",
            frame(
                hierarchies,
                ["table", "hierarchy", "is_hidden", "display_folder", "description", "level_count", "levels", "lineage_tag"],
            ),
            {"table": 32, "hierarchy": 40, "levels": 90, "lineage_tag": 38},
        ),
        (
            "19_Calculation_Groups",
            frame(
                calculation_groups,
                ["table", "calculation_group", "precedence", "item_count", "items", "description"],
            ),
            {"table": 32, "calculation_group": 36, "items": 100, "description": 50},
        ),
        (
            "20_Perspectives",
            frame(perspectives, ["perspective", "description", "modified_time"]),
            {"perspective": 40, "description": 60},
        ),
        (
            "21_KPIs",
            frame(
                kpis,
                [
                    "table",
                    "measure",
                    "target_description",
                    "target_expression",
                    "target_format_string",
                    "status_description",
                    "status_expression",
                    "status_graphic",
                    "trend_description",
                    "trend_expression",
                    "trend_graphic",
                ],
            ),
            {"table": 30, "measure": 40, "target_expression": 60, "status_expression": 60, "trend_expression": 60},
        ),
        (
            "22_OLS",
            frame(ols, ["role", "table", "column", "metadata_permission", "table_permission_expression"]),
            {"role": 24, "table": 32, "column": 40, "table_permission_expression": 80},
        ),
        (
            "23_M_Lineage_Warnings",
            frame(
                lineage_warning_rows
                or [
                    {
                        "step": "",
                        "column": "",
                        "status": "no_warning",
                        "detail": "Semua kolom berhasil dipetakan ke sumbernya melalui query M.",
                    }
                ],
                ["step", "column", "status", "detail"],
            ),
            {"step": 30, "column": 42, "status": 20, "detail": 90},
        ),
    ]

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        for sheet, df, widths in sheets:
            write_sheet(writer, df, sheet, widths)

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    unresolved = sum(1 for row in dependencies if not row["resolved_in_model"])
    unused = sum(1 for row in cross_rows if row["direct_visual_usage"] == 0)
    mode_counts: dict[str, int] = defaultdict(int)
    for table in tables:
        for mode in str(table.get("storage_mode") or "").split(","):
            mode = mode.strip()
            if mode:
                mode_counts[mode] += 1
    log(f"OK  -> {out_file}")
    log(f"Endpoint              : {endpoint} / {catalog}")
    log(f"Tables                : {len(tables)}")
    log("Table modes           : " + ", ".join(f"{key}={value}" for key, value in sorted(mode_counts.items())))
    log(f"Columns               : {len(columns)}  (internal excluded: {internal_columns})")
    lineage_counts = defaultdict(int)
    for row in columns:
        lineage_counts[row.get("m_lineage_status", "")] += 1
    log(
        "  M lineage           : "
        + ", ".join(f"{key}={value}" for key, value in sorted(lineage_counts.items()) if key)
    )
    log(f"  M lineage warnings  : {len(lineage_warning_rows)}")
    log(f"Measures              : {len(measures)}")
    log(f"Partitions            : {len(partitions)}")
    log(f"Expressions/params    : {len(expressions)}")
    log(f"Relationships         : {len(relationships)}")
    log(f"Roles                 : {len({role['role'] for role in roles})}")
    log(f"Table permissions     : {sum(1 for role in roles if role['table'])}")
    log(f"Query groups          : {len(query_groups)}")
    log(f"DAX dependency rows   : {len(dependencies)}")
    log(f"Unresolved DAX refs   : {unresolved}")
    log(f"Model objects unused  : {unused}")
    return {
        "out_file": out_file,
        "endpoint": endpoint,
        "catalog": catalog,
        "tables": len(tables),
        "columns": len(columns),
        "internal_columns": internal_columns,
        "measures": len(measures),
        "partitions": len(partitions),
        "relationships": len(relationships),
        "roles": len({role["role"] for role in roles}),
        "query_groups": len(query_groups),
        "dependency_rows": len(dependencies),
        "unresolved_refs": unresolved,
        "unused_objects": unused,
        "lineage_warnings": len(lineage_warning_rows),
        "report_used": report_available,
        "storage_modes": dict(sorted(mode_counts.items())),
    }



"""Sinkronkan katalog konektor M dari dokumentasi Microsoft (dev-only).

Jalankan manual saat dokumentasi berubah:

    python sync_connector_catalog.py

Menulis ``rules/m_connectors.json``. Runtime aplikasi tidak melakukan network;
katalog dibaca dari aset yang di-commit. Halaman M reference dipakai untuk daftar
fungsi table-returning, sedangkan connector yang tidak ada di halaman itu
(Snowflake, BigQuery, Parquet, dataflow, ...) dicatat dari halaman connector.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

FUNCTIONS_URL = (
    "https://learn.microsoft.com/en-us/powerquery-m/accessing-data-functions"
)
FUNCTION_BASE = "https://learn.microsoft.com/en-us/powerquery-m/"
CONNECTOR_BASE = "https://learn.microsoft.com/en-us/power-query/connectors/"

# Connector yang dipakai tool ini tetapi tidak tercantum di halaman
# `accessing-data-functions` (dicek 2026-11-21). Metadata diambil dari halaman
# connector Power Query masing-masing.
CURATED = [
    {
        "name": "Snowflake.Databases",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "snowflake",
        "parameters": ["server", "warehouse", "options"],
    },
    {
        "name": "GoogleBigQuery.Database",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "google-bigquery",
        "parameters": ["options"],
    },
    {
        "name": "GoogleBigQueryAad.Database",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "google-bigquery",
        "parameters": ["options"],
    },
    {
        "name": "AzureSql.Database",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "azure-sql-database",
        "parameters": ["server", "database", "options"],
    },
    {
        "name": "AzureSynapseAnalytics.Database",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "azure-synapse-analytics",
        "parameters": ["server", "database", "options"],
    },
    {
        "name": "Parquet.Document",
        "category": "File",
        "doc_url": CONNECTOR_BASE + "parquet",
        "parameters": ["contents", "options"],
    },
    {
        "name": "Pdf.Data",
        "category": "File",
        "doc_url": CONNECTOR_BASE + "pdf",
        "parameters": ["contents", "options"],
    },
    {
        "name": "PowerBI.Dataflows",
        "category": "Dataflow",
        "doc_url": CONNECTOR_BASE + "dataflows",
        "parameters": ["options"],
    },
    {
        "name": "PowerPlatform.Dataflows",
        "category": "Dataflow",
        "doc_url": CONNECTOR_BASE + "dataflows",
        "parameters": ["options"],
    },
    {
        "name": "Fabric.Dataflows",
        "category": "Dataflow",
        "doc_url": CONNECTOR_BASE + "dataflows",
        "parameters": ["options"],
    },
    {
        "name": "PowerPlatform.Datasets",
        "category": "Dataset",
        "doc_url": CONNECTOR_BASE + "datasets",
        "parameters": ["options"],
    },
    {
        "name": "Fabric.Datasets",
        "category": "Dataset",
        "doc_url": CONNECTOR_BASE + "datasets",
        "parameters": ["options"],
    },
    {
        "name": "UsageMetricsDataConnector.GetMetricsData",
        "category": "Dataset",
        "doc_url": CONNECTOR_BASE + "usage-metrics",
        "parameters": ["options"],
    },
    {
        "name": "GoogleSheets.Contents",
        "category": "File",
        "doc_url": CONNECTOR_BASE + "google-sheets",
        "parameters": ["url"],
    },
    {
        "name": "Hadoop.Files",
        "category": "File",
        "doc_url": CONNECTOR_BASE + "hadoop-hdfs",
        "parameters": ["url", "options"],
    },
    {
        "name": "Html.BrowserContents",
        "category": "Web",
        "doc_url": CONNECTOR_BASE + "web",
        "parameters": ["url", "options"],
    },
    {
        "name": "Dataverse.Contents",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "dataverse",
        "parameters": ["url", "options"],
    },
    {
        "name": "CommonDataService.Database",
        "category": "Database",
        "doc_url": CONNECTOR_BASE + "dataverse",
        "parameters": ["url", "options"],
    },
]


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "replace")


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_functions(page: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r'<td><a href="([^"]+)"[^>]*><code>([^<]+)</code></a></td>\s*'
        r"<td>(.*?)</td>",
        re.S,
    )
    entries: list[dict[str, str]] = []
    for href, name, description in pattern.findall(page):
        function = html.unescape(name).strip()
        if not re.fullmatch(r"[A-Za-z_][\w.]*", function):
            continue
        entries.append(
            {
                "name": function,
                "description": strip_tags(description),
                "url": FUNCTION_BASE + href,
                "source": "m-reference",
            }
        )
    entries.sort(key=lambda item: item["name"].casefold())
    return entries


def build_catalog(page: str) -> dict:
    functions = parse_functions(page)
    known = {item["name"].casefold() for item in functions}
    undocumented = []
    for item in CURATED:
        if item["name"].casefold() in known:
            continue
        undocumented.append(
            {
                **item,
                "source": "connector-doc",
            }
        )
    undocumented.sort(key=lambda item: item["name"].casefold())
    return {
        "source": FUNCTIONS_URL,
        "generated": dt.date.today().isoformat(),
        "functions": functions,
        "undocumented": undocumented,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sinkronkan katalog konektor M dari dokumentasi Microsoft."
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "rules" / "m_connectors.json"),
        help="path katalog JSON",
    )
    parser.add_argument(
        "--page", default="", help="file HTML lokal (opsional, tanpa network)"
    )
    args = parser.parse_args(argv)

    page = Path(args.page).read_text(encoding="utf-8") if args.page else fetch(FUNCTIONS_URL)
    catalog = build_catalog(page)
    if len(catalog["functions"]) < 50:
        print(
            "GAGAL: daftar fungsi terlalu sedikit; struktur halaman berubah?",
            file=sys.stderr,
        )
        return 1
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Katalog: {len(catalog['functions'])} fungsi M + "
        f"{len(catalog['undocumented'])} connector terdokumentasi terpisah -> {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

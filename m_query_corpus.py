"""Laporan cakupan parser lineage M terhadap korpus query M (dev-only).

Korpus tidak disimpan di repo karena berisi ekspresi pelanggan. Unduh/ekspor
sendiri sebagai CSV dengan kolom ``tableName`` dan ``expression``, lalu:

    set M_QUERY_CSV=D:\\data\\m-query.csv
    python m_query_corpus.py

Opsi:
    --csv PATH     path korpus (default env M_QUERY_CSV)
    --sample N     hanya setiap N baris M (0 = semua)
    --top N        jumlah baris pada daftar peringkat
    --check        exit code 1 bila cakupan di bawah ambang

Ambang ``--check``: origin (tanpa query referensi) >= 95% dan baris warning
<= 15%. Angka ini menjaga regresi konektor/fungsi, bukan angka mutlak.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import re
import sys
from pathlib import Path
from typing import Any

from core.m_lineage import build_lineage, strip_comments

M_LIKE = re.compile(r"(let|if)\b", re.IGNORECASE)
DAX_LIKE = re.compile(
    r"^\s*(calendar|row|datatable|var|evaluate|distinct|summarize|"
    r"selectcolumns|union|filter|addcolumns|calculate|calculatetable)\b",
    re.IGNORECASE,
)


def is_m_query(text: str) -> bool:
    """True untuk ekspresi M; DAX calculated table dilewati."""
    clean = strip_comments(text).lstrip()
    if DAX_LIKE.match(clean):
        return False
    return bool(M_LIKE.match(clean))


def run(path: Path, sample: int) -> dict[str, Any]:
    csv.field_size_limit(50 * 1024 * 1024)
    origins: collections.Counter[str] = collections.Counter()
    statuses: collections.Counter[str] = collections.Counter()
    unknown: collections.Counter[str] = collections.Counter()
    missing: collections.Counter[str] = collections.Counter()
    total = 0
    m_rows = 0
    m_seen = 0
    with_object = 0
    with_warnings = 0
    with_references = 0
    missing_total = 0
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            total += 1
            text = str(row.get("expression") or "").strip()
            if not text or not is_m_query(text):
                continue
            if sample > 1 and m_seen % sample:
                m_seen += 1
                continue
            m_seen += 1
            m_rows += 1
            try:
                result = build_lineage(text)
            except Exception as exc:  # pragma: no cover - diagnostik korpus
                origins["ERROR " + type(exc).__name__] += 1
                missing_total += 1
                continue
            origin = result.origin or "(none)"
            origins[origin] += 1
            if result.source_object:
                with_object += 1
            if result.references:
                with_references += 1
            if result.warnings:
                with_warnings += 1
            for warning in result.warnings:
                statuses[warning.status] += 1
                if warning.status == "unknown_function":
                    match = re.search(r"Fungsi '([^']+)'", warning.detail)
                    unknown[match.group(1) if match else warning.detail[:40]] += 1
            if not result.origin and not result.references:
                missing_total += 1
                first = re.search(
                    r"(?:^|\n)\s*(?:Source|source)\s*=\s*([^\n]+)", text
                )
                missing[first.group(1).strip()[:60] if first else "?"] += 1
    return {
        "rows": total,
        "m_rows": m_rows,
        "with_object": with_object,
        "with_warnings": with_warnings,
        "with_references": with_references,
        "missing_total": missing_total,
        "origins": origins,
        "statuses": statuses,
        "unknown": unknown,
        "missing": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Laporan cakupan parser lineage M pada korpus lokal."
    )
    parser.add_argument(
        "--csv",
        default=os.environ.get("M_QUERY_CSV", ""),
        help="path korpus CSV (default: env M_QUERY_CSV)",
    )
    parser.add_argument("--sample", type=int, default=0, help="setiap N baris M")
    parser.add_argument("--top", type=int, default=15, help="jumlah baris peringkat")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 bila cakupan di bawah ambang",
    )
    args = parser.parse_args(argv)
    if not args.csv:
        parser.error("path korpus belum diberikan (--csv atau M_QUERY_CSV)")
    path = Path(args.csv)
    if not path.exists():
        parser.error(f"korpus tidak ditemukan: {path}")

    data = run(path, max(0, args.sample))
    m_rows = data["m_rows"]
    if not m_rows:
        print("Tidak ada query M di korpus.", file=sys.stderr)
        return 1
    known = m_rows - data["with_references"]
    origin_rate = (
        (known - data["missing_total"]) / known if known else 0.0
    )
    warning_rate = data["with_warnings"] / m_rows
    print(f"Baris CSV        : {data['rows']}")
    print(f"Query M          : {m_rows}")
    print(f"Origin dikenali  : {origin_rate:.1%} (tanpa {data['with_references']} referensi)")
    print(f"Source object    : {data['with_object'] / m_rows:.1%}")
    print(f"Baris berwarning : {warning_rate:.1%}")
    print(f"Query referensi  : {data['with_references']}")
    print("\nOrigin")
    for name, count in data["origins"].most_common(args.top):
        print(f"  {count:6}  {name}")
    print("\nStatus warning")
    for name, count in data["statuses"].most_common(args.top):
        print(f"  {count:6}  {name}")
    print("\nFungsi tak dikenal")
    for name, count in data["unknown"].most_common(args.top):
        print(f"  {count:6}  {name}")
    print("\nSumber tanpa origin (bukan referensi)")
    for name, count in data["missing"].most_common(args.top):
        print(f"  {count:6}  {name}")

    if args.check and (origin_rate < 0.95 or warning_rate > 0.15):
        print("\nGAGAL: cakupan di bawah ambang.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

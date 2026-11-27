"""Dispatcher CLI tunggal: ``bi-tools-cli <command> [options]``.

Satu executable console untuk semua perintah baris. Setiap perintah tetap
berada di modulnya sendiri (``cli.report``, ``cli.model``, dst.) dan diimpor
malas agar ``--help`` cepat dan perintah yang tidak dipakai tidak menyeret
dependensi berat.

``install-browser`` mengunduh Chromium untuk fitur screenshot TSD. Di aplikasi
terpaket tidak ada ``python`` untuk menjalankan ``python -m playwright``,
karena itu driver Playwright dipanggil langsung dari sini.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from core.version import APP_NAME, __version__

from core.pbi_capture.browsers import prepare_environment

COMMANDS: dict[str, tuple[str, str]] = {
    "report": ("cli.report", "report metadata from .pbix or Power BI Service"),
    "model": ("cli.model", "semantic model metadata via XMLA"),
    "tsd": ("cli.tsd", "TSD document (HTML) from the metadata workbook"),
    "lineage": ("cli.lineage", "scan, search, and Power BI lineage"),
    "analyze": ("cli.analysis", "column sizes + usage across reports"),
    "compare": ("cli.compare", "TOM snapshot for semantic model comparison"),
    "partition": ("cli.partition", "partition inventory and refresh for a semantic model"),
    "xmla-worker": ("cli.xmla_worker", "internal interactive ADOMD worker"),
    "tom-worker": ("cli.tom_worker", "internal interactive TOM worker"),
    "install-browser": ("", "download Chromium for TSD screenshots"),
}

USAGE = f"""\
{APP_NAME} {__version__} - command line interface

Usage:
  bi-tools-cli <command> [options]

Commands:
  report           report metadata from .pbix or Power BI Service
  model            semantic model metadata via XMLA
  tsd              TSD document (HTML) from the metadata workbook
  lineage          scan, search, and Power BI lineage
  analyze          column sizes + usage across reports
  compare          TOM snapshot for semantic model comparison (internal)
  partition        partition inventory and refresh for a semantic model
  install-browser  download Chromium for TSD screenshots (default: install chromium)

General options:
  -h, --help       show this help
  -V, --version    show the version

Help per command:
  bi-tools-cli report --help
"""


def install_browser(argv: Sequence[str] | None = None) -> int:
    """Unduh Chromium lewat driver Playwright bawaan aplikasi.

    Tanpa argumen berarti ``install chromium`` (kebutuhan screenshot TSD).
    Argumen lain diteruskan apa adanya ke CLI Playwright.
    """
    args = list(argv or ()) or ["install", "chromium"]
    try:
        from playwright.__main__ import main as playwright_main
    except Exception as exc:  # noqa: BLE001 - pesan instalasi, bukan traceback
        print(
            "Playwright is not available in this package "
            f"({exc}). Reinstall the application or run from source: "
            "pip install playwright",
            file=sys.stderr,
        )
        return 1

    original = sys.argv
    sys.argv = ["playwright", *args]
    try:
        prepare_environment()
        playwright_main()
    except SystemExit as exc:  # playwright memanggil sys.exit(returncode)
        return int(exc.code or 0)
    finally:
        sys.argv = original
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Jalankan perintah; kembalikan exit code."""
    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        print(USAGE, end="")
        return 2
    if args[0] in {"-h", "--help"}:
        print(USAGE, end="")
        return 0
    if args[0] in {"-V", "--version"}:
        print(f"{APP_NAME} {__version__}")
        return 0

    name, rest = args[0], args[1:]
    if name not in COMMANDS:
        print(f"Unknown command: {name}", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2

    if name == "install-browser":
        return install_browser(rest)

    module_name = COMMANDS[name][0]
    module = __import__(module_name, fromlist=["main"])
    return int(module.main(rest))


if __name__ == "__main__":
    raise SystemExit(main())

"""Entry point executable ``bi-tools-sync`` (program sync database)."""

from __future__ import annotations

from cli.sync import main

if __name__ == "__main__":
    raise SystemExit(main())

"""``python -m server`` - jalankan antarmuka web lokal."""

from __future__ import annotations

import sys

# Impor absolut supaya entry PyInstaller (``__main__`` tanpa paket) tetap jalan.
from server.runtime import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

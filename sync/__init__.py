"""Program sync database bersama (service principal).

Paket ini adalah **satu-satunya** tempat yang memanggil endpoint ``admin/*``
Power BI: katalog workspace, Scanner API, dan katalog report. Hasilnya
diterbitkan sebagai snapshot SQLite yang dibaca aplikasi interaktif.

Dipakai oleh:

- ``bi-tools-sync`` (executable/CLI lokal untuk uji dan operasi manual),
- notebook Fabric yang berjalan terjadwal,

dan tidak diimpor oleh ``server/`` (web) maupun perintah interaktif
``bi-tools-cli``.
"""

from __future__ import annotations

from .flow import SyncOptions, SyncResult, run_sync

__all__ = ["SyncOptions", "SyncResult", "run_sync"]

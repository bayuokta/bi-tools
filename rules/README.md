# Best Practice Rules

`BPARules.json` disalin apa adanya dari katalog **Microsoft / Tabular Editor
Best Practice Analyzer**:

- Sumber: https://github.com/microsoft/Analysis-Services/tree/master/BestPracticeRules
- Berkas: `BestPracticeRules/BPARules.json`
- Disalin: 2026-11-20
- Lisensi: MIT (repositori Microsoft Analysis-Services)

Tab **Best practice** di halaman Analisa memakai berkas ini sebagai katalog
aturan model. Tidak semua aturan dapat dievaluasi tanpa Tabular Editor; aturan
yang datanya belum dikumpulkan tool ini ditampilkan sebagai **Not evaluated**
beserta alasannya, bukan dihilangkan.

Jangan mengedit `BPARules.json` secara manual. Untuk memperbarui katalog,
ganti berkas ini dengan versi terbaru dari sumber di atas lalu jalankan uji
`tests/test_best_practice.py`.

# Katalog Konektor M

`m_connectors.json` adalah snapshot dokumentasi Microsoft:

- Sumber utama: https://learn.microsoft.com/en-us/powerquery-m/accessing-data-functions
- Connector yang tidak tercantum di halaman itu (Snowflake, BigQuery, Parquet,
  dataflow, dataset) diambil dari halaman **Power Query connectors** masing-masing.
- Dibuat oleh `sync_connector_catalog.py` (jalankan manual; runtime tidak
  melakukan network).
- Dipakai `core\connector_catalog.py` untuk memastikan daftar konektor lineage,
  model, dan TSD tidak melenceng dari dokumentasi.

Jangan mengedit `m_connectors.json` secara manual; perbarui lewat skrip
sinkronisasi lalu jalankan `tests/test_tsd.py`.

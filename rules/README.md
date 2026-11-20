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

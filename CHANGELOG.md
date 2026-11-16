# Changelog

Riwayat pengembangan tooling metadata Power BI, 2026-11-12 s.d. 2026-11-16 (62 commit).

Tag `v0.1.0` menunjuk commit terakhir di `main`: baseline satu commit berisi seluruh
perubahan di bawah ini, ditambah perubahan pengerasan rilis sesudahnya. Riwayat
per-commit sebelum baseline (62 commit) disimpan di luar repo sebagai
`bi-tools-main-62commits.bundle`.

## 2026-11-12 — Fondasi ekstraksi, GUI, dan lineage

### Ekstraksi metadata

- Struktur flat tooling: ekstraksi report `.pbix` dan semantic model (XMLA) ke workbook Excel.
- Pemisahan `core`/`cli` dan GUI PySide6; satu tab ekstraksi metadata.
- Deteksi jenis `.pbix`: model lokal (`DataModel`) vs live connection (`pbiServiceLive`).

### Lineage dan verifikasi

- Tab Lineage + CLI (scan REST API ke SQLite) dan kanvas visual dua arah.
- `verify_reference.py` untuk membandingkan hasil ekstraksi dengan angka acuan report/model.
- Deteksi instance Power BI Desktop, termasuk versi Microsoft Store.

## 2026-11-13 — Cakupan ekstraksi, Power BI Service, dan TSD

- Sheet `06_Sync_Slicers` dan penomoran ulang urutan sheet report.
- Cakupan ekstraksi report/model di GUI; validasi memakai workbook model yang sudah ada.
- Sumber report Power BI Service lewat Fabric API (`getDefinition`, LRO, retry `429`).
- Generate dokumen TSD dari workbook metadata: agregasi visual, tabel detail field,
  perbaikan layout, dan penghapusan teks instruksi template.

## 2026-11-14 — Arsitektur view model, screenshot, dan katalog workspace

### Screenshot TSD

- Capture page/visual Power BI Service untuk 2.2.7.1 (embed token + RLS + Playwright).
- Viewport mengikuti ukuran halaman; override sidecar kosong tidak lagi menghapus gambar.
- Pairing ketat (label/ukuran, ukuran unik) dan probe bookmark untuk visual tersembunyi.
- Tabel filter hanya menampilkan filter yang aktif.

### Arsitektur dan GUI

- Satu service principal untuk Fabric API, Power BI REST, dan XMLA; token hanya di memori.
- Fondasi presentasi (request, `JobRunner`, formatting, forms) dan view model
  metadata Local/Service, TSD, lineage, serta Pengaturan.
- Sub-tab Local / Power BI Service / Generate TSD; input URL report dihapus.

### Katalog workspace

- Katalog workspace di SQLite, picker workspace di sub-tab Service, dan sinkronisasi
  katalog dari tab Pengaturan.
- Picker workspace/report untuk screenshot TSD; label report memuat 8 karakter ID.
- `Is hidden` halaman dan visual diisi otomatis dari PBIR.

## 2026-11-15 — Mobile layout

- Screenshot mobile layout 2.2.7.2 otomatis (`layoutType=MobilePortrait`).

## 2026-11-16 — Pengaturan, TSD, dan Analisa Semantic Model

### Pengaturan dan TSD

- Tab Pengaturan dipecah menjadi sub-tab Kredensial dan Katalog & Database; database
  lokal pindah ke `data\bi_tools.db` dan scan lineage dipindah ke Sinkronisasi data.
- Klasifikasi tabel TSD 2.2.1.x sesuai sumber data (database/live/file/M query).
- Screenshot visual dalam group memakai hint posisi absolut.
- Nama file TSD bawaan memakai akhiran report ID.
- Label statis diganti peringatan kredensial; field dokumen/penandatangan/narasi
  dipindah ke konteks manual (sidecar JSON).

### Analisa Semantic Model

- Tab baru: ukuran kolom dari DMV VertiPaq + pemakaian kolom/measure dari report.
- Report PBIR dan PBIR-Legacy dianalisa; My Workspace dan report `[App]` dilewati;
  report tidak dapat diakses di-cache 24 jam.
- Measure tampil sebagai baris tabel; ukuran model menyertakan dictionary kolom.
- Sorting semua kolom tabel (klik header, kanan header untuk reset).

### Kebersihan repo

- Identifier pelanggan dinetralkan di dokumentasi, judul jendela, pesan error, dan tes.
- Workbook hasil generate tidak lagi di-track.

## 2026-11-16 — Pengerasan rilis: path eksplisit, `outputs`, dan setelan bersih

### Lokasi hasil generate

- Folder `outputs\` di samping aplikasi/executable menjadi lokasi bawaan workbook report,
  model, TSD, dan ekspor analisa; fallback `%LOCALAPPDATA%\BI Tools` bila folder aplikasi
  read-only. Override lewat `BI_TOOLS_OUTPUTS`/`BI_TOOLS_DATA` (`core\paths.py`).

### Path `.pbix` dan sumber instance

- `DEFAULT_PBIX`, `DRAGON_PBIX_SOURCE`, dan peringatan salinan usang dihapus; path `.pbix`
  selalu disebut eksplisit (`--report`, `--pbix`) dan CLI menolak jalan tanpa path.
- Combo instance Power BI Desktop aktif sebelum file `.pbix` dipilih; hanya nonaktif untuk
  live connection atau cakupan report saja.

### Sesi GUI dan setelan

- Sesi GUI mulai bersih: pilihan workspace/report/dataset/instance dihapus saat aplikasi
  dibuka, sementara kredensial, RLS, path database, cakupan, filter, sort, tab aktif, dan
  opsi render tetap tersimpan.
- QSettings pindah ke `HKCU\Software\BITools\Metadata`; setelan organisasi lama
  (`2W-Dragon\BI Tools`) disalin sekali (`settings/org_migrated_v2`) tanpa menimpa nilai baru.

### Uji

- Uji yang butuh file contoh membaca `RUN_PBIX`/`RUN_LIVE_PBIX`/`RUN_DQ_PBIX`/
  `RUN_MODEL_CATALOG`; tanpa variabel itu uji terkait di-skip, bukan gagal.

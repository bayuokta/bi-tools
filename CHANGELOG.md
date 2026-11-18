# Changelog

Riwayat pengembangan tooling metadata Power BI, 2026-11-12 s.d. 2026-11-16 (62 commit).

Tag `v0.1.0` menunjuk commit terakhir di `main`: baseline satu commit berisi seluruh
perubahan di bawah ini, ditambah perubahan pengerasan rilis sesudahnya. Riwayat
per-commit sebelum baseline (62 commit) disimpan di luar repo sebagai
`bi-tools-main-62commits.bundle`.

## Belum dirilis

### Antarmuka web lokal (0.4.0)

- Antarmuka PySide6 diganti server web lokal: `BI Tools.exe` menjalankan FastAPI +
  uvicorn di `127.0.0.1` (port bebas, default 8765), menulis penanda
  `data\server.json`, lalu membuka browser dengan tautan sesi bertoken. Hanya satu
  instance; peluncuran kedua membuka server yang sudah berjalan.
- Akses dijaga token acak per proses (cookie `HttpOnly`, `SameSite=Strict`),
  validasi `Host`/`Origin`, tanpa bind ke `0.0.0.0` dan tanpa CORS. `client_secret`
  tidak pernah dikirim balik ke browser (hanya `has_secret`).
- Pekerjaan panjang memakai satu antrean job + log live SSE; refresh halaman tidak
  memutus pekerjaan, dan job yang gagal/dibatalkan dilaporkan di konsol halaman.
- Preferensi pindah dari QSettings ke `data\settings.json` dengan migrasi sekali
  dari registry (termasuk `lineage/*` → `auth/*`/`paths/*`); pilihan sesi tetap
  dikosongkan setiap server dimulai.
- Halaman Pengaturan web sudah tersambung: kredensial, RLS default, path database,
  mode sinkronisasi, full scan/personal workspace, sinkronisasi katalog, scan
  lineage, tes token Fabric/Power BI, tema, dan pemilih folder/berkas sisi server.
- `web\` (HTML/CSS/JS tanpa build step) disalin ke samping exe; spec kini juga
  membangun `BI Tools (classic).exe` sebagai fallback PySide6 sampai paritas.
- Halaman Ekstraksi web tersambung penuh: sumber Service/Desktop, cakupan
  report/model, file `.pbix` lewat penjelajah server, instance Desktop, workspace
  + dataset/report dari katalog SQLite lalu REST, endpoint XMLA turunan, job
  dengan log live, serta kartu output dan ringkasan halaman/tabel/kolom/measure.
- Combo workspace, catalog, dan report memakai komponen desain prototype
  (tombol select-like + popup pencarian bersama); semua `<select>` di halaman
  ikut di-enhance kecuali di dalam dialog. Workspace **model** dan workspace
  **report** dipilih terpisah, sehingga report dari workspace lain tidak lagi
  mengikat atau mengubah Catalog; endpoint XMLA selalu diturunkan dari workspace
  model.
- Desain halaman **Ekstraksi metadata** dan **Generate TSD** disamakan dengan
  mockup terbaru: label workspace model/report, panel **Sumber metadata**,
  **Konteks manual**, **Opsi render**, **Screenshot (Power BI Service)** dengan
  cache, **Output** TSD, pratinjau dokumen, dan checklist. Fungsi TSD menyusul
  di M3; tombolnya menampilkan pesan tahap berikutnya.
- Input divalidasi sebelum job (`400`): `.pbix` hilang/tanpa PBIR/tanpa model
  lokal, instance Desktop belum dipilih, report paginated, atau kredensial
  service principal belum lengkap. Kesalahan Fabric/XMLA tetap dilaporkan di
  log job.
- Uji baru: presenter/endpoint metadata (instance, deteksi `.pbix`, workspace
  contents, validasi request, pemetaan kwargs lokal/service, ringkasan hasil).
- Halaman **Generate TSD** web tersambung: state formulir + status berkas,
  render `run_tsd` (HTML mandiri + sidecar), pratinjau dengan CSP ketat,
  edit JSON sidecar, capture screenshot Power BI Service (embed + RLS +
  Playwright) dengan cache `TSD_assets` dan tombol hapus cache.
- Ringkasan `run_tsd` kini juga mengembalikan jumlah tabel dan measure sehingga
  halaman TSD bisa menampilkan statistik tanpa membaca ulang workbook.
- Uji baru: preferensi/migrasi, penjaga token/Host/Origin, endpoint API, antrean
  job/SSE, runtime (state, port, mutex), dan penjaga arsitektur web.

## 2026-11-18 - Perbaikan 0.3.2

- Auto-unduh Chromium 0.3.1 mengunduh ke `%LOCALAPPDATA%\ms-playwright` tetapi
  launch mencari di `_internal\playwright\driver\package\.local-browsers`:
  Playwright memaksa `PLAYWRIGHT_BROWSERS_PATH=0` untuk proses driver saat
  `sys.frozen`. `core/pbi_capture/browsers.py::prepare_environment()` kini
  menyetel `PLAYWRIGHT_BROWSERS_PATH` ke `%LOCALAPPDATA%\ms-playwright` sebelum
  `sync_playwright()` dan sebelum installer, sehingga unduhan dan launch
  menunjuk folder yang sama. Unduhan 0.3.1 yang sudah ada dipakai ulang.
- Lokasi browser berada di luar folder aplikasi, jadi bertahan saat aplikasi
  di-upgrade atau dipindah; path kustom non-`0` tetap dihormati.
- Uji baru: environment frozen (isi otomatis, timpa `0`, hormati path kustom,
  abaikan saat dari source) dan `install-browser` memanggil persiapan.

## 2026-11-18 - Perbaikan 0.3.1

- Sinkronisasi katalog/scan lineage mode otomatis gagal HTTP 400
  "The date should be in the last 30 days." bila jam mesin sedikit maju:
  `probe_admin()` mengirim `modifiedSince` waktu sekarang. Sekarang probe
  memakai `safe_modified_since()` (2 jam ke belakang) dan watermark scan
  di-clamp ke jendela API (29 hari s.d. 31 menit); timestamp rusak memicu
  full scan. Penyebabnya terbukti live: `+10 menit` dan `-40 hari` sama-sama
  ditolak, sedangkan `-10`/`-31` menit diterima.
- `bi-tools-cli install-browser` tanpa argumen kini menjalankan
  `install chromium` (sebelumnya hanya mencetak bantuan Playwright).
- Capture screenshot TSD mengunduh Chromium otomatis pada percobaan pertama
  bila browser belum ada (sekitar 150 MB, lewat driver Playwright), lalu
  mengulang launch. Dapat dimatikan lewat checkbox GUI, `CaptureOptions`, atau
  `--no-auto-install-browser`; pesan kegagalan tetap menyebut
  `bi-tools-cli install-browser`.

## 2026-11-17 - Rilis 0.3.0

- Lineage: opsi **Sertakan My Workspace (personal)** (checkbox di Pengaturan,
  CLI `--include-personal`). Scan memakai `excludePersonalWorkspaces=false`
  sehingga report yang berada di My Workspace ikut muncul sebagai downstream
  dataset bersama; sebelumnya hanya workspace biasa yang dipindai.
  Aktivasi pertama memaksa full scan (watermark lama tidak memuat personal),
  opsi hanya berjalan di mode admin, dan cakupan disimpan di
  `scan_run.include_personal` (database lama dimigrasi otomatis).
- Catatan rilis GitHub kini memuat ringkasan dari CHANGELOG, daftar aset,
  catatan sebelum upgrade, dan checksum; daftar commit otomatis tetap
  ditambahkan di bawahnya.
- Workflow memakai action yang sudah berjalan di Node.js 24
  (`checkout@v7`, `setup-python@v7`, `upload-artifact@v6`), sehingga anotasi
  deprecation Node.js 20 hilang.
- Catatan upgrade: default scan **tidak** berubah (tetap tanpa personal).
  Yang mengaktifkan opsi ini akan menjalani satu full scan lebih lama
  (tenant contoh: 866 menjadi 9.337 workspace) dan nama personal workspace
  memuat email pemilik di database lokal.

## 2026-11-17 - Perbaikan 0.2.2

- Paket portable: ZIP yang diunduh membawa Mark of the Web pada hampir semua
  berkas, sehingga .NET Framework menolak memuat `Python.Runtime.dll` (pesan
  menyesatkan `Failed to resolve Python.Runtime.Loader.Initialize`) dan ADOMD.
  `core/xmla_client.py` kini membuka blokir kedua assembly otomatis sebelum
  `import clr`; bila penanda tidak bisa dihapus (folder read-only), `XmlaError`
  menyebut `Get-ChildItem -Recurse | Unblock-File` dan saran memakai installer.
- Uji baru: deteksi `Zone.Identifier`, buka blokir, assembly yang tetap
  terblokir, pesan bantuan, dan kegagalan non-MOTW yang tidak boleh ditelan.

## 2026-11-17 - Perbaikan 0.2.1

- Perbaikan scan lineage: `POST admin/workspaces/getInfo` menjawab `202 Accepted`
  dengan body job, jadi `core/lineage_api.py` memakai `allow=(200, 202)` (sebelumnya
  `202` dilaporkan sebagai "gagal (HTTP 202)").
- `core/api/transport.py`: `Retry-After` di atas 5 menit tidak ditunggu; request
  gagal dengan pesan throttling berisi perkiraan menit (dulu GUI bisa diam
  puluhan menit), dan status `2xx` di luar `allow` menyebut petunjuk penyebabnya.
- Uji regresi: POST `202` pada scan (termasuk `202` berulang saat masih berjalan),
  throttle panjang, dan uji katalog tidak lagi membaca `.env` sungguhan.

## 2026-11-17 - Paket Windows dan rilis otomatis

- `core/version.py` menjadi satu-satunya sumber versi (`0.2.0`); dipakai version
  resource exe, installer, dan pemeriksaan tag rilis.
- `cli/__main__.py`: dispatcher CLI tunggal `bi-tools-cli`
  (`report`/`model`/`tsd`/`lineage`/`analyze`/`install-browser`) dengan impor malas.
- `packaging/bi_tools.spec`: PyInstaller onedir berisi `BI Tools.exe` (GUI) dan
  `bi-tools-cli.exe` (console); `templates/` dan `libs/` disalin ke samping exe
  karena `core/paths.py` mencari aset di folder aplikasi.
- `packaging/bi-tools.iss` + `packaging/build.ps1`: installer Inno Setup per
  pengguna, ZIP portable, dan `SHA256SUMS.txt`; uninstaller tidak menghapus
  `outputs/` dan `data/`.
- `.github/workflows/ci.yml` (flake8 + uji) dan `release.yml` (tag `v*` → uji,
  build, installer, rilis GitHub dengan tiga aset). Paket belum ditandatangani.
- `packaging/make_icon.py` + `packaging/bi-tools.ico`: ikon aplikasi dan installer.
- `install-browser` mengunduh Chromium untuk screenshot TSD dari paket tanpa
  membutuhkan interpreter Python.
- `.flake8` menetapkan aturan lint yang berlaku; dua temuan lama (F401 di
  `core/jobs.py`, F541 di `core/model.py`) dibersihkan.
- Uji baru `tests/test_packaging.py` (versi, dispatcher, spec/ISS/workflow, ICO).
- Perbaikan yang hanya terlihat di paket frozen: DLL ADOMD dicari dari folder
  aplikasi (`core/xmla_client.py` memakai `APP_DIR`, bukan folder modul di
  `_internal`), dan `core/report.py` membuat folder `outputs/` yang belum ada.
- Pesan `CaptureError` saat Chromium belum terpasang menyebut
  `bi-tools-cli install-browser` (paket tidak menyertakan browser).
- `core/lineage_scan.py`: `scan_run.started_at` dan `LineageScanResult.started_at`
  memakai satu timestamp (waktu mulai scan), sehingga watermark scan incremental
  tidak meleset beberapa detik pada mesin lambat; `close()` capture juga menutup
  socket server.

## 2026-11-12 - Fondasi ekstraksi, GUI, dan lineage

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

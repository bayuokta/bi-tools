# Tooling Metadata Power BI — Report, Model, TSD, Lineage

Ekspor metadata report (dari file `.pbix`) dan semantic model (via XMLA) ke Excel, analisa pemakaian kolom/measure, dokumen TSD, dan lineage Power BI Service. Antarmuka berupa **web lokal** (server Python di `127.0.0.1` yang dibuka di browser), ditambah perintah baris. PySide6 sudah dihapus di 0.4.0. Repo ini terpisah dari project Power BI (PBIP) yang diekstrak.

## Struktur

```
core\                           logika ekstraksi, tanpa UI atau terminal
  pbix.py                       sumber .pbix (Report/definition), salinan, peringatan usang
  report.py                     ekstraksi report -> Report_Metadata.xlsx
  model.py                      ekstraksi model via XMLA -> Semantic_Model_Metadata.xlsx
  jobs.py                       orkestrasi report + job gabungan (deteksi jenis .pbix)
  requests.py                   objek permintaan web/CLI (cakupan, GUID, CaptureOptions)
  tsd.py                        konteks TSD dari workbook + render HTML (template Confluence) + nama output bawaan
  pbi_capture\                  screenshot page/visual/mobile Power BI Service (embed token + RLS + Playwright)
    runner.py                   CaptureOptions, capture_report, load_or_capture (cache)
    embed.py                    embed token + identitas RLS
    client.py                   REST report/dataset/GenerateToken (memakai core.api.Transport)
    capture.py                  Playwright: enumerasi page/visual, screenshot desktop + mobile layout, pairing hint posisi absolut + label/ukuran + ukuran unik + reveal bookmark
    cache.py                    simpan/muat TSD_assets (manifest.json, capture.json)
    assets.py                   ScreenshotSet, penamaan file, data URI, daftar objek dekoratif
    hints.py                    hint posisi absolut visual (dari workbook report) untuk pairing capture
    credentials.py              identitas RLS (username + roles) dari env/.env
  auth.py                       sesi akun 365 (azure-identity, tanpa client id) + service principal untuk program sync
  api\
    transport.py                HTTP bersama: token, retry 429/5xx, long running operation, pagination
  xmla_client.py                koneksi ADOMD; token Power BI; parse/bangun endpoint workspace
  metadata_common.py            usage report, dependency DAX, styling Excel
  m_lineage.py                  parser lineage kolom dari query M
  lineage_api.py                client Power BI REST API (Scanner admin, paging admin, dataset/report per workspace)
  lineage_transform.py          transform hasil scan -> node, edge, datasource
  lineage_store.py              schema SQLite lineage + katalog workspace, pencarian, traversal, diagnostik
  lineage_service.py            akses baca read-only untuk web/CLI (ringkasan, cari, lineage, ekspor, workspace)
  lineage_layout.py             tata letak kanvas lineage (root, upstream kiri, downstream kanan)
  lineage_scan.py               orkestrasi scan + riwayat scan_run
  catalog_sync.py               sinkronisasi daftar workspace ke SQLite + riwayat workspace_sync_run
  lineage_export.py             export hasil lineage ke CSV
  column_stats.py               ukuran kolom/tabel dari DMV VertiPaq (data + hierarki atribut)
  report_usage.py               pemakaian field dari definisi report PBIR + PBIR-Legacy
  usage_store.py                tabel SQLite analisa kolom (cache report, pemakaian, snapshot ukuran)
  usage_service.py              orkestrasi analisa: daftar report, referensi model, verdict, ekspor
  report_catalog.py             katalog report per dataset untuk database bersama
  snapshot.py                   publish/unduh snapshot SQLite + checksum + schema version
  model_compare.py              diff definisi TMDL/TMSL TOM (read-only)
  compare_service.py            subprocess snapshot TOM (token stdin)
  tom_compare.py                serializer objek TOM (TMDL/TMSL) di proses anak
  tmdl_utils.py                 normalisasi + buang blok TMDL/TMSL
  compare_export.py             CSV + manifest script dari definisi TOM
  tom_client.py                 koneksi TOM/XMLA + TMSL refresh partisi (jalur tulis)
  partition_service.py          inventaris partisi + row count DMV (proses CLI terpisah)
  errors.py                     ExtractionError (pesan yang ditampilkan ke pengguna)
  paths.py                      folder aplikasi + outputs\ + data\ (fallback %LOCALAPPDATA% saat read-only)
  version.py                    APP_NAME + __version__ (satu sumber untuk exe, installer, dan tag rilis)
cli\                            perintah baris (argparse): report.py, model.py, tsd.py, lineage.py, analysis.py, compare.py, partition.py
  __main__.py                   dispatcher bi-tools-cli (report/model/tsd/lineage/analyze/partition/install-browser)
sync\                           program sync service principal (hanya paket ini yang memanggil Admin API)
  flow.py                       orkestrasi katalog -> lineage -> katalog report -> snapshot
  admin_api.py                  AdminClient: admin/groups, Scanner API, admin/reports
  catalog.py                    katalog workspace + katalog report
  lineage.py                    scan lineage admin/member
  __main__.py                   CLI bi-tools-sync (run/workspaces/lineage)
sync_main.py                    entry point ``bi-tools-sync`` (program sync service principal)
pyproject.toml                  build wheel bitools-sync untuk notebook Fabric
server\                         server web lokal (FastAPI + uvicorn, hanya 127.0.0.1)
  __main__.py                   python -m server [--port] [--no-browser]
  app.py                        pabrik aplikasi, rute API, aset web, penjaga token
  runtime.py                    satu instance, pilih port, token, buka browser, shutdown
  security.py                   middleware token cookie + validasi Host/Origin
  jobs.py                       antrean satu job + log live (SSE) + pembatalan
  settings_store.py             preferensi JSON + migrasi sekali dari registry QSettings 0.3.x
  settings.py                   kunci preferensi web
  auth_state.py                 status/sign-in/sign-out akun 365
  shared_db.py                  resolusi snapshot database bersama
  presenters\                   logika web tanpa Qt: settings, metadata, tsd, analysis, compare, lineage, partitions
  api\                          system, settings, catalog, metadata, tsd, analysis, compare, lineage, partitions, files, jobs
web\                            aset statis: index.html, styles.css, app.js, api.js, js\core, js\views (tanpa build step)
templates\tsd.template.html     template TSD gaya Confluence (salinan repo template-tsd)
tests\                          uji angka acuan, TSD, lineage, dan penanganan error
libs\Microsoft.AnalysisServices.AdomdClient.dll   dependency ADOMD (v19.120.1.0; mendukung Interactive Login)
libs\tom\*.dll                  dependency TOM/MSAL untuk refresh partisi (net472, terpisah dari ADOMD)
extract_report_metadata.py      wrapper CLI report (perintah lama tetap berfungsi)
extract_model_metadata.py       wrapper CLI model
extract_tsd.py                  wrapper CLI generate TSD
extract_lineage.py              wrapper CLI lineage
analyze_semantic_model.py       wrapper CLI analisa ukuran + pemakaian kolom
verify_reference.py             verifikasi angka acuan report + model (opsional, butuh Desktop untuk model)
outputs\                        hasil generate: Report_Metadata.xlsx, Semantic_Model_Metadata.xlsx, TSD_*.html/json, ekspor analisa (TIDAK di-commit)
data\bi_tools.db                 database lineage + katalog + cache analisa CLI (TIDAK di-commit)
TSD_assets\                     cache screenshot page/visual/mobile (TIDAK di-commit)
.env.example                    contoh kredensial CLI lineage dan screenshot (RLS)
packaging\                      bi_tools.spec (PyInstaller onedir), bi-tools.iss (Inno Setup),
                                build.ps1, make_icon.py + bi-tools.ico
.github\workflows\              ci.yml (flake8 + uji), web-smoke.yml (smoke browser
                                Playwright), dan release.yml (tag v* -> installer + rilis)
*<nama report>.pbix               salinan sumber (TIDAK di-commit)
requirements.txt
```

## Autentikasi akun 365 dan database bersama

Aplikasi web memakai **akun 365** (tanpa client id): REST dan Fabric lewat
`azure-identity` browser, sedangkan XMLA (ADOMD/TOM) memakai dialog login
MSOLAP. Token tetap di memori proses. Klik **Sign in** di Pengaturan.

Untuk XMLA interaktif, server menjalankan **worker ADOMD** (`cli\xmla_worker.py`) di proses terpisah dengan Tk message loop, karena dialog MSOLAP tidak bisa dipompa dari thread job uvicorn. Worker membuka koneksi sekali lalu melayani query lewat JSON. Jendela login hanya tampil sampai login berhasil, lalu disembunyikan; worker tanpa aktivitas ditutup otomatis setelah 10 menit dan seluruh worker dihentikan saat server berhenti.

Program terpisah **`bi-tools-sync.exe`** memakai service principal untuk
endpoint Admin (katalog workspace, Scanner API, `admin/reports`). Hasilnya
diterbitkan sebagai snapshot SQLite:

```powershell
python sync_main.py --database data\bi_tools_sync.db --snapshot-out "D:\Share\bi_tools_snapshot.db"

# Dari paket, kredensial bisa lewat environment atau .env di folder kerja:
# bi-tools-sync.exe --env-file "D:\sync\.env" --snapshot-out "D:\Share\bi_tools_snapshot.db"
```

Aplikasi interaktif mengunduh snapshot ke cache lokal dan membukanya read-only.
Jangan membuka SQLite langsung dari folder SharePoint/OneDrive. Laporan report
dibaca dari tabel `report_catalog`; definisi report tetap diunduh live dengan
akun user.

## Prasyarat

- Windows + Power BI Desktop (hanya untuk ekstraksi model via XMLA).
- Python 3.11 dengan `pip install -r requirements.txt`.
- Path `.pbix` selalu disebut eksplisit (`--report` di CLI/web, `--pbix` di `verify_reference.py`); tidak ada file bawaan. Salin ulang dari project setiap kali report berubah.
- Untuk aplikasi web: akun Microsoft 365 yang punya akses ke workspace. Untuk program sync: service principal yang terdaftar di Microsoft Entra dengan izin Admin API.
- Untuk screenshot TSD dari Power BI Service: `pip install playwright` lalu `python -m playwright install chromium` (sekali per mesin), akses **Build** ke dataset report, dan role RLS bila dataset memakainya. Di aplikasi terpaket, Chromium diunduh otomatis pada capture pertama (dapat dimatikan), atau manual dengan `bi-tools-cli install-browser`.

## Antarmuka web lokal

```powershell
python -m server                       # menjalankan server + membuka browser
python -m server --no-browser --port 8800
```

- Server hanya mendengarkan `127.0.0.1`, memilih port bebas (default 8765), lalu membuka `http://127.0.0.1:<port>/?t=<token>`. Token hanya dipakai sekali untuk memasang cookie `HttpOnly`; permintaan API tanpa cookie ditolak, dan `Host`/`Origin` divalidasi. Menutup jendela konsol atau menekan **Hentikan server** di Pengaturan mengakhiri proses.
- Hanya satu server berjalan. Menjalankan aplikasi lagi akan membuka tautan server yang sudah ada, bukan membuat proses kedua.
- Pekerjaan panjang berjalan di thread server dengan log live (SSE); refresh halaman tidak memutus pekerjaan.
- Berkas dan folder dipilih lewat penjelajah di halaman (server yang membaca disk lokal), bukan dialog native browser.
- Preferensi disimpan di `data\settings.json` (fallback `%LOCALAPPDATA%\BI Tools\data`). Saat pertama dijalankan, nilai QSettings 0.3.x dimigrasikan sekali (termasuk `lineage/*` → `auth/*`/`paths/*`); nilai baru tidak ditimpa. Pilihan sesi (workspace/report/dataset/instance) tetap dikosongkan setiap server dimulai.
- **Extraction & TSD**, **Analisa Semantic Model**, **Partisi**, **Lineage**, dan **Pengaturan** sudah tersambung penuh — sumber Service/Desktop, cakupan, pemilih `.pbix`/folder, instance Desktop, workspace model + workspace report, dataset/report dari katalog, job dengan log live, kartu output, serta ringkasan halaman/tabel/kolom/measure. **Extraction & TSD** adalah satu alur dua langkah: ekstraksi metadata lalu render TSD inline. Halaman **Partisi** membaca inventaris via XMLA dan bisa me-refresh partisi terpilih (jalur tulis dengan konfirmasi).
- **Ekstraksi dari web**:
  - **Service**: pilih **workspace model** dan **workspace report** secara terpisah (boleh berbeda). Workspace model menentukan endpoint XMLA dan daftar Catalog; workspace report menentukan daftar report. Memilih report tidak mengubah Catalog, karena report bisa memakai dataset di workspace lain. Combo memakai komponen desain prototype: tombol select-like dengan chevron yang membuka popup berisi kolom pencarian + daftar pilihan (semua `<select>` di halaman ikut di-enhance). Report PBIR-Legacy (satu `report.json`) ditolak dengan pesan agar disimpan ulang sebagai PBIR; report paginated (RDL) ditandai dan tidak diekstrak.
  - **Desktop**: pilih file `.pbix` lewat penjelajah (bukan dialog browser). Jenis sumber dideteksi otomatis; live connection hanya mengekstrak report. Instance Power BI Desktop dipilih otomatis hanya bila tepat satu terbuka; cakupan report saja tidak memerlukan instance.
  - Cakupan `Report + semantic model`, `Report saja`, atau `Semantic model saja` disimpan per sumber. Cakupan model memerlukan instance Desktop (lokal) atau endpoint + catalog (Service).
  - **Batch report** (Service): centang **Extract several reports**, pilih 2–25 report dari **satu workspace dan satu dataset**, lalu jalankan. Model diekstrak sekali; setiap report ditulis ke `<folder output>\<Nama>_<8 ID>\Report_Metadata.xlsx` dan ringkasan ke `Batch_Summary.xlsx`. Report gagal dicatat di ringkasan tanpa membatalkan report lain. Usage report tidak digabung pada batch (jalankan report tunggal untuk `12_Model_vs_Report`).
  - Tombol **Jalankan ekstraksi** memulai job; log live muncul di konsol, kartu output menampilkan waktu/ukuran berkas, dan ringkasan menampilkan halaman/tabel/kolom/measure. File dibuka di aplikasi default lewat tombol **Buka**.
- **Extraction & TSD dari web** (satu alur dua langkah):
  - Stepper di atas halaman: **1 Metadata extraction** dan **2 Generate TSD**. Langkah 2 tampil inline di bawah langkah 1 dan terbuka setelah ekstraksi sukses atau bila `Report_Metadata.xlsx` sudah tersedia. Selama terkunci, panel **Langkah 2 menunggu ekstraksi** ditampilkan dan tombol langkah 2 memberi pesan.
  - Setelah ekstraksi sukses, workbook report/model otomatis diisi ke langkah 2, status stepper diperbarui, dan tombol **Continue to Generate TSD** menggulir ke langkah 2. Tombol **Back to step 1** kembali ke langkah 1.
  - Pilih **Report workbook** (`Report_Metadata.xlsx`) dan opsional **Model workbook**; template default `templates\tsd.template.html`. Pemilih berkas memakai penjelajah server.
  - **Konteks manual** (`TSD_<nama>.json`) dimuat/disimpan lewat tombol **Muat/Simpan** atau diedit langsung lewat **Edit JSON…**. Generate ulang mempertahankan isi sidecar.
  - **Opsi render**: nama report, tanggal dokumen, mode draft (field kosong menjadi TODO), buka semua panel expand.
  - **Screenshot**: centang, pilih workspace + report (daftar dari katalog + REST), atur RLS (kosong = default Pengaturan), cakupan (page/visual/keduanya), skala, mobile, dekoratif, dan auto-unduh Chromium. **Ambil screenshot** mengisi cache `TSD_assets\<nama>_<id8>`; generate memakai cache yang cocok.
  - **Generate TSD** membuat satu HTML mandiri (screenshot sebagai data URI) + sidecar JSON; pratinjau menampilkan statistik halaman/visual/tabel/measure/TODO dan tombol **Buka dokumen** (CSP ketat, tanpa JavaScript).
  - **Hapus cache** hanya menghapus folder cache report terpilih; preferensi TSD tersimpan, pilihan workspace/report dan nama dokumen berlaku per sesi.
- **Analisa Semantic Model dari web**:
  - Pilih workspace (katalog) dan semantic model (daftar dataset workspace lewat REST). Analisa **tidak** berjalan otomatis: tekan **Analyze now** di panel hasil atau **Analysis** di kanan atas. Tidak ada snapshot lama yang dimuat dari database. Checkbox **Include report usage (pages, visuals, filters)** (default aktif) mengatur apakah definisi report ikut diunduh; mematikannya membuat analisa ±6 detik dan kolom/measure tanpa referensi menjadi **Perlu dicek**. Mengubah checkbox setelah ada hasil hanya memunculkan pengingat untuk menjalankan analisa lagi.
  - Hasil disimpan hanya di **sesi in-memory** server (satu koneksi SQLite per dataset). `data\bi_tools.db` tidak lagi menerima tabel `usage_*` dari halaman ini, sehingga tidak ada data basi; setelah server di-restart, detail report dan ekspor meminta analisa ulang.
  - **Analisa** mengukur ukuran kolom (data + hierarki + dictionary) dan memindai pemakaian report; **Hentikan** mengirim pembatalan dan menyimpan hasil parsial dengan cakupan belum lengkap.
  - Kartu ringkasan menampilkan ukuran dataset, jumlah kolom/measure, kolom/measure tidak dipakai beserta ukuran, serta report/halaman/visual dan cakupan report. Delapan tab: **Semua hasil**, **Tables**, **Relationships**, **Report results**, **DAX expressions**, **M queries**, **Health**, dan **Best practice**.
  - **Semua hasil** adalah daftar datar kolom + measure. Baris measure tidak menampilkan ekspresi DAX (sudah ada di tab **DAX expressions**), sedangkan calculated column tetap menampilkannya. Tiap baris dapat dibuka menjadi kelompok pemakaian: **Used in artifacts**, **Used in visuals**, **Used as key column**, **Used in relationships**, **Used in row/object level security**, **Used in page level filters**, **Used in column sorting**, dan **Used in field parameters**. Kelompok kosong tidak muncul. Tidak ada sub-header per grup; header utama 11 kolom dipakai untuk semua nilai baris anak.
  - **Tables** tetap hierarki per tabel (grup Measure/Kolom) dan menambahkan **Mode** serta **Partisi**. **Relationships** punya tampilan tabel 9 kolom (Nama relasi, Tipe, Cross filter, Kardinalitas, Status, Auto create, # dipakai, Dari kolom, Ke kolom) dan grafik tree per kolom mengikuti arah relasi: edge per pasangan tabel dengan lane routing, badge jumlah, zoom Fit/−/+, **drag untuk menggeser kanvas**, serta panel samping statistik. `# dipakai` dihitung dari DMV `DISCOVER_CALC_DEPENDENCY` (jumlah objek model yang bergantung pada relasi); `Auto create` dideteksi dari nama relasi `AutoDetected_`/GUID. **Report results** bertingkat seperti prototype: report → **Hidden pages/Pages** → halaman → **Visuals** → visual → **Artifacts used** + **Visual level filters** → **Columns used**, plus **Page level filters** dan **Report level filters**. Detail dimuat lazy per report; kolom **Views** ditampilkan `-` karena butuh activity events, sedangkan **Visual rusak** dan **Skor praktik** diisi dari payload health, tema diambil dari definisi report. Tiap baris memakai ikon penanda; halaman/visual tersembunyi ditandai ikon eye-off dan chip **Hidden**. **DAX expressions** menampilkan measure + calculated column; **M queries** menampilkan M tabel + parameter/ekspresi. Tab **Health** merangkum temuan model/report dengan filter severity dan klik baris untuk membuka detail/lineage.
  - Pencarian, filter tipe/status, **Hanya tidak dipakai**, expand/collapse, dan **Export XLSX** tersedia. Sel yang terpotong menampilkan teks lengkap saat di-hover (tooltip).
  - **Klik kanan** baris kolom/measure (atau tombol `⋮` di sel nama, `Shift+F10`) membuka menu aksi: buka/tutup item di bawah, **Salin teks** (`'Tabel'[Nama]`), **Detail kolom/measure** (tipe, ukuran data/hierarki/dictionary, baris, format, folder, hidden, status, alasan, pemakaian, dan ekspresi), serta **Lihat ekspresi DAX** untuk measure.
  - **View column lineage graph** membuka dialog graph bergrup seperti mockup: artifact **Semantic Model** (berisi grup **Model dependencies** dan **M query** per tabel) dan artifact **Report** (berisi grup per **Page** dengan kartu visual/filter). Report dan page menjadi **header grup**, bukan kartu; seed disorot di dalam Model dependencies, atau menjadi output terakhir rantai M jika kolom punya langkah M. Halaman disusun satu kolom dan report berbeda tampil berdampingan. Kartu kolom/measure/step M berada di dalam grupnya, langkah M bernomor `01`, `02`, dan garis digambar sebagai **kurva bezier**. Graph hanya memakai dependency **langsung** (`depth` 1): kolom yang dipakai measure A lewat measure B tidak digambar sebagai garis langsung ke A, tetapi tetap muncul di `04_Model_Usage` lewat kolom **Depth**. Di dalam grup, kartu disusun sebagai **pohon hierarki**: induk berada di tengah anak-anaknya, dan rantai M untuk kolom upstream measure tampil sebagai baris terpisah. Header **Report** terhubung ke header tiap **Page**, dan header **Page** terhubung ke kartu visual/filter dengan garis pohon ortogonal, sehingga isi report terbaca sebagai family tree. Graf padat dipadatkan otomatis: edge berhenti di header halaman atau report, dan edge ke report kedua memakai koridor di atas artifact agar tidak menembus report lain. Klik kartu menyorot lineage langsung kartu itu (bukan seluruh report), klik header/background grup menyorot anggotanya. Kartu, grup, dan artifact bisa **digeser**; kanvas memanjang otomatis ke kanan/bawah bila item melewati batas, edge mengikuti posisi baru, dan hasil drag ikut diekspor. Ada pencarian node, zoom −/+/Fit, geser kanvas, dan **double-click kolom/measure/tabel** untuk menjadikan root baru. Arah bisa **Both/Upstream/Downstream**; graph dibangun dari sesi analisa tanpa XMLA/REST tambahan. Tombol **SVG**/**PNG** mengekspor artifact, grup, kartu, dan edge yang sedang tampil.
  - **View column lineage** membuka dialog yang sama dalam mode **Outline** (pohon "Depends on" / "Used by") dengan pilihan **Compact/Full** (node berulang diringkas atau diperluas); tombol **Graph/Outline** bisa dipakai bergantian tanpa memuat ulang data. Tiap baris juga menampilkan peran pemakaian: `Used in visual (Values/Data/Y-Axis)`, `Visual/Page/Report level filter`, `Sort`, dan `Formatting`, termasuk nama visual dan tipe visual; baris `Tidak dipakai` diberi warna merah. Di sisi **Depends on**, langkah M diringkas sehingga kolom langsung terhubung ke M query lalu datasource; graph tetap menampilkan langkah M lengkap. Node **datasource** memakai path penuh sesuai konektor: `dbo.Sales` (SQL Server/Azure SQL/Synapse), `proyek.dataset.tabel` (BigQuery), `database.schema.tabel` (Snowflake), `schema.tabel` (PostgreSQL/MySQL), `entity` (dataflow), nama sheet/tabel (Excel/SharePoint/OData/Google Sheets), nama berkas (File/Folder/Parquet/PDF), dan host untuk URL (Web/SharePoint/OData). Koneksi **native query** (`Value.NativeQuery`, `Sql.Database(..., [Query=...])`, `Odbc.Query`) memakai `server.database`/DSN karena tidak ada navigasi tabel; bila SQL punya klausa `FROM` sederhana, nama tabel dipakai sebagai label (termasuk SQL yang dirangkai `&` dengan parameter, mis. `sales_daily`), sedangkan CTE/subquery/tabel dinamis dilewati. Katalog konektor mengikuti dokumentasi Microsoft (`rules\m_connectors.json`); connector yang tidak tercantum di halaman M reference seperti Snowflake tetap didukung lewat aturan navigasi generik `database.schema.tabel`. Parameter M tidak masuk label; nama parameter, path/URL lengkap, dan penanda *native query* tampil sebagai keterangan node (`param:ServerURL`). Alias dataflow memakai `entity`, bukan ID workspace/dataflow. Query yang sumbernya query lain (`Table.Combine({#"Nama", ...})`) ditelusuri bila ekspresi shared query tersedia (memo + guard siklus) dan menampilkan `ref:<Nama>` di detail; bila tidak tersedia, dicatat sebagai referensi tanpa mengarang sumber. Di **Outline**, baris datasource menampilkan `ref:`, `param:`, dan `Native query`; path/URL lengkap ada di tooltip.
  - **View dependencies ▸** membuka submenu kategori (semua, measure, kolom, relasi, sorting, security, field parameter, report & visual, kalkulasi) dan menampilkan graph yang sudah difilter.
  - Baris dependency pada tab **Dependencies** bisa diklik untuk langsung membuka lineage graph node tujuan (measure, calculated column/table, relasi, key column). Baris tanpa objek model tetap berupa teks biasa.
  - Baris **tabel** di tab **Tables** punya menu konteks sendiri: **Table lineage** (M query → tabel → kolom/measure → report dengan layout artifact/grup yang sama), **Table details**, **Show in analysis**, **Copy table name**, dan **Exports**.
  - Untuk kolom dengan query M, graph menampilkan **sumber data → tabel M → langkah M** (rename/select/derive/split/transform, bercabang bila kolom turunan memakai beberapa kolom sumber) sebelum kolom model. Tabel tanpa `QueryDefinition` hanya menampilkan node tabel M. Measure ikut menampilkan rantai M kolom upstream yang dipakainya (maksimal 3 kolom, 8 langkah per rantai) dan kelebihan kolom dicatat di notice.
  - Chip **M lineage** menunjukkan keyakinan (`Complete`/`Partial`/`Unavailable`) beserta alasan; panel **M warnings** merinci langkah bermasalah (TransformColumns, rename/kolom dinamis, fungsi tak dikenal).
  - **Raw data** (kolom/measure) membuka dialog **metadata mentah TMSCHEMA**: seluruh baris `TMSCHEMA_COLUMNS`/`TMSCHEMA_MEASURES` sebagai JSON, lengkap dengan **Copy JSON**. Tidak ada nilai data/RLS.
  - **Preview values** membaca contoh nilai model dengan akun yang login (RLS pengguna berlaku): kolom memakai `TOPN` + `SELECTCOLUMNS`, measure memakai `ROW`, maksimal 100 baris dan timeout 60 detik. Data baru dimuat setelah tombol **Load preview**.
  - **Column details / Measure details** membuka tab **Properties**, **Usage**, **Dependencies**, dan **Raw JSON** (metadata TMSCHEMA dimuat saat tab dibuka). Field yang tidak dideteksi tool ini ditandai `null` dan dicantumkan di daftar `unsupported`.
  - **Table options ▸** berisi **Table details** (mode, partisi, baris, ukuran, jumlah kolom/measure, sumber + ekspresi M), **Show in analysis** (kembali ke tabel utama dengan filter tabel), dan **Copy table name**.
  - **Model options ▸** berisi **Model details** (workspace, waktu analisa, metode/cakupan, ukuran model, jumlah objek, status report usage), **Copy model name**, **Run analysis again**, dan **Open settings**.
  - **Exports ▸** menulis **CSV node/edge**, **JSON lineage**, **Copy as Mermaid**, **Lineage graph (SVG)**, **Lineage graph (PNG)**, dan **Dependencies (CSV)** ke `outputs\`. Hanya format yang diminta yang ditulis, sehingga file CSV yang sedang dibuka Excel tidak menggagalkan ekspor JSON. Gambar SVG/PNG juga bisa diekspor langsung dari tombol di toolbar dialog lineage.
  - **Muat ulang** di samping semantic model memuat ulang daftar dataset workspace terpilih; workspace tidak punya tombol muat ulang sendiri.
  - Sidebar punya item **Partisi** dan tombol ciutkan yang statusnya diingat di browser.
- **Partisi dari web**:
  - Pilih workspace + semantic model, lalu **Muat inventaris**. Daftar partisi dibaca dari TOM/XMLA: tabel, partisi, jumlah baris, rentang (best-effort), mode, tipe source, state, waktu proses terakhir, dan modified time.
- Tabel dengan lebih dari satu partisi (umumnya incremental) ditampilkan sebagai **baris grup** yang bisa di-expand/collapse; tabel satu partisi tetap baris biasa. Baris grup merangkum jumlah partisi, total rows, rentang, mode/source/state unik, waktu proses terbaru, dan chip **Incremental**. Checkbox grup memilih semua partisi tabel itu. Tombol **Expand all**/**Collapse all** membuka atau menutup semua grup; status buka dipertahankan saat inventaris dimuat ulang.
  - **Rows** diambil dari DMV `DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS` (`RECORDS_COUNT` terbesar per partisi). Karena ADOMD dan TOM membawa versi assembly yang berbeda, **inventaris/refresh (TOM)** dan **row count (DMV)** dijalankan di proses CLI anak; token dikirim lewat stdin, bukan argumen atau file. Dengan begitu halaman ini tidak merusak ekstraksi/analisa model di sesi server yang sama. Bila DMV tidak tersedia, kolom ditampilkan `-`.
  - **Range** diambil dari literal tanggal di ekspresi M (`RangeStart`/`RangeEnd`) lalu pola tanggal pada nama partisi. Bila tidak ditemukan, nilainya `-`; ekspresi M asli tetap tersimpan di data inventaris, bukan dikarang.
  - **Process selected** mengirim satu perintah TMSL untuk semua partisi terpilih. Semua 8 jenis refresh tersedia (`full`, `automatic`, `dataOnly`, `clearValues`, `calculate`, `add`, `defragment`, `indexes`); server memvalidasi kombinasi yang tidak berlaku (`add` untuk calculated/DirectQuery, `defragment` dikirim level tabel).
  - Konfirmasi memerlukan centang dan mengetik **PROCESS**. Setelah TMSL dikirim, perintah tidak bisa dibatalkan dari aplikasi; hasilnya dibaca ulang dan pesan mengarahkan ke Refresh history (**Via XMLA Endpoint**). Tidak ada perubahan metadata/query/policy.
- **Bahasa antarmuka**: Inggris (bawaan) atau Indonesia, dipilih di **Pengaturan → Tampilan → Language**. Pilihan disimpan di preferensi server dan diterapkan tanpa reload; angka mengikuti locale. Sort dengan klik header tersedia di tab datar (Semua hasil, Relationships, Report results, DAX expressions, M queries, Health); tab Tables mengikuti urutan model. Kolom mockup yang tidak punya sumber data (views) ditampilkan `-`; tema, skor praktik, visual rusak, dan auto-create relationship sudah diisi dari data analisa. Halaman **Analisa** tetap read-only; **Partisi** adalah satu-satunya jalur tulis ke model.
- **Lineage dari web**:
  - Cari item (kata kunci, workspace, tipe) dari `data\bi_tools.db`. Pencarian hanya menampilkan daftar; klik hasil untuk menjadikannya akar (tidak ada auto-buka hasil pertama). Database belum ada → pencarian dinonaktifkan dan diarahkan ke **Sinkronisasi data** di Pengaturan.
  - Kanvas dua arah: upstream di kiri, root di tengah, downstream di kanan, dengan panah tipe relasi, node berwarna per tipe (band + ikon), serta **zoom −/+/Fit** dan **drag untuk menggeser** (seperti grafik Relationships). Klik node memilih node itu, menampilkan detail, dan menyorot tetangga langsung beserta edge-nya; node lain tidak ikut menyala. Tombol **Upstream/Downstream** meredupkan sisi lain; **Kedalaman** 1–15; klik dua kali node menjadikannya akar, dan tombol **Jadikan akar** tersedia di panel detail. Tautan **Buka report** tersedia untuk node Report.
  - **Export CSV** menulis `Lineage_<nama>.csv` ke `outputs\` (UTF-8 BOM, header Inggris) dan membuka filenya. Tombol **SVG**/**PNG** mengekspor kanvas yang sedang tampil ke `Lineage_<nama>.svg`/`.png` (PNG maksimal 8000 px sisi terpanjang). Tidak ada scan dari tab ini; scan tetap dijalankan dari Pengaturan.
  - Filter **Node type** di toolbar kanvas menyembunyikan node/edge tipe lain tanpa menghitung ulang posisi; indikator `x / y` menunjukkan jumlah node yang tampil. Ekspor gambar mengikuti filter, sedangkan CSV tetap memuat seluruh lineage.

## API yang dipakai

Semua HTTP keluar lewat `core\api\transport.py` (token Bearer, retry `429`/`5xx`, long running operation, pagination). **Tidak ada metode HTTP `DELETE`** ke API mana pun; operasi hapus/bersihkan memakai `POST` (`.../clear`, `.../cancel`).

### Microsoft Entra

| Method | Endpoint | Kegunaan |
|---|---|---|
| POST | `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` | Token client credentials (MSAL) untuk scope Fabric dan Power BI |

### Fabric API (`api.fabric.microsoft.com`)

| Method | Endpoint | Kegunaan |
|---|---|---|
| POST | `workspaces/{workspaceId}/reports/{reportId}/getDefinition` | Definisi PBIR report |
| GET | `operations/{operationId}` | Polling LRO (`202` + `Location`) |
| GET | `operations/{operationId}/result` | Hasil operasi bila tidak ada di body status |

### Power BI Admin REST (`api.powerbi.com/v1.0/myorg`)

Hanya dipakai **program sync** dengan service principal (Fabric administrator);
aplikasi interaktif tidak memanggil endpoint ini.

| Method | Endpoint | Kegunaan |
|---|---|---|
| GET | `admin/reports?$filter=datasetId eq '<guid>'&$top=&$skip=` | Report pemakai dataset (lintas workspace) |
| GET | `admin/reports/{reportId}/subscriptions` | Subscription report (maks. 200 request/jam) |
| GET | `admin/groups?$top=&$skip=` | Sinkronisasi katalog workspace |
| GET | `admin/workspaces/modified?modifiedSince=&excludePersonalWorkspaces=` | Workspace yang berubah |
| POST | `admin/workspaces/getInfo` | Scanner API (batch 100 workspace) |
| GET | `admin/workspaces/scanStatus/{scanId}` | Status scan |
| GET | `admin/workspaces/scanResult/{scanId}` | Hasil scan |

### Power BI Member REST

| Method | Endpoint | Kegunaan |
|---|---|---|
| GET | `groups` | Fallback daftar workspace (non-admin) |
| GET | `groups/{workspaceId}/datasets` | Daftar dataset |
| GET | `groups/{workspaceId}/reports` | Daftar report |
| GET | `groups/{workspaceId}/dataflows` | Dataflow |
| GET | `groups/{workspaceId}/dataflows/{id}/datasources` | Datasource dataflow |
| GET | `groups/{workspaceId}/dataflows/{id}/upstreamDataflows` | Lineage dataflow |
| GET | `groups/{workspaceId}/datasets/{id}/datasources` | Datasource dataset |
| GET | `groups/{workspaceId}/dashboards` | Dashboard |
| GET | `groups/{workspaceId}/dashboards/{id}/tiles` | Tile dashboard |
| GET | `groups/{workspaceId}/reports/{reportId}` | Metadata report (embed/capture) |
| GET | `groups/{workspaceId}/datasets/{datasetId}` | Metadata dataset (embed) |
| POST | `GenerateToken` | Embed token untuk screenshot TSD |

### Bukan REST

| Protokol | Kegunaan |
|---|---|
| XMLA / ADOMD | DMV `DISCOVER_*` dan `TMSCHEMA_*` (read-only) |
| XMLA / TOM | TMSL `refresh` partisi (satu-satunya jalur tulis, konfirmasi `PROCESS`) |
| Browser Playwright | Memuat `app.powerbi.com` untuk capture; mengunduh Chromium |

### API lokal web (server sendiri)

| Prefix | Method | Endpoint |
|---|---|---|
| `/api/analysis` | GET | `state`, `workspaces/{id}/datasets`, `snapshot`, `report-detail`, `lineage`, `details` |
| `/api/analysis` | POST | `lineage/export`, `lineage/image`, `dependencies/export`, `preview`, `raw-metadata`, `run`, `preferences`, `export` |
| `/api/catalog` | GET | `status` |
| `/api/catalog` | POST | `sync`, `scan` |
| `/api/compare` | GET | `state` |
| `/api/compare` | POST | `run`, `export`, `script` |
| `/api/files` | GET | `browse`, `outputs` |
| `/api/files` | POST | `open` |
| `/api/jobs` | GET | ``, `{id}`, `{id}/stream` |
| `/api/jobs` | POST | `{id}/cancel` |
| `/api/lineage` | GET | `state`, `search`, `node/{id}` |
| `/api/lineage` | POST | `export`, `image` |
| `/api/metadata` | GET | `instances`, `pbix`, `workspaces`, `workspaces/{id}/contents` |
| `/api/metadata` | POST | `run` |
| `/api/partitions` | GET | `state`, `workspaces/{id}/datasets` |
| `/api/partitions` | POST | `inventory`, `refresh` |
| `/api/settings` | GET | `` |
| `/api/settings` | PUT | `credentials`, `rls`, `paths`, `catalog`, `ui`, `extraction`, `tenant`, `shared-db` |
| `/api/settings` | POST | `test-token`, `sign-in`, `sign-out`, `snapshot/download` |
| `/api/system` | GET | `state` |
| `/api/system` | POST | `shutdown` |
| `/api/health` | GET | health check |
| `/api/tsd` | GET | `state`, `manual`, `preview` |
| `/api/tsd` | POST | `state`, `run`, `capture`, `cache/clear` |
| `/api/tsd` | PUT | `manual` |

Semua endpoint lokal memakai token sesi cookie (`HttpOnly`, `SameSite=Strict`) dan validasi `Host`/`Origin`; tidak ada `DELETE` dan tidak ada CORS.

## Perintah baris

Program sync database bersama (service principal, Admin API):

```powershell
python sync_main.py --database data\bi_tools_sync.db `
  --snapshot-out "D:\Share\bi_tools_snapshot.db" --mode admin --full
```

Report (tidak butuh Power BI Desktop terbuka):

```powershell
python extract_report_metadata.py --report "path\ke\Report.pbix"
python extract_report_metadata.py --report "path\ke\Report.pbix" --no-model   # lewati validasi; semua field TIDAK DIVALIDASI
python extract_report_metadata.py --report "path\ke\Report.pbix" --model-workbook Semantic_Model_Metadata.xlsx
python extract_report_metadata.py --report "path\ke\Report.pbix" --extract-to _pbir
```

Tanpa `--model-workbook`, workbook `Semantic_Model_Metadata.xlsx` dicari di folder `--out` lebih dulu, lalu `outputs\`, lalu folder aplikasi. `--no-model` tetap berarti validasi dimatikan.

Report dari Power BI Service (memakai Fabric API `getDefinition`):

```powershell
python extract_report_metadata.py --report-url "https://app.powerbi.com/groups/<workspaceId>/reports/<reportId>"
python extract_report_metadata.py --workspace-id <workspaceId> --report-id <reportId>
python extract_report_metadata.py --workspace-id <workspaceId> --report-id <id1> --report-id <id2> --out "<folder output>"   # batch
```

Kredensial dibaca dari `TENANT_ID`/`CLIENT_ID`/`CLIENT_SECRET` di environment atau `.env` (tidak ada lagi pilihan login browser). Service principal butuh izin Fabric API `Report.ReadWrite.All` atau `Item.ReadWrite.All` beserta admin consent, dan tenant setting **Service principals can call Fabric public APIs** harus aktif.

Model via XMLA (Power BI Desktop **harus terbuka**):

```powershell
python extract_model_metadata.py --list-instances
python extract_model_metadata.py --report "path\ke\Report.pbix"   # hanya jika tepat satu instance terbuka
python extract_model_metadata.py --report "path\ke\Report.pbix" --port 59348
python extract_model_metadata.py --report "path\ke\Report.pbix" --catalog "<guid>"
python extract_model_metadata.py --endpoint "powerbi://..." --catalog "Dataset" --report "path\ke\Report.pbix"
python extract_model_metadata.py --no-report                      # lewati kolom usage report
```

`--report` wajib bila kolom usage report diinginkan; gunakan `--no-report` untuk melewatinya.

Untuk `--endpoint` berisi `powerbi://`/`asazure://`, token Power BI diambil otomatis dari service principal di `.env` (workspace di-encode dan `?readonly` ditambahkan bila belum ada). Instance Desktop lokal (`localhost:<port>`) tidak memakai token. Jangan menempelkan `Password=<token>` di connection string.

Analisa semantic model (ukuran kolom + pemakaian di semua report pemakai dataset):

```powershell
python analyze_semantic_model.py --workspace-id <workspaceId> --dataset-id <semanticModelId>
python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --list-reports
python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --workspace-only
python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --model-only
python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --refresh --max-reports 20
python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --refresh --scan-workers 4
```

Nama workspace/dataset diambil dari katalog SQLite (`data\bi_tools.db`); `--workspace-name`/`--dataset-name` hanya perlu bila katalog belum pernah disinkronkan. Hasil ditulis ke `Analisa_Semantic_Model_<nama>_<id8>.xlsx` (`--out` untuk path lain).

Partisi semantic model (inventaris read-only + refresh lewat XMLA):

```powershell
python -m cli partition --workspace-id <ws> --dataset-id <ds> --list
python -m cli partition --workspace-id <ws> --dataset-id <ds> `
  --table "Fact Sales" --partition "Fact Sales 2025" --refresh-type full --yes
python -m cli partition --workspace-id <ws> --dataset-id <ds> `
  --target "Fact Sales|Fact Sales 2025" --yes
```

Refresh memerlukan XMLA **Read Write**, akun dengan akses tulis ke workspace, dan `--yes` (setara konfirmasi `PROCESS`). Tanpa `--yes` perintah hanya menampilkan error. Gunakan `--list` untuk melihat state, jumlah baris, dan range sebelum memilih target.

## Generate TSD (langkah 2)

Dokumen TSD (Technical Specification Design) dibuat dari workbook metadata memakai template Confluence di `..\template-tsd`. Di web, langkah ini ada di halaman **Extraction & TSD** dan terbuka setelah ekstraksi atau bila workbook report sudah tersedia. Template disalin apa adanya ke `templates\tsd.template.html`; perubahan template dilakukan di repo `template-tsd` lebih dulu.

```powershell
python extract_tsd.py                        # workbook di outputs\ -> TSD_<nama>.html
python extract_tsd.py --name "Report Uji"
python extract_tsd.py --model Semantic_Model_Metadata.xlsx --final --expand-all
python extract_tsd.py --manual TSD_uji.json --out out\TSD_uji.html
python extract_tsd.py --screenshots --workspace-id <ws> --report-id <id> --rls-roles HO
python extract_tsd.py --screenshots --workspace-id <ws> --report-id <id> --no-auto-install-browser
```

- Sumber data: `Report_Metadata.xlsx` (wajib) dan `Semantic_Model_Metadata.xlsx` (opsional). Tanpa workbook model, bagian model memakai empty state dan tidak ada data karangan.
- Konteks manual disimpan sebagai sidecar JSON (default `<nama output>.json`) berisi **override saja**, sehingga generate ulang tidak menghapus tulisan manual. Override per halaman/visual memakai `page_id`/`visual_id`. Override `field_details`/`interactions` juga bisa ditambahkan di bawah visual bila perlu mengoreksi hasil ekstraksi.
- Field **Dokumen** (workspace, folder, subjudul, prepared for, navigation menu), **Penandatangan** (author/authorizer), dan **Narasi** (overview/insight) diisi lewat sidecar JSON — tombol **Edit JSON...** atau file `<nama output>.json` (kunci `document.*` dan `report.*`). Formulir web hanya memuat **Nama report** (di grup Opsi render), opsi render, screenshot, dan output, sehingga isian JSON tidak pernah tertimpa nilai kosong saat Generate.
- Nama file TSD bawaan untuk report dari Power BI Service memakai akhiran 8 karakter report ID: `TSD_<nama report>_<id8>.html` (sidecar JSON memakai basename yang sama). Ini mencegah dua report bernama sama saling menimpa HTML/sidecar. Local `.pbix` tetap `TSD_<nama report>.html`, dan nama output yang Anda ketik sendiri tidak diubah.
- `--draft` (default) menandai field kosong sebagai `TODO`; `--final` menyembunyikannya. `--expand-all` membuka semua panel expand.
- Kolom **Custom Column Logic** hanya terisi untuk calculated column (formula DAX) dan kolom buatan Power Query (`Table.AddColumn`, duplikat kolom, gabungan kolom, agregasi `Table.Group`). Kolom yang hanya di-rename atau di-expand dari sumber dibiarkan kosong.
- Panel **Click here to expand parameter list** tampil untuk setiap tabel, termasuk `Database / Datamart` dan `File-based`, berisi parameter M yang dipakai query tersebut (mis. `ServerURL`, `Datamart`, `RangeStart`, `RangeEnd`).
- Di **2.2.7.1 Web layout**, sel **Is hidden** pada tabel tiap halaman diisi otomatis dari `01_Pages.is_hidden` (PBIR `page.json`: `visibility=HiddenInViewMode` atau halaman bertipe `Tooltip`), jadi halaman tersembunyi tampil `TRUE` dan halaman biasa `FALSE`. Workbook lama tanpa kolom itu dibiarkan kosong.
- Tabel **Visual(s) Information** di 2.2.7.1 memakai kolom **Is hidden** di ujung kanan, diisi otomatis dari `08_Visual_Summary.is_hidden` (PBIR `visual.json.isHidden`; group induk yang disembunyikan ikut menandai visual anak). Workbook lama tanpa kolom itu dibiarkan kosong.
- Di **2.2.7.1 Web layout**, detail visual ada di panel **Click here to expand field list** berisi tabel **Table | Field | Type | Display Name | Expression | Aggregation | Query Ref**. `Expression` diisi DAX measure/calculated column dari workbook model dan DAX visual calculation dari `04_Visual_Fields.expression`; `Aggregation` diisi fungsi agregasi visual (Sum, Average, Distinct count, Min, Max, Count, Median, Standard deviation, Variance).
- Tabel filter di 2.2.7.1 (**Filter in All Page**, **Filter in All This Page**, **Filter in this visual**) memakai kolom **Column / Measure Name | Table Name | Type | Values | is hidden | is locked**. Hanya filter yang benar-benar punya definisi yang ditampilkan; kartu kosong di filter pane (tidak memfilter) dilewati, sehingga blok **Filter in this visual** tidak muncul pada visual tanpa filter aktif. Label **Filter in All Page** dan **Filter in All This Page** tetap tampil dengan tabel kosong bila tidak ada filter. Nilai kosong ditulis `—`, bukan `TODO`.
- Tabel **2.2.1.1 / 2.2.1.2 / 2.2.1.3 / 2.2.1.4** dibagi menurut sumber datanya: 2.2.1.1 hanya tabel database/datamart (SQL Server, Snowflake, BigQuery, Oracle, PostgreSQL, OData, Web, dll), 2.2.1.2 dataflow/dataset, 2.2.1.3 file-based (Excel, CSV, JSON, XML, TXT/TSV, PDF, Folder, `File.Contents`, SharePoint), dan 2.2.1.4 query yang dibuat di Power BI (Enter Data/`#table`, `Binary.FromText`, `Table.FromRows/Value/List/Records`, shared M query/fungsi non-parameter) termasuk tabel yang connector-nya tidak dikenali.
- Tabel **2.2.1.1 / 2.2.1.2 / 2.2.1.3** memakai satu baris data + baris detail; sel **Columns** digabung (`rowspan="2"`) dan memuat panel **Click here to expand columns list**, sedangkan baris detail memuat Power Query Formula dan daftar parameter.
- **2.2.3 Calculated Tables** hanya berisi tabel dengan partisi DAX (`calculated`); **2.2.4 Calculated Columns** berisi semua kolom `is_calculated` dari seluruh tabel. Kolom calculated tetap dicatat dua kali secara sengaja: di daftar **Columns** tabel 2.2.1.x (dengan `Custom Column Logic`) dan di 2.2.4.
- Template tidak memuat teks instruksi pengisian; mode draft hanya menandai field kosong dengan `TODO`. Jangan menambahkan penanda `**bold**`/`*italic*` atau filter khusus untuk teks instruksi.
- Kolom **Interaction** memakai tabel **Source | Target | Type** dari `03_Interactions`; visual tanpa interaksi keluar tetap menampilkan `N/A`.
- Output berupa satu file HTML mandiri (CSS inline, tanpa JavaScript, line ending CRLF) yang siap ditempel ke Confluence.
- Screenshot page/visual di 2.2.7.1 dan mobile layout di 2.2.7.2 diambil otomatis dari Power BI Service dengan `--screenshots` (workspace/report ID + kredensial `TENANT_ID`/`CLIENT_ID`/`CLIENT_SECRET`, identitas RLS `RLS_USERNAME`/`RLS_ROLES`). Data mengikuti role RLS yang dipilih. Mobile layout hanya diambil untuk halaman yang punya phone layout; matikan dengan `--no-mobile-screenshots`. Halaman tanpa phone layout tidak dibuatkan gambar dan 2.2.7.2 menampilkan catatan.
- Objek dekoratif (`shape`, `image`, `textbox`, `actionButton`, `basicShape`, `pageNavigator`, `bookmarkNavigator`) tidak dibuatkan baris visual sendiri karena tetap terlihat di screenshot halaman. Slicer tetap tampil. Untuk report contoh hasilnya 101 baris visual (dari 137 baris `08_Visual_Summary`). Gunakan `--include-decorative-visuals` (CLI) atau centang **Sertakan shape/image/tombol** (web) bila ingin semua baris.
- Capture memakai embed token + Chromium headless (Playwright): page/visual dienumerasi lewat embedded client, lalu di-screenshot per page dan per visual. Bila Chromium belum ada, capture pertama mengunduh otomatis (sekitar 150 MB) lewat driver Playwright; matikan dengan `--no-auto-install-browser`. Mobile layout memakai embed kedua dengan `layoutType=MobilePortrait`; viewport mengikuti `page.mobileSize` (fallback 375x667). Viewport desktop mengikuti ukuran halaman terbesar dari `01_Pages` agar tidak ada letterbox putih. Hasil disimpan di `TSD_assets\<nama report>_<8 karakter report ID>\` (`manifest.json`, `capture.json`, `pages\`, `visuals\`, `mobile\`, PNG) dan di-inline ke HTML sebagai `data:image/png;base64` supaya dokumen tetap satu file. Tipe dekoratif tidak ikut disimpan sebagai PNG.
- Pairing visual ke elemen DOM memakai **hint posisi absolut** dari `08_Visual_Summary.position_x_abs`/`position_y_abs` (posisi visual + seluruh group induk, diisi saat ekstraksi report). Offset canvas diestimasi dari hint yang ukurannya cocok, jadi slicer/matrix di dalam group tetap terpasang walau layout embed memakai koordinat relatif. Bila workbook belum punya kolom itu (hasil ekstraksi lama), capture memakai pencocokan label/ukuran dengan batas posisi dan fallback **ukuran unik**; tidak ada fallback urutan baca, dan elemen berlabel/dekoratif tidak dipinjam.
- Capture web/CLI ikut mengecualikan objek dekoratif secara default (sama dengan filter TSD); centang **Sertakan shape/image/tombol** atau `--include-decorative-visuals` untuk menyertakannya.
- Generate ulang memakai cache selama workspace/report/cakupan sama. Cache lama dari versi pairing sebelumnya otomatis dianggap tidak cocok (`captureVersion`, kini 5 karena pairing memakai hint posisi absolut), jadi capture ulang berjalan sekali setelah upgrade. `--refresh-screenshots` memaksa capture baru. `--screenshot-scope pages|visuals|both` mengatur isi dan `--screenshot-scale 1|2` resolusi (default 1 agar file ringkas). `--no-mobile-screenshots` mematikan capture mobile.
- Slicer di panel filter yang tersembunyi dicoba dibuka lewat bookmark report: bookmark dijalankan satu per satu (nama tidak dipakai), lalu dicek apakah elemen DOM visual yang hilang muncul. State report disimpan sebelum percobaan dan dipulihkan setelahnya. Matikan dengan `--no-reveal-bookmarks`. Bookmark yang berhasil dicatat di `capture.json`.
- Generate ulang memakai cache selama workspace/report/cakupan sama. Cache lama dari versi pairing sebelumnya otomatis dianggap tidak cocok (`captureVersion`, kini 5 karena pairing memakai hint posisi absolut), jadi capture ulang berjalan sekali setelah upgrade. `--refresh-screenshots` memaksa capture baru. `--screenshot-scope pages|visuals|both` mengatur isi dan `--screenshot-scale 1|2` resolusi (default 1 agar file ringkas). `--no-mobile-screenshots` mematikan capture mobile.
- Halaman tersembunyi dan halaman yang hanya ada di `.pbix` (mis. `Halaman Contoh`) tidak ada di service sehingga tetap placeholder; visual yang tetap gagal dipetakan juga placeholder dan dicatat di `capture.json`.
- Sidecar tetap menang: isi `objects.pages.<page_id>.screenshot` atau `objects.pages.<page_id>.visuals.<visual_id>.screenshot` untuk menimpa hasil otomatis (path relatif atau `data:` URI). Biarkan kosong (`""`) untuk memakai hasil capture — nilai kosong tidak menghapus gambar.
- Perkiraan ukuran HTML: skala 1 sekitar 4 MB untuk report contoh (10 page + 137 visual), skala 2 sekitar 17 MB.
- Token embed dan client secret hanya ada di memori proses; tidak ditulis ke cache, sidecar, log, atau HTML.

## Lineage Power BI Service

Database `data\bi_tools.db` menyimpan workspace, report, semantic model, dataflow, dashboard, dan datasource beserta relasi `contains`, `feeds`, `uses_dataset`, dan `pinned_to`. Scan bersifat read-only terhadap Power BI (hanya REST API) dan menulis ke SQLite lokal.

### Kredensial

CLI membaca `TENANT_ID`, `CLIENT_ID`, dan `CLIENT_SECRET` dari environment. Variabel yang sudah di-set di shell diprioritaskan; file `.env` di folder tooling dipakai sebagai fallback. Contoh:

```powershell
Copy-Item .env.example .env
notepad .env
```

Service principal perlu akses ke workspace yang akan dipindai. Untuk mode admin, aktifkan **Allow service principals to use read-only admin APIs** dan tambahkan service principal ke security group pada pengaturan Admin API tenant.

```powershell
python -m sync run --full                        # katalog + lineage + report + snapshot
python -m sync workspaces --mode admin           # daftar workspace ke SQLite (1-2 request)
python -m sync lineage --mode admin --full       # Scanner API admin
python -m sync lineage --mode member             # hanya workspace yang dapat diakses
python -m sync lineage --include-personal        # sertakan My Workspace (personal)
python -m sync --env-file .env                   # kredensial dari file lain
python extract_lineage.py --stats
python extract_lineage.py --search "Contoh" --workspace "Contoh" --type Report
python extract_lineage.py --impact <node-id>        # item yang memakai node ini (downstream)
python extract_lineage.py --upstream <node-id>      # sumber data node ini (upstream)
python extract_lineage.py --check                   # diagnostik edge dan riwayat scan
python extract_lineage.py --impact <node-id> --export-csv Lineage.csv
```

- Scan admin memakai `admin/workspaces/modified` + Scanner API `getInfo`/`scanStatus`/`scanResult` dengan batch 100 workspace; mode member memakai endpoint `groups` dengan batch 20 workspace.
- Respons `429` diulang maksimal 8 kali mengikuti header `Retry-After`.
- Scan incremental admin hanya memindai workspace yang berubah sejak scan sukses terakhir. Mode member selalu memindai seluruh workspace yang dapat diakses.
- Default scan **tidak** menyertakan My Workspace (personal). Dengan `--include-personal` (opsi program sync), daftar workspace memakai `excludePersonalWorkspaces=false`: report yang berada di My Workspace pengguna ikut muncul sebagai downstream dataset bersama. Opsi ini hanya berjalan di mode admin (service principal tidak menjadi anggota My Workspace siapa pun) dan aktivasi pertama memaksa full scan karena watermark lama tidak memuat personal. Full scan pertama jauh lebih lama (tenant contoh: 866 menjadi 9.337 workspace) dan menambah isi database; nama personal workspace memuat email pemilik.
- Mode incremental memakai watermark dari scan sukses terakhir, tetapi dibatasi ke jendela API (29 hari s.d. 31 menit ke belakang); watermark terlalu baru/terlalu lama tidak dikirim mentah-mentah, dan timestamp rusak memicu full scan.
- `--search`, `--impact`, `--upstream`, `--stats`, dan `--check` memakai database read-only. Tambahkan `--json` untuk hasil mesin, atau `--export-csv` pada `--impact`/`--upstream`.
- Item yang hilang dari scan berikutnya ditandai nonaktif (`is_active=0`) dan tidak muncul lagi di pencarian; riwayat scan tetap tersimpan di tabel `scan_run`.
- `--check` menampilkan edge per tipe, contoh ID node yang tidak ada di tabel `nodes`, jumlah sumber feed tanpa metadata, dan 10 scan terakhir.

### Aturan pemilihan instance Power BI Desktop

- Hanya satu instance terbuka: dipakai otomatis.
- Lebih dari satu instance: perintah berhenti dan menampilkan daftar port. Pilih dengan `--port` atau `--catalog`. Aplikasi tidak memilih diam-diam.
- `--port` hanya memakai port itu; tidak ada cadangan ke instance lain.
- Nama yang tampil di daftar instance adalah nama file report yang dibuka di jendela Power BI Desktop (mis. `Report Uji - localhost:51249`), diambil dari judul jendela. Bila judulnya tidak terbaca, dipakai nama model `Model`.
- Instance dideteksi dari workspace Power BI Desktop, baik installer klasik (`%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces`) maupun Microsoft Store (`%USERPROFILE%\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces`).

### Verifikasi angka acuan

```powershell
python verify_reference.py --pbix "path\ke\Report.pbix"              # report + model (Desktop terbuka)
python verify_reference.py --pbix "path\ke\Report.pbix" --no-model   # report saja
```

Skrip mengekstrak ulang ke folder sementara (workbook di folder tooling tidak ditimpa), lalu membandingkan jumlah halaman, visual, field, slicer, filter, interaksi, measure, kolom, dan jumlah sheet dengan angka acuan. Angka model hanya diperiksa bila ada instance Desktop (atau `--port`/`--catalog`). Exit code: `0` cocok, `1` ada beda/belum diverifikasi, `2` tidak bisa dijalankan. Bila ada lebih dari satu instance, skrip berhenti dan menampilkan pilihan; jalankan ulang dengan `--port`/`--catalog`.

## Compare Semantic Model

Halaman ini membandingkan dua semantic model dari Power BI Service atau instance Power BI Desktop. Perbandingan **read-only**: tidak ada perubahan ke model target.

- Sumber/target: Service (workspace + semantic model) atau Desktop (instance yang terbuka).
- Definisi objek dibaca lewat **TOM di proses CLI anak** dan diserialisasi dengan `TmdlSerializer`/`JsonSerializer`; server tidak memuat TOM agar ADOMD tetap sehat.
- Status: **Same definition**, **Different definition**, **Source only**, **Target only**.
- Aksi disarankan: `Skip`, `Create`, `Update`, `Delete`; aksi target-only default `Skip`.
- Default opsi mengikuti ALM Toolkit: **roles/partitions/annotations/lineage off**, measure/relationship/expression/measure-dependency on. Opsi lain lewat tombol **Options**.
- Opsi **Display warnings for measure dependencies** menandai DAX yang merujuk kolom/measure yang tidak ada di model yang sama; jumlahnya tampil di ringkasan.
- Tabel hasil berupa tree seperti ALM: Table → Measure/Relationship/Calculation item; root Data source/Expression/Role/Perspective/Culture.
- Panel bawah menampilkan definisi **TMDL/TMSL persis dari TOM** untuk baris yang dipilih, dengan highlight baris berbeda.
- DAX/JSON memakai Prism lokal; TMDL memakai grammar lexical lokal. Panel definisi lebih tinggi dan bisa ditarik (`resize: vertical`).
- Diff ditampilkan sejajar: blok sumber hijau, target merah, area kosong hatch penuh dengan border blok; semua baris memakai tinggi sama agar tidak bergeser, perubahan intra-baris ditandai, dan scroll kedua panel sinkron.
- **Validate** hanya validasi lokal; **Generate script** menulis manifest definisi TOM ke `outputs\`; **Export CSV** menulis seluruh hasil.
- Tidak ada tombol Apply/endpoint tulis. Terapkan script secara manual.

## Analisa Semantic Model

Tab ini **read-only**: tidak ada perubahan ke model maupun report. Tujuannya menjawab dua pertanyaan sekaligus: berapa ukuran tiap kolom, dan apakah kolom/measure itu masih dipakai. Halaman **Partisi** adalah pengecualian yang disengaja untuk me-refresh partisi lewat XMLA Read Write dengan konfirmasi `PROCESS`; halaman lain tidak mengirim request tulis.

### Ukuran kolom

Ukuran diambil dari DMV VertiPaq lewat XMLA (`DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS` + `DISCOVER_STORAGE_TABLE_COLUMNS`) dengan metadata `TMSCHEMA_*`:

- **Data** = jumlah `USED_SIZE` segmen `BASIC_DATA` kolom tersebut.
- **Hierarki** = segmen `POS_TO_ID`/`ID_TO_POS` yang diatribusikan ke kolom lewat `TABLE_ID` (`H$Tabel (22)$Kolom (16923)`).
- **Dictionary** = `DICTIONARY_SIZE` per kolom (satu baris `BASIC_DATA` per atribut, tidak dobel dengan hierarki).
- **Cardinality** = `Statistics_DistinctStates` dari `TMSCHEMA_COLUMN_STORAGES`, ditampilkan sebagai baris di **Column details**. Ini metrik VertiPaq (bukan `COUNTROWS(DISTINCT(...))`); kolom yang belum resident bisa bernilai 0 dan ditampilkan `—`.
- **Size** di tree = data + hierarki + dictionary; tooltip memuat rinciannya.
- Kolom `rowNumber` internal tidak ditampilkan; jumlah baris tabel dihitung dari `RECORDS_COUNT` terbesar di antara kolomnya.

Contoh live dataset `Report Uji`: total model **79,1 MB** (data kolom 7,5 MB + hierarki 12,8 MB + dictionary 58,9 MB), 94 kolom setelah rowNumber dibuang; 35 kolom tidak dipakai = **48,1 MB**. Angka ini setara **Total Size** di DAX Studio/VertiPaq Analyzer, bukan ukuran file `.pbix` atau metrik kapasitas.

**Measure** ditampilkan sebagai baris tersendiri (nama, tabel asal, data type, format string, display folder, hidden, DAX, error) tetapi **tidak punya ukuran VertiPaq**; kolom **Size** diisi `-` dan measure tidak ikut perhitungan potensi hemat.

Dataset harus berada di kapasitas Premium/PPU/Fabric dengan **XMLA Read**; tanpa itu ukuran tidak tersedia. Model Direct Lake yang belum resident bisa memberi 0 B dan dicatat di catatan.

### Pemakaian kolom & measure

Pemakaian dibaca dari definisi report, **bukan** dari nama field saja:

1. **Daftar report** — `GET admin/reports?$filter=datasetId eq '<id>'` (lintas workspace, 1 request). Bila service principal bukan Fabric administrator, fallback ke `reports_in_group` + hasil scan lineage di `data\bi_tools.db`. Report di **My Workspace** (`PersonalGroup`) dilewati secara default karena service principal tidak dapat mengaksesnya; centang **Sertakan report My Workspace (personal)** atau `--include-personal` untuk memaksa. Report dari fitur **Power BI App** (nama berawalan `[App]`) selalu dilewati karena salinan report sumbernya sudah ada di daftar.
2. **Definisi report** — Fabric `getDefinition`, hanya untuk report baru/berubah. Polling LRO dipangkas (`poll_wait=1`) karena operasi selesai ±1 detik walaupun `Retry-After` 20 detik.
3. **Dua format didukung**: PBIR (`definition/pages/.../visual.json`) dan **PBIR-Legacy** (`report.json`, `singleVisual.prototypeQuery` + `projections`). Report legacy tidak bisa diekstrak menjadi workbook, tetapi tetap bisa dianalisa di sini. REST memberi label `PBIRLegacy`; label itu dinormalkan ke `PBIR-Legacy` agar gate format tidak melewatinya. Report RDL/paginated dilewati dan dihitung di kolom cakupan.
4. **Jenis pemakaian** yang dicatat: field visual, filter report/halaman/visual, filter query visual, sort, conditional formatting (`objects`/`vcObjects`/`visualContainerObjects`), dan visual calculation (termasuk kolom model yang dirujuk ekspresinya).
5. **Pemakaian di dalam model** dihitung tanpa request tambahan: measure (langsung & berantai), calculated column/table, relationship, sort by, hierarchy/level, RLS (table/column permission), calculation item, KPI, calculated table column, dan langkah M yang menyebut kolom.
6. **Measure** mendapat baris sendiri. Pemakaiannya dihitung dari proyeksi/filter/sort/format visual, ditambah graf measure -> measure (measure yang dipakai measure lain yang dipakai report dianggap **dipakai tidak langsung**). Calculation item, KPI, dan calculated table (termasuk field parameter) yang merujuk measure membuat measure berstatus **Wajib dipertahankan**. Baris legacy `Field`/`Arithmetic` yang memuat nama measure ikut dicocokkan.

Hasil web **tidak ditulis ke `data\bi_tools.db`**. Halaman Analisa memakai satu koneksi SQLite **in-memory per dataset** selama proses server berjalan, memakai skema yang sama (`usage_report`, `usage_field`, `usage_column`, `usage_measure`, `usage_m_query`, `usage_model_ref`, `usage_unresolved`, `usage_scan_run`). Konsekuensinya:

- Memilih semantic model hanya menyiapkan analisa; job berjalan setelah **Analyze now** atau **Analysis** diklik (tanpa memuat snapshot lama dari disk). Hasil sebelumnya hanya dipakai sebagai cache definisi report di sesi yang sama.
- Analisa ulang hanya mengunduh definisi report yang `modifiedDateTime`-nya berubah, jadi run kedua dalam sesi yang sama kembali ±6 detik untuk XMLA.
- Setelah server di-restart, hasil hilang: detail report dan ekspor XLSX meminta analisa ulang.
- Checkbox **Include report usage (pages, visuals, filters)** (default aktif) bisa dimatikan untuk analisa cepat tanpa mengunduh report; kolom/measure tanpa referensi model lalu berstatus **Perlu dicek** dan tab `Report results` kosong.

Di web, filter **Semua tipe/Kolom/Measure** (disimpan di `analysis/object_filter`) mengatur objek yang tampil; pencarian juga mencocokkan nama measure, tabel, display folder, dan potongan DAX. Pada tab datar, klik judul kolom mengurutkan dengan nilai bertipe (Size/Uses/Pages/Visuals turun lebih dulu, Status menurut peringkat `Tidak dipakai` → `Perlu dicek` → `Dipakai` → `Wajib dipertahankan`); klik lagi membalik arah. Urutan disimpan di `analysis/sort_column`/`analysis/sort_desc`. Tab hierarkis tidak diurutkan agar grup tabel dan baris anak tetap konsisten.

### Status kolom & measure

| Status | Arti |
|---|---|
| **Tidak dipakai** | 0 referensi di report, model, dan langkah M, **dan** cakupan report lengkap |
| **Dipakai** | ada referensi; anak node memuat report/halaman/visual atau objek model pemakainya |
| **Wajib dipertahankan** | dipakai relationship, sort by, hierarchy, RLS/OLS, calculation item, KPI, calculated column/table, atau langkah M - dihapus akan merusak model |
| **Perlu dicek** | belum ada referensi tetapi cakupan belum lengkap (report tidak dapat diakses, field tak terpetakan, batas `--max-reports`, atau analisa dihentikan) |

Untuk measure, `Dipakai` mencakup pemakaian langsung oleh visual dan pemakaian **tidak langsung** (measure hanya dirujuk measure lain yang dipakai report). Measure yang hanya dirujuk measure lain yang juga tidak dipakai tetap `Tidak dipakai` dengan catatan, sedangkan yang dirujuk calculation item/KPI/calculated table menjadi `Wajib dipertahankan`.

Cakupan selalu ditampilkan, misalnya `38 report · 25 dipindai · 12 personal dilewati · 1 App dilewati · 0 field tak terpetakan`. Batas `--max-reports`, tombol **Hentikan**, report **tidak dapat diakses** (403/404), dan field tak terpetakan **tidak** boleh menghasilkan klaim "Tidak dipakai" — kolom otomatis menjadi **Perlu dicek**.

Report di **My Workspace** (`PersonalGroup`) dilewati secara default dan tidak dihitung sebagai penghalang cakupan; centang **Sertakan report My Workspace (personal)** (atau `--include-personal`) bila salinan itu memang ingin dianalisa. Report dari **Power BI App** (`[App] …`) selalu dilewati dan juga tidak menghalangi cakupan. Report di workspace biasa yang ditolak 403/404 dicatat `inaccessible`, dicoba ulang paling cepat 24 jam kemudian (atau saat `--refresh`), dan tetap menurunkan cakupan.

### Highlight DAX

Ekspresi DAX di tab **DAX expressions**, dialog detail measure/calculated column, dan baris kode tabel memakai Prism lokal (`web\vendor\prism\`) dengan grammar DAX resmi. Tidak ada CDN dan tidak ada build step.

### Tab Roles (RLS/OLS)
Tab **Roles** menampilkan role model beserta member dan table permission:

- Role: nama, model permission, jumlah member, sumber RLS.
- Member: nama, provider (`AzureAD`/`Windows`), tipe user/group, member ID, modified.
- Table permission: tabel, ekspresi filter RLS, status OLS.

Data berasal dari `TMSCHEMA_ROLES`, `TMSCHEMA_ROLE_MEMBERSHIPS`, `TMSCHEMA_TABLE_PERMISSIONS`, dan `TMSCHEMA_COLUMN_PERMISSIONS`. Tabel tetap memakai 11 kolom Analisa yang sudah ada; role dan member dirender sebagai baris hierarkis.

### Kesehatan model & report

Tab **Health** merangkum temuan dari `core\model_health.py` tanpa request tambahan (semua berasal dari `AnalysisResult`):

| Tingkat | Aturan |
|---|---|
| Kritis | kolom/measure dengan error, visual yang memuat field tak terpetakan |
| Peringatan | tabel yang seluruh kolom/measure-nya tidak dipakai, tabel tanpa relasi, relasi dua arah, relasi many-to-many, dictionary kolom ≥ 50% ukuran kolom (min 1 MB), halaman tanpa visual |
| Info | relasi tidak aktif, relasi terdeteksi otomatis, halaman tersembunyi berisi visual, calculated column tidak dipakai, report tanpa tema |

Tombol **Rules** di toolbar Health membuka dialog yang menjelaskan setiap aturan (sumber data, ambang, dan saran tindakan). Ikon `i` di sel **Rule** membuka dialog yang sama dan menyorot aturan tersebut.

| Aturan | Sumber data | Ambang |
|---|---|---|
| `column_error`, `measure_error` | `TMSCHEMA_COLUMNS`/`TMSCHEMA_MEASURES` (`ErrorMessage`) | — |
| `unused_table` | verdict kolom + measure tabel | semua berstatus `Tidak dipakai` |
| `isolated_table` | `TMSCHEMA_RELATIONSHIPS` | tabel tidak muncul sebagai from/to |
| `bidirectional_relationship` | `CrossFilteringBehavior` | `bothDirections` |
| `many_to_many_relationship` | `FromCardinality`/`ToCardinality` | kedua sisi `many` |
| `inactive_relationship` | `IsActive` | `false` |
| `auto_relationship` | nama relasi / `RelationshipIsAuto` | `AutoDetected_`/GUID |
| `large_dictionary` | `DISCOVER_STORAGE_TABLE_COLUMNS` (`DICTIONARY_SIZE`) | ≥ 50% ukuran kolom dan ≥ 1 MB |
| `unused_calculated_column` | verdict kolom + ukuran VertiPaq | calculated + `Tidak dipakai` + ukuran > 0 |
| `page_without_visuals` | definisi report (`usage_page.visual_count`) | 0 visual |
| `hidden_page_with_visuals` | definisi report (visibilitas halaman) | hidden + visual > 0 |
| `missing_theme` | definisi report (tema) | tema kosong |
| `broken_visual` | hasil pindai report (`usage_unresolved`) | ada field tak terpetakan |

Semua aturan bersifat heuristik internal tool ini, bukan standar resmi Microsoft.

Klik baris membuka detail kolom/measure, lineage tabel, atau tab **Report results**. Kolom **Visual rusak** di tab Report results memakai visual unik dari field tak terpetakan, dan **Skor praktik** dihitung hanya untuk report berstatus `ok`:

```
100 - 5×visual rusak - 3×halaman tanpa visual - 1×field tak terpetakan
```

Masing-masing dibatasi 30/15/20 poin; rincian penalti muncul sebagai tooltip. Skor ini **heuristik**, bukan standar resmi, dan report yang tidak dipindai tetap `-`. Tema dan halaman tersembunyi sengaja tidak mengurangi skor karena keduanya bisa merupakan pilihan desain (mis. halaman tooltip).

### Best practice model

Tab **Best practice** memakai katalog resmi **Microsoft / Tabular Editor Best Practice Analyzer** dari `rules\BPARules.json` (71 aturan; Performance 24, Formatting 15, DAX Expressions 12, Maintenance 9, Error Prevention 8, Naming Conventions 3).

- **54 aturan dievaluasi** dengan data analisa; **17 aturan** ditampilkan sebagai **Not evaluated** beserta alasannya (RLS/role, perspective, data source, referential integrity, annotation `Vertipaq_*`, nama partisi, SourceColumn tidak andal di PBIP).
- Setiap aturan punya status `Violation`, `Pass`, `Not evaluated`, atau `Needs coverage` (untuk aturan yang butuh cakupan report lengkap). Katalog lengkap bisa dibuka lewat tombol **Rules**.
- Tabel menampilkan aturan yang dilanggar dan bisa di-expand untuk melihat objeknya; klik objek membuka detail/lineage.
- Skor model memakai penskalaan logaritmik:

```
skor aturan = round(severity × jumlah objek × log10(N))
```

dengan `N` = jumlah objek model yang dianalisa (kolom + measure + tabel + relasi + M query; minimal 10). Total skor = jumlah skor aturan.
- Verdict model: `<50 Power BI Pro`, `50–200 Good`, `201–400 Ok`, `401–600 Poor`, `601–800 Awful`, `≥800 Power BI Criminal`.

Ekspor XLSX menambah sheet `10_BestPractice_Model` (temuan) dan `11_BestPractice_Model_Rules` (status 71 aturan). Aturan report-level (13 aturan Measure Killer/PBI-Inspector) belum termasuk di versi ini.

### Batasan

- Subscription report dideteksi lewat Admin API **hanya untuk report yang tidak bisa dipindai** (RDL/personal/inaccessible), dengan cache 24 jam dan batas 25 report per run. Subscription aktif pada report seperti itu membuat kolom tanpa referensi menjadi `Perlu dicek`, bukan `Tidak dipakai`. Data alert, Excel/ad-hoc (Analyze in Excel), Q&A, personalisasi user, dan pemetaan field RDL/personal tetap tidak terdeteksi. Kuota endpoint subscription 200 request/jam.
- Report RDL/paginated tidak dianalisa field-nya dan dilaporkan sebagai `unsupported`.
- Report di My Workspace tidak dapat diakses service principal pada program sync; default dilewati. Akun user yang punya akses bisa membukanya secara manual.
- Report dari Power BI App (`[App] …`) selalu dilewati; pemakaian yang hanya ada di salinan app tidak dihitung.
- Report di workspace biasa yang tidak dapat diakses akun user dicatat `inaccessible` dan membuat cakupan belum lengkap sampai akses diberikan atau report dihapus/dipindahkan.
- Mode **Sertakan report dari workspace lain** dimatikan memakai daftar report workspace (`reports_in_group`) yang tidak memuat waktu modifikasi, jadi semua report diunduh ulang setiap analisa; mode admin memakai cache.
- Tidak ada aksi hapus kolom/measure; verdict hanya saran, perubahan tetap dilakukan di Power BI Desktop/Tabular Editor.
- Measure ditampilkan termasuk yang hidden (kolom Hidden = Yes); ukurannya tidak tersedia karena measure tidak menyimpan data.

### Kinerja

Analisa satu dataset: ±6 detik untuk XMLA + 1,5–12 detik per report (bergantung jumlah parts). Scan report mengunduh definisi secara paralel: `--scan-workers` (1–4, bawaan 2) dan `scan_workers` di payload web. Pada dataset 186 report, 12 report `refresh=True` memakan 36–56 dtk serial, 23–44 dtk dengan 2 worker, dan 18 dtk dengan 4 worker. Polling lebih rapat dari 1 dtk justru memicu throttling Fabric, jadi nilainya tetap 1 dtk. Di web, run berikutnya memakai cache definisi report di sesi server (<30 dtk); CLI memakai cache SQLite antar-run. Atur **Hentikan**, `--max-reports`, `--scan-workers`, atau matikan **Include report usage** (`--model-only`) untuk analisa cepat.

### Ekspor XLSX

`Export XLSX...` (atau `--out` di CLI) menulis `Analisa_Semantic_Model_<nama>_<id8>.xlsx` dengan sheet:

| Sheet | Isi |
|---|---|
| `01_Summary` | ukuran model, jumlah report/personal/inaccessible, jumlah kolom/measure per status, catatan |
| `02_Columns` | semua kolom + ukuran data/hierarki/dictionary, jumlah baris, status, jumlah pemakaian, alasan |
| `03_Report_Usage` | satu baris per titik pemakaian di report (kolom maupun measure) |
| `04_Model_Usage` | referensi dari objek model (measure, relasi, RLS, M, dst.) |
| `05_Reports` | status setiap report (ok/personal/app/inaccessible/unsupported/failed) + pesan |
| `06_Tables` | ukuran per tabel |
| `07_Unresolved` | field yang tidak bisa dipetakan (report, halaman, visual, queryRef, alasan) |
| `08_Measures` | semua measure + data type, status, pemakaian, format, DAX, alasan |
| `09_Health` | temuan kesehatan model/report (severity, area, aturan, objek, ukuran, detail) |
| `10_BestPractice_Model` | temuan Best Practice model + skor per aturan |
| `11_BestPractice_Model_Rules` | status 71 aturan katalog (Violation/Pass/Not evaluated/Needs coverage) |

## Paket dan rilis

Aplikasi dibagikan sebagai paket Windows: `BI Tools.exe` (server web lokal + browser) dan `bi-tools-cli.exe` (perintah baris). Semua perintah di bagian sebelumnya memakai bentuk `bi-tools-cli <perintah>` saat dijalankan dari paket, mis. `bi-tools-cli report --report "path\ke\Report.pbix"`.

Paket membawa DLL ADOMD di `libs\` dan DLL TOM/MSAL di `libs\tom\`. Halaman Partisi menjalankan **inventaris dan refresh TOM di proses CLI anak** (`bi-tools-cli.exe`), sedangkan row count DMV juga lewat proses anak terpisah karena kedua assembly Microsoft.AnalysisServices tidak kompatibel dalam satu proses. Proses server hanya memakai ADOMD. Jangan menghapus `libs\tom\` atau memindahkannya ke `_internal`. DLL Microsoft Analysis Services/MSAL tetap tunduk pada lisensi Microsoft; perhatikan ketentuan redistribusi bila paket dibagikan.

Rilis otomatis berjalan di GitHub Actions setiap tag `vX.Y.Z`:

1. ubah `core\version.py` (`__version__`) dan `CHANGELOG.md`;
2. commit, lalu `git tag -a v<versi> -m "BI Tools <versi>"`;
3. `git push origin main --tags`.

`.github\workflows\release.yml` menjalankan uji, membangun paket, lalu menerbitkan rilis dengan tiga aset:

| Aset | Isi |
|---|---|
| `BITools-Setup-<versi>.exe` | installer Inno Setup (per pengguna, tanpa UAC) |
| `BITools-<versi>-portable.zip` | folder aplikasi siap ekstrak |
| `SHA256SUMS.txt` | checksum SHA-256 kedua aset |

Tag yang tidak sama dengan `core\version.py` menggagalkan build. `workflow_dispatch` hanya menghasilkan artefak (tanpa menerbitkan rilis); push/PR menjalankan `ci.yml` (flake8 + uji).

Build lokal memakai jalur yang sama dengan CI:

```powershell
python -m pip install -r requirements.txt "pyinstaller==6.22.3"
winget install JRSoftware.InnoSetup                                    # sekali saja, untuk installer
powershell -File packaging\build.ps1                                   # uji + dist + zip + installer
powershell -File packaging\build.ps1 -SkipTests -SkipInstaller          # hanya dist + zip portable
```

`build.ps1` mencari `ISCC.exe` di lokasi standar Inno Setup 6. Bila Inno dipasang di tempat lain (mis. mode portable), set `$env:BI_TOOLS_ISCC = "path\ke\ISCC.exe"`.

Hasil: `dist\BI Tools\` (folder aplikasi), `dist\BITools-<versi>-portable.zip`, dan `packaging\Output\BITools-Setup-<versi>.exe`.

Catatan paket:

- Paket memakai mode **onedir**. `templates\`, `libs\` (ADOMD), dan `web\` disalin ke samping exe karena `core\paths.py` mencari aset di folder aplikasi, bukan di `sys._MEIPASS`; mode onefile akan memutus pencarian itu.
- Installer memasang per pengguna (`%LOCALAPPDATA%\Programs\BI Tools`) sehingga tidak perlu UAC. Opsi "all users" tetap tersedia; dalam kasus itu `outputs\` dan `data\` otomatis pindah ke `%LOCALAPPDATA%\BI Tools`.
- Uninstaller tidak menghapus `outputs\` dan `data\`.
- Screenshot TSD butuh Chromium (±150 MB) dan tidak ikut dibundel. Capture pertama mengunduhnya otomatis ke `%LOCALAPPDATA%\ms-playwright` (bertahan saat aplikasi di-upgrade); installer juga menyediakan task opsional, dan kapan saja bisa diulang dengan `bi-tools-cli install-browser` (tanpa argumen = `install chromium`).
- ZIP portable yang diunduh ditandai Windows sebagai "berasal dari internet" (Mark of the Web). Aplikasi membuka blokir otomatis DLL .NET yang dibutuhkan (`Python.Runtime.dll` dan ADOMD) saat XMLA pertama dipakai. Bila folder aplikasi read-only sehingga penanda tidak bisa dihapus, jalankan sekali:
  ```powershell
  Get-ChildItem -Recurse -Path "<folder aplikasi>" | Unblock-File
  ```
  Alternatif: klik kanan ZIP → **Properties** → **Unblock** sebelum mengekstrak, atau pakai installer yang berkasnya dibuat ulang tanpa penanda.
- Paket belum ditandatangani digital, jadi Windows SmartScreen bisa menampilkan peringatan saat pertama dijalankan.

## Uji

```powershell
python -m unittest discover -s tests -t .
```

Uji angka acuan dan file contoh butuh path `.pbix` lewat environment (tanpa env, uji tersebut dilewati):

```powershell
$env:RUN_PBIX = "path\ke\Report.pbix"            # angka acuan report/model
$env:RUN_MODEL_CATALOG = "<Catalog di 01_Model_Overview>"   # bila ingin angka acuan measure/kolom
$env:RUN_LIVE_PBIX = "path\ke\live.pbix"         # uji live connection
$env:RUN_DQ_PBIX = "path\ke\directquery.pbix"    # uji model lokal DirectQuery
python -m unittest discover -s tests -t .
```

Uji model live (butuh Power BI Desktop terbuka):

```powershell
$env:RUN_LIVE_TESTS = "1"; python -m unittest discover -s tests -t .
```

Smoke test browser (Playwright) memeriksa antarmuka nyata: semua view, langkah TSD, pergantian bahasa, aset gagal, dan overflow. Butuh Chromium dan tidak dijalankan di CI utama:

```powershell
python -m pip install playwright
python -m playwright install chromium
$env:RUN_WEB_SMOKE = "1"; python -m unittest tests.test_web_smoke -v
```

Workflow `.github\workflows\web-smoke.yml` menjalankan uji yang sama saat `web\`, `server\`, atau berkas smoke berubah. Endpoint daftar instance Desktop dipalsukan di uji ini supaya tidak bergantung pada Power BI Desktop yang terbuka.

## Catatan

- Logika di `core\` tidak mencetak ke terminal dan tidak menghentikan proses; kesalahan dilaporkan sebagai `ExtractionError`.
- `Semantic_Model_Metadata.xlsx` memuat 24 sheet (00–23). Peringatan lineage M ada di sheet `23_M_Lineage_Warnings`.
- `Report_Metadata.xlsx` memuat 13 sheet dengan urutan: `00_README`, `01_Pages`, `02_Bookmarks`, `03_Interactions`, `04_Visual_Fields`, `05_Slicers`, `06_Sync_Slicers`, `07_Filters`, `08_Visual_Summary`, `09_Usage_Measures`, `10_Usage_Columns`, `11_Validation`, `12_Model_Inventory`.
- Sheet `01_Pages` memuat `is_hidden` yang diisi dari `page.json` PBIR: `TRUE` bila `visibility=HiddenInViewMode` atau halaman bertipe `Tooltip`, selain itu `FALSE`.
- Sheet `08_Visual_Summary` memuat `is_hidden` dari `visual.json` (termasuk visual di dalam group yang hidden) serta `position_x_abs`/`position_y_abs` (posisi visual + seluruh group induk) yang dipakai sebagai hint pairing screenshot.
- Sheet `06_Sync_Slicers` berisi slicer yang sync antar halaman (dibaca dari `visual.syncGroup` di `visual.json`): nama grup, halaman asal, kolom, dan daftar halaman lain dalam grup. Baris diurutkan per grup lalu halaman.
- Kolom usage report pada `04_Measures` dan sheet `12_Model_vs_Report` dibaca dari `Report/definition` di dalam `.pbix`.
- Agregasi level visual (mis. `Min(TabelA.Kolom1)`) dihitung sebagai pemakaian kolom dasarnya, bukan objek model baru. `12_Model_vs_Report` menandainya dengan catatan `Dipakai visual lewat agregasi: Min, …`.
- Report hanya menerima `.pbix` dengan PBIR GA (`Report/definition`). Format `Report/Layout` legacy ditolak.
- Deteksi jenis sumber memakai isi `.pbix`: entry `DataModel` berarti model lokal; tanpa `DataModel` tetapi ada koneksi `pbiServiceLive` berarti live connection. `RemoteArtifacts` saja bukan penanda live karena `.pbix` model lokal yang pernah dipublish juga menyimpannya.
- Import vs DirectQuery tidak dibaca dari file (isi `DataModel` berupa backup XPress9). Mode per tabel dilaporkan dari XMLA saat model diekstrak (`Import`, `DirectQuery`, `Dual`, dan sebagainya).
- Untuk live connection, metadata model tidak tersedia di file. Ekstraksi report berjalan dengan validasi dilewati atau memakai workbook model yang sudah ada (`TIDAK DIVALIDASI` bila tidak ada), dan hanya `Report_Metadata.xlsx` yang dibuat.
- Report dari Power BI Service diambil lewat `POST /v1/workspaces/{workspaceId}/reports/{reportId}/getDefinition` (Fabric API, long running operation). Part `InlineBase64` ditulis ke folder temporary sebagai PBIR sebelum diekstrak; `StaticResources` tidak dipakai.
- **Metode HTTP `DELETE` dilarang** untuk API apa pun (Power BI, Fabric, API lokal). Operasi hapus/bersihkan memakai `POST` (`/api/tsd/cache/clear`, `/api/jobs/{id}/cancel`); `Transport.request` menolak `DELETE` sebelum dikirim. Larangan ini hanya metode HTTP; `DELETE FROM` pada SQLite lokal tetap dipakai untuk pemeliharaan tabel.
- Report service harus memakai format PBIR. Report PBIR-Legacy (satu file `report.json`) tidak bisa diekstrak; simpan ulang report sebagai PBIR di Power BI Desktop lalu publish lagi.
- Semantic model dari service diekstrak lewat XMLA. Halaman Ekstraksi Service selalu memakai endpoint workspace + catalog; pemanggil CLI/`core\jobs.py` juga menerima instance Power BI Desktop (port + catalog). Jika cakupan menyertakan report, definition report service dipakai sebagai sumber kolom usage model tanpa perlu file `.pbix`.
- Token hanya disimpan di memori proses. Satu service principal dipakai untuk Fabric API (`https://api.fabric.microsoft.com/.default`), Power BI REST, dan XMLA (`https://analysis.windows.net/powerbi/api/.default`); token Power BI yang sama dipakai embed/Scanner/ADOMD. Token disegarkan 2 menit sebelum kedaluwarsa, termasuk lewat `OnAccessTokenExpired` pada koneksi ADOMD.
- Bila XMLA sempat gagal dengan `Specified cast is not valid` di `DeserializeFromGlobalObject`, penyebabnya cache controller ADOMD (`XmlaLibControllerCache`) yang dipakai bersama beberapa aplikasi. Aplikasi membersihkan cache itu sebelum koneksi XMLA pertama dan mengulang sekali secara otomatis. Bila masih gagal, tutup Power BI Desktop/DAX Studio/Tabular Editor/SSMS lalu jalankan ulang.
- Folder output default `outputs\` di samping aplikasi (folder executable saat dipaket, root repo saat dijalankan sebagai skrip); dapat diubah dan nilainya tersimpan. Folder tidak lagi mengikuti folder `.pbix`. Bila folder aplikasi tidak bisa ditulis (mis. `C:\Program Files`), hasil pindah ke `%LOCALAPPDATA%\BI Tools\outputs`.
- Sesi web selalu mulai bersih: pilihan workspace/report Service, workspace/report TSD, workspace/dataset Analisa, dan instance Desktop dikosongkan tiap aplikasi dibuka. Kredensial, RLS, path database, cakupan ekstraksi, filter/sort, tab aktif, dan opsi render TSD tetap tersimpan.
- Untuk paket executable: `templates\tsd.template.html` dan `libs\` harus berada di samping exe (diatur `packaging\bi_tools.spec`); `outputs\` dan `data\` dibuat saat runtime, jangan di-bundle. Lihat [Paket dan rilis](#paket-dan-rilis).
- `Report_Metadata.xlsx` dan `Semantic_Model_Metadata.xlsx` adalah file biner hasil generate; setiap regenerasi menghasilkan diff biner.
- `data\bi_tools.db`, `outputs\`, file `*.db` lain, dan `.env` di-ignore git. Jangan meng-commit database lineage atau secret.
- Credential web disimpan di `data\settings.json` (dulu QSettings `HKCU\Software\BITools\Metadata`, kunci `auth/*`) sebagai teks biasa; CLI memakai environment/`.env`. Aplikasi tidak pernah menulis kredensial ke database lineage. Kunci lama `lineage/*` dan `paths/*` dimigrasi sekali oleh `server\settings_store.SettingsStore` saat server pertama kali membaca preferensi. Setelan dari organisasi lama (`2W-Dragon`/`BI Tools`) disalin sekali ke organisasi baru (`settings/org_migrated_v2`) tanpa menimpa nilai yang sudah ada; setelah migrasi terverifikasi, kunci lama boleh dihapus manual:
  ```powershell
  Remove-Item 'HKCU:\Software\2W-Dragon' -Recurse
  ```
- Nama node Workspace mengikuti nama workspace saat scan terakhir; node Datasource memakai nama `"<tipe>: <server> / <database>"` atau URL/path bila tersedia.
- `--check` pada salinan database saat ini mencatat 4 sumber edge `feeds` dan 11 sumber `uses_dataset` yang belum memiliki metadata node; aktifkan detailed metadata admin lalu jalankan `--scan --full` bila angka ini perlu ditekan.

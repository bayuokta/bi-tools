# Changelog

Riwayat pengembangan tooling metadata Power BI, 2026-11-12 s.d. 2026-11-16 (62 commit).

Tag `v0.1.0` menunjuk commit terakhir di `main`: baseline satu commit berisi seluruh
perubahan di bawah ini, ditambah perubahan pengerasan rilis sesudahnya. Riwayat
per-commit sebelum baseline (62 commit) disimpan di luar repo sebagai
`bi-tools-main-62commits.bundle`.

## Belum dirilis

### Perbaikan

- Aset statis (`/index.html`, `/app.js`, `styles.css`, modul `js/`) dikirim dengan
  `Cache-Control: no-store`. Sebelumnya Chrome memakai heuristic caching sehingga
  tampilan lama bisa bertahan berhari-hari setelah aplikasi diperbarui; port lokal
  yang selalu sama membuat cache key tidak berubah.
- Halaman Analisa: opsi **Include reports from other workspaces** dan
  **Include My Workspace** tidak lagi dinonaktifkan saat *Include report usage*
  dimatikan; muncul hint bahwa keduanya hanya berlaku bila report usage disertakan.
- Halaman Analisa: baris hasil pencarian kini bisa dibuka/ditutup dan tombol
  **Expand all**/**Collapse all** tetap bekerja saat kotak pencarian terisi.
- Halaman Analisa: kata kunci pencarian disimpan per tab, jadi filter di DAX
  tidak ikut menyaring M queries (dan sebaliknya).
- Halaman Analisa: Table details menyertakan tombol **Copy expression** dan
  ekspresi M diwarnai dengan grammar M (sebelumnya memakai grammar DAX).
- Halaman Analisa: baris kode di tab DAX Expressions dan M queries punya tombol
  copy di pojok kanan; M queries kini memakai syntax highlight.
- Halaman Analisa: dialog details punya tombol maximize/restore.
- Grafik Relationships memakai latar kanvas bertitik seperti lineage dan kartu
  tabel dapat digeser (edge mengikuti, posisi direset saat analisa baru).
- Halaman awal saat URL dibuka kini **Analisa** (Model analysis), bukan
  Extraction & TSD. Halaman ekstraksi tetap menjadi langkah 1 alur ekstraksi.
- Login XMLA interaktif kini terlihat di log job: `Menunggu login XMLA...` dan
  `Login XMLA selesai.` Jendela `BI Tools - XMLA login` dipaksa selalu di depan
  selama koneksi, dan pembukaan worker dibatasi 300 detik dengan pesan yang
  menyebut jendela login (sebelumnya job bisa tampak menggantung tanpa batas).
- Tab **All results**: satu klik pada panah baris kini langsung membuka/menutup
  walau pencarian aktif (sebelumnya klik pertama tidak berefek karena status
  dihitung tanpa `ignoreQuery`).
- Blok **Expression** di Measure/Column details, DAX expression, dan Table
  details punya ikon copy di kanan atas, sama seperti baris kode di tab
  DAX Expressions dan M queries.
- **View column lineage graph** dirapikan: lebar kartu mengikuti panjang label
  (170–320 px), rantai M sejajar dengan kartu tabel yang dibangunnya, tinggi
  artifact mengikuti isi nyata (tanpa ruang kosong besar), datasource sejajar
  dengan kartu tujuannya, halaman report diurutkan mengikuti baris model yang
  dirujuk, dan urutan layer memakai transpose untuk menekan persilangan edge.
  Graph otomatis **Fit** saat canvas lebih besar dari viewport.
- Tab All results kini menampilkan kelompok pemakaian dengan urutan seperti
  Measure Killer: **Used in visuals**, **Used in artifacts** (dulu *Model
  references*), **Used in visual level filters**, **Used in report level
  filters**, **Used in Power Query**, **Used as default label**, **Used in
  calculated tables**, dan **Used in hierarchy** (sebelumnya hanya sebagian
  yang tampil).
- Ekspor halaman Analisa kini **per tab**: tab All results menulis template Measure
  Killer (25 kolom, satu baris per pemakaian), tab lain *coming soon*, dan workbook
  lama tetap tersedia lewat `tab=full`.
- Hierarchy eksplisit dibaca sebagai objek sendiri (Type `Hierarchy`, `Uses` dari
  visual/filter levelnya) dan ikut diekspor; level auto date/time tetap dihitung
  pada kolom basis.
- Pemakaian filter dihitung per **filter object** (dua filter pada satu visual tetap
  terhitung), formatting hanya dibuang bila field yang sama dipakai di visual yang
  sama, dan calculated column `[Kolom]` tanpa nama tabel diresolusi ke tabelnya.
- Level hierarchy otomatis date/time dipetakan ke kolom basis; query passthrough
  tabel lain dan incremental refresh dihitung sebagai pemakaian Power Query.
- Proyeksi `Arithmetic` (mis. `Divide(Sum(Tabel.Kolom), ...)`) kini dipetakan ke
  field di dalamnya, sehingga measure tidak lagi dipinjamkan ke kolom bernama sama
  dan hitungan `# used` measure/kolom lebih akurat.
- Filter PBIR v2 tanpa `field` sekarang dibaca dari `filter.From`/`Where`
  (filter gabungan lintas entity diabaikan), dan
  level hierarchy tidak lagi dihitung sebagai pemakaian kolom; pemakaian
  filter/field/measure dihitung sekali per visual.
- Paritas kolom/measure dengan Measure Killer untuk dataset SDMS:
  `calculatedTableColumn` lain dilabeli `Column`, data type memakai nama ramah
  (Text/Integer/Double/DateTime), ekspor menambah kolom `Source`, `Uses`/status
  mengabaikan langkah M, dan pemakaian field/measure dihitung sekali per visual.
- Kolom tabel field parameter kini bertipe **Field parameter** (bukan
  `Column`/`calculatedTableColumn`), dan label **Type** di tab All results
  mengikuti bahasa aktif (`Column`/`Kolom`, `Field parameter`).
- Grafik **Relationships** kini benar-benar menampilkan latar bertitik seperti
  lineage. Sebelumnya `background-image` tertimpa shorthand `background` dari
  `.graph-wrap`; selektor diganti menjadi `.graph-wrap.rel-graph-canvas`.
- Tab **All results**: rujukan measure dipisah menjadi **Model references**
  (langsung, `depth <= 1`) dan **Indirect references** (transitif, label
  menyertakan `depth N`). Sebelumnya semua rujukan transitif tampil dalam satu
  grup sehingga satu measure bisa terlihat dirujuk 10 measure padahal hanya 1
  yang langsung. Kolom **Uses** = pemakaian report + rujukan model **langsung**
  (relationship/RLS/measure ikut dihitung, seperti Measure Killer); rujukan
  transitif tidak menambah `Uses`. Ekspor XLSX menambah kolom
  **Direct references** dan **Transitive references**.
- Perhitungan **Uses** diselaraskan dengan Measure Killer: `key column`
  (`IsKey`), RLS tanpa kualifikasi tabel (`[Email] = USERPRINCIPALNAME()`),
  field parameter (kolom tabel parameter dan measure yang dirujuk `NAMEOF`),
  serta referensi `'Tabel'[Measure]` kini terdeteksi. Langkah M dan sort visual
  tetap disimpan di detail tetapi tidak menambah `Uses`.
- Pemakaian **formatting** untuk field yang sudah dipakai sebagai field visual
  di report tidak lagi menambah `Uses` (memperbaiki `Month` dan `Quarter`).
- Scanner report menghitung formatting per properti dan mencatat
  `fieldParameters` sebagai pemakaian visual; kolom `Parameter Fields` pada
  tabel field parameter dihitung sebagai column grouping. Perbandingan `Uses`
  dengan Measure Killer pada model uji kini **0 selisih**.

## 2026-11-26 - Rilis 0.9.1

### Perbaikan

- Tombol **Sign in** dan **Sign out** kembali berfungsi. Handler-nya ikut
  terhapus saat pemisahan paket sync di 0.9.0 sehingga tombol tidak melakukan
  apa pun.
- Restore dengan opsi **Overwrite** gagal saat memantau operasi Fabric karena
  `updateDefinition` selesai tanpa payload hasil. Hasil kosong sekarang
  diperlakukan sebagai sukses; create tetap mengambil ID item dari hasil.
- Field Workspace/File/Target di halaman **Backup and Restore** memakai
  komponen combo yang sama dengan halaman lain (sebelumnya dropdown native).

### Pembersihan

- Sisa mode service principal di web dihapus (`auth_mode`, `principal`,
  `set_principal`, cabang service di status auth, field `auth_mode` di payload).
  Web selalu memakai `UserSession`.
- Guard arsitektur baru: `server/` tidak boleh memuat kode service principal,
  `web/` tidak boleh memuat `auth_mode`, dan literal `/updateDefinition` hanya
  boleh ada di `core/fabric_api.py`.

## 2026-11-25 - Rilis 0.9.0

### Halaman Backup and Restore

- Halaman **Backup and Restore** dengan dua tab: menyimpan definisi semantic
  model dan report per workspace, lalu memulihkannya dari file backup.
- Model diekspor dari Fabric `getDefinition` (TMDL + `definition.pbism` +
  `.platform`) dengan `model.bim` dari TOM sebagai cadangan; report disimpan
  sebagai part `getDefinition` apa adanya (PBIR dan legacy).
- Item dipilih lewat dua multi-select combo (semantic model dan report) dengan
  pencarian, pilih semua, dan hitungan.
- Satu ZIP per item di folder `Backup_<workspace>_<waktu>/` + `manifest.json`;
  kegagalan satu item tidak menghentikan item lain.
- Restore memakai Fabric `updateDefinition`/create dengan akun user: item baru
  (`<nama> restored <tanggal>`) atau menimpa item yang dipilih (dengan
  konfirmasi). ZIP divalidasi dulu (path aman, part wajib, `model.bim`). Model
  hasil restore belum diproses dan perlu di-refresh manual.
- `.pbix` tidak dipakai karena diblokir untuk incremental refresh/perubahan
  TOM. Data, jadwal refresh, permission, kredensial, dan sensitivity label
  tidak termasuk.

### Perubahan UI

- Urutan sidebar mengikuti mockup: Analisa, Compare model, Partisi,
  Ekstraksi & TSD, Lineage, **Backup and Restore**, Pengaturan.
- "Compare semantic model" menjadi **Compare model**.
- Ikon aplikasi/installer baru: mark grafik kuning di latar grafit.

## 2026-11-25 - Rilis 0.8.0

### Pemisahan program sync

- Paket baru `sync\` (`admin_api.py`, `catalog.py`, `lineage.py`, `flow.py`)
  menjadi satu-satunya pemilik Admin API Power BI; aplikasi web dan
  `bi-tools-cli` tidak lagi memuat endpoint `admin/*`.
- `bi-tools-cli sync`, `lineage --scan`, dan `lineage --sync-workspaces`
  dihapus; penggantinya `bitools-sync run`, `bitools-sync workspaces`,
  `bitools-sync lineage`, dan `bitools-sync check`.
- Pengaturan web tidak lagi punya kredensial service principal, tes token,
  sinkronisasi katalog, atau scan lineage.
- `report_catalog` tetap diisi program sync; definisi dan usage report tetap
  diambil live oleh aplikasi user.

### Upload snapshot ke SharePoint

- Program sync bisa mengunggah snapshot langsung ke document library SharePoint
  lewat Graph app-only: `--upload`, `--sharepoint-host/site/library/folder`,
  atau `SP_*` dari `.env`.
- File >10 MiB memakai upload session; folder tujuan dibuat otomatis;
  `.sha256` diunggah setelah database.
- Perintah `bitools-sync check` menampilkan site, library, folder, dan isi
  folder untuk verifikasi.

### Subscription report dihapus

- Deteksi subscription (endpoint admin, tabel `usage_subscription*`, sheet
  `12_Subscriptions`, dan badge UI) dihapus.
- Konsekuensi: subscription report, data alert, Excel/ad-hoc, Q&A, dan
  personalisasi user tidak terdeteksi; kolom tanpa referensi pada report tak
  terpindai tetap `Perlu dicek` lewat cakupan.

### Paket dan notebook

- Wheel `bitools_sync` (dependensi `msal`, `requests`, `python-dotenv`)
  diterbitkan sebagai aset rilis untuk dijalankan di notebook Fabric.
- `notebooks\bi_tools_sync.ipynb` menjalankan sync lalu upload dengan
  parameter notebook.
- Guard arsitektur memastikan `admin/` dan `graph.microsoft.com` hanya ada di
  paket `sync`.

## 2026-11-25 - Rilis 0.7.0

### Autentikasi akun 365

- Aplikasi web kini memakai akun Microsoft 365 tanpa client id
  (`azure-identity` browser). Tidak ada client secret di aplikasi interaktif.
- Token Power BI/Fabric diambil dari sesi user; XMLA memakai login interaktif
  MSOLAP karena token browser ditolak XMLA.
- Pengaturan memiliki **Sign in/Sign out**, status akun, dan token Fabric.
- Program terpisah **`bi-tools-sync`** memegang service principal dan menjalankan
  Admin API (katalog workspace, Scanner API, `admin/reports`).

### Database bersama

- Tabel baru `report_catalog` di snapshot SQLite; Analisa membaca daftar report
  dari DB lalu fallback ke endpoint member, tanpa Admin API.
- `bi-tools-sync` menerbitkan snapshot konsisten (`VACUUM INTO`), checksum
  SHA-256, dan `schema_version`.
- Aplikasi mengunduh snapshot ke cache lokal dan membukanya read-only; SQLite
  tidak dibuka langsung dari folder SharePoint/OneDrive.
- Subscription report dan sinkronisasi katalog/lineage hanya tersedia di program
  sync; aplikasi user menolak job admin.

### Lain-lain

- Koneksi XMLA/TOM mendukung `Interactive Login` + `Identity Mode=Connection`.
- `open_client`/`connect_server` menerima mode `interactive`; proses anak partisi
  dan compare mengirim payload `interactive` tanpa token.
- Paket berisi tiga executable: `BI Tools.exe`, `bi-tools-cli.exe`, dan
  `bi-tools-sync.exe`.
- Jendela login worker ADOMD/TOM hanya tampil saat login. Setelah koneksi
  berhasil jendela disembunyikan, worker menutup diri setelah idle 10 menit, dan
  seluruh worker dihentikan saat server berhenti.
- Batasan diketahui: pada mode user, setiap proses anak TOM/DMV tetap membuka
  sesi MSOLAP sendiri, sehingga login pertama per proses masih memerlukan
  identitas MSOLAP (umumnya silent setelah login pertama).
- Program sync terpaket menerima `--env-file` agar kredensial service principal
  bisa dibaca dari berkas di luar folder aplikasi.

## 2026-11-22 - Rilis 0.6.4

### Perbaikan web

- Semua jalur error di modul view sekarang memakai `app.reportError`: kegagalan
  ekspor lineage/dependensi/gambar, simpan sidecar TSD, hapus cache screenshot,
  buka folder, pencarian lineage, dan pembatalan job menampilkan pesan lagi
  (sebelumnya `ReferenceError: reportError is not defined`).
- Guard job lokal di tombol **Analysis**, **Extraction**, **TSD**, dan **Partisi**
  dihapus. `startJob()` selalu mengecek status job ke server lebih dulu, jadi job
  basi setelah koneksi SSE putus tidak lagi mengunci tombol sampai halaman
  di-refresh.
- `state.jobPending` menahan klik ganda selama POST job berlangsung.

### Partisi

- Tombol **Expand all** dan **Collapse all** untuk membuka/menutup semua grup
  tabel sekaligus.
- Klik di mana pun pada baris grup (kecuali checkbox) membuka atau menutup grup.
- Status grup yang terbuka dipertahankan saat inventaris dimuat ulang selama
  tabelnya masih ada.
- Nama tabel dan badge jumlah partisi berada di kolom **Table**; kolom
  **Partition** pada baris grup berisi `—`.

### Tes dan dokumentasi

- Tes arsitektur memindai semua referensi helper `app.js` (termasuk
  `.catch(reportError)`), bukan hanya pemanggilan `nama(`.
- Smoke test browser merender inventaris partisi dengan state palsu: grup,
  expand/collapse, pilih semua, dan Expand all/Collapse all.
- README diperbaiki: versi pengembangan usang dihapus, jalur TOM Partisi
  dijelaskan sebagai proses CLI anak, dan pengelompokan partisi didokumentasikan.

## 2026-11-22 - Rilis 0.6.3

### Compare Semantic Model

- Diff expression memakai baris sejajar seperti ALM Toolkit: baris hapus di kiri,
  baris tambah di kanan, penanda hatch untuk celah, dan penyorotan perubahan
  dalam baris.
- Tinggi baris blok dan baris kosong disamakan supaya kedua panel tetap sejajar;
  hatch memenuhi lebar panel tanpa border merah.
- Highlight TMDL/DAX/JSON memakai Prism lokal (tanpa CDN) dengan grammar TMDL
  ringan; panel expression lebih tinggi dan bisa di-resize.

### Partisi

- Inventaris partisi dikelompokkan per tabel: tabel incremental dengan banyak
  partisi tampil sebagai satu baris grup yang bisa di-expand/collapse.
- Baris grup merangkum jumlah partisi, total rows, rentang, mode/source/state
  unik, waktu proses terbaru, dan chip **Incremental**; checkbox grup memilih
  seluruh partisi tabel.
- Selection refresh tetap memakai pasangan `{table, partition}` sehingga payload
  proses tidak berubah.

### Perbaikan web

- Helper partisi (`partitionRows`, `partitionSelectedRows`, `partitionTime`,
  `partitionRefreshLabel`) dipindahkan ke modul Partisi supaya tidak lagi muncul
  `partitionRows is not defined`.
- Panggilan `setChip`/`startJob` di halaman Partisi memakai jembatan `app.*`.
- Job lokal yang basi tidak lagi mengunci tombol: status dicek ke server sebelum
  menolak job baru, dan state dibersihkan pada semua jalur selesai/gagal.
- Tes penjaga arsitektur baru memastikan helper UI di modul view selalu dipanggil
  lewat `app.*`.

## 2026-11-22 - Rilis 0.6.2

### Compare Semantic Model

- **Peringatan dependensi measure** mengikuti opsi ALM: referensi DAX ke kolom/
  measure yang tidak ada di model yang sama dicatat di snapshot TOM dan
  ditampilkan sebagai jumlah **Warnings** di ringkasan Compare.
- Opsi `Display warnings for measure dependencies` sekarang benar-benar
  mengaktifkan/mematikan pemeriksaan itu.

## 2026-11-22 - Rilis 0.6.1

### Compare Semantic Model — TOM/TMDL persis

- Snapshot compare sekarang dibuat lewat **TOM di proses CLI anak** dan
  diserialisasi dengan `TmdlSerializer` (atau `JsonSerializer` untuk TMSL),
  bukan parser properti buatan sendiri.
- Server tidak memuat TOM; proses anak memakai token lewat stdin, sehingga
  koneksi ADOMD di server tetap sehat.
- Definisi Table memuat kolom persis dari TOM; measure/relationship/expression/
  role/perspective/culture dibandingkan sebagai objek terpisah.
- **Options** baru mengikuti ALM Toolkit: perspectives, cultures, roles, TMSL,
  partitions, annotations, lineage tag, dan warning dependensi measure. Opsi
  update/apply-only ditampilkan disabled karena compare read-only.
- Default ALM: roles/partitions/annotations/lineage off, measure/relationship/
  expression/warning on. TEST vs PRD `Dragon - Simparts` kembali 0 different.
- Tabel hasil menjadi tree seperti ALM (Table → Measure/Relationship/
  Calculation item; root Data source/Expression/Role/Perspective/Culture).
- Panel definisi di bawah menampilkan **TMDL/TMSL persis dari TOM** dan
  highlight baris berbeda.
- CLI internal baru: `bi-tools-cli compare --snapshot-json`.

## 2026-11-22 - Rilis 0.6.0

### Compare Semantic Model

- **Halaman Compare baru** (read-only) untuk membandingkan dua semantic model
  dari Power BI Service atau instance Power BI Desktop.
- Sumber/target: Dataset (workspace + model) atau Desktop (instance terbuka),
  dengan tombol tukar.
- Status `Same definition`, `Different definition`, `Source only`,
  `Target only`; aksi `Skip`, `Create`, `Update`, `Delete` (target-only default
  `Skip`).
- Opsi: measure & kolom, relasi, M query & ekspresi, format string, role & RLS.
- Tabel hasil dengan filter status/tipe/pencarian, panel detail item, dan diff
  baris ekspresi sumber/target.
- **Validate** lokal, **Generate script** (manifest TMSL pratinjau), dan
  **Export CSV**. Tombol Apply selalu disabled: tidak ada jalur tulis ke target.
- API baru: `GET /api/compare/state`, `POST /api/compare/run|export|script`.

### Analisa Semantic Model

- **Tab Roles** baru: role, member (provider/tipe/ID/modified), table permission
  RLS, dan status OLS. Data dari `TMSCHEMA_ROLES`,
  `TMSCHEMA_ROLE_MEMBERSHIPS`, `TMSCHEMA_TABLE_PERMISSIONS`, dan
  `TMSCHEMA_COLUMN_PERMISSIONS`; tabel 11 kolom Analisa dipertahankan.

### UI

- Chevron console log mengikuti mockup (`M6 15l6-6 6 6`).
- Modul `web\js\views\compare.js`; label Indonesia untuk halaman Compare,
  Roles, dan dialog terkait.

## 2026-11-22 - Rilis 0.5.3

### UI Web

- **Modularisasi tanpa framework/build step**: `web\app.js` turun dari ±9.400
  baris menjadi ±2.100 baris. Helper inti pindah ke `web\js\core\` (`state`,
  `dom`, `i18n`, `format`, `combo`, `app_api`), sedangkan view pindah ke
  `web\js\views\` (`analysis`, `metadata-tsd`, `partitions-lineage`).
- **ES module native**: `<script type="module" src="app.js">`; `locales.js`
  dan `api.js` tetap classic script dan tetap dimuat lebih dulu. Tidak ada
  npm, bundler, CDN, atau framework baru.
- **Peta navigasi web**: `web\ARCHITECTURE.md` memuat struktur file, anchor
  fungsi, kelompok `state`, konvensi DOM, aturan i18n, dan tes penjaga. Pekerjaan
  UI tidak perlu membaca seluruh `app.js`.
- **Jembatan sementara** `web\js\core\app_api.js` untuk helper UI yang masih di
  `app.js`; modul view memanggil `app.toast`, `app.startJob`, `app.api`, dll.
- **Tes penjaga diperluas**: `test_i18n.py` dan `test_architecture.py` memindai
  semua modul JS; tes baru memastikan `web\` tetap tanpa `package.json`,
  `node_modules`, impor eksternal, atau CDN.

## 2026-11-21 - Rilis 0.5.2

### Analisa Semantic Model

- **Katalog konektor dari dokumentasi**: `rules\m_connectors.json` menyimpan
  snapshot 85 fungsi halaman M `accessing-data-functions` plus connector yang
  tidak tercantum di sana (Snowflake, BigQuery, Parquet, dataflow, dataset).
  `sync_connector_catalog.py` membuat ulang katalog, dan
  `core\connector_catalog.py` membacanya tanpa network. Tes memastikan setiap
  `CONNECTOR_SPECS` punya entri katalog; Snowflake kini tervalidasi dari
  halaman connector resmi (`Snowflake.Databases(server, warehouse, options)`)
  tanpa menunggu sampel pelanggan.
- **Native SQL `Sql.Database`/`Odbc.Query`**: klausa `FROM` literal kini
  menjadi label sumber (`dbo.Sales`), sedangkan koneksi asal disimpan sebagai
  `connection:srv.db`/`connection:DSN` di detail. `Value.NativeQuery` memakai
  aturan yang sama; CTE/subquery/tabel dinamis tetap dilewati.
- **Satu resolver per graph**: `build_lineage_resolver` membuat cache referensi
  shared query sekali per dialog lineage; semua rantai M memakai resolver yang
  sama sehingga ekspresi shared query tidak di-parse berulang.
- **Detail outline lineage**: View column lineage menampilkan peran pemakaian di
  setiap baris (visual `Values/Data/Y-Axis`, filter visual/page/report, sort,
  formatting), nama/tipe visual, status merah untuk `Tidak dipakai`, dan batas
  outline 2000 baris. Depth outline 6 sementara graph tetap 4. Di sisi
  **Depends on**, rantai langkah M diringkas: kolom langsung ke M query lalu
  datasource, sedangkan graph tetap menampilkan langkah M.
- **M query partisi incremental**: `m_query_rows` memakai `source_expression`
  sebagai fallback ketika `QueryDefinition` kosong, sehingga query M seperti
  `OCRKK` menampilkan langkah M di lineage, tab M queries, ekspor, dan Best
  Practice.
- **Sumber lineage per konektor**: node `datasource` tidak lagi hanya mengenal
  SQL Server. `core\m_lineage.py` membaca path bertingkat dari navigasi M:
  BigQuery `proyek.dataset.tabel`, Snowflake `database.schema.tabel`,
  PostgreSQL/MySQL `schema.tabel`, Azure SQL/Synapse `schema.tabel`, dataflow
  `entity`, serta Excel/SharePoint/OData. Origin PostgreSQL/Oracle/Teradata/
  DB2/SAP HANA/Sybase/Informix/Analysis Services kini dikenali (sebelumnya
  jatuh ke `table`), dan konektor database yang belum punya pola di
  `CONNECTOR_PATTERNS` tidak lagi masuk bucket tabel `mquery` pada TSD.
- **Cakupan konektor M dari korpus nyata**: registry `CONNECTOR_SPECS` kini
  mengenali `PowerBI.Dataflows` (rantai `workspaceId`/`dataflowId` tidak lagi
  mengotori label), `GoogleBigQueryAad`, `Odbc.Query`/`Odbc.DataSource`,
  `SapBusinessWarehouse.Cubes`, `UsageMetricsDataConnector`,
  `GoogleSheets.Contents`, `Parquet.Document`, `SharePoint.Contents`,
  `Pdf.Data`, `AzureStorage.*`, `Excel.CurrentWorkbook`, `Web.Page`, dan
  `Html.Table`. Navigasi berakhir `[Content]`/`[Value]` (Folder/SharePoint)
  ikut dibaca. Koneksi **native query** memakai label `server.database`/DSN,
  path/URL lengkap dan nama parameter disimpan sebagai keterangan node, dan
  parameter tidak pernah masuk label. `Value.NativeQuery`, `Table.Combine`,
  `if then else`, serta `let` bersarang kini mempertahankan origin.
- **Warning M yang jujur**: `Table.PromoteHeaders` (3.052 query pada korpus
  uji), fungsi skalar (`Date.*`, `Text.*`, `List.*`, `#date`), passthrough
  (`Table.ReplaceErrorValues`, `Table.RemoveRowsWithErrors`,
  `Table.ExpandListColumn`, ...), dan `Cube.*` tidak lagi memicu
  `unknown_function`; kolom yang tidak bisa dipastikan ditandai
  `columns_known=False` tanpa warning. Pada korpus 9.832 query M, baris
  berwarning turun dari 72% ke 7,1% dan `unknown_function` dari 8.138 ke 24
  (hanya fungsi buatan pengguna). `m_query_corpus.py` menambah laporan
  dev-only; korpus pelanggan tidak di-commit, regresi memakai
  `tests\data\m_query_patterns.json` yang anonim.
- **Native query BigQuery**: `Value.NativeQuery` mengambil nama tabel dari
  klausa `FROM` sederhana, termasuk SQL yang dirangkai `&` dengan placeholder
  parameter (`` ... from `"&DatasetID&"`.`sales_daily` ``). CTE, subquery,
  target fungsi seperti `UNNEST(...)`, dan tabel dinamis dilewati; parameter
  pada klausa `FROM` masuk ke detail (`param:DatasetID`). Fixture menambah dua
  pola BigQuery AAD: incremental berparameter (navigasi
  `Database`/`Schema`/`Table` + `RangeStart`/`RangeEnd`) dan native SQL
  terangkai.
- **Resolusi shared query**: `build_lineage(..., registry=...)` menelusuri
  referensi `#"Nama"`/nama query ke ekspresi shared query dengan memo dan
  guard siklus (`MAX_QUERY_DEPTH` 8). `core\analysis_lineage.py::_m_query_registry`
  membangun registry dari baris `Tabel` **dan** `Expression` di `m_queries`,
  sehingga `Table.Combine`/`Table.NestedJoin` yang sumbernya shared query
  memakai datasource sebenarnya dan menampilkan detail `ref:<Nama>`.
  Referensi yang tidak ditemukan tetap dicatat di `references` tanpa warning;
  siklus tidak membuat rekursi tak berujung.
- **Detail sumber di Outline dan panel M lineage**: baris `datasource` kini
  menampilkan `ref:`, `param:`, dan `Native query` (path/URL lengkap di
  tooltip), dan panel **M lineage** menampilkan label sumber, origin,
  parameter, referensi query, serta chip native — bukan hanya warning. Hasil
  resolusi shared query dan parameter konektor langsung terlihat tanpa
  membuka graph.
- **Registry konektor konsisten**: daftar `CONNECTOR_SPECS` (lineage),
  `CONNECTORS` (model/`15_Data_Sources`), dan `CONNECTOR_PATTERNS` (TSD) kini
  dijaga tes. `Hdfs.Files`/`Hadoop.Files` mendapat origin file + bucket TSD
  file, dan `File.Contents`, `Xml.Tables`, `Web.BrowserContents`, `Html.Table`,
  `Html.BrowserContents` dikenali `extract_connector`.
- **Subscription report** dideteksi lewat `GET admin/reports/{id}/subscriptions`
  untuk report yang tidak bisa dipindai (RDL/personal/inaccessible), dengan
  cache 24 jam, batas 25 report/run, dan kuota 200 request/jam. Subscription
  aktif pada report seperti itu membuat `coverage_complete=False` dan kolom
  tanpa referensi menjadi `Perlu dicek`; 401/403 dan 429 tidak mengubah
  coverage. Chip jumlah subscription muncul di tab **Report results**, ekspor
  XLSX menambah sheet `12_Subscriptions`, dan CLI menampilkan ringkasannya.
- **Lineage graph bergrup**: dialog lineage kolom/measure dan tabel sekarang
  menampilkan artifact **Semantic Model** dan **Report**, grup **Model
  dependencies**, **M query**, dan tiap **Page**, dengan report/page sebagai
  header grup. Halaman disusun satu kolom dan report berbeda tampil
  berdampingan; urutan halaman mengikuti urutan report. Jika ada langkah M,
  seed menjadi output terakhir rantai M dan kartu tabel menjadi header grup;
  tanpa langkah M kartu tabel pindah ke Model dependencies. Graf padat
  dipadatkan otomatis ke header halaman/report, edge ke report kedua memakai
  koridor di atas artifact, dan ekspor SVG/PNG ikut menggambar artifact/grup.
- **Dependency langsung di lineage**: graph lineage tidak lagi menggambar
  referensi DAX transitive sebagai garis langsung. `ModelReference.depth`
  membedakan dependency langsung (1) dan transitive (2+); graph hanya memakai
  depth 1, sedangkan `04_Model_Usage` menampilkan kolom **Depth** agar impact
  analysis tetap terlihat. Contoh: `Engine No → # KK Acquired` kini hanya lewat
  `# Unit Sales`.
- **Hierarki dan drag lineage**: kartu di dalam grup disusun sebagai pohon
  (induk di tengah anak-anaknya) dan rantai M kolom upstream ikut tampil untuk
  measure (maksimal 3 kolom, 8 langkah per rantai). Header **Report** terhubung
  ke tiap **Page** dan header **Page** ke kartu visual/filter lewat garis pohon
  ortogonal. Klik kartu kini menyorot lineage langsung kartu itu lewat
  `highlight_edges`, bukan seluruh report. Kartu, grup, dan artifact bisa
  digeser; kanvas memanjang otomatis ke kanan/bawah saat item melewati batas
  awal, edge mengikuti posisi baru, pan tetap hanya di area kosong, dan posisi
  kembali ke layout otomatis saat graph dimuat ulang.

### Kebijakan API

- Inventaris API (Fabric, Power BI Admin/member REST, XMLA, API lokal) didokumentasikan di `README.md` dan `AGENTS.md`.
- Metode HTTP **`DELETE` dilarang** untuk API apa pun; `Transport.request` menolak sebelum request dikirim, dan `tests\test_architecture.py` menjaga tidak ada pemakaian `DELETE`/`requests.delete(`. Operasi hapus/bersihkan memakai `POST` (`.../clear`, `.../cancel`).

### Ekstraksi report

- **Batch report** Power BI Service: pilih 2–25 report dari satu workspace + satu
  dataset lewat checkbox di halaman Ekstraksi (atau ulangi `--report-id` di CLI).
  Model diekstrak sekali, setiap report ke folder `<Nama>_<8 ID>` dengan
  `Report_Metadata.xlsx`, dan ringkasan `Batch_Summary.xlsx`. Kegagalan satu
  report dicatat tanpa membatalkan report lain; usage report tidak digabung pada
  batch.

### Pengujian & antarmuka

- Smoke test browser (`tests\test_web_smoke.py`, `RUN_WEB_SMOKE=1`) menjalankan
  server uvicorn nyata dan Chromium untuk memeriksa semua view, langkah TSD,
  pergantian bahasa + reload, aset gagal, dan overflow. Workflow terpisah
  `.github\workflows\web-smoke.yml` menjalankannya saat `web\`/`server\` berubah.
- Tes i18n memindai literal `` t(`...`) `` dan frasa UI Indonesia yang tidak
  boleh ditulis langsung di `app.js`; sisa teks Indonesia di empty state relasi,
  halaman report, dan layar "server berhenti" dipindahkan ke kamus.

### Lineage

- Halaman **Lineage** menambah ekspor **SVG/PNG** kanvas (tombol di kanan atas,
  `POST /api/lineage/image`) dengan nama `Lineage_<akar>.svg|png` di `outputs\`.
- Filter **Node type** di toolbar menyembunyikan node/edge tipe lain tanpa
  menghitung ulang tata letak, dengan indikator `x / y`; ekspor gambar mengikuti
  filter, CSV tetap penuh.

### Performa analisa

- Scan report mengunduh definisi `getDefinition` secara paralel lewat
  `scan_workers` (web/CLI bawaan 2, maks 4, `--scan-workers`), dengan prefetch
  satu langkah, penulisan SQLite tetap berurutan, dan fallback otomatis ke
  serial saat Fabric menjawab 429.
- Satu klien Fabric dipakai ulang per worker (bukan per report), dan
  `poll_wait` tetap 1 dtk karena polling lebih rapat memicu throttling.
- `usage_scan_run` menyimpan `fetch_ms`, `scan_ms`, dan `scan_workers`; log job
  mencetak `Scan report: …` untuk membandingkan run.

### Analisa Semantic Model

- Tab **Health** memeriksa model dan report tanpa request tambahan: error
  kolom/measure, visual dengan field tak terpetakan, tabel tidak dipakai atau
  tanpa relasi, relasi dua arah/many-to-many/tidak aktif/otomatis, dictionary
  kolom besar, halaman tanpa visual, halaman tersembunyi, report tanpa tema,
  dan calculated column tidak dipakai.
- Tab **Best practice** (model) memakai katalog Microsoft/Tabular Editor
  `rules\BPARules.json` (71 aturan): 54 dievaluasi, 17 ditandai
  `Not evaluated` dengan alasan. Skor logaritmik per aturan, verdict model,
  ekspansi objek, filter kategori, dan dialog katalog lengkap.
- Ekspor XLSX menambah `10_BestPractice_Model` dan
  `11_BestPractice_Model_Rules`; CLI menampilkan skor dan verdict.
- **Column details** menampilkan `Cardinality` dari
  `TMSCHEMA_COLUMN_STORAGES.Statistics_DistinctStates` sebagai baris baru.
- Tombol **Rules** (dan ikon `i` di sel Rule) membuka dialog yang menjelaskan
  setiap aturan: sumber data, ambang, dan saran tindakan, termasuk rincian
  rumus skor praktik.
- Analisa semantic model kini **manual**: memilih model tidak lagi memulai job.
  Tekan **Analyze now** di panel hasil atau **Analysis** di kanan atas. Mengubah
  *Include report usage* hanya memberi pengingat untuk menjalankan ulang, dan
  hasil job lama diabaikan bila model diganti saat job berjalan.
- Klik baris Health membuka detail kolom/measure, lineage tabel, atau tab
  **Report results**; filter severity dan sort tersedia.
- Kolom **Visual rusak** dan **Skor praktik** di tab Report results kini
  terisi. Skor bersifat heuristik untuk report berstatus `ok`, dengan rincian
  penalti di tooltip.
- Ekspor XLSX menambah sheet `09_Health`; CLI menampilkan ringkasan
  `critical/warning/info`.
- Kelengkapan terjemahan dijaga tes baru: setiap literal `t("...")` wajib ada
  di kamus, dan enam kunci yang sebelumnya hilang sudah ditambahkan.

## 2026-11-20 - Rilis 0.5.1

Analisa semantic model mendapat lineage tabel, click-through dependensi, outline
compact/full, routing graph ortogonal, serta ekspor lineage sebagai SVG/PNG.

### Analisa Semantic Model

- Lineage M kini mengenali `Table.SplitColumn`, `Table.TransformColumns`, dan
  `Table.RenameColumns` dengan pasangan tunggal. Kolom hasil split/transform
  tetap tercatat sebagai langkah M.
- Dialog lineage menampilkan chip **M lineage** (`Complete`, `Partial`,
  `Unavailable`) beserta alasan, dan panel **M warnings** per tabel
  (`TransformColumns`, rename/kolom dinamis, fungsi tak dikenal, dll.).
- Keyakinan dihitung per kolom; `Table.TransformColumns` dan rename dinamis
  ditandai `Partial`, sedangkan tabel tanpa ekspresi M `Unavailable`.
- Baris tabel di tab **Tables** punya menu konteks sendiri dengan **Table
  lineage**: graph M query → tabel → kolom/measure → report/halaman/visual.
- Baris dependency pada detail kolom/measure bisa diklik untuk membuka lineage
  graph node tujuan (measure, calculated column/table, relasi, key column).
- Dialog lineage punya mode **Outline Compact/Full**: node yang muncul berulang
  diringkas di mode ringkas dan diperluas di mode lengkap. Ekspor lineage dan
  dependensi juga menerima `kind=table` (menggabungkan kolom + measure tabel).
- Graph lineage memakai **routing ortogonal** dengan lane di celah antar-kolom,
  sehingga edge tidak menembus node; edge mundur berbelok di luar kanan node.
- Toolbar lineage dan submenu **Exports** bisa menyimpan graph sebagai **SVG**
  atau **PNG** ke `outputs\` (nama `Lineage_<tabel>_<item>_lineage`). PNG
  dibuat di browser dengan skala maksimum 8000 px, lalu server memvalidasi
  isi dan ukuran berkas sebelum menulis.

## 2026-11-20 - Rilis 0.5.0

Analisa semantic model di web kini realtime, punya menu konteks per baris,
lineage graph/outline, langkah M, detail item bertab, raw metadata TMSCHEMA,
preview nilai, serta ekspor lineage/dependensi.

### Analisa Semantic Model

- Memilih semantic model langsung menjalankan analisa; halaman tidak lagi
  memuat snapshot lama dari SQLite. Ringkasan menampilkan waktu data
  (`Diperbarui …`).
- Hasil analisa disimpan di sesi SQLite **in-memory** per dataset selama server
  hidup, sehingga `data\bi_tools.db` tidak bertambah. Cache definisi report
  tetap bekerja di sesi yang sama; setelah server di-restart, detail report dan
  ekspor meminta analisa ulang.
- Checkbox **Include report usage (pages, visuals, filters)** (default aktif)
  memungkinkan analisa model saja. Tanpa report, kolom/measure tanpa referensi
  model berstatus **Perlu dicek**, metrik report `—`, dan tab `Report results`
  menjelaskan bahwa pemakaian report tidak disertakan. CLI mendapat opsi
  `--model-only`.
- Preferensi baru `analysis/include_reports`.
- Baris kolom/measure bisa diklik kanan (atau tombol `⋮`, `Shift+F10`) untuk
  membuka menu aksi: buka/tutup item di bawah, salin `'Tabel'[Nama]`, lihat
  detail kolom/measure (ukuran, tipe, status, alasan, pemakaian, ekspresi), dan
  lihat ekspresi DAX measure.
- **View column lineage graph** menampilkan graph dua arah di dialog: M query,
  dependensi model (measure, calculated column, relasi, sort, RLS, field
  parameter), lalu report → halaman → visual/filter. Graph memakai layout dari
  `core\analysis_lineage.py` (bukan dihitung di browser), dengan pencarian,
  zoom/Fit, pan, sorot lineage, dan double-click untuk root baru. Arah
  Both/Upstream/Downstream memuat ulang graph; mode model-only menampilkan
  notice tanpa sisi report.
- **View column lineage** membuka mode **Outline** (pohon upstream/downstream)
  dengan tombol Graph/Outline di dialog yang sama.
- **View dependencies** kini membuka submenu kategori (semua, measure, kolom,
  relasi, sorting, security, field parameter, report & visual, kalkulasi) dan
  menampilkan graph terfilter.
- Kolom dengan query M menampilkan **sumber data → tabel M → langkah M**
  (rename/select/derive) sebelum kolom model; `core\m_lineage.py` mencatat
  langkah per kolom (`StepLink`) dan pemotongan langkah dilaporkan lewat notice.
- **Table options** (details, show in analysis, copy table name), **Model
  options** (details, copy model name, run analysis again, open settings), dan
  **Exports** (CSV node/edge, JSON, Mermaid, dependencies CSV) kini berfungsi.
  Ekspor menulis hanya format yang diminta dan memberi pesan bila berkas sedang
  dibuka aplikasi lain.
- **Raw data** (kolom/measure) menampilkan **metadata mentah TMSCHEMA**
  (`TMSCHEMA_COLUMNS`/`TMSCHEMA_MEASURES`) sebagai JSON lengkap dengan Copy
  JSON; tidak ada nilai data.
- **Preview values** membaca contoh nilai model dengan service principal
  (RLS pengguna tidak berlaku), maksimal 100 baris dan timeout 60 detik. Data
  dimuat hanya setelah tombol **Load preview**; query asli tampil di bagian
  **Query**.
- **Column/Measure details** kini bertab: **Properties**, **Usage**,
  **Dependencies**, dan **Raw JSON**. Field yang tidak dideteksi tool ini
  bernilai `null` dan dicantumkan di daftar `unsupported`.

## 2026-11-19 - Rilis 0.4.4

Menggabungkan halaman metadata dan TSD menjadi satu alur, serta memperbaiki
perilaku klik node di Lineage.

### Extraction & TSD

- Sidebar kini punya satu item **Extraction & TSD**. Langkah 1 (ekstraksi
  metadata) dan langkah 2 (Generate TSD) tampil inline di halaman yang sama
  dengan stepper dua langkah dan panel pengunci.
- Langkah 2 terbuka setelah ekstraksi sukses atau bila `Report_Metadata.xlsx`
  sudah tersedia. Setelah ekstraksi, path workbook report/model otomatis diisi
  dan status stepper diperbarui.
- Tombol **Continue to Generate TSD** dan **Back to step 1** memakai
  `setMetaStep()` untuk menggulir ke bagian yang dituju. Navigasi sidebar
  `Generate TSD` yang terpisah dihapus.

### Lineage

- Klik node tidak lagi menyalakan seluruh komponen terhubung (semua node
  kuning). Hanya node terpilih, tetangga langsung, dan edge yang menyentuh node
  terpilih yang disorot; node lain tetap redup hanya karena filter arah.
- Node tetap bisa diklik (mouse dan keyboard), klik dua kali menjadikan root,
  dan panel detail mengikuti node yang dipilih.

## 2026-11-19 - Rilis 0.4.3

Memperbaiki ekstraksi model yang gagal karena cache ADOMD, mengisolasi TOM dari
proses server, dan menyelaraskan halaman Lineage dengan mockup.

### Perbaikan ekstraksi model (`Specified cast is not valid`)

- ADOMD menyimpan controller HTTP di cache shared memory `XmlaLibControllerCache`
  yang dipakai bersama semua proses. Entri dari ADOMD versi lain (Power BI
  Desktop, DAX Studio, Tabular Editor, SSMS) tidak bisa dibaca dan membuat
  ekstraksi/analisa gagal. Aplikasi kini membersihkan cache itu sekali per
  proses sebelum koneksi XMLA pertama, lalu mengulang sekali bila error yang
  sama muncul. Pesan akhir menyebutkan langkah yang bisa dilakukan pengguna.
- Semua operasi TOM (inventaris dan refresh partisi) dipindahkan ke proses CLI
  anak (`partition --inventory-json` / `--refresh-json`). Proses server hanya
  memakai ADOMD, sehingga membuka halaman Partisi tidak lagi mematikan
  ekstraksi model/analisa di sesi yang sama.
- `core\partition_plan.py` baru menyimpan tipe, parser range, dan validasi TMSL
  tanpa CLR; `core\partition_service.py` tidak lagi mengimpor `core\tom_client`.

### Halaman Lineage

- Daftar hasil pencarian diperbaiki: chip tipe tidak lagi menempati kolom
  pertama, sehingga nama/workspace tidak tertumpuk dan tinggi baris kembali
  ringkas.
- Pencarian hanya menampilkan daftar (tidak lagi otomatis membuka hasil
  pertama). Klik hasil menjadikan root; klik node menyalakan jalur + detail;
  klik dua kali node menjadikan root baru.
- Node grafik mengikuti mockup: warna per tipe, band header, ikon, halo untuk
  node terpilih, dan sorotan tetangga langsung. Toolbar dan panel detail
  diselaraskan (tombol **Jadikan akar** selalu tampil, nonaktif di root).

### Pengujian

- Suite menjadi 652 tes (643 lulus, 9 skip). Uji baru mencakup retry cache
  ADOMD, isolasi TOM/proses anak, mode CLI internal, dan penjaga arsitektur.

## 2026-11-19 - Rilis 0.4.2

Menambahkan halaman **Partisi** yang berfungsi penuh dan perintah CLI `partition`.

### Inventaris partisi

- Daftar partisi dibaca dari TOM/XMLA: tabel, partisi, jumlah baris, range,
  mode, tipe source, state, waktu proses terakhir, dan modified time.
- Jumlah baris diambil dari DMV `DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS`
  (`RECORDS_COUNT` terbesar per partisi). ADOMD dan TOM memakai versi assembly
  `Microsoft.AnalysisServices` yang tidak kompatibel dalam satu proses, sehingga
  DMV dijalankan lewat proses CLI `partition --dmv-json`; token dikirim melalui
  stdin, bukan argumen atau file.
- Range bersifat best-effort dari literal M (`RangeStart`/`RangeEnd`) lalu pola
  tanggal pada nama partisi. Bila tidak ditemukan, UI menampilkan `-` dan tidak
  mengarang nilai.
- DLL TOM/MSAL net472 dibundel di `libs\tom\`; ADOMD tetap di `libs\`.

### Refresh partisi

- **Process selected** mengirim satu perintah TMSL untuk semua partisi terpilih.
  Semua 8 jenis refresh tersedia: `full`, `automatic`, `dataOnly`,
  `clearValues`, `calculate`, `add`, `defragment`, `indexes`.
- `add` ditolak untuk calculated partition dan DirectQuery; `defragment`
  dikirim sebagai objek tabel tanpa partisi.
- Konfirmasi web memerlukan checkbox dan mengetik **PROCESS**; CLI memerlukan
  `--yes`. Satu perintah TMSL tidak bisa dibatalkan setelah dikirim.
- Status partisi dibaca ulang setelah eksekusi; tidak ada perubahan metadata,
  query M, atau refresh policy.

### CLI dan pengujian

- Perintah baru: `bi-tools-cli partition --workspace-id ... --dataset-id ... --list`
  dan `--table`/`--partition` + `--refresh-type` + `--yes`.
- Suite menjadi 645 tes (636 lulus, 9 skip); uji baru mencakup TMSL, parser
  range, row count per partisi, presenter/endpoint, dan CLI tanpa .NET/network.
- Smoke test live: 39 partisi dan 39 row count terbaca dari model uji, 0 warning.

## 2026-11-19 - Rilis 0.4.1

Rilis ini menyempurnakan halaman Analisa dan Lineage, menambahkan pemilih
bahasa Inggris/Indonesia, dan menyiapkan halaman Partisi (masih empty state).

### Bahasa antarmuka dan penyempurnaan tab Analisa

- Web kini punya pemilih bahasa di **Pengaturan → Tampilan**:
  **English** (bawaan) atau **Bahasa Indonesia**. Pilihan disimpan sebagai
  `ui/language`, di-cache di browser agar tidak berkedip saat boot, dan
  diterapkan tanpa reload (label, header tabel, status, ringkasan, tombol).
- Seluruh teks dasar dipindah ke Bahasa Inggris dengan kamus Indonesia di
  `web/locales.js`; pesan dari server diterjemahkan di klien dan log
  diagnostik `core` tetap Bahasa Indonesia.
- Angka mengikuti bahasa (desimal `20.3 MB` vs `20,3 MB`), termasuk ukuran
  dataset, ukuran berkas, dan jumlah item.
- Suite menjadi 609 tes (600 lulus, 9 skip).

### Analisa semantic model sesuai mockup

- Halaman Analisa memakai enam tab: **Semua hasil**, **Tables**,
  **Relationships**, **Report results**, **DAX expressions**, dan **M queries**.
- **Semua hasil** kini daftar datar kolom + measure (bukan hierarki per tabel).
  Tiap baris dapat dibuka menjadi delapan kelompok pemakaian: **Used in
  artifacts**, **Used in visuals**, **Used as key column**, **Used in
  relationships**, **Used in row/object level security**, **Used in page level
  filters**, **Used in column sorting**, dan **Used in field parameters**.
  Kelompok kosong tidak dirender. Tiap kelompok membawa sub-header sendiri
  (mis. visuals: Type, Page, Report, Used as) dan nilai baris anak mengikuti
  indeks kolom sub-header itu, bukan diulang dari 11 judul kolom utama.
- **Tables** tetap hierarki per tabel (grup Measure/Kolom) dan menampilkan mode
  penyimpanan serta jumlah partisi per tabel; **Report results** menampilkan
  halaman/visual/field/tak terpetakan; **DAX expressions** memuat measure +
  calculated column; **M queries** memuat M tabel + parameter/ekspresi.
- **Relationships** memakai 9 kolom: Nama relasi (`'Tabel'[Kolom] N ← 1
  'Tabel'[Kolom]`), Tipe, Cross filter, Kardinalitas, Status, Auto create,
  # dipakai, Dari kolom, Ke kolom. `Auto create` dideteksi dari nama relasi,
  `# dipakai` dari DMV `DISCOVER_CALC_DEPENDENCY` (jumlah objek model yang
  bergantung pada relasi). Grafik mengelompokkan edge per pasangan tabel
  (badge jumlah), punya zoom Fit/−/+ dan panel samping statistik.
- Grafik memakai layout tree per kolom mengikuti arah relasi (`from → to`) dengan
  lane routing untuk edge yang melompat kolom, kanvas dinamis, dan zoom berbasis
  ukuran kanvas; node tetap berlabel `Tabel`.
- **Semua hasil** tidak lagi menampilkan DAX pada baris measure (DAX hanya di
  tab **DAX expressions**); calculated column tetap menampilkan ekspresinya.
- **Sumber & opsi** memakai tombol **Muat ulang** di samping semantic model untuk
  memuat ulang daftar dataset; tombol muat ulang workspace dihapus.
- Sidebar mendapat item **Partisi** dan tombol ciutkan (`#sidebarToggle`) yang
  statusnya disimpan di `localStorage` (`pbi-sidebar`). Halaman Partisi masih
  empty state tanpa data contoh; dialog proses partisi dihapus.
- Bug tab `Tables` diperbaiki: setelah **Collapse**, membuka satu tabel tidak lagi
  membuka semua tabel/grup; default grup tertutup dan kondisi awal diisi eksplisit
  saat analisa diterapkan.
- Grafik `Relationships` bisa digeser (drag) saat di-zoom; `Fit` mengembalikan
  posisi dan zoom. Klik node tetap memilih tabel selama gerakan di bawah 4 px.
- **Report results** kini hierarkis: report → grup Halaman → baris halaman →
  anak Visual/Field. Data per halaman dihitung dari `usage_field` lewat
  `report_pages`; filter memakai Dipakai/Tidak dipakai.
- Combo **Workspace** dan **Semantic model** di `Sumber & opsi` melebar penuh
  (`.row-inline .select{flex:1 1 auto}`).
- **Report results** kini sedetail prototype: report → Hidden pages/Pages →
  halaman → Visuals → visual → Artifacts used + Visual level filters → Columns
  used, plus Page/Report level filters. Detail dimuat lazy dari endpoint
  `/api/analysis/report-detail`; tabel `usage_page` menyimpan halaman (termasuk
  hidden) dan tema report ikut discan. Kolom **Views**, **Visual rusak**, dan
  **Skor praktik** ditampilkan `-`.
- Baris sub-header per grup di tab **Semua hasil** dihapus; header utama sudah
  mewakili semua kolom.
- Indentasi tabel Analisa diperbaiki: aturan `padding-left` sel nama tidak lagi
  ditimpa `#analyzeTable td`, sehingga level 0-8 tampil bertingkat (16 px/level)
  dan ekspansi satu baris tidak lagi terlihat sejajar.
- Report results memakai ikon penanda (report/page/visual/filter/table/column)
  dan menandai halaman/visual tersembunyi dengan ikon eye-off + chip `Hidden`.
- Baris grup di Report results kini hanya berisi nama (tanpa teks `Type`/`Source`)
  agar konsisten dengan tab Semua hasil.
- Lineage kini interaktif seperti Relationships: tombol zoom `-/+/Fit`,
  kanvas bisa digeser (drag), dan data contoh statis (`lineageNodes`,
  `lineageEdges`, `renderLineage`) dihapus.
- Report dengan nama `[App] ...` memakai tipe `Apps` di tab Report results.
- Sel tabel Analisa yang terpotong kini punya tooltip berisi teks lengkap
  (tanpa melebarkan kolom).
- Overlap Lineage diperbaiki: grafik tidak lagi menimpa header (SVG
  `overflow:hidden`), dan tombol `Jadikan akar` tidak tertimpa URL panjang.
- Klik node Lineage menyalakan rantai hulu–hilir berwarna kuning, node di luar
  rantai diredupkan.
- Deteksi field parameter baru (`find_field_parameter_refs`): calculated table
  berisi `NAMEOF(...)` dibaca sebagai pemakaian kolom/measure asal, bukan tabel
  calculated biasa, sehingga tidak dihitung ganda.
- Backend analisa membaca tabel/relasi/partisi/M dari TMSCHEMA tanpa koneksi
  tambahan (`read_model_metadata`), menyimpan relasi di snapshot dan M query di
  tabel `usage_m_query`, sehingga tab tetap terisi setelah restart tanpa XMLA.
- Kolom mockup tanpa sumber data (views, tema, skor praktik, visual rusak)
  tidak ditampilkan. Mode Analisa tetap read-only; pemrosesan partisi akan
  menjadi pengecualian di halaman Partisi.
- Prototipe data contoh di `web\app.js` dihapus.

## 2026-11-18 - Rilis 0.4.0

### Antarmuka web lokal

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
- `web\` (HTML/CSS/JS tanpa build step) disalin ke samping exe.
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
- Perbaikan combo: daftar 800+ workspace tidak lagi dipaksa flexbox menyusut
  (teks terpotong di baris pertama), baris placeholder tidak ikut daftar, dan
  posisi scroll daftar direset setiap kali dropdown dibuka.
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
- Halaman **Analisa Semantic Model** web tersambung: picker workspace/dataset,
  opsi report lintas workspace/personal, analisa XMLA + pemakaian report dengan
  stop, snapshot SQLite otomatis, kartu ringkasan, tab Semua/Kolom/Measure/Report,
  pencarian/filter/sort/expand, detail pemakaian + referensi model, tautan report,
  dan ekspor XLSX.
- Teks bantuan Endpoint XMLA dipindahkan menjadi tooltip ikon `!` di kanan field;
  baris workspace model tidak lagi menampilkan hint statis.
- Halaman **Lineage** web tersambung: pencarian di SQLite read-only, pembukaan
  hasil pertama, kanvas dua arah (upstream/root/downstream) dari
  `graph_for`/`build_graph`, peredupan sisi sesuai arah, kedalaman 1–15, detail
  node + datasource, jadikan akar lewat klik dua kali, tautan report, dan ekspor
  CSV ke `outputs\Lineage_<nama>.csv`.
- Uji baru: preferensi/migrasi, penjaga token/Host/Origin, endpoint API, antrean
  job/SSE, runtime (state, port, mutex), dan penjaga arsitektur web.

### Finalisasi 0.4.0

- GUI PySide6 dihapus: paket `app\` beserta 10 berkas uji GUI, `tests\test_app_settings.py`,
  `tests\test_app_tabs.py`, dan tes view model. `requirements.txt` tidak lagi
  memuat PySide6, dan `tests\test_architecture.py` menjaga agar `app\`/PySide6
  tidak kembali.
- Paket kini hanya dua executable: `BI Tools.exe` (server web, console) dan
  `bi-tools-cli.exe` (console). `BI Tools (classic).exe` dihapus dari spec,
  `packaging\build.ps1`, dan `.github\workflows\release.yml`, sehingga paket
  dan installer lebih kecil.
- `README.md` dan `AGENTS.md` ditulis ulang untuk alur web: struktur `server\`,
  `web\`, dua executable, dan tanpa instruksi `python -m app`/QSettings.
- `packaging\make_icon.py` tetap tersedia sebagai skrip dev-only untuk
  meregenerasi ikon (PySide6 tidak dipakai saat build/runtime).
- Suite menjadi 585 tes (576 lulus, 9 skip) tanpa PySide6.

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

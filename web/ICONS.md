# Ikon UI

Referensi untuk mengganti ikon antarmuka web secara manual. Semua ikon berasal
dari **Lucide 0.468.0** (ISC) yang di-vendor lokal; tidak ada CDN, icon font,
atau build step.

- Sprite: `web/index.html` (blok `<!-- lucide:sprite:begin -->` … `<!-- lucide:sprite:end -->`)
- Manifest: `web/vendor/lucide/icons.json` (versi + geometri, tidak dimuat saat runtime)
- Helper JS: `web/js/core/icons.js` → `icon(name, className, strokeWidth)`
- Penjaga: `tests/test_web_icons.py`
- Lisensi: `web/vendor/lucide/LICENSE`

Nomor baris di dokumen ini sesuai commit `4d001a9` dan bisa bergeser setelah
perubahan lain. Selalu cari nama ikonnya lebih dulu:

```powershell
Select-String -Path web\index.html,web\js\**\*.js -Pattern '#i-column|icon\("column"'
```

## Aturan singkat

1. Geometri hanya ditulis sekali, di `<symbol>` dalam sprite. Jangan menyalin
   `<path>` ke `index.html` atau ke view.
2. `fill`/`stroke`/`stroke-width` dipasang di elemen `<svg>` pemakai
   (`currentColor` + `fill="none"`), **bukan** di `<symbol>`, supaya tema dan
   warna baris berlaku otomatis.
3. Nama semantik di view (`column`, `measure`, `link`, `report`, …) boleh tetap;
   yang diganti adalah nama ikon Lucide di dalamnya.
4. Setiap ikon di sprite **wajib dipakai** dan setiap `#i-...` wajib punya
   `<symbol>`. `tests/test_web_icons.py` gagal bila ada yang yatim.
5. Jangan menambah ikon dari URL/CDN. Simpan geometri di `icons.json` + sprite.
6. Pengecualian yang tetap menggambar SVG sendiri: kanvas `relGraphSvg`,
   `lineageSvg`, `analysisLineageSvg`, dan dokumen SVG hasil ekspor lineage.
   Tanda centang checkbox di `styles.css` juga masih berupa data-URI CSS.

## Ukuran dan ketebalan

| Konteks | Kelas | Ukuran | stroke-width |
|---|---|---|---|
| Ikon baris tabel Analisa | `.row-ico` | 14px | 1.6–1.7 |
| Ikon di dalam `.lg-icon` / `.lineage-node` | `.row-ico` | 16–18px | 1.6 |
| Sidebar, tombol, dialog, tooltip | `.od-icon` | `--od-icon-size` (12–20px) | 1.6–1.9 |
| Tombol ⋮ dan ikon menu tanpa kelas | — | mengikuti kontainer | 2 |
| Glyph node kanvas Lineage | `.node-icon` | 10×10 | 2.6 (kompensasi skala 24→10) |

Chevron memakai 1.8–2; ikon informasi 1.7; centang tema/toast 2.2.

## Peta peran → ikon

### Baris tabel Analisa — `web/js/views/analysis.js:11–22`

| Peran | Ikon | Muncul untuk |
|---|---|---|
| `table` | `table` | Baris tabel |
| `group` | `rows-3` | Header grup (Measures, Columns, Pages, …) |
| `column` | `table-columns-split` | Kolom |
| `measure` | `sigma` | Measure |
| `link` | `link-2` | Relationship |
| `code` | `code-xml` | Ekspresi DAX |
| `query` | `database` | M query |
| `page` | `file` | Halaman report |
| `report` | `file-chart-column` | Report |
| `visual` | `chart-column` | Visual |
| `filter` | `filter` | Filter report/halaman/visual |
| `hidden` | `eye-off` | Halaman/visual tersembunyi |

### Menu konteks Analisa — `web/js/views/analysis.js:25–40`

| Kunci | Ikon | Item menu |
|---|---|---|
| `more` | `ellipsis-vertical` | Tombol ⋮ |
| `expand` | `chevron-down` | Expand items below |
| `collapse` | `chevron-up` | Collapse items below |
| `copy` | `copy` | Copy text / Copy JSON |
| `sigma` | `square-function` | View DAX expression |
| `lineage` | `git-branch` | View column lineage |
| `graph` | `network` | View column lineage graph |
| `details` | `table-properties` | Column/Measure details |
| `raw` | `braces` | Column/Measure raw data |
| `dependencies` | `git-fork` | View dependencies |
| `table` | `table` | Table options |
| `model` | `box` | Model options |
| `export` | `download` | Exports |
| `refresh` | `refresh-cw` | Run analysis again |
| `settings` | `settings` | Open settings |
| `chevron` | `chevron-right` | Panah submenu |

### Compare — `web/js/views/compare.js:55–63`

| Tipe objek | Ikon |
|---|---|
| Table | `table` |
| Measure | `sigma` |
| Relationship | `link-2` |
| Expression | `braces` |
| Role | `users` |
| Data source | `database` |
| Perspective | `layers` |
| Culture | `globe` |
| Calculation item | `square-function` |
| Toggle tree | `chevron-right` (baris 383) |

### Kanvas Lineage — `web/js/views/partitions-lineage.js:440–446`

| Hue node | Ikon |
|---|---|
| `db` | `database` |
| `flow` | `workflow` |
| `model` | `box` |
| `table` | `table` |
| `measure` | `sigma` |
| `report` | `file-text` |
| `neutral` | `circle` |

### Sidebar & shell — `web/index.html`

| Baris | Ikon | Dipakai untuk |
|---|---|---|
| 71 | `chart-line` | Logo brand |
| 81 | `chart-column` | Nav **Model analysis** |
| 85 | `git-compare` | Nav **Compare model** |
| 89 | `layers` | Nav **Partitions** |
| 93 | `database` | Nav **Extraction & TSD** |
| 97 | `git-fork` | Nav **Lineage** |
| 101 | `download` | Nav **Backup and Restore** |
| 106 | `sliders-horizontal` | Nav **Settings** |
| 110 | `panel-left-close` | **Collapse sidebar** |
| 1568 | `chevron-up` | Toggle **Console log** |
| 1591, 1629, 1655, 1675, 1709, 1727, 1813, 1845, 1870, 1889, 1907 | `x` | Tombol tutup 11 dialog |
| 1706 | `maximize-2` | **Maximize** dialog Details |
| 585, 953, 1312, 1387, 1451, 1488 | `info` | Catatan/tooltip |
| 318, 1512, 1529, 1939 | `check` | Extraction selesai, kartu tema, toast |
| 782 | `chart-column` | Empty state Analisa |

### Extraction & TSD — `web/index.html`

| Baris | Ikon | Dipakai untuk |
|---|---|---|
| 131 | `play` | **Run extraction** |
| 197 | `refresh-cw` | **Reload** instance |
| 275 | `file-spreadsheet` | `Report_Metadata.xlsx` |
| 283 | `file-spreadsheet` | `Semantic_Model_Metadata.xlsx` |
| 291 | `file-code` | `TSD_Report.html` |
| 301 | `folder` | **Open folder** |
| 347 | `chart-column` | Empty state **Result summary** |
| 367 | `lock` | Langkah 2 TSD terkunci |
| 388 | `file` | **Generate TSD** |
| 569 | `file-text` | Empty state **Document preview** |

### Compare, Partisi, Lineage — `web/index.html`

| Baris | Ikon | Dipakai untuk |
|---|---|---|
| 805 | `sliders-horizontal` | Tombol **Options** |
| 809 | `play` | **Run comparison** |
| 820 | `arrow-left-right` | **Swap** source/target |
| 854 | `arrow-right` | Panah source → target |
| 933 | `columns-2` | Empty state Compare |
| 967 | `download` | **Export CSV** |
| 1028 / 1032 | `minus` / `plus` | Depth lineage |
| 1181 | `table-2` | Empty state Partitions |
| 1204 | `download` | **Run backup** |

## Daftar lengkap ikon terpasang (52)

<!-- icon-inventory:begin -->

| Ikon | Jumlah | Lokasi |
|---|---|---|
| `arrow-left-right` | 1 | index.html:820 |
| `arrow-right` | 1 | index.html:854 |
| `box` | 2 | analysis.js:36, partitions-lineage.js:442 |
| `braces` | 2 | analysis.js:33, compare.js:58 |
| `chart-column` | 4 | index.html:81, 347, 782; analysis.js:20 |
| `chart-line` | 1 | index.html:71 |
| `check` | 4 | index.html:318, 1512, 1529, 1939 |
| `chevron-down` | 1 | analysis.js:26 |
| `chevron-right` | 4 | analysis.js:9, 40; compare.js:383; partitions-lineage.js:8 |
| `chevron-up` | 2 | index.html:1568; analysis.js:27 |
| `circle` | 1 | partitions-lineage.js:446 |
| `code-xml` | 1 | analysis.js:16 |
| `columns-2` | 1 | index.html:933 |
| `copy` | 1 | analysis.js:28 |
| `database` | 4 | index.html:93; analysis.js:17; compare.js:60; partitions-lineage.js:440 |
| `download` | 4 | index.html:101, 967, 1204; analysis.js:37 |
| `ellipsis-vertical` | 1 | analysis.js:25 |
| `eye-off` | 1 | analysis.js:22 |
| `file` | 2 | index.html:388; analysis.js:18 |
| `file-chart-column` | 1 | analysis.js:19 |
| `file-code` | 1 | index.html:291 |
| `file-spreadsheet` | 2 | index.html:275, 283 |
| `file-text` | 2 | index.html:569; partitions-lineage.js:445 |
| `filter` | 1 | analysis.js:21 |
| `folder` | 1 | index.html:301 |
| `git-branch` | 1 | analysis.js:30 |
| `git-compare` | 1 | index.html:85 |
| `git-fork` | 2 | index.html:97; analysis.js:34 |
| `globe` | 1 | compare.js:62 |
| `info` | 6 | index.html:585, 953, 1312, 1387, 1451, 1488 |
| `layers` | 2 | index.html:89; compare.js:61 |
| `link-2` | 2 | analysis.js:15; compare.js:57 |
| `lock` | 1 | index.html:367 |
| `maximize-2` | 1 | index.html:1706 |
| `minus` | 1 | index.html:1028 |
| `network` | 1 | analysis.js:31 |
| `panel-left-close` | 1 | index.html:110 |
| `play` | 2 | index.html:131, 809 |
| `plus` | 1 | index.html:1032 |
| `refresh-cw` | 2 | index.html:197; analysis.js:38 |
| `rows-3` | 1 | analysis.js:12 |
| `settings` | 1 | analysis.js:39 |
| `sigma` | 3 | analysis.js:14; compare.js:56; partitions-lineage.js:444 |
| `sliders-horizontal` | 2 | index.html:106, 805 |
| `square-function` | 2 | analysis.js:29; compare.js:63 |
| `table` | 4 | analysis.js:11, 35; compare.js:55; partitions-lineage.js:443 |
| `table-2` | 1 | index.html:1181 |
| `table-columns-split` | 1 | analysis.js:13 |
| `table-properties` | 1 | analysis.js:32 |
| `users` | 1 | compare.js:59 |
| `workflow` | 1 | partitions-lineage.js:441 |
| `x` | 11 | index.html:1591, 1629, 1655, 1675, 1709, 1727, 1813, 1845, 1870, 1889, 1907 |

<!-- icon-inventory:end -->

## Cara mengganti

### 1. Satu peran saja (mis. ikon kolom)

Edit `web/js/views/analysis.js`:

```js
// sebelum
column: icon("table-columns-split", "row-ico", 1.6),
// sesudah
column: icon("columns-3", "row-ico", 1.6),
```

Nama `columns-3` harus sudah ada di sprite. Bila belum, lihat bagian
**Menambah ikon** di bawah. Lalu muat ulang halaman (server mengirim aset dengan
`no-store`) dan jalankan `python -m unittest tests.test_web_icons`.

### 2. Satu tempat di HTML

Ganti hanya nilai `href` pada baris tersebut:

```html
<!-- web/index.html:131 -->
<use href="#i-play"></use>
```

### 3. Semua pemakaian satu glyph

Ubah geometri `<symbol>` di sprite **dan** entri yang sama di
`web/vendor/lucide/icons.json`. Nama ikon tidak berubah, jadi semua call site
tetap jalan.

### 4. Menukar ke ikon Lucide lain

1. Unduh geometri dari versi yang dipin (0.468.0), lalu tempel ke
   `icons.json` dan sprite. Contoh mengambil inner markup:

   ```python
   import re, urllib.request
   name = "columns-3"
   url = f"https://unpkg.com/lucide-static@0.468.0/icons/{name}.svg"
   raw = urllib.request.urlopen(url).read().decode()
   print(re.sub(r"\s+", " ", raw.split(">", 1)[1].rsplit("</svg>", 1)[0]).strip())
   ```

2. Tambahkan `<symbol id="i-columns-3" viewBox="0 0 24 24">…</symbol>` ke blok
   sprite.
3. Ubah call site (`icon("columns-3", …)` atau `<use href="#i-columns-3">`).
4. Hapus simbol lama yang sudah tidak dipakai beserta entri `icons.json`-nya.
   Guard menolak ikon yang tidak dipakai.
5. Jalankan `python -m unittest tests.test_web_icons`.

### 5. Mengubah ukuran atau ketebalan

- Ukuran baris tabel: `.row-ico` di `web/styles.css` (sekarang 14px).
- Ukuran ikon besar/sidebar/tombol: `--od-icon-size` di CSS terkait.
- Ketebalan di JS: argumen ketiga `icon("table", "row-ico", 1.6)`.
- Ketebalan di HTML: atribut `stroke-width` pada `<svg>`.
- Glyph kanvas Lineage memakai skala 24→10, jadi `stroke-width="2.6"` agar
  setara ±1,1px. Jangan menurunkannya ke 1.1.

## Menambah ikon baru

1. Tambahkan entri di `web/vendor/lucide/icons.json` (`icons`).
2. Tambahkan `<symbol>` yang identik (teks geometri sama) di sprite `index.html`.
3. Pakai di kode dengan nama literal: `icon("nama-baru", …)` atau
   `<use href="#i-nama-baru">`.
4. Jalankan guard. Guard membandingkan manifest dengan sprite dan memastikan
   tidak ada ikon yatim.

Catatan: nama ikon harus ditulis sebagai **literal string** di
`icon("...")`; guard memindai literal tersebut. Nama yang dirakit dinamis
(mis. `icon(prefix + "x")`) tidak terdeteksi dan akan dianggap tidak dipakai.

## Verifikasi

```powershell
python -m unittest tests.test_web_icons
python -m unittest tests.test_english_only
python -m unittest tests.test_architecture
$env:RUN_WEB_SMOKE='1'; python -m unittest tests.test_web_smoke
python -m unittest discover -s tests -t .
```

Pemeriksaan visual cepat: sidebar, tombol header, 8 tab Analisa, menu konteks,
Compare tree, baris grup Partisi, kanvas Lineage, dialog detail, dan toast.
Perhatikan juga tema terang/gelap karena semua ikon memakai `currentColor`.

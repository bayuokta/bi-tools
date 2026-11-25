# Peta Web BI Tools

Dokumen ini adalah **peta navigasi**, bukan dokumentasi API. Tujuannya agar
pekerjaan pada UI web tidak perlu membaca seluruh file JS.

## Cara memakai peta ini

1. Baca file ini dulu.
2. Cari nama fungsi dengan `grep` (posisi baris berubah; jangan bergantung
   pada nomor baris di dokumen ini).
3. Baca hanya jendela kecil di sekitar fungsi tersebut (`read` dengan
   `offset`/`limit`), bukan seluruh file.
4. Untuk tugas yang menyentuh banyak view, pertimbangkan subagent `explore`
   agar konteks utama tetap ringkas.

## Struktur file

| Path | Isi |
|---|---|
| `web\index.html` | Seluruh markup view, dialog, tooltip, dan id DOM. Tanpa logika bisnis. |
| `web\styles.css` | Semua gaya: combo, tabel analisa, kanvas lineage, dialog. |
| `web\locales.js` | Kamus `en`/`id` (`window.BIToolsI18n`). Classic script, dimuat sebelum `app.js`. |
| `web\api.js` | Klien HTTP (`window.BIToolsApi`). Satu-satunya jalur aksi dari UI. |
| `web\app.js` | Entry module. Impor core + view, `init()`, `bootstrap()`, event wiring. |
| `web\js\core\state.js` | Objek `state` global + `store` localStorage. |
| `web\js\core\dom.js` | `$`, `$$`, `escapeHtml`. |
| `web\js\core\i18n.js` | `i18n`, `t`, `tr`, `currentLanguage`. |
| `web\js\core\format.js` | `decimalText`, `fmtInt`, `sizeText`, `fileMeta`. |
| `web\js\core\combo.js` | Komponen combo: enhance select, popup, pencarian, set/get options. |
| `web\js\core\highlight.js` | Prism DAX/JSON + grammar TMDL lexical; `highlightCode`, `highlightLine`, `compareLanguage`. |
| `web\vendor\prism\` | Prism 1.29 core + DAX + JSON + LICENSE, vendored lokal (tanpa CDN). |
| `web\js\core\app_api.js` | Jembatan sementara: `app.toast`, `app.startJob`, `app.api`, dll. Diisi `app.js` sebelum `init()`. |
| `web\js\views\analysis.js` | Seluruh logika halaman Analisa (payload, tabel, menu, detail, lineage, health, best practice, relationships, roles). |
| `web\js\views\compare.js` | Halaman Compare semantic model: picker sumber/target, job compare read-only, tree hasil, detail TMDL/TMSL persis, options dialog, validate/export/script. |
| `web\js\views\metadata-tsd.js` | Ekstraksi metadata + TSD: instance, workspace, picker, batch, payload, render TSD, capture/cache, sidecar, preview. |
| `web\js\views\partitions-lineage.js` | Halaman Partisi dan Lineage SQLite: inventory/refresh, tabel partisi, pencarian, grafik lineage, ekspor. |
| `web\ARCHITECTURE.md` | Dokumen ini. |

Server melayani seluruh folder `web\` lewat `StaticFiles`; PyInstaller menyalin
folder `web\` apa adanya (`ASSET_DIRS`). Menambah subfolder **tidak** memerlukan
perubahan `server\app.py` atau `packaging\bi_tools.spec`.

## Titik masuk

- `app.js` adalah **ES module** (`<script type="module" src="app.js">`).
  `locales.js` dan `api.js` tetap classic script sehingga dieksekusi lebih dulu.
- `init()` (bagian bawah `app.js`): memasang event listener, memanggil
  `initComboEvents()`, `enhanceAllSelects()`, `applyLanguage()`, `applyTheme()`,
  `applyMotion()`, `setSource()`, lalu `renderLog()` dan `analysisRender()`.
- `bootstrap()`: memuat system/settings/catalog/outputs/instances/workspaces,
  state TSD, analisa, partisi, dan lineage.
- `showView(name)`: menampilkan `#view-<name>`, mengatur `aria-current`,
  `applyMetaSteps()`, lalu memuat state lineage/partisi bila perlu.
- `rerenderLanguage()`: render ulang view aktif setelah bahasa berganti.

## Peta `app.js` (core, preferensi, event wiring)

Cari dengan `grep "function <nama>("`.

### Kerangka dan preferensi

`showView`, `tsdUnlocked`, `applyMetaSteps`, `setMetaStep`, `setSource`,
`applyLanguage`, `applyComboLanguage`, `rerenderLanguage`, `applyTheme`,
`applyMotion`, `applySidebar`, `showSettingsTab`, `savePreference`,
`loadSystem`, `loadSettings`, `renderSettings`, `loadCatalogStatus`,
`renderCatalogStatus`, `loadOutputs`, `renderOutputs`, `openOutput`,
`revealOutputFolder`.

### Job, log, toast, berkas

`toast`, `addLog`, `renderLog`, `setConsole`, `logLine`, `reportError`,
`finishJob`, `pollJob`, `startJob`, `setChip`, `api`, `apiReady`,
`pendingFeature`, `parentDir`, `browseRow`, `renderBrowse`, `browseFolder`,
`openFolderPicker`, `openFilePicker`.

Catatan: `finishJob` memanggil `inspectTsd`, `loadCatalogStatus`, dan
`loadSettings`; helper lintas modul memakai jembatan `app_api.js`.

## Peta `js\views\metadata-tsd.js`

Ekstraksi: `loadInstances`, `renderModelAvailability`, `loadWorkspaces`,
`loadModelContents`, `loadReportContents`, `applyReportDefaults`, `refreshPbix`,
`batchReports`, `batchSelectedIds`, `batchDatasetIds`, `renderBatchHint`,
`renderBatchReports`, `setBatchMode`, `buildMetadataPayload`,
`renderExtractResult`, `runExtraction`.

TSD: `tsdPayload`, `markChecklist`, `renderTsdState`, `loadTsdState`,
`inspectTsd`, `scheduleTsdInspect`, `startTsdProgress`, `renderTsdResult`,
`runTsd`, `loadTsdReports`, `captureTsdScreenshots`, `clearTsdCache`,
`openTsdDocument`, `openTsdFolder`, `loadTsdManual`, `saveTsdManualFile`,
`tsdManualPath`, `openJsonDialog`, `saveJsonDialog`.

Modul ini memanggil helper UI di `app.js` lewat `app.*` (`applyMetaSteps`,
`loadOutputs`, `parentDir`, `setMetaStep`, `startJob`, `toast`, dll.).

## Peta `js\views\partitions-lineage.js`

Partisi: `partitionLoadState`, `partitionLoadDatasets`, `partitionLoadInventory`,
`partitionApply`, `partitionRender`, `partitionGroups`, `partitionGroupSummary`,
`partitionGroupRow`, `partitionItemRow`, `partitionToggleTable`,
`partitionSelectTable`, `partitionSetAllOpen`, `partitionToggleAll`,
`partitionOpenConfirm`, `partitionConfirmProcess`, `partitionCloseDialog`.

Lineage SQLite: `lineageLoadState`, `lineageSearch`, `lineageOpen`,
`lineageSelectNode`, `lineageRenderGraph`, `lineageRenderDetail`,
`lineageLayout`, `lineageVisibleNodes`, `lineageSvgDocument`,
`lineageExport`, `lineageExportImage`, `lineageZoomBy`, `lineageApplyZoom`,
`lineageSetDirection`, `lineageSetDepth`, `setLineageZoom`.

Helper node bersama: `clipLabel`, `lineageTypeName`, `nodeHue`,
`nodeIconMarkup`, `nodeTypeLabel`.

## Peta `app.js` — pengaturan

`renderSettings`, `showSettingsTab`, `savePreference`, `testToken`,
sign-in/sign-out (`/api/settings/sign-in`, `/api/settings/sign-out`),
snapshot sumber/unduh (`/api/settings/shared-db`, `/api/settings/snapshot/download`).
Job admin `syncCatalog`/`runScan` tetap ada untuk mode service/uji.

## Peta `js\views\compare.js`

- Picker: `compareLoadState`, `fillCompareSide`, `loadCompareDatasets`, `setCompareType`, `comparePayload`, `validateCompareForm`.
- Options: `DEFAULT_OPTIONS`, `loadOptions`, `saveOptions`, `syncOptionControls`, `readOptionControls`, `openOptionsDialog`, `closeOptionsDialog`.
- Job: `runCompare` (`startJob` `/api/compare/run`), `applyCompareResult`.
- Render: `renderCompare`, `renderCompareMetrics`, `compareGroups`, `treeRow`, `renderCompareTable`, `renderCompareDetail`, `renderCompareDiff`, `renderDiffPane`.
- Aksi: `selectCompareRow`, `validateCompare`, `exportCompare`, `generateCompareScript`, `initCompareEvents`.
- Halaman read-only; `#cmpApply` selalu disabled.
- Definisi yang ditampilkan adalah output TOM/TMDL atau TMSL persis; JS tidak menyusun/menebak definisi.
- Diff pane memakai `.diff-code` tinggi `clamp(320px,45vh,620px)` dan highlight per baris (TMDL atau JSON/TMSL). Baris sejajar: `is-source` hijau, `is-target` merah, `is-spacer` hatch selebar panel dengan border blok (`is-block-start`/`is-block-end`), `diff-token` untuk perubahan intra-baris; semua baris memakai tinggi `1.65em` agar tidak bergeser, dan scroll kedua pane disinkronkan.

## Peta `js\views\analysis.js`

File ini masih besar (~5.000 baris); **jangan dibaca penuh**. Cari anchor
dengan `grep`, lalu baca jendela kecil.

- Konstanta: `ANALYSIS_CHEVRON`, `ANALYSIS_ICONS`, `MENU_ICONS`,
  `LINEAGE_KIND_LABELS`, `LINEAGE_KIND_ICONS`, `LINEAGE_CATEGORIES`,
  `LINEAGE_ORIGIN_LABELS`, `DETAIL_GROUPS`, `USAGE_FLAG_LABELS`,
  `UNSUPPORTED_LABELS`, `ANALYSIS_TABS`, `ANALYSIS_STATUS_ORDER`,
  `ANALYSIS_STATUS_LABELS`, `HEALTH_RULES`, `HEALTH_RULE_HELP`,
  `BP_STATUS_LABELS`, `REL_NODE_*`, `REL_LANE_STEPS`.
- Payload/preferensi: `analysisPayload`, `analysisFmtBytes`, `tStatus`,
  `analysisStatusChip`, `analysisReportUrl`, `analysisCoverageSuffix`,
  `analysisTabConfig`, `analysisApplyPrefs`, `analysisSyncReportOptions`,
  `analysisSavePrefs`, `analysisLoad`, `analysisLoadDatasets`, `analysisNote`,
  `analysisApply`, `analysisApplyTabTools`, `analysisRun`, `analysisStop`.
- Menu dan detail: `analysisMenuEntries`, `analysisMenuMarkup`,
  `analysisSubmenuEntries`, `analysisSubmenuMarkup`, `analysisOpenMenu`,
  `analysisCloseMenu`, `analysisRunMenuAction`, `copyTextValue`,
  `analysisOpenTableDetails`, `analysisOpenModelDetails`, `analysisShowTable`,
  `analysisExportLineage`, `analysisExportDependencies`.
- Lineage dialog: `analysisLineageSvgPalette`, `analysisLineageSvgDocument`,
  `analysisLineagePngData`, `analysisLineageFetchGraph`,
  `analysisExportLineageImage`, `analysisLineageMermaid`, `analysisOpenDetails`,
  `analysisOpenItemDetails`, `analysisLoadLineage`, `analysisLineageRender`,
  `analysisLineageRenderM`, `analysisLineageCardText`,
  `analysisLineageNodeMarkup`, `analysisLineageOutlineMarkup`,
  `analysisLineageEdgePath`, `analysisLineageEdgeRoutes`,
  `analysisLineageDragTarget`, `analysisLineageMoveItems`,
  `analysisLineageApplySelection`, `analysisLineageSelect`,
  `analysisLineageReroot`, `analysisLineageApplySearch`.
- Tabel dan baris: `analysisTableSummary`, `analysisTreeGroups`,
  `analysisChildGroups`, `analysisFlatRows`, `analysisTreeView`,
  `analysisFilteredRelationships`, `analysisRelationshipRows`,
  `analysisReportRows`, `analysisDaxRows`, `analysisMRows`,
  `analysisHealthRows`, `analysisBestPracticeRows`, `analysisSortItems`,
  `analysisRoleRows`, `analysisHead`, `analysisBody`, `analysisRender`.
- Health/best practice: `analysisHealthRuleLabel`, `analysisHealthRulesMarkup`,
  `analysisPracticeTitle`, `analysisHealthDetail`, `analysisHealthOpen`,
  `analysisBestPracticeIcon`, `analysisBestPracticeSeverity`,
  `analysisBpRulesMarkup`, `analysisOpenBpRules`.
- Relationships: `analysisRelPairs`, `analysisRelTreeLayout`,
  `analysisRelRoutePath`, `analysisLaneClear`, `analysisRelRender`,
  `analysisRelZoomBy`, `analysisRelApplyZoom`, `analysisRelSelect`.
  Cari varian lain dengan `grep "analysisRel"`.

## State (`js/core/state.js`)

Satu objek `state` dimutasi in-place. Kelompok penting:

- Preferensi/kerangka: `view`, `theme`, `language`, `motion`, `sidebarCollapsed`,
  `source`, `ready`, `applying`, `settings`, `system`, `outputs`, `logs`.
- Job: `jobId`, `jobStream`, `jobPending`, `jobLogCount`, `lastJob`.
- Ekstraksi: `instances`, `workspaces`, `reports`, `datasets`, `pbix`,
  `endpoint`, `batchMode`, `batchSelected`, `extractReady`.
- TSD: `tsd`, `tsdLoaded`, `tsdManual`, `tsdManualCustom`, `tsdLastResult`,
  `tsdOutputPath`, `tsdTimer`, `tsdInspectTimer`, `tsdReady`, `metaStep`.
- Analisa: `analysis`, `analysisTab`, `analysisSort`, `analysisSortDesc`,
  `analysisOpen`, `analysisSettings`, `analysisTarget`, `reportDetail`.
- Lineage dialog: `analysisLineage*` (`Target`, `Direction`, `View`,
  `OutlineMode`, `Category`, `Zoom`, `Drag`, `Highlight`).
- Detail/menu: `analysisMenuTarget`, `analysisSubmenuTarget`, `analysisItem*`,
  `analysisRaw*`.
- Relationships: `relView`, `relSelected`, `relZoom`, `relPanX`, `relPanY`,
  `relDrag`, `relGraphBaseWidth`, `relGraphBaseHeight`.
- Lineage SQLite: `lineageData`, `lineageGraph`, `lineageNodesLive`,
  `lineageHasDb`, `lineageQuery`, `lineageZoom`, `lineagePanX`, `lineagePanY`,
  `lineageNodeType`, `lineageLayout`.
- Partisi: `partitions`, `partitionLoaded`, `partitionSelected`,
  `partitionOpen`, `partitionRunning`, `partitionStateLoaded`.
- Picker: `pickDir`, `pickFile`, `pickKind`, `pickExt`, `pickCallback`.

## Konvensi DOM

- View: `#view-ekstraksi`, `#view-analisa`, `#view-partisi`,
  `#view-pengaturan`, `#view-lineage`; navigasi `data-view`.
- Alur TSD: `#metaSteps`, `#tsdLock`, `#goTsd`, `#doneToTsd`,
  `#backToExtract`.
- Combo: `<select>` asli disembunyikan (`.combo-native`), tombol
  `.combo-button`, popup bersama `#comboPopup` + `#comboSearch` + `#comboList`.
- Analisa: tabel `#analyzeTable`, tab `data-tab`, baris membawa
  `data-item-kind`/`data-item-table`/`data-item-name`; menu `#analysisMenu`.
- Lineage dialog: semua id berawalan `analysisLineage*` (mis.
  `#analysisLineageDialog`, `#analysisLineageCanvasWrap`) agar tidak bentrok
  dengan halaman Lineage.
- Halaman Lineage: id `#lineage*`; kanvas SVG dan detail node.
- Dialog berkas: `#folderDialog`, `#folderPathInput`, `#chooseFolder`.

## i18n

- Bahasa dasar Inggris di `index.html`, `app.js`, dan modul `js/**`.
- Kamus Indonesia di `locales.js` (`messages.id`).
- Markup statis memakai `data-i18n`, `data-i18n-title`,
  `data-i18n-placeholder`, `data-i18n-aria-label`.
- Teks dinamis memakai `t()`; pesan server memakai `tr()`.
- Jangan menulis teks UI Indonesia langsung di JS/HTML; tambahkan kunci kamus.
- Nilai kanonik (status verdict, kunci filter/sort, tipe field) tetap Bahasa
  Indonesia di data; tampilan memakai `tStatus()`.

## Tes penjaga

- `tests\test_i18n.py`: kunci `data-i18n`/`t()`, frasa Indonesia tersisa,
  blok `HEALTH_RULE_HELP`, urutan `locales.js` sebelum `app.js`.
- `tests\test_architecture.py`: helper inti satu deklarasi, `app.js` memuat
  `api.js`, tidak ada framework/CDN/build step di `web\`, dan aturan
  arsitektur lain.
- `tests\test_web_smoke.py`: server nyata + Chromium; menangkap error boot
  module, aset 404, dan overflow.
- `tests\test_server_*.py`: endpoint/presenter, bukan detail DOM.

## Aturan penting

- `web\` tetap aset statis: tanpa bundler, tanpa npm, tanpa framework.
- Logika bisnis tetap di `core\`/`server\`; JS hanya mengirim payload dan
  merender state.
- Jangan menambah dependensi CDN; seluruh aplikasi harus jalan offline.
- `app_api.js` adalah jembatan sementara. Saat helper dipindah ke `core\`,
  ganti pemanggilan `app.*` di modul view dengan impor langsung.

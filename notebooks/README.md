# Notebook Fabric untuk `bitools-sync`

`bi_tools_sync.ipynb` menjalankan program sync (katalog workspace, lineage,
katalog report, snapshot SQLite) lalu mengunggah snapshot ke SharePoint lewat
Graph. Notebook ini pengganti `bi-tools-sync.exe` untuk jadwal otomatis di
Fabric.

## Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| Kapasitas Fabric | Notebook berjalan di kapasitas workspace (butuh F2 ke atas) |
| Service principal | Terdaftar di Entra, punya peran **Fabric administrator** dan izin Graph aplikasi `Sites.Selected` (atau `Sites.ReadWrite.All`) yang sudah di-consent |
| Grant site | SP harus di-grant untuk site tujuan: `scripts/grant_site_permission.ps1` dari repo `py-sharepoint` |
| Workspace tanpa Git integration | Supaya `CLIENT_SECRET` di notebook tidak ikut ter-commit |
| Anggota workspace minimal | Siapa pun yang bisa membuka notebook bisa membaca secret |

## Langkah pakai

1. Buat notebook baru di workspace Fabric, impor `bi_tools_sync.ipynb`
   (atau salin cell-nya).
2. Isi cell **Parameter**:
   - `WHEEL_URL` — aset rilis, mis.
     `https://github.com/bayuokta/bi-tools/releases/download/v0.8.0/bitools_sync-0.8.0-py3-none-any.whl`
   - `SP_HOSTNAME`, `SP_SITE_PATH`, `SP_DRIVE_NAME`, `SP_FOLDER`
   - `MODE`, `FULL`, `INCLUDE_PERSONAL`, `UPLOAD`
3. Isi cell **Kredensial** dengan `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`.
4. Jalankan **Run all** sekali untuk memastikan tidak ada error.
5. Periksa output: jumlah workspace/node/edge/report, ukuran snapshot, dan
   hasil upload (nama file + ukuran).

Run penuh terukur ±2,5 menit (9.400 workspace, 867 workspace di-scan).

## Jadwal otomatis

Gunakan **Data Pipeline** (bukan schedule notebook langsung):

1. Buat pipeline → tambahkan aktivitas **Notebook**.
2. Pilih notebook ini.
3. Schedule harian (mis. 02:00 WIB), retry 1×, timeout ±30 menit.
4. Jalankan sebagai akun layanan yang stabil (pemilik schedule), bukan akun
   pribadi yang bisa berubah.

## Verifikasi manual

Sebelum menjadwalkan, jalankan dari mesin lokal:

```powershell
bi-tools-sync check --env-file .env `
  --sharepoint-host <host> --sharepoint-site /teams/<site> `
  --sharepoint-library Documents --sharepoint-folder "Apps/BI Tools"
```

Perintah ini menampilkan site, library, folder, dan isi folder sehingga bisa
dicocokkan dengan folder OneDrive yang dipakai aplikasi.

## Rotasi secret (setiap 6 bulan)

1. Entra → App registrations → SP sync → **Certificates & secrets** →
   **New client secret**.
2. Salin value baru, ganti `CLIENT_SECRET` di notebook.
3. Jalankan notebook sekali (manual) sampai sukses.
4. Hapus secret lama di Entra.
5. Catat tanggal kedaluwarsa di kalender.

## Troubleshooting

| Gejala | Penyebab | Solusi |
|---|---|---|
| `Akses Graph ditolak` (401/403) | `Sites.Selected` belum di-grant untuk site | Jalankan `grant_site_permission.ps1` untuk SP tersebut |
| `Admin API` 401/403 | SP bukan Fabric administrator / Admin API tenant dimatikan | Aktifkan **Allow service principals to use read-only admin APIs** dan tambahkan SP ke security group admin |
| `Wheel bitools_sync tidak ditemukan` | URL rilis salah atau versi tidak cocok | Cek aset rilis; cocokkan `WHEEL_URL` dengan tag |
| `%pip install` lalu import gagal | Session lama masih memakai versi sebelumnya | Restart session notebook lalu **Run all** |
| Upload lambat/putus | Ukuran snapshot ±37 MB | Dijalankan ulang oleh pipeline (retry 1×) |

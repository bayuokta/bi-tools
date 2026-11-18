"""Server lokal untuk antarmuka web BI Tools.

Server ini hanya mendengarkan ``127.0.0.1`` dan memakai ``core`` yang sama
dengan CLI, sehingga semua pekerjaan ekstraksi tetap berjalan di komputer
pengguna. Lapisan ini tidak boleh mengimpor PySide6 dan tidak menyimpan token
di berkas mana pun.
"""

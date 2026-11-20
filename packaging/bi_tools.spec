# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller: satu paket onedir berisi server web dan CLI.

Dua executable dibangun dari satu kumpulan dependensi:

- ``BI Tools.exe``      -> server web lokal (console), entry ``server/__main__.py``
- ``bi-tools-cli.exe``  -> CLI (console), entry ``cli/__main__.py``

Mode **onedir** dipakai dengan sengaja. ``core/paths.py`` menentukan folder
aplikasi dari folder ``.exe``, dan ``core/pbix.py``/``core/tsd.py``/
``core/xmla_client.py``/``core/best_practice.py`` mencari ``templates/``,
``libs/``, serta ``rules/`` **di samping exe**, bukan di ``sys._MEIPASS``.
Aset ``web/`` juga dicari lewat ``core/paths.APP_DIR``. Karena itu keempat
folder itu disalin ke akar folder hasil setelah COLLECT (bukan lewat ``datas``
yang masuk ke ``_internal``).
Mode onefile akan memutus pencarian itu; jangan diubah tanpa menyesuaikan
``core/paths.py``.

Jalankan lewat ``packaging/build.ps1`` atau:

    pyinstaller --noconfirm --clean packaging/bi_tools.spec
"""

import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - disediakan PyInstaller
sys.path.insert(0, str(ROOT))

from core.version import APP_NAME, __version__, version_tuple  # noqa: E402

ICON_PATH = ROOT / "packaging" / "bi-tools.ico"
ASSET_DIRS = ("templates", "libs", "web", "rules")

for asset in ASSET_DIRS:
    if not (ROOT / asset).is_dir():
        raise SystemExit(f"Aset wajib tidak ditemukan: {ROOT / asset}")


def _version_file() -> str:
    """Tulis version resource Windows dari ``core.version``."""
    major, minor, patch, build = version_tuple()
    text = f"""# Dibuat otomatis oleh packaging/bi_tools.spec
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', '{APP_NAME}'),
            StringStruct('FileDescription', '{APP_NAME} - tooling metadata Power BI'),
            StringStruct('FileVersion', '{__version__}'),
            StringStruct('InternalName', '{APP_NAME}'),
            StringStruct('OriginalFilename', '{APP_NAME}.exe'),
            StringStruct('ProductName', '{APP_NAME}'),
            StringStruct('ProductVersion', '{__version__}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    target = ROOT / "build" / "version_info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")
pythonnet_datas, pythonnet_binaries, pythonnet_hidden = collect_all("pythonnet")

hiddenimports = [
    "clr",
    "clr_loader",
    "pythonnet",
    # Perintah CLI diimpor dinamis oleh cli/__main__.py (lihat COMMANDS).
    "cli",
    "cli.report",
    "cli.model",
    "cli.tsd",
    "cli.lineage",
    "cli.analysis",
    "cli.partition",
    # Server memuat app FastAPI secara malas di runtime.run().
    *collect_submodules("server"),
    # uvicorn memilih implementasi loop/protokol saat runtime.
    *collect_submodules("uvicorn"),
    *playwright_hidden,
    *pythonnet_hidden,
]
datas = [*playwright_datas, *pythonnet_datas]
binaries = [*playwright_binaries, *pythonnet_binaries]

excludes = [
    "tkinter",
    "PySide6",
    "shiboken6",
    "pytest",
    "IPython",
    "matplotlib",
    "notebook",
    "tests",
]

common = dict(
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

web_analysis = Analysis(
    [str(ROOT / "server" / "__main__.py")],
    **common,
)
cli_analysis = Analysis(
    [str(ROOT / "cli" / "__main__.py")],
    **common,
)

web_pyz = PYZ(web_analysis.pure)
cli_pyz = PYZ(cli_analysis.pure)

web_exe = EXE(
    web_pyz,
    web_analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
    version=_version_file(),
)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    [],
    exclude_binaries=True,
    name="bi-tools-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
    version=_version_file(),
)

collected = COLLECT(
    web_exe,
    web_analysis.binaries,
    web_analysis.datas,
    cli_exe,
    cli_analysis.binaries,
    cli_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# templates/, libs/, dan web/ harus berada di samping exe (lihat docstring).
target_root = Path(DISTPATH) / APP_NAME  # noqa: F821 - disediakan PyInstaller
for asset in ASSET_DIRS:
    shutil.copytree(ROOT / asset, target_root / asset, dirs_exist_ok=True)

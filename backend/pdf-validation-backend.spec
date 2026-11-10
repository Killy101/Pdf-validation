# PyInstaller build of the validation engine: one folder with pdf-validation-backend.exe, used by the Electron shell.
# Build with scripts\build-backend.ps1 (it runs: python -m PyInstaller backend\pdf-validation-backend.spec).
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas, binaries, hiddenimports = [], [], []
# Packages that load modules by name or read bundled data files at run time.
for package in ("scrapling", "playwright", "curl_cffi", "browserforge", "apify_fingerprint_datapoints", "tld", "tzdata"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
datas += collect_data_files("reportlab")
# Routers, services and workers are imported lazily; uvicorn picks its protocol modules at run time.
hiddenimports += collect_submodules("app") + collect_submodules("uvicorn")

analysis = Analysis(
    ["run_server.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Only the system browser through Playwright is used; the stealth engines are never loaded.
    excludes=["patchright", "camoufox", "tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)
# A dependency hook still copies the stealth engine's 100 MB browser driver; it is never used, so drop it.
UNUSED = ("patchright", "camoufox")
analysis.datas = [entry for entry in analysis.datas if not entry[0].replace("\\", "/").startswith(UNUSED)]
analysis.binaries = [entry for entry in analysis.binaries if not entry[0].replace("\\", "/").startswith(UNUSED)]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="pdf-validation-backend",
    console=True,
    upx=False,
    version="version_info.txt",
    icon="../electron/assets/icon.ico",
)
COLLECT(exe, analysis.binaries, analysis.datas, name="pdf-validation-backend", upx=False)

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve().parents[2]
APP_NAME = "Nebula Master"

desktop_src = ROOT / "apps" / "desktop" / "src"
package_paths = [
    desktop_src,
    ROOT / "packages" / "engine" / "src",
    ROOT / "packages" / "image-io" / "src",
    ROOT / "packages" / "project-io" / "src",
    ROOT / "packages" / "project-model" / "src",
    ROOT / "packages" / "versioning" / "src",
]
asset_dir = ROOT / "apps" / "desktop" / "assets"
icon_file = asset_dir / ("nebula-master.icns" if sys.platform == "darwin" else "nebula-master.ico")

entry_script = desktop_src / "nebula_desktop" / "application" / "main.py"
hiddenimports = sorted(
    set(
        collect_submodules("nebula_desktop")
        + collect_submodules("engine")
        + collect_submodules("image_io")
        + collect_submodules("project_io")
        + collect_submodules("project_model")
        + collect_submodules("versioning")
    )
)


a = Analysis(
    [str(entry_script)],
    pathex=[str(path) for path in package_paths],
    binaries=[],
    datas=[(str(asset_dir), "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,
    icon=str(icon_file) if icon_file.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(icon_file),
        bundle_identifier="com.bicalcarata.nebulamaster",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "0.4.0",
            "CFBundleVersion": "0.4.0",
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
        },
    )

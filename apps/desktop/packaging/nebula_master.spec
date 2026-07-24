from __future__ import annotations

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
    datas=[],
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

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=None,
    bundle_identifier="com.bicalcarata.nebulamaster",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    },
)

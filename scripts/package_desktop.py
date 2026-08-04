from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build" / "pyinstaller"
PYINSTALLER_CONFIG_DIR = ROOT_DIR / "build" / "pyinstaller-config"
DMG_STAGE_DIR = ROOT_DIR / "build" / "dmg-stage"
SPEC_PATH = ROOT_DIR / "apps" / "desktop" / "packaging" / "nebula_master.spec"
WINDOWS_INSTALLER_SCRIPT = ROOT_DIR / "apps" / "desktop" / "packaging" / "nebula_master.iss"
ASSETS_DIR = ROOT_DIR / "apps" / "desktop" / "assets"
ICON_ICNS = ASSETS_DIR / "nebula-master.icns"
APP_NAME = "NebulaMaster"
MACOS_ZIP_NAME = "NebulaMaster-MacOS.app.zip"
MACOS_DMG_NAME = "NebulaMaster-MacOS.dmg"
WINDOWS_ZIP_NAME = "NebulaMaster-Windows.zip"
WINDOWS_INSTALLER_NAME = "NebulaMaster-Windows-Setup.exe"


class PackagingError(RuntimeError):
    pass


def _run(*args: str, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        list(args),
        cwd=ROOT_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Command failed."
        raise PackagingError(message)


def _clean_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def _app_version() -> str:
    with (ROOT_DIR / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise PackagingError("Could not determine application version from pyproject.toml.")
    return version


def _build_icons() -> None:
    _run(sys.executable, str(ROOT_DIR / "scripts" / "build_app_icon.py"))


def _build_macos_icns() -> None:
    if not ICON_ICNS.is_file():
        raise PackagingError(f"macOS icon was not generated: {ICON_ICNS}")


def _run_pyinstaller() -> None:
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(PYINSTALLER_CONFIG_DIR)
    _run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        str(SPEC_PATH),
        env=env,
    )


def _find_windows_iscc() -> str | None:
    candidates = [
        shutil.which("ISCC.exe"),
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _build_windows_installer(app_dir: Path) -> Path | None:
    iscc = _find_windows_iscc()
    if iscc is None:
        print("Warning: Inno Setup was not found; skipping Windows installer build.")
        return None

    installer_path = DIST_DIR / WINDOWS_INSTALLER_NAME
    _clean_path(installer_path)
    _run(
        iscc,
        f"/DAppName={APP_NAME}",
        f"/DAppVersion={_app_version()}",
        f"/DSourceDir={app_dir}",
        f"/DOutputDir={DIST_DIR}",
        f"/DOutputBaseFilename={installer_path.stem}",
        f"/DIconFile={ASSETS_DIR / 'nebula-master.ico'}",
        str(WINDOWS_INSTALLER_SCRIPT),
    )
    return installer_path if installer_path.is_file() else None


def _package_macos() -> list[Path]:
    app_bundle_path = DIST_DIR / f"{APP_NAME}.app"
    zip_path = DIST_DIR / MACOS_ZIP_NAME
    dmg_path = DIST_DIR / MACOS_DMG_NAME
    _clean_path(app_bundle_path)
    _clean_path(zip_path)
    _clean_path(dmg_path)
    _clean_path(BUILD_DIR)
    _clean_path(DMG_STAGE_DIR)
    _build_icons()
    _build_macos_icns()
    _run_pyinstaller()
    _run(
        "ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        str(app_bundle_path),
        str(zip_path),
    )
    DMG_STAGE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app_bundle_path, DMG_STAGE_DIR / app_bundle_path.name)
    artifacts = [app_bundle_path, zip_path]
    try:
        _run(
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(DMG_STAGE_DIR),
            "-ov",
            "-format",
            "UDZO",
            str(dmg_path),
        )
    except PackagingError:
        print(
            "Warning: hdiutil could not create a DMG in this environment; "
            "app and zip were built."
        )
    else:
        artifacts.append(dmg_path)
    return artifacts


def _package_windows() -> list[Path]:
    app_dir = DIST_DIR / APP_NAME
    zip_base = DIST_DIR / WINDOWS_ZIP_NAME.removesuffix(".zip")
    zip_path = DIST_DIR / WINDOWS_ZIP_NAME
    _clean_path(app_dir)
    _clean_path(zip_path)
    _clean_path(DIST_DIR / WINDOWS_INSTALLER_NAME)
    _clean_path(BUILD_DIR)
    _build_icons()
    _run_pyinstaller()
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=DIST_DIR, base_dir=APP_NAME)
    if Path(archive) != zip_path:
        _clean_path(zip_path)
        Path(archive).rename(zip_path)
    artifacts: list[Path] = [app_dir, zip_path]
    installer_path = _build_windows_installer(app_dir)
    if installer_path is not None:
        artifacts.append(installer_path)
    return artifacts


def main() -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    PYINSTALLER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    system = platform.system()
    if system == "Darwin":
        artifacts = _package_macos()
    elif system == "Windows":
        artifacts = _package_windows()
    else:
        raise PackagingError("Desktop packaging currently supports macOS and Windows only.")

    print("Built:")
    for artifact in artifacts:
        print(f"  {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

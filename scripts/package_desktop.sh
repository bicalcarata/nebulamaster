#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build/pyinstaller"
PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/build/pyinstaller-config"
DMG_STAGE_DIR="${ROOT_DIR}/build/dmg-stage"
SPEC_PATH="${ROOT_DIR}/apps/desktop/packaging/nebula_master.spec"
APP_NAME="Nebula Master"
APP_BUNDLE_PATH="${DIST_DIR}/${APP_NAME}.app"
ZIP_PATH="${DIST_DIR}/NebulaMaster.app.zip"
DMG_PATH="${DIST_DIR}/NebulaMaster.dmg"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Desktop packaging currently supports macOS only." >&2
  exit 1
fi

if [[ ! -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  echo "Missing virtual environment at ${ROOT_DIR}/.venv. Run 'uv sync --dev' first." >&2
  exit 1
fi

mkdir -p "${DIST_DIR}" "${BUILD_DIR}"
mkdir -p "${PYINSTALLER_CONFIG_DIR}"
rm -rf "${APP_BUNDLE_PATH}" "${ZIP_PATH}" "${DMG_PATH}" "${BUILD_DIR}" "${DMG_STAGE_DIR}"

PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR}" \
"${ROOT_DIR}/.venv/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "${DIST_DIR}" \
  --workpath "${BUILD_DIR}" \
  "${SPEC_PATH}"

ditto -c -k --sequesterRsrc --keepParent "${APP_BUNDLE_PATH}" "${ZIP_PATH}"

mkdir -p "${DMG_STAGE_DIR}"
cp -R "${APP_BUNDLE_PATH}" "${DMG_STAGE_DIR}/"

hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "${DMG_STAGE_DIR}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

echo "Built:"
echo "  ${APP_BUNDLE_PATH}"
echo "  ${ZIP_PATH}"
echo "  ${DMG_PATH}"

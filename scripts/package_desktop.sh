#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build/pyinstaller"
PYINSTALLER_CONFIG_DIR="${ROOT_DIR}/build/pyinstaller-config"
DMG_STAGE_DIR="${ROOT_DIR}/build/dmg-stage"
ICONSET_DIR="${ROOT_DIR}/build/nebula-master.iconset"
SPEC_PATH="${ROOT_DIR}/apps/desktop/packaging/nebula_master.spec"
ASSETS_DIR="${ROOT_DIR}/apps/desktop/assets"
ICON_PNG="${ASSETS_DIR}/nebula-master-icon.png"
ICON_ICNS="${ASSETS_DIR}/nebula-master.icns"
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
rm -rf "${APP_BUNDLE_PATH}" "${ZIP_PATH}" "${DMG_PATH}" "${BUILD_DIR}" "${DMG_STAGE_DIR}" "${ICONSET_DIR}"

"${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/scripts/build_app_icon.py"
mkdir -p "${ICONSET_DIR}"
sips -z 16 16 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_16x16.png" >/dev/null
sips -z 32 32 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_32x32.png" >/dev/null
sips -z 64 64 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_128x128.png" >/dev/null
sips -z 256 256 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_256x256.png" >/dev/null
sips -z 512 512 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "${ICON_PNG}" --out "${ICONSET_DIR}/icon_512x512.png" >/dev/null
cp "${ICON_PNG}" "${ICONSET_DIR}/icon_512x512@2x.png"
iconutil -c icns "${ICONSET_DIR}" -o "${ICON_ICNS}"

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

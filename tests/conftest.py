from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for relative in [
    "packages/project-model/src",
    "packages/project-io/src",
    "packages/image-io/src",
    "packages/engine/src",
    "packages/versioning/src",
    "apps/renderer-cli/src",
    "apps/desktop/src",
]:
    sys.path.insert(0, str(ROOT / relative))

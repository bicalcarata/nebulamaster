from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

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


@pytest.fixture(autouse=True)
def _allow_main_window_close_without_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from nebula_desktop.application.window import MainWindow

    monkeypatch.setattr(
        MainWindow,
        "_confirm_unsaved_navigation",
        lambda self, action_label: True,
    )

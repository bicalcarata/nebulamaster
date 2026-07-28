from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast


def asset_path(*parts: str) -> Path:
    if hasattr(sys, "frozen") and sys.frozen:
        base = Path(cast(Any, sys)._MEIPASS)
    else:
        base = Path(__file__).resolve().parents[3]
    return base.joinpath("assets", *parts)

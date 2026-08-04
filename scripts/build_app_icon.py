from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "apps" / "desktop" / "assets"
BRAND_SOURCE = ASSETS_DIR / "nebulamaster-brand.png"
ICON_PNG = ASSETS_DIR / "nebula-master-icon.png"
ICON_ICO = ASSETS_DIR / "nebula-master.ico"
ICON_ICNS = ASSETS_DIR / "nebula-master.icns"


def build_icon() -> Path:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not BRAND_SOURCE.is_file():
        raise FileNotFoundError(f"Brand source was not found: {BRAND_SOURCE}")

    with Image.open(BRAND_SOURCE) as source:
        # App icons require a square canvas; crop evenly rather than stretching the artwork.
        icon = ImageOps.fit(
            source.convert("RGBA"),
            (1024, 1024),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        icon.save(ICON_PNG)
        icon.save(
            ICON_ICO,
            format="ICO",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
        )
        icon.save(ICON_ICNS, format="ICNS")
    return ICON_PNG


if __name__ == "__main__":
    path = build_icon()
    print(path)
    print(ICON_ICO)
    print(ICON_ICNS)

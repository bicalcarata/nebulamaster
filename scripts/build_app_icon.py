from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "apps" / "desktop" / "assets"
ICON_PNG = ASSETS_DIR / "nebula-master-icon.png"


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _add_radial_glow(
    image: Image.Image,
    *,
    center: tuple[float, float],
    radius: float,
    color: tuple[int, int, int],
    alpha: float,
    blur: float,
) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left = center[0] - radius
    top = center[1] - radius
    right = center[0] + radius
    bottom = center[1] + radius
    draw.ellipse(
        (left, top, right, bottom),
        fill=(
            color[0],
            color[1],
            color[2],
            _clamp_channel(alpha * 255.0),
        ),
    )
    softened = overlay.filter(ImageFilter.GaussianBlur(radius=blur))
    image.alpha_composite(softened)


def _draw_arc_cloud(
    image: Image.Image,
    *,
    center: tuple[float, float],
    orbit_radius: float,
    start_deg: float,
    end_deg: float,
    blob_radius: float,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    steps = 18
    for step in range(steps):
        t = step / max(steps - 1, 1)
        angle = math.radians(start_deg + ((end_deg - start_deg) * t))
        x = center[0] + (math.cos(angle) * orbit_radius)
        y = center[1] + (math.sin(angle) * orbit_radius * 0.78)
        radius = blob_radius * (0.70 + (0.35 * math.sin(t * math.pi)))
        _add_radial_glow(
            image,
            center=(x, y),
            radius=radius,
            color=color,
            alpha=alpha,
            blur=radius * 0.45,
        )


def _draw_star_field(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    stars: tuple[tuple[float, float, int, int], ...] = (
        (0.17, 0.18, 3, 200),
        (0.29, 0.73, 2, 180),
        (0.52, 0.14, 2, 155),
        (0.80, 0.22, 3, 190),
        (0.71, 0.79, 2, 170),
        (0.87, 0.62, 4, 210),
        (0.12, 0.52, 2, 150),
        (0.62, 0.34, 2, 160),
        (0.77, 0.48, 3, 185),
        (0.38, 0.26, 2, 145),
        (0.42, 0.86, 2, 160),
        (0.93, 0.16, 2, 170),
    )
    for x_ratio, y_ratio, radius, alpha in stars:
        x = width * x_ratio
        y = height * y_ratio
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(230, 238, 255, alpha),
        )


def build_icon() -> Path:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (1024, 1024), (8, 12, 24, 255))

    _add_radial_glow(
        canvas,
        center=(512, 512),
        radius=360,
        color=(18, 26, 56),
        alpha=0.95,
        blur=140,
    )
    _draw_arc_cloud(
        canvas,
        center=(520, 500),
        orbit_radius=210,
        start_deg=138,
        end_deg=332,
        blob_radius=115,
        color=(255, 104, 42),
        alpha=0.24,
    )
    _draw_arc_cloud(
        canvas,
        center=(520, 500),
        orbit_radius=180,
        start_deg=150,
        end_deg=306,
        blob_radius=88,
        color=(255, 150, 62),
        alpha=0.20,
    )
    _draw_arc_cloud(
        canvas,
        center=(520, 500),
        orbit_radius=144,
        start_deg=165,
        end_deg=285,
        blob_radius=66,
        color=(255, 74, 38),
        alpha=0.20,
    )

    _add_radial_glow(
        canvas,
        center=(552, 470),
        radius=120,
        color=(110, 196, 255),
        alpha=0.36,
        blur=34,
    )
    _add_radial_glow(
        canvas,
        center=(552, 470),
        radius=42,
        color=(236, 248, 255),
        alpha=0.95,
        blur=6,
    )

    draw = ImageDraw.Draw(canvas)
    for arm in range(8):
        angle = math.radians(arm * 45.0)
        inner = 18
        outer = 82 if arm % 2 == 0 else 58
        x1 = 552 + (math.cos(angle) * inner)
        y1 = 470 + (math.sin(angle) * inner)
        x2 = 552 + (math.cos(angle) * outer)
        y2 = 470 + (math.sin(angle) * outer)
        draw.line((x1, y1, x2, y2), fill=(236, 245, 255, 180), width=5)

    _draw_star_field(canvas)

    rounded = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mask = Image.new("L", canvas.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, 1024, 1024), radius=228, fill=255)
    rounded.paste(canvas, mask=mask)
    rounded.save(ICON_PNG)
    return ICON_PNG


if __name__ == "__main__":
    path = build_icon()
    print(path)

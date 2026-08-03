from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from engine import EXIT_VALIDATION_SUCCESS
from engine.preview import render_preview, render_preview_image
from engine.selection import (
    apply_colour_temperature,
    apply_faux_palette,
    apply_local_contrast,
    apply_tone_shaping,
    apply_vibrance,
    compute_luminance,
    rgb_to_oklab,
)
from engine.semantic import analyze_dark_dust, dark_dust_influence, star_influence
from engine.validation import load_valid_project_bundle
from image_io import load_canonical_image, resize_to_max_edge
from PIL import Image
from project_model import DarkDustSettings
from renderer_cli.main import app
from typer.testing import CliRunner

RUNNER = CliRunner()
FAUX_PALETTE_IDS = ("hubble", "hoo", "foraxx", "gold_cyan", "natural_bicolour")
FAUX_PALETTE_NAMES = {
    "hubble": "Faux Hubble",
    "hoo": "Faux HOO",
    "foraxx": "Foraxx-Inspired",
    "gold_cyan": "Gold & Cyan",
    "natural_bicolour": "Natural Bi-colour",
}


def _write_palette(project_dir: Path) -> None:
    (project_dir / "palettes/default-nebula.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "default-nebula",
                "colour_points": [
                    {
                        "id": "nebula-blue",
                        "name": "Nebula Blue Point",
                        "value": {"model": "working-rgb", "channels": [0.12, 0.18, 0.92]},
                    },
                    {
                        "id": "blue-green",
                        "name": "Blue Green Point",
                        "value": {"model": "working-rgb", "channels": [0.1, 0.55, 0.7]},
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_common_files(project_dir: Path) -> None:
    for directory in ["palettes", "regions", "render_profiles", "plugins", "sources"]:
        (project_dir / directory).mkdir(parents=True, exist_ok=True)

    _write_palette(project_dir)
    (project_dir / "regions/lower-right.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "lower-right",
                "name": "Lower Right",
                "feather": {"radius": 0.08},
                "polygon": [[0.55, 0.35], [0.95, 0.35], [0.95, 0.95], [0.55, 0.95]],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "render_profiles/screen.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "screen",
                "name": "Screen",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 800,
                    "interpolation": "lanczos",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "plugins/lock.yaml").write_text(
        yaml.safe_dump(
            {"plugins": [{"id": "core.semantic-masks", "version": "1.2.0"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_source_image(path: Path, size: tuple[int, int] = (64, 48)) -> None:
    width, height = size
    data = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            data[y, x] = [
                min(255, 30 + x * 2 + y),
                min(255, 25 + y * 3),
                min(255, 90 + x * 2 + (y // 2)),
            ]

    # Keep a strongly blue lower-right area so ordered current/original selection differs.
    data[20:44, 36:60, 2] = np.clip(data[20:44, 36:60, 2] + 90, 0, 255)
    Image.fromarray(data, mode="RGB").save(path, format="PNG")


def _write_star_nebula_source_image(path: Path, size: tuple[int, int] = (64, 48)) -> None:
    width, height = size
    data = np.zeros((height, width, 3), dtype=np.uint8)
    data[:, :, :] = [12, 10, 20]
    data[18:34, 20:48, :] = [35, 28, 90]
    stars = [(10, 8), (50, 10), (44, 36)]
    for x, y in stars:
        data[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2, :] = [255, 255, 255]
    Image.fromarray(data, mode="RGB").save(path, format="PNG")


def _dark_nebula_fixture_float_image(size: tuple[int, int] = (96, 64)) -> np.ndarray:
    width, height = size
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    x = xx / max(width - 1, 1)
    y = yy / max(height - 1, 1)

    image = np.full((height, width, 3), [0.045, 0.045, 0.055], dtype=np.float32)

    illuminated_field = np.exp(-(((x - 0.52) ** 2) / 0.16 + ((y - 0.58) ** 2) / 0.11)).astype(
        np.float32
    )
    image += illuminated_field[..., None] * np.asarray([0.44, 0.40, 0.34], dtype=np.float32)

    veil = np.exp(-(((x - 0.50) ** 2) / 0.10 + ((y - 0.60) ** 2) / 0.08)).astype(np.float32)
    veil_detail = (
        0.65 + 0.18 * np.sin((x * 9.0) + (y * 5.0)) + 0.12 * np.cos((x * 6.0) - (y * 7.0))
    ).astype(np.float32)
    veil_detail = np.clip(veil_detail, 0.35, 1.0).astype(np.float32, copy=False)
    image -= (
        veil[..., None] * veil_detail[..., None] * np.asarray([0.13, 0.12, 0.11], dtype=np.float32)
    )

    core = np.exp(-(((x - 0.52) ** 2) / 0.018 + ((y - 0.60) ** 2) / 0.025)).astype(np.float32)
    image -= core[..., None] * np.asarray([0.19, 0.18, 0.17], dtype=np.float32)

    bright_patch = np.exp(-(((x - 0.66) ** 2) / 0.012 + ((y - 0.43) ** 2) / 0.010)).astype(
        np.float32
    )
    image += bright_patch[..., None] * np.asarray([0.28, 0.33, 0.40], dtype=np.float32)

    return np.clip(image, 0.0, 1.0).astype(np.float32, copy=False)


def _structured_rgb_fixture_image(size: tuple[int, int] = (96, 64)) -> np.ndarray:
    width, height = size
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    x = xx / max(width - 1, 1)
    y = yy / max(height - 1, 1)

    image = np.full((height, width, 3), [0.025, 0.026, 0.030], dtype=np.float32)
    image += (0.12 * x[..., None]).astype(np.float32, copy=False)
    image += (0.05 * y[..., None]).astype(np.float32, copy=False)

    warm_cloud = np.exp(-(((x - 0.34) ** 2) / 0.030 + ((y - 0.42) ** 2) / 0.040)).astype(
        np.float32
    )
    cool_cloud = np.exp(-(((x - 0.66) ** 2) / 0.040 + ((y - 0.62) ** 2) / 0.050)).astype(
        np.float32
    )
    ridge = np.exp(-(((x - 0.50) ** 2) / 0.090 + ((y - 0.28) ** 2) / 0.018)).astype(np.float32)

    image += warm_cloud[..., None] * np.asarray([0.34, 0.18, 0.12], dtype=np.float32)
    image += cool_cloud[..., None] * np.asarray([0.08, 0.24, 0.38], dtype=np.float32)
    image += ridge[..., None] * np.asarray([0.20, 0.19, 0.16], dtype=np.float32)

    return np.clip(image, 0.0, 1.0).astype(np.float32, copy=False)


def _write_dark_nebula_source_image(path: Path, size: tuple[int, int] = (96, 64)) -> None:
    image = _dark_nebula_fixture_float_image(size)
    encoded = np.clip(image * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8, copy=False)
    Image.fromarray(encoded, mode="RGB").save(path, format="PNG")


def test_render_preview_image_can_skip_provenance_hashing(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "preview-fast"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_source_image(project_dir / "sources/source.png")
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(
            _base_project_payload([_rule_colour_amount(rule_id="blue", name="Blue")]),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    bundle, report = load_valid_project_bundle(project_dir)
    assert bundle is not None
    assert report.valid is True

    def fail_hash(path: Path) -> str:
        raise AssertionError(f"hashing should be skipped for {path}")

    monkeypatch.setattr("engine.preview.sha256_file", fail_hash)
    result = render_preview_image(bundle, include_provenance=False, use_cached_sources=True)

    assert result.source_sha256 == ""
    assert result.project_sha256 == ""


def _base_project_payload(rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {"id": "preview-demo", "name": "Preview Demo"},
        "sources": [{"id": "source-01", "path": "sources/source.png", "enabled": True}],
        "semantic_channels": [
            {"id": "combined", "name": "Combined Image"},
            {"id": "nebula", "name": "Nebula"},
            {"id": "stars", "name": "Stars"},
            {"id": "dark_dust", "name": "Dark Dust"},
            {"id": "background", "name": "Background"},
        ],
        "palettes": [{"id": "default-nebula", "path": "palettes/default-nebula.yaml"}],
        "regions": [{"id": "lower-right", "path": "regions/lower-right.yaml"}],
        "render_profiles": [{"id": "screen", "path": "render_profiles/screen.yaml"}],
        "plugins": {"path": "plugins/lock.yaml"},
        "rules": rules,
    }


def _rule_colour_amount(
    *,
    rule_id: str,
    name: str,
    enabled: bool = True,
    selection_source: str = "current",
    target: str = "nebula",
    regions: list[str] | None = None,
    channel: str = "blue",
    colour_point: str = "nebula-blue",
    colour_range: float = 0.18,
    amount: float = 2.0,
    response_version: str | None = None,
    faint_colour_sensitivity: float | None = None,
    reveal_faint_colour: float | None = None,
    faint_range: float | None = None,
    structure_size: str | None = None,
    bright_colour_protection: float | None = None,
    highlight_protection: float | None = None,
    extended_range: bool | None = None,
) -> dict[str, Any]:
    transform: dict[str, Any] = {
        "type": "colour_amount",
        "channel": channel,
        "amount": amount,
        "preserve_luminance": False,
    }
    if response_version is not None:
        transform["response_version"] = response_version
    if faint_colour_sensitivity is not None:
        transform["faint_colour_sensitivity"] = faint_colour_sensitivity
    if reveal_faint_colour is not None:
        transform["reveal_faint_colour"] = reveal_faint_colour
    if faint_range is not None:
        transform["faint_range"] = faint_range
    if structure_size is not None:
        transform["structure_size"] = structure_size
    if bright_colour_protection is not None:
        transform["bright_colour_protection"] = bright_colour_protection
    if highlight_protection is not None:
        transform["highlight_protection"] = highlight_protection
    if extended_range is not None:
        transform["extended_range"] = extended_range

    return {
        "id": rule_id,
        "name": name,
        "enabled": enabled,
        "selection_source": selection_source,
        "target": target,
        "regions": regions or [],
        "match": {
            "colour_point": colour_point,
            "colour_range": colour_range,
            "brightness": {"min": 0.0, "max": 1.0},
            "softness": 0.5,
        },
        "transform": transform,
    }


def _rule_shift_colour(
    *,
    rule_id: str,
    name: str,
    selection_source: str = "current",
    regions: list[str] | None = None,
    amount: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": selection_source,
        "target": "nebula",
        "regions": regions or [],
        "match": {
            "colour_point": "nebula-blue",
            "colour_range": 0.18,
            "softness": 0.5,
        },
        "transform": {
            "type": "shift_colour_point",
            "target_colour_point": "blue-green",
            "amount": amount,
            "preserve_luminance": True,
        },
    }


def _write_project(project_dir: Path, payload: dict[str, Any]) -> None:
    _write_common_files(project_dir)
    _write_source_image(project_dir / "sources/source.png")
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _create_project(tmp_path: Path, rules: list[dict[str, Any]]) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    _write_project(project_dir, _base_project_payload(rules))
    return project_dir


def _rule_brightness(
    *,
    rule_id: str,
    name: str,
    target: str,
    amount: float = 1.8,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": [],
        "match": {"softness": 0.5},
        "transform": {"type": "brightness", "amount": amount},
    }


def _rule_faux_palette(
    *,
    rule_id: str,
    name: str,
    target: str = "nebula",
    palette: str = "hubble",
    amount: float = 0.0,
    preserve_brightness: bool = True,
    colour_balance: dict[str, float] | None = None,
    regions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": regions or [],
        "match": {"softness": 0.5},
        "transform": {
            "type": "faux_palette",
            "palette": palette,
            "amount": amount,
            "preserve_brightness": preserve_brightness,
            "colour_balance": colour_balance or {},
        },
    }


def _rule_dark_nebula_processing(
    *,
    rule_id: str,
    name: str,
    target: str = "dark_dust",
    amount: float = 1.0,
    reveal_dust: float = 0.40,
    dust_contrast: float = 0.30,
    core_depth: float = 0.55,
    dust_colour: float = 0.15,
    softness: float = 0.20,
    preserve_bright_areas: bool = True,
    regions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": regions or [],
        "match": {"softness": 0.5},
        "transform": {
            "type": "dark_nebula_processing",
            "amount": amount,
            "reveal_dust": reveal_dust,
            "dust_contrast": dust_contrast,
            "core_depth": core_depth,
            "dust_colour": dust_colour,
            "softness": softness,
            "preserve_bright_areas": preserve_bright_areas,
        },
    }


def _rule_tone_shaping(
    *,
    rule_id: str,
    name: str,
    target: str = "nebula",
    regions: list[str] | None = None,
    shadows: float = 0.0,
    midtones: float = 0.0,
    highlights: float = 0.0,
    contrast: float = 0.0,
    black_protection: float = 0.70,
    highlight_protection: float = 0.70,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": regions or [],
        "match": {"softness": 0.5},
        "transform": {
            "type": "tone_shaping",
            "shadows": shadows,
            "midtones": midtones,
            "highlights": highlights,
            "contrast": contrast,
            "black_protection": black_protection,
            "highlight_protection": highlight_protection,
        },
    }


def _rule_local_contrast(
    *,
    rule_id: str,
    name: str,
    target: str = "nebula",
    regions: list[str] | None = None,
    amount: float = 0.0,
    structure_size: str = "broad",
    background_protection: float = 0.70,
    highlight_protection: float = 0.70,
    softness: float = 0.50,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": regions or [],
        "match": {"softness": 0.5},
        "transform": {
            "type": "local_contrast",
            "amount": amount,
            "structure_size": structure_size,
            "background_protection": background_protection,
            "highlight_protection": highlight_protection,
            "softness": softness,
        },
    }


def _rule_vibrance(
    *,
    rule_id: str,
    name: str,
    target: str = "nebula",
    regions: list[str] | None = None,
    amount: float = 0.0,
    protect_strong_colours: float = 0.75,
    protect_bright_areas: float = 0.50,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": regions or [],
        "match": {"softness": 0.5},
        "transform": {
            "type": "vibrance",
            "amount": amount,
            "protect_strong_colours": protect_strong_colours,
            "protect_bright_areas": protect_bright_areas,
        },
    }


def _rule_colour_temperature(
    *,
    rule_id: str,
    name: str,
    target: str = "combined",
    regions: list[str] | None = None,
    warmth: float = 0.0,
    tint: float = 0.0,
    preserve_brightness: bool = True,
    protect_neutral_background: float = 0.50,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": True,
        "selection_source": "current",
        "target": target,
        "regions": regions or [],
        "match": {"softness": 0.5},
        "transform": {
            "type": "colour_temperature",
            "warmth": warmth,
            "tint": tint,
            "preserve_brightness": preserve_brightness,
            "protect_neutral_background": protect_neutral_background,
        },
    }


def _faux_palette_swatch_image() -> np.ndarray:
    return np.asarray(
        [
            [
                [0.82, 0.22, 0.12],
                [0.74, 0.16, 0.48],
                [0.08, 0.72, 0.88],
                [0.12, 0.28, 0.84],
                [0.45, 0.45, 0.45],
            ]
        ],
        dtype=np.float32,
    )


def _palette_output(
    palette: str,
    *,
    amount: float = 1.0,
    preserve_brightness: bool = True,
    colour_balance: dict[str, float] | None = None,
) -> np.ndarray:
    image = _faux_palette_swatch_image()
    weights = np.ones(image.shape[:2], dtype=np.float32)
    return apply_faux_palette(
        image,
        weights,
        palette=palette,
        amount=amount,
        preserve_brightness=preserve_brightness,
        colour_balance=colour_balance,
    )


@pytest.mark.parametrize(
    ("label", "builder"),
    [
        (
            "tone_shaping",
            lambda image, weights: apply_tone_shaping(
                image,
                weights,
                shadows=0.0,
                midtones=0.0,
                highlights=0.0,
                contrast=0.0,
                black_protection=0.70,
                highlight_protection=0.70,
            ),
        ),
        (
            "local_contrast",
            lambda image, weights: apply_local_contrast(
                image,
                weights,
                amount=0.0,
                structure_size="broad",
                background_protection=0.70,
                highlight_protection=0.70,
                softness=0.50,
            ),
        ),
        (
            "vibrance",
            lambda image, weights: apply_vibrance(
                image,
                weights,
                amount=0.0,
                protect_strong_colours=0.75,
                protect_bright_areas=0.50,
            ),
        ),
        (
            "colour_temperature",
            lambda image, weights: apply_colour_temperature(
                image,
                weights,
                warmth=0.0,
                tint=0.0,
                preserve_brightness=True,
                protect_neutral_background=0.50,
            ),
        ),
    ],
)
def test_new_adjustments_neutral_values_leave_image_unchanged(
    label: str,
    builder: Any,
) -> None:
    image = _structured_rgb_fixture_image()
    weights = np.ones(image.shape[:2], dtype=np.float32)

    result = builder(image, weights)

    assert np.all(np.isfinite(result)), label
    assert np.allclose(result, image, atol=1e-6), label


def test_tone_shaping_remains_monotonic_on_a_smooth_gradient() -> None:
    gradient = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    image = np.repeat(gradient[None, :, None], 3, axis=2)
    weights = np.ones(image.shape[:2], dtype=np.float32)

    result = apply_tone_shaping(
        image,
        weights,
        shadows=0.35,
        midtones=0.45,
        highlights=-0.20,
        contrast=0.30,
        black_protection=0.70,
        highlight_protection=0.80,
    )
    luminance = compute_luminance(result)[0]

    assert np.all(np.diff(luminance) >= -1e-5)


def test_local_contrast_structure_size_changes_the_result_scale() -> None:
    image = _dark_nebula_fixture_float_image()
    weights = np.ones(image.shape[:2], dtype=np.float32)

    fine = apply_local_contrast(
        image,
        weights,
        amount=0.50,
        structure_size="fine",
        background_protection=0.70,
        highlight_protection=0.70,
        softness=0.50,
    )
    broad = apply_local_contrast(
        image,
        weights,
        amount=0.50,
        structure_size="very_broad",
        background_protection=0.70,
        highlight_protection=0.70,
        softness=0.50,
    )

    assert not np.allclose(fine, broad, atol=1e-6)


def test_local_contrast_keeps_a_flat_image_substantially_unchanged() -> None:
    image = np.full((24, 24, 3), 0.14, dtype=np.float32)
    weights = np.ones(image.shape[:2], dtype=np.float32)

    result = apply_local_contrast(
        image,
        weights,
        amount=0.75,
        structure_size="broad",
        background_protection=0.70,
        highlight_protection=0.70,
        softness=0.50,
    )

    assert np.allclose(result, image, atol=1e-4)


def test_vibrance_boosts_weaker_colour_more_than_stronger_colour() -> None:
    image = np.asarray(
        [
            [
                [0.52, 0.46, 0.46],
                [0.90, 0.12, 0.12],
                [0.35, 0.35, 0.35],
            ]
        ],
        dtype=np.float32,
    )
    weights = np.ones(image.shape[:2], dtype=np.float32)

    result = apply_vibrance(
        image,
        weights,
        amount=0.85,
        protect_strong_colours=0.75,
        protect_bright_areas=0.50,
    )

    before_chroma = np.sqrt(np.sum(rgb_to_oklab(image)[..., 1:] ** 2, axis=-1))
    after_chroma = np.sqrt(np.sum(rgb_to_oklab(result)[..., 1:] ** 2, axis=-1))

    weak_gain = float(after_chroma[0, 0] - before_chroma[0, 0])
    strong_gain = float(after_chroma[0, 1] - before_chroma[0, 1])

    assert weak_gain > strong_gain
    assert np.allclose(result[0, 2], image[0, 2], atol=1e-5)


def test_colour_temperature_warmth_and_tint_shift_in_expected_directions() -> None:
    image = np.asarray([[[0.56, 0.48, 0.42]]], dtype=np.float32)
    weights = np.ones(image.shape[:2], dtype=np.float32)

    warmer = apply_colour_temperature(
        image,
        weights,
        warmth=0.60,
        tint=0.0,
        preserve_brightness=True,
        protect_neutral_background=0.0,
    )
    cooler = apply_colour_temperature(
        image,
        weights,
        warmth=-0.60,
        tint=0.0,
        preserve_brightness=True,
        protect_neutral_background=0.0,
    )
    magenta = apply_colour_temperature(
        image,
        weights,
        warmth=0.0,
        tint=0.60,
        preserve_brightness=True,
        protect_neutral_background=0.0,
    )
    green = apply_colour_temperature(
        image,
        weights,
        warmth=0.0,
        tint=-0.60,
        preserve_brightness=True,
        protect_neutral_background=0.0,
    )

    base_lab = rgb_to_oklab(image)[0, 0]
    warmer_lab = rgb_to_oklab(warmer)[0, 0]
    cooler_lab = rgb_to_oklab(cooler)[0, 0]
    magenta_lab = rgb_to_oklab(magenta)[0, 0]
    green_lab = rgb_to_oklab(green)[0, 0]

    assert warmer_lab[2] > base_lab[2]
    assert cooler_lab[2] < base_lab[2]
    assert magenta_lab[1] > base_lab[1]
    assert green_lab[1] < base_lab[1]
    assert np.allclose(compute_luminance(warmer), compute_luminance(image), atol=5e-3)


@pytest.mark.parametrize(
    ("rule_builder", "inside", "outside"),
    [
        (
            lambda: _rule_tone_shaping(
                rule_id="tone",
                name="Tone Shaping",
                target="combined",
                regions=["lower-right"],
                shadows=0.25,
                midtones=0.35,
                contrast=0.20,
            ),
            (42, 30),
            (10, 10),
        ),
        (
            lambda: _rule_local_contrast(
                rule_id="contrast",
                name="Local Contrast",
                target="combined",
                regions=["lower-right"],
                amount=0.60,
                structure_size="broad",
            ),
            (42, 30),
            (10, 10),
        ),
        (
            lambda: _rule_vibrance(
                rule_id="vibrance",
                name="Vibrance",
                target="combined",
                regions=["lower-right"],
                amount=0.65,
            ),
            (42, 30),
            (10, 10),
        ),
        (
            lambda: _rule_colour_temperature(
                rule_id="temperature",
                name="Colour Temperature",
                target="combined",
                regions=["lower-right"],
                warmth=0.55,
                tint=0.18,
            ),
            (42, 30),
            (10, 10),
        ),
    ],
)
def test_new_adjustments_respect_region_masks(
    tmp_path: Path,
    rule_builder: Any,
    inside: tuple[int, int],
    outside: tuple[int, int],
) -> None:
    project_dir = _create_project(tmp_path, [rule_builder()])
    preview_path = tmp_path / "preview-region.png"
    render_preview(project_dir, preview_path, force=True)

    output = load_canonical_image(preview_path).data
    source = load_canonical_image(project_dir / "sources/source.png").data

    inside_x, inside_y = inside
    outside_x, outside_y = outside
    inside_delta = np.abs(output[inside_y, inside_x] - source[inside_y, inside_x]).mean()
    outside_delta = np.abs(output[outside_y, outside_x] - source[outside_y, outside_x]).mean()

    assert inside_delta > 1e-3
    assert outside_delta < 5e-4


@pytest.mark.parametrize(
    "rule_builder",
    [
        lambda: _rule_tone_shaping(
            rule_id="tone",
            name="Tone Shaping",
            target="nebula",
            shadows=0.25,
            midtones=0.30,
            contrast=0.15,
        ),
        lambda: _rule_local_contrast(
            rule_id="contrast",
            name="Local Contrast",
            target="nebula",
            amount=0.60,
            structure_size="medium",
        ),
        lambda: _rule_vibrance(
            rule_id="vibrance",
            name="Vibrance",
            target="nebula",
            amount=0.65,
        ),
        lambda: _rule_colour_temperature(
            rule_id="temperature",
            name="Colour Temperature",
            target="nebula",
            warmth=0.60,
            tint=0.10,
        ),
    ],
)
def test_new_adjustments_respect_semantic_targets(
    tmp_path: Path,
    rule_builder: Any,
) -> None:
    project_dir = tmp_path / "targeted"
    project_dir.mkdir(parents=True)
    _write_common_files(project_dir)
    _write_star_nebula_source_image(project_dir / "sources/source.png")
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(_base_project_payload([rule_builder()]), sort_keys=False),
        encoding="utf-8",
    )

    preview_path = tmp_path / "preview-target.png"
    render_preview(project_dir, preview_path, force=True)

    output = load_canonical_image(preview_path).data
    source = load_canonical_image(project_dir / "sources/source.png").data

    nebula_delta = np.abs(output[30, 28] - source[30, 28]).mean()
    star_delta = np.abs(output[10, 10] - source[10, 10]).mean()

    assert nebula_delta > star_delta + 1e-3


def test_two_rules_run_in_declaration_order(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    result = render_preview(project_dir, tmp_path / "preview.png", force=True)

    assert result.applied_rule_ids == ["reveal-faint-blue", "shift-blue-glow"]
    assert [trace.declared_order for trace in result.execution_trace] == [1, 2]
    assert [trace.rule_id for trace in result.execution_trace] == [
        "reveal-faint-blue",
        "shift-blue-glow",
    ]


def test_reversing_rule_order_changes_output(tmp_path: Path) -> None:
    project_a = _create_project(
        tmp_path / "a",
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    project_b = _create_project(
        tmp_path / "b",
        [
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
        ],
    )

    preview_a = tmp_path / "a-preview.png"
    preview_b = tmp_path / "b-preview.png"
    render_preview(project_a, preview_a, force=True)
    render_preview(project_b, preview_b, force=True)

    image_a = load_canonical_image(preview_a).data
    image_b = load_canonical_image(preview_b).data
    assert not np.allclose(image_a, image_b, atol=1e-6)


def test_disabling_rule_preserves_it_but_excludes_effect(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                enabled=False,
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    result = render_preview(project_dir, tmp_path / "preview.png", force=True)

    assert result.declared_rule_ids == ["reveal-faint-blue", "shift-blue-glow"]
    assert result.enabled_rule_ids == ["shift-blue-glow"]
    assert result.applied_rule_ids == ["shift-blue-glow"]
    assert result.skipped_rules == [{"id": "reveal-faint-blue", "reason": "disabled"}]


def test_removing_one_rule_leaves_later_rule_active(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            )
        ],
    )
    result = render_preview(project_dir, tmp_path / "preview.png", force=True)

    assert result.applied_rule_ids == ["shift-blue-glow"]
    assert len(result.execution_trace) == 1


def test_original_vs_current_selection_source_behaves_differently(tmp_path: Path) -> None:
    project_current = _create_project(
        tmp_path / "current",
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    project_original = _create_project(
        tmp_path / "original",
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
        ],
    )

    preview_current = tmp_path / "current.png"
    preview_original = tmp_path / "original.png"
    render_preview(project_current, preview_current, force=True)
    render_preview(project_original, preview_original, force=True)

    current_data = load_canonical_image(preview_current).data
    original_data = load_canonical_image(preview_original).data
    assert not np.allclose(current_data, original_data, atol=1e-6)


def test_zero_rule_project_produces_resized_source_preview(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, [])
    output_path = tmp_path / "preview.png"
    result = render_preview(project_dir, output_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png")
    resized = resize_to_max_edge(source, 1024)
    preview = load_canonical_image(output_path)

    assert result.applied_rule_ids == []
    np.testing.assert_allclose(preview.data, resized.data, atol=1e-6)


def test_preview_rule_execution_uses_preview_sized_working_image_for_large_sources(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "preview-large"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_source_image(project_dir / "sources/source.png", size=(2048, 1024))
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(
            _base_project_payload(
                [
                    _rule_brightness(
                        rule_id="increase-blue",
                        name="Lift",
                        target="combined",
                    )
                ]
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    bundle, report = load_valid_project_bundle(project_dir)
    assert bundle is not None
    assert report.valid is True

    result = render_preview_image(bundle, include_provenance=False, use_cached_sources=True)

    assert result.width == 1024
    assert result.height == 512
    assert result.execution_trace[0].affected_pixel_count == 1024 * 512


def test_existing_single_rule_projects_remain_compatible(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_source_image(project_dir / "sources/source.png")
    legacy_payload = _base_project_payload(
        [
            {
                "id": "increase-nebula-blue",
                "target": "nebula",
                "match": {
                    "colour_point": "nebula-blue",
                    "colour_range": 0.18,
                    "softness": 0.5,
                    "regions": ["lower-right"],
                },
                "transform": {"blue": 0.25, "preserve_brightness": True},
            }
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(legacy_payload, sort_keys=False),
        encoding="utf-8",
    )

    result = render_preview(project_dir, tmp_path / "legacy.png", force=True)
    assert result.applied_rule_ids == ["increase-nebula-blue"]


def test_explicit_legacy_colour_amount_matches_legacy_default_rendering(tmp_path: Path) -> None:
    project_implicit = _create_project(
        tmp_path / "implicit",
        [
            _rule_colour_amount(
                rule_id="legacy-blue",
                name="Legacy Blue",
                amount=2.0,
            )
        ],
    )
    project_explicit = _create_project(
        tmp_path / "explicit",
        [
            _rule_colour_amount(
                rule_id="legacy-blue",
                name="Legacy Blue",
                amount=2.0,
                response_version="legacy",
                faint_colour_sensitivity=0.0,
                reveal_faint_colour=0.0,
                highlight_protection=0.0,
                extended_range=False,
            )
        ],
    )

    implicit_path = tmp_path / "implicit.png"
    explicit_path = tmp_path / "explicit.png"
    render_preview(project_implicit, implicit_path, force=True)
    render_preview(project_explicit, explicit_path, force=True)

    implicit = load_canonical_image(implicit_path).data
    explicit = load_canonical_image(explicit_path).data
    np.testing.assert_allclose(implicit, explicit, atol=1e-6)


def test_enhanced_colour_amount_preview_is_stronger_than_legacy_at_same_amount(
    tmp_path: Path,
) -> None:
    project_legacy = _create_project(
        tmp_path / "legacy-strength",
        [
            _rule_colour_amount(
                rule_id="blue-legacy",
                name="Blue Legacy",
                target="combined",
                amount=2.0,
                response_version="legacy",
            )
        ],
    )
    project_enhanced = _create_project(
        tmp_path / "enhanced-strength",
        [
            _rule_colour_amount(
                rule_id="blue-enhanced",
                name="Blue Enhanced",
                target="combined",
                amount=2.0,
                response_version="enhanced",
                faint_colour_sensitivity=0.20,
                highlight_protection=0.65,
                colour_range=0.24,
            )
        ],
    )

    legacy_path = tmp_path / "legacy-strength.png"
    enhanced_path = tmp_path / "enhanced-strength.png"
    render_preview(project_legacy, legacy_path, force=True)
    render_preview(project_enhanced, enhanced_path, force=True)

    source = load_canonical_image(project_legacy / "sources/source.png").data
    legacy = load_canonical_image(legacy_path).data
    enhanced = load_canonical_image(enhanced_path).data

    legacy_delta = float(np.abs(legacy[6:18, 6:18] - source[6:18, 6:18]).mean())
    enhanced_delta = float(np.abs(enhanced[6:18, 6:18] - source[6:18, 6:18]).mean())

    assert enhanced_delta > (legacy_delta * 1.10)


def test_execution_trace_is_stable_and_ordered(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    result = render_preview(project_dir, tmp_path / "preview.png", force=True)

    assert [trace.rule_id for trace in result.execution_trace] == [
        "reveal-faint-blue",
        "shift-blue-glow",
    ]
    assert [trace.declared_order for trace in result.execution_trace] == [1, 2]
    assert all(trace.ran for trace in result.execution_trace)


def test_debug_masks_are_emitted_per_rule(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    debug_dir = tmp_path / "debug"
    render_preview(
        project_dir,
        tmp_path / "preview.png",
        force=True,
        write_debug_masks_dir=debug_dir,
    )

    assert (debug_dir / "001-reveal-faint-blue-glow/colour-weight.png").is_file()
    assert (debug_dir / "001-reveal-faint-blue-glow/brightness-weight.png").is_file()
    assert (debug_dir / "001-reveal-faint-blue-glow/region-weight.png").is_file()
    assert (debug_dir / "001-reveal-faint-blue-glow/target-weight.png").is_file()
    assert (debug_dir / "001-reveal-faint-blue-glow/combined-weight.png").is_file()
    assert (debug_dir / "002-shift-blue-glow/combined-weight.png").is_file()


def test_renderer_stability_for_multi_rule_project(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    output_path = tmp_path / "preview.png"
    render_preview(project_dir, output_path, force=True)
    preview = load_canonical_image(output_path)

    expected = np.array(
        [
            [0.118, 0.098, 0.353],
            [0.125, 0.098, 0.361],
            [0.133, 0.098, 0.369],
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(preview.data[0, :3], expected, atol=0.04)


def test_cli_integration_with_multiple_rules(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_colour_amount(
                rule_id="reveal-faint-blue",
                name="Reveal faint blue glow",
                selection_source="original",
                regions=["lower-right"],
            ),
            _rule_shift_colour(
                rule_id="shift-blue-glow",
                name="Shift blue glow",
                selection_source="current",
                regions=["lower-right"],
            ),
        ],
    )
    output_path = tmp_path / "preview.png"
    debug_dir = tmp_path / "debug"

    result = RUNNER.invoke(
        app,
        [
            "preview",
            str(project_dir),
            "--output",
            str(output_path),
            "--write-debug-masks",
            str(debug_dir),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_VALIDATION_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["declared_rule_ids"] == ["reveal-faint-blue", "shift-blue-glow"]
    assert payload["enabled_rule_ids"] == ["reveal-faint-blue", "shift-blue-glow"]
    assert payload["applied_rule_ids"] == ["reveal-faint-blue", "shift-blue-glow"]
    assert len(payload["execution_trace"]) == 2
    manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["declared_rule_ids"] == ["reveal-faint-blue", "shift-blue-glow"]


def test_stars_target_only_affects_star_pixels(tmp_path: Path) -> None:
    project_dir = tmp_path / "stars-project"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_star_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_brightness(
                rule_id="dim-stars",
                name="Dim Stars",
                target="stars",
                amount=0.4,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )

    preview_path = tmp_path / "stars-preview.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data

    star_pixel_shift = float(preview[8, 10, 0] - source[8, 10, 0])
    nebula_pixel_shift = float(preview[24, 32, 0] - source[24, 32, 0])
    background_shift = float(preview[4, 4, 0] - source[4, 4, 0])

    assert star_pixel_shift < -0.05
    assert abs(nebula_pixel_shift) < 0.02
    assert abs(background_shift) < 0.02


def test_nebula_target_only_affects_diffuse_nebula_pixels(tmp_path: Path) -> None:
    project_dir = tmp_path / "nebula-project"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_star_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [_rule_brightness(rule_id="lift-nebula", name="Lift Nebula", target="nebula")]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )

    preview_path = tmp_path / "nebula-preview.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data

    star_pixel_shift = float(preview[8, 10, 0] - source[8, 10, 0])
    nebula_pixel_shift = float(preview[24, 32, 0] - source[24, 32, 0])
    background_shift = float(preview[4, 4, 0] - source[4, 4, 0])

    assert nebula_pixel_shift > 0.05
    assert star_pixel_shift < 0.02
    assert background_shift > 0.02


def test_flat_black_image_produces_little_or_no_dark_dust_mask() -> None:
    image = np.zeros((32, 32, 3), dtype=np.float32)
    mask = dark_dust_influence(image)

    assert float(mask.max()) < 0.01


def test_uniform_grey_image_produces_little_or_no_dark_dust_mask() -> None:
    image = np.full((32, 32, 3), 0.35, dtype=np.float32)
    mask = dark_dust_influence(image)

    assert float(mask.max()) < 0.02


def test_broad_dark_shape_within_brighter_field_produces_dark_dust_mask() -> None:
    image = np.full((64, 64, 3), 0.55, dtype=np.float32)
    image[18:46, 18:46, :] = 0.18
    mask = dark_dust_influence(image)

    assert float(mask[32, 32]) > 0.4
    assert float(mask[6, 6]) < 0.05


def test_dark_dust_analysis_distinguishes_veil_and_core_masks() -> None:
    image = _dark_nebula_fixture_float_image()
    analysis = analyze_dark_dust(image)

    veil_value = float(analysis.veil_mask.max())
    core_value = float(analysis.core_mask.max())
    background_value = float(analysis.final_mask[6, 6])

    assert veil_value > 0.50
    assert core_value > 0.70
    assert core_value > float(analysis.core_mask[40, 40])
    assert background_value < 0.20


def test_dark_dust_analysis_masks_are_clamped_and_match_image_dimensions() -> None:
    image = _dark_nebula_fixture_float_image()
    analysis = analyze_dark_dust(image)

    for plane in (
        analysis.final_mask,
        analysis.veil_mask,
        analysis.core_mask,
        analysis.relative_darkness,
        analysis.local_illumination,
        analysis.background_support,
    ):
        assert plane.shape == image.shape[:2]
        assert float(plane.min()) >= 0.0
        assert float(plane.max()) <= 1.0


def test_dark_dust_background_protection_reduces_low_support_selection() -> None:
    image = _dark_nebula_fixture_float_image()

    low_protection = analyze_dark_dust(
        image,
        settings=DarkDustSettings(background_protection=0.0),
    )
    high_protection = analyze_dark_dust(
        image,
        settings=DarkDustSettings(background_protection=1.0),
    )

    assert float(high_protection.final_mask.mean()) < float(low_protection.final_mask.mean())
    assert float(high_protection.final_mask[6, 6]) <= float(low_protection.final_mask[6, 6])
    assert float(high_protection.final_mask[40, 40]) < float(low_protection.final_mask[40, 40])


def test_dark_dust_structure_size_changes_detected_structure_scale() -> None:
    image = _dark_nebula_fixture_float_image()
    compact = analyze_dark_dust(
        image,
        settings=DarkDustSettings(structure_size=0.04),
    )
    broad = analyze_dark_dust(
        image,
        settings=DarkDustSettings(structure_size=0.25),
    )

    assert float(compact.final_mask[18, 60]) > float(broad.final_mask[18, 60])
    assert np.allclose(compact.final_mask, broad.final_mask) is False


def test_dark_dust_softness_changes_edge_transition_more_than_detection_extent() -> None:
    image = _dark_nebula_fixture_float_image()
    crisp = analyze_dark_dust(
        image,
        settings=DarkDustSettings(softness=0.05),
    )
    soft = analyze_dark_dust(
        image,
        settings=DarkDustSettings(softness=0.75),
    )

    crisp_extent = int(np.count_nonzero(crisp.final_mask > 0.50))
    soft_extent = int(np.count_nonzero(soft.final_mask > 0.50))
    crisp_partial = int(np.count_nonzero((crisp.final_mask > 0.05) & (crisp.final_mask < 0.95)))
    soft_partial = int(np.count_nonzero((soft.final_mask > 0.05) & (soft.final_mask < 0.95)))

    assert soft_extent != crisp_extent
    assert soft_partial > crisp_partial


def test_dark_dust_coverage_is_deterministic() -> None:
    image = _dark_nebula_fixture_float_image()
    first = analyze_dark_dust(image)
    second = analyze_dark_dust(image)

    assert first.coverage_percent == second.coverage_percent
    assert np.array_equal(first.final_mask, second.final_mask)


def test_isolated_black_pixels_are_suppressed_from_dark_dust_mask() -> None:
    image = np.full((64, 64, 3), 0.55, dtype=np.float32)
    image[32, 32, :] = 0.0
    mask = dark_dust_influence(image)

    assert float(mask[32, 32]) < 0.2


def test_stars_are_excluded_from_dark_dust_mask() -> None:
    image = np.full((64, 64, 3), 0.55, dtype=np.float32)
    image[18:46, 18:46, :] = 0.20
    image[31:34, 31:34, :] = 1.0

    mask = dark_dust_influence(image)
    stars = star_influence(image)

    assert float(stars[32, 32]) > 0.5
    assert float(mask[32, 32]) < 0.1


def test_dark_dust_is_a_subset_of_non_star_content() -> None:
    image = np.full((64, 64, 3), 0.55, dtype=np.float32)
    image[18:46, 18:46, :] = 0.20
    image[8:11, 8:11, :] = 1.0

    mask = dark_dust_influence(image)
    non_star = 1.0 - star_influence(image)

    assert np.all(mask <= non_star + 1e-5)


def test_dark_dust_target_only_affects_broad_relative_dark_regions(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-dust-project"
    project_dir.mkdir()
    _write_common_files(project_dir)
    dark_dust_source = np.full((48, 64, 3), 160, dtype=np.uint8)
    dark_dust_source[12:36, 20:48, :] = 70
    dark_dust_source[7:10, 9:12, :] = 255
    Image.fromarray(dark_dust_source, mode="RGB").save(
        project_dir / "sources/source.png",
        format="PNG",
    )
    payload = _base_project_payload(
        [_rule_brightness(rule_id="lift-dark-dust", name="Lift Dark Dust", target="dark_dust")]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )

    preview_path = tmp_path / "dark-dust-preview.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data

    dark_dust_shift = float(preview[24, 32, 0] - source[24, 32, 0])
    star_shift = float(preview[8, 10, 0] - source[8, 10, 0])
    background_shift = float(preview[4, 4, 0] - source[4, 4, 0])

    assert dark_dust_shift > 0.02
    assert abs(star_shift) < 0.02
    assert abs(background_shift) < 0.02


def test_faux_hubble_amount_zero_produces_unchanged_output() -> None:
    image = _faux_palette_swatch_image()
    for palette in FAUX_PALETTE_IDS:
        transformed = _palette_output(palette, amount=0.0)
        assert np.allclose(transformed, image)


def test_faux_palettes_amount_hundred_produces_full_mapped_result() -> None:
    image = _faux_palette_swatch_image()
    for palette in FAUX_PALETTE_IDS:
        full = _palette_output(palette, amount=1.0)
        assert not np.allclose(full, image)


def test_faux_palettes_amount_fifty_is_midpoint_between_incoming_and_full_mapping() -> None:
    for palette in FAUX_PALETTE_IDS:
        unchanged = _palette_output(palette, amount=0.0)
        midpoint = _palette_output(palette, amount=0.5)
        full = _palette_output(palette, amount=1.0)
        assert np.allclose(midpoint, (unchanged + full) / 2.0, atol=1e-5)


def test_faux_palette_all_colour_balances_zero_resolves_to_incoming_image() -> None:
    image = _faux_palette_swatch_image()
    for palette in FAUX_PALETTE_IDS:
        if palette == "hubble":
            colour_balance = {"gold": 0.0, "green": 0.0, "cyan": 0.0}
        elif palette == "hoo":
            colour_balance = {"red": 0.0, "cyan": 0.0}
        elif palette == "foraxx":
            colour_balance = {"amber": 0.0, "cyan": 0.0}
        elif palette == "gold_cyan":
            colour_balance = {"gold": 0.0, "cyan": 0.0}
        else:
            colour_balance = {"warm": 0.0, "cool": 0.0}
        transformed = _palette_output(palette, amount=1.0, colour_balance=colour_balance)
        assert np.allclose(transformed, image, atol=1e-6)


def test_hubble_colour_balance_controls_shift_expected_destination_families() -> None:
    default = _palette_output("hubble", amount=1.0)
    boosted_cyan = _palette_output(
        "hubble",
        amount=1.0,
        colour_balance={"gold": 100.0, "green": 100.0, "cyan": 200.0},
    )
    reduced_gold = _palette_output(
        "hubble",
        amount=1.0,
        colour_balance={"gold": 0.0, "green": 100.0, "cyan": 100.0},
    )

    assert boosted_cyan[0, 1, 2] > default[0, 1, 2]
    assert reduced_gold[0, 0, 0] < default[0, 0, 0]


def test_faux_palettes_preserve_brightness_keeps_luminance_within_tolerance() -> None:
    image = _faux_palette_swatch_image()
    source_luma = compute_luminance(image)
    for palette in FAUX_PALETTE_IDS:
        transformed = _palette_output(palette, amount=1.0, preserve_brightness=True)
        transformed_luma = compute_luminance(transformed)
        assert np.allclose(source_luma, transformed_luma, atol=0.04)


def test_faux_hubble_adjustment_consumes_output_of_earlier_adjustments(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_brightness(rule_id="lift", name="Lift", target="combined", amount=1.6),
            _rule_faux_palette(rule_id="faux", name="Faux Hubble", target="combined", amount=1.0),
        ],
    )
    preview_path = tmp_path / "ordered.png"
    render_preview(project_dir, preview_path, force=True)
    ordered = load_canonical_image(preview_path).data

    project_reversed = _create_project(
        tmp_path / "other",
        [
            _rule_faux_palette(rule_id="faux", name="Faux Hubble", target="combined", amount=1.0),
            _rule_brightness(rule_id="lift", name="Lift", target="combined", amount=1.6),
        ],
    )
    preview_reversed = tmp_path / "reversed.png"
    render_preview(project_reversed, preview_reversed, force=True)
    reversed_image = load_canonical_image(preview_reversed).data

    assert not np.allclose(ordered, reversed_image)


def test_faux_hubble_targeting_nebula_protects_stars(tmp_path: Path) -> None:
    project_dir = tmp_path / "nebula-faux"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_star_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [_rule_faux_palette(rule_id="faux", name="Faux Hubble", target="nebula", amount=1.0)]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    preview_path = tmp_path / "nebula-faux.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data
    star_delta = float(np.abs(preview[8, 10] - source[8, 10]).max())
    nebula_delta = float(np.abs(preview[24, 32] - source[24, 32]).max())

    assert star_delta < 0.02
    assert nebula_delta > 0.02


def test_faux_hubble_targeting_dark_dust_uses_dark_dust_mask(tmp_path: Path) -> None:
    project_dir = tmp_path / "dust-faux"
    project_dir.mkdir()
    _write_common_files(project_dir)
    image = np.full((48, 64, 3), 160, dtype=np.uint8)
    image[12:36, 20:48, :] = [70, 55, 55]
    image[7:10, 9:12, :] = 255
    Image.fromarray(image, mode="RGB").save(project_dir / "sources/source.png", format="PNG")
    payload = _base_project_payload(
        [_rule_faux_palette(rule_id="faux", name="Faux Hubble", target="dark_dust", amount=1.0)]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    preview_path = tmp_path / "dust-faux.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data
    dust_delta = float(np.abs(preview[24, 32] - source[24, 32]).max())
    background_delta = float(np.abs(preview[4, 4] - source[4, 4]).max())

    assert dust_delta > 0.02
    assert background_delta < 0.02


def test_dark_nebula_processing_amount_zero_is_unchanged(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-nebula-zero"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula", name="Dark Nebula Processing", amount=0.0
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    preview_path = tmp_path / "dark-nebula-zero.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data
    assert np.allclose(preview, source, atol=1e-6)


def test_dark_nebula_processing_reveal_dust_raises_veil_luminance(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-nebula-reveal"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.80,
                dust_contrast=0.0,
                core_depth=0.0,
                dust_colour=0.0,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    bundle, report = load_valid_project_bundle(project_dir)
    assert bundle is not None
    assert report.valid is True
    source_luma = compute_luminance(load_canonical_image(project_dir / "sources/source.png").data)
    preview_luma = compute_luminance(render_preview_image(bundle).image.data)

    assert float(preview_luma[40, 58]) > float(source_luma[40, 58]) + 0.02


def test_dark_nebula_processing_core_depth_keeps_core_darker_than_lifted_veil(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "dark-nebula-core"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.75,
                dust_contrast=0.35,
                core_depth=0.85,
                dust_colour=0.0,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    bundle, report = load_valid_project_bundle(project_dir)
    assert bundle is not None
    assert report.valid is True
    preview_luma = compute_luminance(render_preview_image(bundle).image.data)
    assert float(preview_luma[40, 58]) > float(preview_luma[40, 40]) + 0.005


def test_dark_nebula_processing_dust_contrast_increases_low_frequency_veil_contrast(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "dark-nebula-contrast"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")

    low_payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.75,
                dust_contrast=0.0,
                core_depth=0.35,
                dust_colour=0.0,
            )
        ]
    )
    high_payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.75,
                dust_contrast=0.85,
                core_depth=0.35,
                dust_colour=0.0,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(low_payload, sort_keys=False), encoding="utf-8"
    )
    low_bundle, low_report = load_valid_project_bundle(project_dir)
    assert low_bundle is not None
    assert low_report.valid is True
    low_luma = compute_luminance(render_preview_image(low_bundle).image.data)
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(high_payload, sort_keys=False), encoding="utf-8"
    )
    high_bundle, high_report = load_valid_project_bundle(project_dir)
    assert high_bundle is not None
    assert high_report.valid is True
    high_luma = compute_luminance(render_preview_image(high_bundle).image.data)
    low_delta = abs(float(low_luma[37, 54] - low_luma[44, 58]))
    high_delta = abs(float(high_luma[37, 54] - high_luma[44, 58]))

    assert high_delta > low_delta


def test_dark_nebula_processing_dust_colour_increases_existing_chroma_without_new_hue_family(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "dark-nebula-colour"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")

    neutral_payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.70,
                dust_contrast=0.20,
                core_depth=0.35,
                dust_colour=0.0,
            )
        ]
    )
    colour_payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.70,
                dust_contrast=0.20,
                core_depth=0.35,
                dust_colour=0.85,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(neutral_payload, sort_keys=False), encoding="utf-8"
    )
    neutral_bundle, neutral_report = load_valid_project_bundle(project_dir)
    assert neutral_bundle is not None
    assert neutral_report.valid is True
    neutral = render_preview_image(neutral_bundle).image.data[37, 54]
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(colour_payload, sort_keys=False), encoding="utf-8"
    )
    colour_bundle, colour_report = load_valid_project_bundle(project_dir)
    assert colour_bundle is not None
    assert colour_report.valid is True
    coloured = render_preview_image(colour_bundle).image.data[37, 54]
    neutral_chroma = float(np.max(neutral) - np.min(neutral))
    colour_chroma = float(np.max(coloured) - np.min(coloured))

    assert colour_chroma > neutral_chroma + 0.02
    assert int(np.argmax(neutral)) == int(np.argmax(coloured))


def test_dark_nebula_processing_preserve_bright_areas_limits_highlight_changes(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "dark-nebula-bright"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")

    protected_payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.80,
                dust_contrast=0.50,
                core_depth=0.45,
                dust_colour=0.20,
                preserve_bright_areas=True,
            )
        ]
    )
    unprotected_payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.80,
                dust_contrast=0.50,
                core_depth=0.45,
                dust_colour=0.20,
                preserve_bright_areas=False,
            )
        ]
    )
    source = load_canonical_image(project_dir / "sources/source.png").data
    bright_source = np.clip((source * 255.0) + 70.0, 0.0, 255.0).astype(np.uint8, copy=False)
    Image.fromarray(bright_source, mode="RGB").save(
        project_dir / "sources/source.png", format="PNG"
    )

    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(protected_payload, sort_keys=False), encoding="utf-8"
    )
    protected_bundle, protected_report = load_valid_project_bundle(project_dir)
    assert protected_bundle is not None
    assert protected_report.valid is True
    protected = render_preview_image(protected_bundle).image.data
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(unprotected_payload, sort_keys=False), encoding="utf-8"
    )
    unprotected_bundle, unprotected_report = load_valid_project_bundle(project_dir)
    assert unprotected_bundle is not None
    assert unprotected_report.valid is True
    unprotected = render_preview_image(unprotected_bundle).image.data

    source = load_canonical_image(project_dir / "sources/source.png").data
    protected_delta = float(np.abs(protected[40, 58] - source[40, 58]).max())
    unprotected_delta = float(np.abs(unprotected[40, 58] - source[40, 58]).max())

    assert protected_delta <= unprotected_delta


def test_dark_nebula_processing_does_not_globally_lift_empty_background(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-nebula-background"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.90,
                dust_contrast=0.60,
                core_depth=0.50,
                dust_colour=0.20,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    preview_path = tmp_path / "dark-nebula-background.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data
    background_delta = float(np.abs(preview[6, 6] - source[6, 6]).max())

    assert background_delta < 0.02


def test_dark_nebula_processing_keeps_core_gradients_and_avoids_flat_black(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-nebula-gradients"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.80,
                dust_contrast=0.55,
                core_depth=0.95,
                dust_colour=0.10,
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    preview_path = tmp_path / "dark-nebula-gradients.png"
    render_preview(project_dir, preview_path, force=True)

    preview_luma = compute_luminance(load_canonical_image(preview_path).data)
    core_patch = preview_luma[34:44, 44:54]

    assert float(core_patch.min()) > 0.0
    assert float(core_patch.std()) > 0.002


def test_dark_nebula_processing_regions_constrain_the_effect(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-nebula-region"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=1.0,
                reveal_dust=0.75,
                dust_contrast=0.40,
                core_depth=0.50,
                regions=["lower-right"],
            )
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    bundle, report = load_valid_project_bundle(project_dir)
    assert bundle is not None
    assert report.valid is True
    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = render_preview_image(bundle).image.data
    inside_delta = float(np.abs(preview[40, 58] - source[40, 58]).max())
    outside_delta = float(np.abs(preview[20, 22] - source[20, 22]).max())

    assert inside_delta > 0.02
    assert outside_delta < 0.01


def test_dark_nebula_processing_ordering_remains_deterministic(tmp_path: Path) -> None:
    project_dir = tmp_path / "dark-nebula-deterministic"
    project_dir.mkdir()
    _write_common_files(project_dir)
    _write_dark_nebula_source_image(project_dir / "sources/source.png")
    payload = _base_project_payload(
        [
            _rule_dark_nebula_processing(
                rule_id="dark-nebula",
                name="Dark Nebula Processing",
                amount=0.65,
                reveal_dust=0.55,
                dust_contrast=0.45,
                core_depth=0.60,
                dust_colour=0.30,
            ),
            _rule_faux_palette(
                rule_id="faux",
                name="Foraxx-Inspired",
                target="dark_dust",
                palette="foraxx",
                amount=0.25,
            ),
        ]
    )
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    first_path = tmp_path / "dark-nebula-deterministic-first.png"
    second_path = tmp_path / "dark-nebula-deterministic-second.png"
    render_preview(project_dir, first_path, force=True)
    render_preview(project_dir, second_path, force=True)

    first = load_canonical_image(first_path).data
    second = load_canonical_image(second_path).data
    assert np.array_equal(first, second)


def test_dark_nebula_processing_avoids_nan_and_infinity_for_extreme_inputs(tmp_path: Path) -> None:
    for name, fill in (
        ("black", 0),
        ("very-dark", 8),
        ("grey", 128),
        ("white", 255),
    ):
        project_dir = tmp_path / name
        project_dir.mkdir()
        _write_common_files(project_dir)
        image = np.full((48, 64, 3), fill, dtype=np.uint8)
        Image.fromarray(image, mode="RGB").save(project_dir / "sources/source.png", format="PNG")
        payload = _base_project_payload(
            [_rule_dark_nebula_processing(rule_id="dark-nebula", name="Dark Nebula Processing")]
        )
        (project_dir / "project.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )
        preview_path = tmp_path / f"{name}.png"
        render_preview(project_dir, preview_path, force=True)
        preview = load_canonical_image(preview_path).data

        assert np.isfinite(preview).all()


def test_faux_hubble_regions_constrain_the_effect(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [
            _rule_faux_palette(
                rule_id="faux",
                name="Faux Hubble",
                target="combined",
                amount=1.0,
                regions=["lower-right"],
            )
        ],
    )
    preview_path = tmp_path / "regional.png"
    render_preview(project_dir, preview_path, force=True)

    source = load_canonical_image(project_dir / "sources/source.png").data
    preview = load_canonical_image(preview_path).data
    inside_delta = float(np.abs(preview[36, 50] - source[36, 50]).max())
    outside_delta = float(np.abs(preview[8, 8] - source[8, 8]).max())

    assert inside_delta > 0.02
    assert outside_delta < 0.02


def test_faux_hubble_render_is_deterministic(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        [_rule_faux_palette(rule_id="faux", name="Faux Hubble", target="combined", amount=0.6)],
    )
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    render_preview(project_dir, first_path, force=True)
    render_preview(project_dir, second_path, force=True)

    first = load_canonical_image(first_path).data
    second = load_canonical_image(second_path).data
    assert np.array_equal(first, second)


def test_faux_palettes_produce_meaningfully_different_outputs() -> None:
    outputs = {palette: _palette_output(palette, amount=1.0) for palette in FAUX_PALETTE_IDS}
    for palette_a, image_a in outputs.items():
        for palette_b, image_b in outputs.items():
            if palette_a >= palette_b:
                continue
            assert not np.allclose(image_a, image_b, atol=1e-4)


def test_faux_hoo_is_predominantly_red_and_cyan_with_limited_green() -> None:
    output = _palette_output("hoo", amount=1.0)
    warm_pixel = output[0, 0]
    cool_pixel = output[0, 2]
    assert warm_pixel[0] > warm_pixel[1]
    assert cool_pixel[2] >= cool_pixel[1]
    assert float(output[..., 1].mean()) < (float(output[..., 0].mean()) + 0.08)


def test_foraxx_is_more_aggressive_than_gold_and_cyan() -> None:
    foraxx = _palette_output("foraxx", amount=1.0)
    gold_cyan = _palette_output("gold_cyan", amount=1.0)
    foraxx_separation = float(np.linalg.norm(foraxx[0, 0] - foraxx[0, 2]))
    gold_cyan_separation = float(np.linalg.norm(gold_cyan[0, 0] - gold_cyan[0, 2]))
    foraxx_chroma = float((np.max(foraxx, axis=-1) - np.min(foraxx, axis=-1)).mean())
    gold_cyan_chroma = float((np.max(gold_cyan, axis=-1) - np.min(gold_cyan, axis=-1)).mean())
    assert foraxx_separation > gold_cyan_separation
    assert foraxx_chroma > gold_cyan_chroma


def test_natural_bicolour_preserves_more_original_chroma_than_faux_hoo() -> None:
    source = _faux_palette_swatch_image()
    hoo = _palette_output("hoo", amount=1.0)
    natural = _palette_output("natural_bicolour", amount=1.0)
    source_shift_hoo = float(np.abs(hoo - source).mean())
    source_shift_natural = float(np.abs(natural - source).mean())
    hoo_chroma = float((np.max(hoo, axis=-1) - np.min(hoo, axis=-1)).mean())
    natural_chroma = float((np.max(natural, axis=-1) - np.min(natural, axis=-1)).mean())
    assert source_shift_natural < source_shift_hoo
    assert natural_chroma < hoo_chroma


def test_faux_palettes_do_not_produce_nan_or_infinite_values() -> None:
    samples = np.asarray(
        [
            [
                [0.0, 0.0, 0.0],
                [1.0, 1.0, 1.0],
                [0.5, 0.5, 0.5],
                [0.8, 0.1, 0.1],
                [0.02, 0.02, 0.03],
            ]
        ],
        dtype=np.float32,
    )
    weights = np.ones(samples.shape[:2], dtype=np.float32)
    for palette in FAUX_PALETTE_IDS:
        output = apply_faux_palette(
            samples,
            weights,
            palette=palette,
            amount=1.0,
            preserve_brightness=True,
        )
        assert np.isfinite(output).all()

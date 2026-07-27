from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from engine import EXIT_VALIDATION_SUCCESS
from engine.preview import render_preview, render_preview_image
from engine.selection import apply_faux_palette, compute_luminance
from engine.semantic import dark_dust_influence, star_influence
from engine.validation import load_valid_project_bundle
from image_io import load_canonical_image, resize_to_max_edge
from PIL import Image
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
    regions: list[str] | None = None,
    amount: float = 2.0,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "name": name,
        "enabled": enabled,
        "selection_source": selection_source,
        "target": "nebula",
        "regions": regions or [],
        "match": {
            "colour_point": "nebula-blue",
            "colour_range": 0.18,
            "brightness": {"min": 0.0, "max": 1.0},
            "softness": 0.5,
        },
        "transform": {
            "type": "colour_amount",
            "channel": "blue",
            "amount": amount,
            "preserve_luminance": False,
        },
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
        },
    }


def _faux_palette_swatch_image() -> np.ndarray:
    return np.asarray(
        [[
            [0.82, 0.22, 0.12],
            [0.74, 0.16, 0.48],
            [0.08, 0.72, 0.88],
            [0.12, 0.28, 0.84],
            [0.45, 0.45, 0.45],
        ]],
        dtype=np.float32,
    )


def _palette_output(
    palette: str,
    *,
    amount: float = 1.0,
    preserve_brightness: bool = True,
) -> np.ndarray:
    image = _faux_palette_swatch_image()
    weights = np.ones(image.shape[:2], dtype=np.float32)
    return apply_faux_palette(
        image,
        weights,
        palette=palette,
        amount=amount,
        preserve_brightness=preserve_brightness,
    )


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
        [[
            [0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            [0.5, 0.5, 0.5],
            [0.8, 0.1, 0.1],
            [0.02, 0.02, 0.03],
        ]],
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

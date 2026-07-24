from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from engine import EXIT_VALIDATION_SUCCESS
from engine.preview import render_preview, render_preview_image
from engine.validation import load_valid_project_bundle
from image_io import load_canonical_image, resize_to_max_edge
from PIL import Image
from renderer_cli.main import app
from typer.testing import CliRunner

RUNNER = CliRunner()


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
        "semantic_channels": [{"id": "nebula", "name": "Nebula"}],
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

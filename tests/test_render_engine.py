from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from engine import EXIT_INPUT_ERROR, EXIT_VALIDATION_SUCCESS
from engine.render import apply_crop, plan_render, render_output
from engine.selection import apply_levels_transform
from image_io import CanonicalImage, load_canonical_image, resize_exact
from PIL import Image
from project_model import CropDeclaration, PrintRenderProfile, ScreenRenderProfile
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
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_source_image(path: Path, size: tuple[int, int] = (120, 80)) -> None:
    width, height = size
    data = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            data[y, x] = [
                min(255, 20 + x * 2),
                min(255, 15 + y * 3),
                min(255, 70 + x + y),
            ]
    data[24:72, 60:116, 2] = np.clip(data[24:72, 60:116, 2] + 80, 0, 255)
    Image.fromarray(data, mode="RGB").save(path, format="PNG")


def _write_common_files(project_dir: Path) -> None:
    for directory in ["palettes", "regions", "render_profiles", "plugins", "sources"]:
        (project_dir / directory).mkdir(parents=True, exist_ok=True)

    _write_palette(project_dir)
    (project_dir / "regions/lower-right.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "lower-right",
                "name": "Lower Right",
                "feather": {"radius": 0.04},
                "polygon": [[0.45, 0.30], [0.98, 0.30], [0.98, 0.95], [0.45, 0.95]],
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


def _profile_file(project_dir: Path, profile_id: str, payload: dict[str, Any]) -> None:
    (project_dir / f"render_profiles/{profile_id}.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _base_project_payload(
    render_profiles: list[dict[str, str]],
    *,
    crop: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {"id": "render-demo", "name": "Render Demo"},
        "sources": [{"id": "source-01", "path": "sources/source.png", "enabled": True}],
        "semantic_channels": [{"id": "nebula", "name": "Nebula"}],
        "palettes": [{"id": "default-nebula", "path": "palettes/default-nebula.yaml"}],
        "regions": [{"id": "lower-right", "path": "regions/lower-right.yaml"}],
        "render_profiles": render_profiles,
        "plugins": {"path": "plugins/lock.yaml"},
        "crop": crop or {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
        "rules": [
            {
                "id": "boost-blue",
                "name": "Boost blue",
                "enabled": True,
                "selection_source": "original",
                "target": "nebula",
                "regions": ["lower-right"],
                "match": {
                    "colour_point": "nebula-blue",
                    "colour_range": 0.18,
                    "brightness": {"min": 0.0, "max": 1.0},
                    "softness": 0.5,
                },
                "transform": {
                    "type": "colour_amount",
                    "channel": "blue",
                    "amount": 1.35,
                    "preserve_luminance": True,
                },
            }
        ],
    }


def _create_project(
    tmp_path: Path,
    *,
    profile_payloads: dict[str, dict[str, Any]],
    crop: dict[str, float] | None = None,
) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    _write_common_files(project_dir)
    _write_source_image(project_dir / "sources/source.png")
    render_profiles = []
    for profile_id, payload in profile_payloads.items():
        _profile_file(project_dir, profile_id, payload)
        render_profiles.append({"id": profile_id, "path": f"render_profiles/{profile_id}.yaml"})
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(
            _base_project_payload(render_profiles, crop=crop),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return project_dir


def test_screen_render_with_width_only_preserves_aspect() -> None:
    profile = ScreenRenderProfile.model_validate(
        {
            "type": "screen",
            "format": "png",
            "color_space": "srgb",
            "bit_depth": 8,
            "width_px": 400,
        }
    )
    plan = plan_render(
        profile,
        source_width=120,
        source_height=80,
        crop=CropDeclaration(),
    )

    assert plan.output_size.width == 400
    assert plan.output_size.height == 267


def test_exact_screen_dimensions_are_preserved() -> None:
    profile = ScreenRenderProfile.model_validate(
        {
            "type": "screen",
            "format": "png",
            "color_space": "srgb",
            "bit_depth": 8,
            "width_px": 640,
            "height_px": 360,
        }
    )
    plan = plan_render(
        profile,
        source_width=120,
        source_height=80,
        crop=CropDeclaration(),
    )

    assert plan.output_size.model_dump() == {"width": 640, "height": 360}


def test_print_dimension_calculations_for_cm_and_inches() -> None:
    profile_cm = PrintRenderProfile.model_validate(
        {
            "type": "print",
            "format": "tiff",
            "color_space": "srgb",
            "bit_depth": 16,
            "width": 42.0,
            "height": 29.7,
            "units": "cm",
            "ppi": 300,
            "crop_mode": "exact",
        }
    )
    profile_inches = PrintRenderProfile.model_validate(
        {
            "type": "print",
            "format": "tiff",
            "color_space": "srgb",
            "bit_depth": 16,
            "width": 8.0,
            "height": 10.0,
            "units": "inches",
            "ppi": 300,
            "crop_mode": "exact",
        }
    )

    plan_cm = plan_render(profile_cm, source_width=120, source_height=80, crop=CropDeclaration())
    plan_inches = plan_render(
        profile_inches,
        source_width=120,
        source_height=80,
        crop=CropDeclaration(),
    )

    assert plan_cm.output_size.model_dump() == {"width": 4961, "height": 3508}
    assert plan_inches.output_size.model_dump() == {"width": 2400, "height": 3000}


def test_levels_transform_affects_dark_pixels_more_than_bright_pixels() -> None:
    image = np.asarray(
        [
            [[0.10, 0.10, 0.10], [0.90, 0.90, 0.90]],
        ],
        dtype=np.float32,
    )
    weights = np.ones((1, 2), dtype=np.float32)

    transformed = apply_levels_transform(
        image,
        weights,
        darkest=2.0,
        dark=1.0,
        mid=1.0,
        light=1.0,
        brightest=1.0,
    )

    dark_delta = float(transformed[0, 0, 0] - image[0, 0, 0])
    bright_delta = float(transformed[0, 1, 0] - image[0, 1, 0])
    assert dark_delta > bright_delta


def test_normalized_crop_calculation_and_application() -> None:
    image = CanonicalImage(data=np.zeros((80, 120, 3), dtype=np.float32), width=120, height=80)
    cropped = apply_crop(
        image,
        CropDeclaration.model_validate({"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}),
    )

    assert cropped.width == 60
    assert cropped.height == 40


def test_cli_render_matches_direct_renderer_for_faux_hubble(tmp_path: Path) -> None:
    profile_payload = {
        "id": "screen",
        "name": "Screen",
        "profile": {
            "type": "screen",
            "format": "png",
            "color_space": "srgb",
            "bit_depth": 8,
            "width_px": 480,
            "interpolation": "nearest",
        },
    }
    project_dir = _create_project(tmp_path, profile_payloads={"screen": profile_payload})
    project_file = project_dir / "project.yaml"
    payload = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules[:] = [
        {
            "id": "faux-hubble",
            "name": "Faux Hubble",
            "enabled": True,
            "selection_source": "current",
            "target": "nebula",
            "match": {"softness": 0.5},
            "transform": {
                "type": "faux_palette",
                "palette": "hubble",
                "amount": 0.6,
                "preserve_brightness": True,
            },
        }
    ]
    project_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    direct_path = tmp_path / "direct.png"
    cli_path = tmp_path / "cli.png"
    render_output(
        project_dir,
        profile_id="screen",
        output_path=direct_path,
        force=True,
    )

    result = RUNNER.invoke(
        app,
        [
            "render",
            str(project_dir),
            "--profile",
            "screen",
            "--output",
            str(cli_path),
            "--force",
        ],
    )

    assert result.exit_code == 0
    direct_image = load_canonical_image(direct_path).data
    cli_image = load_canonical_image(cli_path).data
    assert np.allclose(direct_image, cli_image)


def test_nearest_upscale_preserves_existing_pixels_without_inventing_detail() -> None:
    source = CanonicalImage(
        data=np.array(
            [
                [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            ],
            dtype=np.float32,
        ),
        width=2,
        height=2,
    )

    resized = resize_exact(source, 4, 4, method="nearest")

    expected = np.array(
        [
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
            [[0.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
        ],
        dtype=np.float32,
    )
    np.testing.assert_allclose(resized.data, expected, atol=1e-6)


def test_fit_fill_and_exact_modes_resolve_differently() -> None:
    fit = PrintRenderProfile.model_validate(
        {
            "type": "print",
            "format": "tiff",
            "color_space": "srgb",
            "bit_depth": 16,
            "width": 8.0,
            "height": 8.0,
            "units": "inches",
            "ppi": 300,
            "crop_mode": "fit",
        }
    )
    fill = fit.model_copy(update={"crop_mode": "fill"})
    exact = fit.model_copy(update={"crop_mode": "exact"})

    fit_plan = plan_render(fit, source_width=120, source_height=80, crop=CropDeclaration())
    fill_plan = plan_render(fill, source_width=120, source_height=80, crop=CropDeclaration())
    exact_plan = plan_render(exact, source_width=120, source_height=80, crop=CropDeclaration())

    assert fit_plan.output_size.model_dump() == {"width": 2400, "height": 1600}
    assert fill_plan.output_size.model_dump() == {"width": 2400, "height": 2400}
    assert exact_plan.output_size.model_dump() == {"width": 2400, "height": 2400}


def test_png_render_manifest_and_deterministic_hash(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        profile_payloads={
            "screen-preview": {
                "id": "screen-preview",
                "name": "Screen Preview",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 320,
                    "interpolation": "lanczos",
                },
            }
        },
    )
    output_a = tmp_path / "a.png"
    output_b = tmp_path / "b.png"
    result_a = render_output(
        project_dir,
        profile_id="screen-preview",
        output_path=output_a,
        force=True,
    )
    result_b = render_output(
        project_dir,
        profile_id="screen-preview",
        output_path=output_b,
        force=True,
    )

    assert result_a.output_dimensions.model_dump() == {"width": 320, "height": 213}
    assert result_a.output_sha256 == result_b.output_sha256
    manifest = json.loads(Path(result_a.manifest_path).read_text(encoding="utf-8"))
    assert manifest["render_profile_id"] == "screen-preview"
    assert manifest["output_sha256"] == result_a.output_sha256
    assert manifest["output_dimensions"] == {"width": 320, "height": 213}


def test_tiff_render_and_overwrite_behaviour(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        profile_payloads={
            "archive": {
                "id": "archive",
                "name": "Archive",
                "profile": {
                    "type": "archive",
                    "format": "tiff",
                    "color_space": "srgb",
                    "bit_depth": 16,
                    "interpolation": "lanczos",
                },
            }
        },
    )
    output_path = tmp_path / "archive.tiff"
    result = render_output(project_dir, profile_id="archive", output_path=output_path, force=True)

    assert output_path.is_file()
    assert result.output_format == "tiff"
    second_call_error = RUNNER.invoke(
        app,
        [
            "render",
            str(project_dir),
            "--profile",
            "archive",
            "--output",
            str(output_path),
        ],
    )
    assert second_call_error.exit_code == EXIT_INPUT_ERROR


def test_dry_run_creates_no_files(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        profile_payloads={
            "screen-preview": {
                "id": "screen-preview",
                "name": "Screen Preview",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 320,
                    "interpolation": "lanczos",
                },
            }
        },
    )
    output_path = tmp_path / "dry-run.png"
    result = render_output(
        project_dir,
        profile_id="screen-preview",
        output_path=output_path,
        dry_run=True,
    )

    assert result.dry_run is True
    assert not output_path.exists()
    assert not Path(result.manifest_path).exists()


def test_crop_changes_output(tmp_path: Path) -> None:
    full_project = _create_project(
        tmp_path / "full",
        profile_payloads={
            "screen-preview": {
                "id": "screen-preview",
                "name": "Screen Preview",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 320,
                    "interpolation": "lanczos",
                },
            }
        },
    )
    cropped_project = _create_project(
        tmp_path / "cropped",
        profile_payloads={
            "screen-preview": {
                "id": "screen-preview",
                "name": "Screen Preview",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 320,
                    "interpolation": "lanczos",
                },
            }
        },
        crop={"x": 0.25, "y": 0.0, "width": 0.5, "height": 1.0},
    )
    full_result = render_output(
        full_project,
        profile_id="screen-preview",
        output_path=tmp_path / "full.png",
        force=True,
    )
    cropped_result = render_output(
        cropped_project,
        profile_id="screen-preview",
        output_path=tmp_path / "cropped.png",
        force=True,
    )

    assert full_result.output_sha256 != cropped_result.output_sha256


def test_preview_and_render_share_rule_execution_behaviour(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        profile_payloads={
            "screen-preview": {
                "id": "screen-preview",
                "name": "Screen Preview",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 320,
                    "interpolation": "lanczos",
                },
            }
        },
    )
    render_result = render_output(
        project_dir,
        profile_id="screen-preview",
        output_path=tmp_path / "render.png",
        force=True,
    )
    preview_result = RUNNER.invoke(
        app,
        [
            "preview",
            str(project_dir),
            "--output",
            str(tmp_path / "preview.png"),
            "--json",
        ],
    )

    assert preview_result.exit_code == EXIT_VALIDATION_SUCCESS
    preview_payload = json.loads(preview_result.stdout)
    assert render_result.applied_rule_ids == preview_payload["applied_rule_ids"]
    assert [trace.rule_id for trace in render_result.execution_trace] == [
        trace["rule_id"] for trace in preview_payload["execution_trace"]
    ]


def test_render_cli_integration_and_force(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        profile_payloads={
            "screen-preview": {
                "id": "screen-preview",
                "name": "Screen Preview",
                "profile": {
                    "type": "screen",
                    "format": "jpeg",
                    "color_space": "srgb",
                    "bit_depth": 8,
                    "width_px": 400,
                    "interpolation": "bicubic",
                    "jpeg_quality": 82,
                },
            }
        },
    )
    output_path = tmp_path / "screen.jpg"
    result = RUNNER.invoke(
        app,
        [
            "render",
            str(project_dir),
            "--profile",
            "screen-preview",
            "--output",
            str(output_path),
            "--force",
            "--json",
        ],
    )

    assert result.exit_code == EXIT_VALIDATION_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["output_dimensions"] == {"width": 400, "height": 267}
    assert payload["profile_type"] == "screen"
    assert output_path.is_file()


def test_invalid_crop_and_unsupported_colour_space_fail_validation(tmp_path: Path) -> None:
    project_dir = _create_project(
        tmp_path,
        profile_payloads={
            "bad-profile": {
                "id": "bad-profile",
                "name": "Bad Profile",
                "profile": {
                    "type": "screen",
                    "format": "png",
                    "color_space": "adobe-rgb",
                    "bit_depth": 8,
                    "width_px": 320,
                },
            }
        },
        crop={"x": 0.8, "y": 0.0, "width": 0.4, "height": 1.0},
    )
    result = RUNNER.invoke(
        app,
        [
            "render",
            str(project_dir),
            "--profile",
            "bad-profile",
            "--output",
            str(tmp_path / "bad.png"),
            "--json",
        ],
    )

    assert result.exit_code != 0

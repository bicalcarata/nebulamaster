from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from engine import EXIT_VALIDATION_SUCCESS, clear_prepared_sources_cache, inspect_sources
from engine.diff import diff_projects
from engine.render import render_output
from engine.validation import load_valid_project_bundle
from image_io import CanonicalImage, save_png, translate_image
from project_model import ProjectBundle
from renderer_cli.main import app
from typer.testing import CliRunner
from versioning import init_repository, project_boundary_from_path

RUNNER = CliRunner()


def _star_field(size: tuple[int, int] = (96, 64)) -> CanonicalImage:
    width, height = size
    data = np.zeros((height, width, 3), dtype=np.float32)
    stars = [
        (10, 8, 0.9),
        (30, 15, 1.0),
        (48, 20, 0.8),
        (70, 30, 0.95),
        (55, 45, 0.7),
        (82, 18, 0.85),
    ]
    for x, y, value in stars:
        data[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2, :] = value
    data[:, :, 2] += 0.05
    return CanonicalImage(data=np.clip(data, 0.0, 1.0), width=width, height=height)


def _write_common(project_dir: Path) -> None:
    for directory in ["sources", "palettes", "regions", "render_profiles", "plugins"]:
        (project_dir / directory).mkdir(parents=True, exist_ok=True)
    (project_dir / "palettes/default.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "default",
                "colour_points": [
                    {
                        "id": "nebula-blue",
                        "name": "Nebula Blue",
                        "value": {"model": "working-rgb", "channels": [0.1, 0.2, 0.9]},
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "regions/region-a.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "region-a",
                "name": "Region A",
                "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
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
                    "width_px": 320,
                    "interpolation": "lanczos",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "plugins/lock.yaml").write_text(
        yaml.safe_dump({"plugins": []}, sort_keys=False),
        encoding="utf-8",
    )


def _write_sources(project_dir: Path, *, shift_x: float = 0.0, shift_y: float = 0.0) -> None:
    base = _star_field()
    blue = translate_image(base, x_px=shift_x, y_px=shift_y)
    blue_data = np.clip(blue.data * np.array([0.55, 0.85, 1.0], dtype=np.float32), 0.0, 1.0)
    neutral_data = np.clip(base.data * np.array([0.9, 0.9, 0.75], dtype=np.float32), 0.0, 1.0)
    save_png(project_dir / "sources/base.png", base.data)
    save_png(project_dir / "sources/blue.png", blue_data)
    save_png(project_dir / "sources/neutral.png", neutral_data)


def test_inspect_sources_reuses_cached_preparation(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    clear_prepared_sources_cache()
    project_dir = tmp_path / "sources-cache"
    project_dir.mkdir()
    _write_common(project_dir)
    _write_sources(project_dir, shift_x=2.0, shift_y=-1.0)
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(_project_payload(), sort_keys=False),
        encoding="utf-8",
    )
    bundle, report = load_valid_project_bundle(project_dir)
    assert bundle is not None
    assert report.valid is True

    from image_io import load_canonical_image as original_loader

    calls: list[str] = []

    def tracking_loader(path: Path) -> CanonicalImage:
        calls.append(str(path))
        return original_loader(path)

    monkeypatch.setattr("engine.sources.load_canonical_image", tracking_loader)

    first = inspect_sources(bundle)
    second = inspect_sources(bundle)

    assert first.reference_source_id == second.reference_source_id
    assert len(calls) == 3


def _project_payload(
    *,
    shift_mode: str = "translation",
    shift_x: float = 0.0,
    shift_y: float = 0.0,
    source_mix: dict[str, Any] | None = None,
    disabled_blue: bool = False,
) -> dict[str, Any]:
    alignment: dict[str, Any]
    if shift_mode == "manual":
        alignment = {"mode": "manual", "x_px": shift_x, "y_px": shift_y}
    elif shift_mode == "inspect":
        alignment = {"mode": "inspect", "max_shift_px": 16}
    elif shift_mode == "none":
        alignment = {"mode": "none"}
    else:
        alignment = {"mode": "translation", "max_shift_px": 16}
    return {
        "schema_version": 1,
        "project": {"id": "sources-demo", "name": "Sources Demo"},
        "sources": [
            {
                "id": "base",
                "name": "Base",
                "path": "sources/base.png",
                "role": "base",
                "reference": True,
                "enabled": True,
                "weight": 1.0,
                "checksum": "sha256:base",
                "alignment": {"mode": "none"},
            },
            {
                "id": "blue",
                "name": "Blue",
                "path": "sources/blue.png",
                "role": "blue",
                "enabled": not disabled_blue,
                "weight": 0.75,
                "checksum": "sha256:blue",
                "alignment": alignment,
            },
            {
                "id": "neutral",
                "name": "Neutral",
                "path": "sources/neutral.png",
                "role": "neutral",
                "enabled": True,
                "weight": 0.4,
                "checksum": "sha256:neutral",
                "alignment": {"mode": "manual", "x_px": 0.0, "y_px": 0.0},
            },
        ],
        "semantic_channels": [{"id": "nebula", "name": "Nebula"}],
        "palettes": [{"id": "default", "path": "palettes/default.yaml"}],
        "regions": [{"id": "region-a", "path": "regions/region-a.yaml"}],
        "render_profiles": [{"id": "screen", "path": "render_profiles/screen.yaml"}],
        "plugins": {"path": "plugins/lock.yaml"},
        "source_mix": source_mix or {"mode": "weighted_average"},
        "rules": [],
    }


def _create_project(
    tmp_path: Path,
    *,
    image_shift_x: float = 0.0,
    image_shift_y: float = 0.0,
    shift_mode: str = "translation",
    mix: dict[str, Any] | None = None,
    disabled_blue: bool = False,
) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    _write_common(project_dir)
    _write_sources(project_dir, shift_x=image_shift_x, shift_y=image_shift_y)
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(
            _project_payload(
                shift_mode=shift_mode,
                shift_x=-image_shift_x,
                shift_y=-image_shift_y,
                source_mix=mix,
                disabled_blue=disabled_blue,
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return project_dir


def _bundle(project_dir: Path) -> ProjectBundle:
    bundle, report = load_valid_project_bundle(project_dir)
    assert report.valid and bundle is not None
    return bundle


def test_single_source_compatibility(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path)
    payload = yaml.safe_load((project_dir / "project.yaml").read_text(encoding="utf-8"))
    payload["sources"] = [payload["sources"][0]]
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    bundle = _bundle(project_dir)

    prepared = inspect_sources(bundle)

    assert prepared.reference_source_id == "base"
    assert prepared.enabled_source_ids == ["base"]


def test_known_translation_detection_and_render_match(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, image_shift_x=3.0, image_shift_y=-2.0)
    bundle = _bundle(project_dir)

    prepared = inspect_sources(bundle)
    blue_report = next(
        report for report in prepared.alignment_reports if report.source_id == "blue"
    )

    assert abs(blue_report.estimated_x_px + 3.0) < 0.6
    assert abs(blue_report.estimated_y_px - 2.0) < 0.6
    assert blue_report.applied_x_px == blue_report.estimated_x_px


def test_subpixel_translation_detection_within_tolerance(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, image_shift_x=1.5, image_shift_y=-0.75)
    bundle = _bundle(project_dir)

    prepared = inspect_sources(bundle)
    blue_report = next(
        report for report in prepared.alignment_reports if report.source_id == "blue"
    )

    assert abs(blue_report.estimated_x_px + 1.5) < 0.6
    assert abs(blue_report.estimated_y_px - 0.75) < 0.6


def test_excessive_shift_rejection_and_manual_offset(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, image_shift_x=24.0, image_shift_y=0.0)
    bundle = _bundle(project_dir)
    prepared = inspect_sources(bundle)
    blue_report = next(
        report for report in prepared.alignment_reports if report.source_id == "blue"
    )
    assert blue_report.compatible is False

    manual_project = _create_project(
        tmp_path / "manual",
        image_shift_x=4.0,
        image_shift_y=0.0,
        shift_mode="manual",
    )
    manual_bundle = _bundle(manual_project)
    manual_prepared = inspect_sources(manual_bundle)
    manual_report = next(
        report for report in manual_prepared.alignment_reports if report.source_id == "blue"
    )
    assert abs(manual_report.applied_x_px + 4.0) < 1e-6


def test_inspect_and_none_modes(tmp_path: Path) -> None:
    inspect_project = _create_project(tmp_path / "inspect", image_shift_x=2.0, shift_mode="inspect")
    inspect_bundle = _bundle(inspect_project)
    inspect_report = next(
        report
        for report in inspect_sources(inspect_bundle).alignment_reports
        if report.source_id == "blue"
    )
    assert inspect_report.applied_x_px == 0.0

    none_project = _create_project(tmp_path / "none", image_shift_x=2.0, shift_mode="none")
    none_bundle = _bundle(none_project)
    none_report = next(
        report
        for report in inspect_sources(none_bundle).alignment_reports
        if report.source_id == "blue"
    )
    assert none_report.applied_x_px == 0.0


def test_weighted_average_lighten_screen_and_channel_contribution(tmp_path: Path) -> None:
    weighted = _create_project(tmp_path / "weighted")
    lighten = _create_project(tmp_path / "lighten", mix={"mode": "lighten"})
    screen = _create_project(tmp_path / "screen", mix={"mode": "screen"})
    channel = _create_project(
        tmp_path / "channel",
        mix={
            "mode": "channel_contribution",
            "contributions": [
                {"source": "base", "red": 1.0, "green": 0.5, "blue": 0.3},
                {"source": "blue", "red": 0.0, "green": 0.6, "blue": 1.0},
                {"source": "neutral", "red": 0.2, "green": 0.2, "blue": 0.2},
            ],
        },
    )
    outputs = []
    for project_dir in [weighted, lighten, screen, channel]:
        outputs.append(
            render_output(
                project_dir,
                profile_id="screen",
                output_path=project_dir.parent / f"{project_dir.name}.png",
                force=True,
            ).output_sha256
        )
    assert len(set(outputs)) == 4


def test_disabled_source_ignored_and_boundary_includes_tracked_assets(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, disabled_blue=True)
    bundle = _bundle(project_dir)
    prepared = inspect_sources(bundle)
    assert "blue" not in prepared.enabled_source_ids

    repo_dir = tmp_path / "repo"
    shutil.copytree(project_dir, repo_dir / "project")
    init_repository(repo_dir / "project")
    boundary = project_boundary_from_path(repo_dir / "project")
    assert any(item.endswith("sources/base.png") for item in boundary.files)
    assert any(item.endswith("sources/blue.png") for item in boundary.files)


def test_manifest_alignment_provenance_and_preview_render_shared_sources(tmp_path: Path) -> None:
    project_dir = _create_project(tmp_path, image_shift_x=2.0)
    render_result = render_output(
        project_dir,
        profile_id="screen",
        output_path=tmp_path / "render.png",
        force=True,
    )
    manifest = json.loads(Path(render_result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["reference_source_id"] == "base"
    assert manifest["source_mix_mode"] == "weighted_average"
    assert len(manifest["source_alignment"]) == 3

    preview_result = RUNNER.invoke(
        app,
        ["preview", str(project_dir), "--output", str(tmp_path / "preview.png"), "--json"],
    )
    assert preview_result.exit_code == EXIT_VALIDATION_SUCCESS
    preview_manifest = json.loads(
        Path(json.loads(preview_result.stdout)["manifest_path"]).read_text(encoding="utf-8")
    )
    assert preview_manifest["reference_source_id"] == manifest["reference_source_id"]


def test_source_diff_and_cli_commands(tmp_path: Path) -> None:
    project_a = _create_project(tmp_path / "a")
    project_b = _create_project(tmp_path / "b", mix={"mode": "lighten"})
    payload = yaml.safe_load((project_b / "project.yaml").read_text(encoding="utf-8"))
    payload["sources"][1]["weight"] = 1.25
    (project_b / "project.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )

    result = diff_projects(project_a, project_b)
    codes = [change.code for change in result.modified_items]
    assert "source.weight_changed" in codes
    assert "source_mix.mode_changed" in codes

    inspect_result = RUNNER.invoke(app, ["inspect-sources", str(project_a), "--json"])
    assert inspect_result.exit_code == EXIT_VALIDATION_SUCCESS
    aligned_result = RUNNER.invoke(
        app,
        ["align-sources", str(project_a), "--output", str(tmp_path / "aligned"), "--json"],
    )
    assert aligned_result.exit_code == EXIT_VALIDATION_SUCCESS
    manifest_path = Path(json.loads(aligned_result.stdout)["manifest_path"])
    assert manifest_path.is_file()

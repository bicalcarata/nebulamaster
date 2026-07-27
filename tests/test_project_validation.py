from __future__ import annotations

from pathlib import Path

from engine import validate_project
from project_io import load_project_file, locate_project_file
from project_model import ProjectFile

ROOT = Path(__file__).resolve().parents[1]


def test_load_valid_project_file() -> None:
    project_file = locate_project_file(ROOT / "examples/valid/minimal-project")
    project = load_project_file(project_file)

    assert project.project.id == "horsehead-demo"
    assert project.schema_version == 1
    assert project.sources[0].path.as_posix() == "sources/source-01.tif"
    assert project.dark_dust.enabled is True


def test_project_model_accepts_dark_dust_target_and_settings() -> None:
    project = ProjectFile.model_validate(
        {
            "schema_version": 1,
            "project": {"id": "dark-dust-demo", "name": "Dark Dust Demo"},
            "sources": [{"id": "source-01", "path": "sources/source.png", "enabled": True}],
            "semantic_channels": [{"id": "nebula", "name": "Nebula"}],
            "palettes": [],
            "regions": [],
            "render_profiles": [],
            "plugins": {"path": "plugins/lock.yaml"},
            "dark_dust": {
                "enabled": True,
                "sensitivity": 0.66,
                "structure_size": 0.14,
                "background_protection": 0.21,
                "softness": 0.33,
            },
            "rules": [
                {
                    "id": "lift-dark-dust",
                    "name": "Lift Dark Dust",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "dark_dust",
                    "match": {"softness": 0.5},
                    "transform": {"type": "brightness", "amount": 1.1},
                }
            ],
        }
    )

    assert project.rules[0].target == "dark_dust"
    assert project.dark_dust.sensitivity == 0.66


def test_validate_valid_example_project() -> None:
    report = validate_project(ROOT / "examples/valid/minimal-project")

    assert report.valid is True
    assert report.issues == []


def test_validate_missing_source_project() -> None:
    report = validate_project(ROOT / "tests/fixtures/invalid/missing-source")

    assert report.valid is False
    assert any(issue.code == "missing-source-image" for issue in report.issues)


def test_validate_bad_region_project() -> None:
    report = validate_project(ROOT / "tests/fixtures/invalid/bad-region")

    assert report.valid is False
    assert any(issue.code == "region-schema" for issue in report.issues)


def test_validate_bad_colour_point_project() -> None:
    report = validate_project(ROOT / "tests/fixtures/invalid/bad-colour-point")

    assert report.valid is False
    assert any(issue.code in {"project-schema", "palette-schema"} for issue in report.issues)


def test_validate_bad_plugin_lock_project() -> None:
    report = validate_project(ROOT / "tests/fixtures/invalid/bad-plugin-lock")

    assert report.valid is False
    assert any(issue.code == "plugin-lock-schema" for issue in report.issues)


def test_unknown_fields_fail_validation() -> None:
    report = validate_project(ROOT / "tests/fixtures/invalid/unknown-field")

    assert report.valid is False
    assert any(issue.code == "project-schema" for issue in report.issues)

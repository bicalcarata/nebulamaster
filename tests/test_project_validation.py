from __future__ import annotations

from pathlib import Path

from engine import validate_project
from project_io import load_project_file, locate_project_file

ROOT = Path(__file__).resolve().parents[1]


def test_load_valid_project_file() -> None:
    project_file = locate_project_file(ROOT / "examples/valid/minimal-project")
    project = load_project_file(project_file)

    assert project.project.id == "horsehead-demo"
    assert project.schema_version == 1
    assert project.sources[0].path.as_posix() == "sources/source-01.tif"


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


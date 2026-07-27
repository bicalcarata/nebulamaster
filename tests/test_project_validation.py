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


def test_legacy_project_missing_builtin_semantic_channels_is_normalized() -> None:
    project = ProjectFile.model_validate(
        {
            "schema_version": 1,
            "project": {"id": "legacy-demo", "name": "Legacy Demo"},
            "sources": [{"id": "source-01", "path": "sources/source.png", "enabled": True}],
            "semantic_channels": [
                {"id": "nebula", "name": "Nebula"},
                {"id": "background", "name": "Background"},
            ],
            "palettes": [],
            "regions": [],
            "render_profiles": [],
            "plugins": {"path": "plugins/lock.yaml"},
            "rules": [
                {
                    "id": "combined-brightness",
                    "name": "Combined Brightness",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "combined",
                    "match": {"softness": 0.5},
                    "transform": {"type": "brightness", "amount": 1.1},
                }
            ],
        }
    )

    assert [channel.id for channel in project.semantic_channels[:5]] == [
        "combined",
        "nebula",
        "stars",
        "dark_dust",
        "background",
    ]
    assert project.rules[0].target == "combined"


def test_project_model_accepts_dark_dust_target_and_settings() -> None:
    project = ProjectFile.model_validate(
        {
            "schema_version": 1,
            "project": {"id": "dark-dust-demo", "name": "Dark Dust Demo"},
            "sources": [{"id": "source-01", "path": "sources/source.png", "enabled": True}],
            "semantic_channels": [
                {"id": "combined", "name": "Combined Image"},
                {"id": "nebula", "name": "Nebula"},
                {"id": "stars", "name": "Stars"},
                {"id": "dark_dust", "name": "Dark Dust"},
                {"id": "background", "name": "Background"},
            ],
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


def test_project_model_accepts_faux_palette_transform() -> None:
    for palette in ["hubble", "hoo", "foraxx", "gold_cyan", "natural_bicolour"]:
        project = ProjectFile.model_validate(
            {
                "schema_version": 1,
                "project": {"id": "faux-demo", "name": "Faux Demo"},
                "sources": [{"id": "source-01", "path": "sources/source.png", "enabled": True}],
                "semantic_channels": [
                    {"id": "combined", "name": "Combined Image"},
                    {"id": "nebula", "name": "Nebula"},
                    {"id": "stars", "name": "Stars"},
                    {"id": "dark_dust", "name": "Dark Dust"},
                    {"id": "background", "name": "Background"},
                ],
                "palettes": [],
                "regions": [],
                "render_profiles": [],
                "plugins": {"path": "plugins/lock.yaml"},
                "rules": [
                    {
                        "id": f"faux-{palette}",
                        "name": f"Faux {palette}",
                        "enabled": True,
                        "selection_source": "current",
                        "target": "nebula",
                        "match": {"softness": 0.5},
                        "transform": {
                            "type": "faux_palette",
                            "palette": palette,
                            "amount": 0.6,
                            "preserve_brightness": True,
                        },
                    }
                ],
            }
        )

        transform = project.rules[0].transform
        assert transform.type == "faux_palette"


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


def test_validate_accepts_legacy_builtin_target_and_normalizes_semantic_channels(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "legacy-stars-target"
    project_dir.mkdir()
    (project_dir / "sources").mkdir()
    (project_dir / "plugins").mkdir()
    (project_dir / "sources/source.png").write_bytes(b"not-an-image-but-exists")
    (project_dir / "plugins/lock.yaml").write_text("plugins: []\n", encoding="utf-8")
    (project_dir / "project.yaml").write_text(
        """
schema_version: 1
project:
  id: legacy-stars-target
  name: Legacy Stars Target
sources:
  - id: source-01
    path: sources/source.png
    enabled: true
semantic_channels:
  - id: nebula
    name: Nebula
  - id: background
    name: Background
palettes: []
regions: []
render_profiles: []
plugins:
  path: plugins/lock.yaml
rules:
  - id: stars-only
    name: Stars Only
    enabled: true
    selection_source: current
    target: stars
    match:
      softness: 0.5
    transform:
      type: brightness
      amount: 1.1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validate_project(project_dir)

    assert report.valid is True
    assert report.issues == []

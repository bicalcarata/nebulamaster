from __future__ import annotations

from pathlib import Path

import pytest
from engine import validate_project
from project_io import load_project_file, locate_project_file
from project_model import CropDeclaration, FauxPaletteTransform, ProjectFile, ScreenRenderProfile

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
                "veil_strength": 0.61,
                "core_strength": 0.73,
                "veil_core_balance": 0.49,
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
    assert project.dark_dust.veil_strength == 0.61
    assert project.dark_dust.core_strength == 0.73
    assert project.dark_dust.veil_core_balance == 0.49


def test_project_model_accepts_dark_nebula_processing_transform() -> None:
    project = ProjectFile.model_validate(
        {
            "schema_version": 1,
            "project": {"id": "dark-nebula-demo", "name": "Dark Nebula Demo"},
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
                    "id": "dark-nebula",
                    "name": "Dark Nebula Processing",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "dark_dust",
                    "match": {"softness": 0.5},
                    "transform": {
                        "type": "dark_nebula_processing",
                        "amount": 0.5,
                        "reveal_dust": 0.4,
                        "dust_contrast": 0.3,
                        "core_depth": 0.55,
                        "dust_colour": 0.15,
                        "softness": 0.2,
                        "preserve_bright_areas": True,
                    },
                }
            ],
        }
    )

    transform = project.rules[0].transform
    assert transform.type == "dark_nebula_processing"
    assert transform.amount == 0.5
    assert transform.core_depth == 0.55


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
        assert transform.cool_mode == "enhance"
        assert transform.supported_colour_balance()
        assert all(value == 100.0 for value in transform.supported_colour_balance().values())


def test_faux_palette_transform_rejects_unknown_cool_mode() -> None:
    with pytest.raises(Exception) as error_info:  # noqa: BLE001
        FauxPaletteTransform.model_validate(
            {
                "type": "faux_palette",
                "palette": "hubble",
                "cool_mode": "replace",
            }
        )

    assert "Input should be 'enhance' or 'add'" in str(error_info.value)


def test_render_profile_without_crop_remains_valid() -> None:
    profile = ScreenRenderProfile.model_validate(
        {
            "type": "screen",
            "format": "png",
            "color_space": "srgb",
            "bit_depth": 8,
            "width_px": 2400,
        }
    )

    assert profile.crop is None


def test_crop_declaration_migrates_legacy_non_full_frame_to_enabled() -> None:
    crop = CropDeclaration.model_validate(
        {
            "x": 0.10,
            "y": 0.20,
            "width": 0.70,
            "height": 0.60,
        }
    )

    assert crop.enabled is True


def test_render_profile_crop_rejects_out_of_bounds_values() -> None:
    with pytest.raises(ValueError, match="crop width must remain inside source bounds"):
        ScreenRenderProfile.model_validate(
            {
                "type": "screen",
                "format": "png",
                "color_space": "srgb",
                "bit_depth": 8,
                "width_px": 2400,
                "crop": {
                    "enabled": True,
                    "x": 0.75,
                    "y": 0.10,
                    "width": 0.30,
                    "height": 0.60,
                },
            }
        )


def test_project_model_accepts_new_tone_and_colour_transforms() -> None:
    project = ProjectFile.model_validate(
        {
            "schema_version": 1,
            "project": {"id": "new-adjustments-demo", "name": "New Adjustments Demo"},
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
                    "id": "tone",
                    "name": "Tone Shaping",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "nebula",
                    "match": {"softness": 0.5},
                    "transform": {
                        "type": "tone_shaping",
                        "shadows": 0.2,
                        "midtones": 0.3,
                        "highlights": -0.1,
                        "contrast": 0.25,
                        "black_protection": 0.8,
                        "highlight_protection": 0.65,
                    },
                },
                {
                    "id": "contrast",
                    "name": "Local Contrast",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "nebula",
                    "match": {"softness": 0.5},
                    "transform": {
                        "type": "local_contrast",
                        "amount": 0.35,
                        "structure_size": "broad",
                        "background_protection": 0.75,
                        "highlight_protection": 0.7,
                        "softness": 0.45,
                    },
                },
                {
                    "id": "vibrance",
                    "name": "Vibrance",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "nebula",
                    "match": {"softness": 0.5},
                    "transform": {
                        "type": "vibrance",
                        "amount": 0.4,
                        "protect_strong_colours": 0.85,
                        "protect_bright_areas": 0.55,
                    },
                },
                {
                    "id": "temperature",
                    "name": "Colour Temperature",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "combined",
                    "match": {"softness": 0.5},
                    "transform": {
                        "type": "colour_temperature",
                        "warmth": 0.18,
                        "tint": 0.12,
                        "preserve_brightness": True,
                        "protect_neutral_background": 0.55,
                    },
                },
            ],
        }
    )

    assert project.rules[0].transform.type == "tone_shaping"
    assert project.rules[1].transform.type == "local_contrast"
    assert project.rules[2].transform.type == "vibrance"
    assert project.rules[3].transform.type == "colour_temperature"


def test_project_model_accepts_enhanced_colour_amount_controls() -> None:
    project = ProjectFile.model_validate(
        {
            "schema_version": 1,
            "project": {"id": "enhanced-red-demo", "name": "Enhanced Red Demo"},
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
                    "id": "reveal-faint-red",
                    "name": "Reveal Faint Red",
                    "enabled": True,
                    "selection_source": "current",
                    "target": "nebula",
                    "match": {
                        "colour_point": "nebula-red",
                        "colour_range": 0.28,
                        "softness": 0.45,
                    },
                    "transform": {
                        "type": "colour_amount",
                        "channel": "red",
                        "amount": 1.55,
                        "preserve_luminance": True,
                        "response_version": "enhanced",
                        "faint_colour_sensitivity": 0.40,
                        "reveal_faint_colour": 0.35,
                        "faint_range": 0.60,
                        "structure_size": "broad",
                        "bright_colour_protection": 0.75,
                        "highlight_protection": 0.70,
                        "extended_range": True,
                    },
                }
            ],
        }
    )

    transform = project.rules[0].transform
    assert transform.type == "colour_amount"
    assert transform.response_version == "enhanced"
    assert transform.faint_colour_sensitivity == 0.40
    assert transform.reveal_faint_colour == 0.35
    assert transform.faint_range == 0.60
    assert transform.structure_size == "broad"
    assert transform.bright_colour_protection == 0.75
    assert transform.highlight_protection == 0.70
    assert transform.extended_range is True


def test_faux_palette_transform_accepts_supported_colour_balance_controls() -> None:
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
                        "cool_mode": "add",
                        "colour_balance": {"gold": 80.0, "green": 120.0, "cyan": 140.0},
                    },
                }
            ],
        }
    )

    transform = project.rules[0].transform
    assert transform.type == "faux_palette"
    assert transform.cool_mode == "add"
    assert transform.supported_colour_balance() == {
        "gold": 80.0,
        "green": 120.0,
        "cyan": 140.0,
    }


def test_faux_palette_transform_rejects_unsupported_colour_balance_keys() -> None:
    with pytest.raises(Exception) as error_info:  # noqa: BLE001
        ProjectFile.model_validate(
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
                        "id": "faux-foo",
                        "name": "Faux HOO",
                        "enabled": True,
                        "selection_source": "current",
                        "target": "nebula",
                        "match": {"softness": 0.5},
                        "transform": {
                            "type": "faux_palette",
                            "palette": "hoo",
                            "amount": 0.6,
                            "preserve_brightness": True,
                            "colour_balance": {"green": 120.0},
                        },
                    }
                ],
            }
        )

    assert "unsupported keys for palette 'hoo': green" in str(error_info.value)


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

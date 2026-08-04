from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from engine import EXIT_VALIDATION_ERROR
from engine.diff import diff_projects
from renderer_cli.main import app
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "diff"
RUNNER = CliRunner()


def _copy_example(name: str, destination: Path) -> Path:
    source = EXAMPLES / name
    target = destination / name
    shutil.copytree(source, target)
    return target


def _read_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def test_identical_projects_produce_no_differences() -> None:
    result = diff_projects(EXAMPLES / "lion-natural", EXAMPLES / "lion-natural")

    assert result.summary.added == 0
    assert result.summary.removed == 0
    assert result.summary.modified == 0
    assert result.summary.reordered_rules == 0
    assert result.explanations == []


def test_rule_additions_and_removals_are_detected(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    project_file = project_b / "project.yaml"
    payload = _read_yaml(project_file)
    rules = payload["rules"]
    assert isinstance(rules, list)
    payload["rules"] = rules[:-1]
    _write_yaml(project_file, payload)

    removed_diff = diff_projects(project_a, project_b)
    added_diff = diff_projects(project_b, project_a)

    assert [change.code for change in removed_diff.removed_items] == ["rule.removed"]
    assert [change.code for change in added_diff.added_items] == ["rule.added"]


def test_natural_to_strong_blue_reports_expected_visual_changes() -> None:
    result = diff_projects(EXAMPLES / "lion-natural", EXAMPLES / "lion-strong-blue")
    modified_codes = [change.code for change in result.modified_items]
    reordered_codes = [change.code for change in result.reordered_rules]
    summaries = [change.human_summary for change in result.modified_items]

    assert modified_codes == [
        "project.name_changed",
        "colour_point.moved",
        "region.geometry_changed",
        "region.feather_changed",
        "rule.transform_changed",
        "rule.disabled",
    ]
    assert reordered_codes == ["rule.reordered", "rule.reordered"]
    assert any("towards darker blue" in summary for summary in summaries)
    assert any("35%" in summary for summary in summaries)
    assert any("region was enlarged" in summary for summary in summaries)


def test_selection_source_source_replacement_render_profile_and_plugin_lock_changes() -> None:
    result = diff_projects(EXAMPLES / "lion-strong-blue", EXAMPLES / "lion-print")
    modified_codes = [change.code for change in result.modified_items]

    assert "source.changed" in modified_codes
    assert "rule.selection_source_changed" in modified_codes
    assert "rule.removed" not in modified_codes
    assert "render_profile.changed" in modified_codes
    assert "plugin_lock.changed" in modified_codes


def test_render_profile_crop_change_is_reported_semantically(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    screen_profile = project_b / "render_profiles" / "screen.yaml"
    payload = _read_yaml(screen_profile)
    profile = payload["profile"]
    assert isinstance(profile, dict)
    profile["crop"] = {
        "enabled": True,
        "x": 0.10,
        "y": 0.05,
        "width": 0.80,
        "height": 0.64,
        "aspect_ratio": "4:5",
        "lock_aspect_ratio": True,
    }
    _write_yaml(screen_profile, payload)

    result = diff_projects(project_a, project_b)

    assert [change.code for change in result.modified_items] == ["render_profile.crop_added"]
    assert result.modified_items[0].human_summary == "Added 4:5 crop to Screen Preview output."


def test_rule_target_change_is_reported_in_plain_language(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    project_file = project_b / "project.yaml"
    payload = _read_yaml(project_file)
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules[0]["target"] = "dark_dust"
    _write_yaml(project_file, payload)

    result = diff_projects(project_a, project_b)

    assert [change.code for change in result.modified_items] == ["rule.target_changed"]
    assert "Dark Dust" in result.modified_items[0].human_summary


def test_project_dark_dust_setting_change_is_reported(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    project_file = project_b / "project.yaml"
    payload = _read_yaml(project_file)
    payload["dark_dust"] = {
        "enabled": True,
        "sensitivity": 0.72,
        "structure_size": 0.15,
        "background_protection": 0.18,
        "softness": 0.30,
    }
    _write_yaml(project_file, payload)

    result = diff_projects(project_a, project_b)

    assert [change.code for change in result.modified_items] == ["project.dark_dust_changed"]


def test_faux_hubble_amount_change_is_reported_semantically(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    project_file = project_b / "project.yaml"
    payload = _read_yaml(project_file)
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
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
                "amount": 0.25,
                "preserve_brightness": True,
            },
        }
    )
    _write_yaml(project_a / "project.yaml", payload)
    rules[-1]["transform"]["amount"] = 0.60
    _write_yaml(project_file, payload)

    result = diff_projects(project_a, project_b)
    summaries = [change.human_summary for change in result.modified_items]

    assert "Changed Faux Hubble amount from 25% to 60%." in summaries


def test_faux_hubble_colour_balance_change_is_reported_semantically(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    payload = _read_yaml(project_a / "project.yaml")
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
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
                "amount": 0.60,
                "preserve_brightness": True,
                "colour_balance": {"gold": 100.0, "green": 100.0, "cyan": 100.0},
            },
        }
    )
    _write_yaml(project_a / "project.yaml", payload)
    _write_yaml(project_b / "project.yaml", payload)

    other_payload = _read_yaml(project_b / "project.yaml")
    other_rules = other_payload["rules"]
    assert isinstance(other_rules, list)
    other_rules[-1]["transform"]["colour_balance"]["gold"] = 70.0
    other_rules[-1]["transform"]["colour_balance"]["cyan"] = 135.0
    _write_yaml(project_b / "project.yaml", other_payload)

    result = diff_projects(project_a, project_b)
    summaries = [change.human_summary for change in result.modified_items]

    assert (
        "Changed Faux Hubble colour balance: Gold from 100% to 70% and Cyan from 100% to 135%."
        in summaries
    )


def test_faux_palette_cool_behaviour_change_is_reported_semantically(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    payload = _read_yaml(project_a / "project.yaml")
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
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
                "amount": 0.60,
                "preserve_brightness": True,
                "cool_mode": "enhance",
            },
        }
    )
    _write_yaml(project_a / "project.yaml", payload)
    transform = rules[-1]["transform"]
    assert isinstance(transform, dict)
    transform["cool_mode"] = "add"
    _write_yaml(project_b / "project.yaml", payload)

    result = diff_projects(project_a, project_b)
    summaries = [change.human_summary for change in result.modified_items]

    assert "Changed Faux Hubble Cyan behaviour from Enhance to Add." in summaries


def test_faux_palette_name_change_is_reported_semantically(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    project_file = project_a / "project.yaml"
    payload = _read_yaml(project_file)
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
        {
            "id": "faux-palette",
            "name": "Faux HOO",
            "enabled": True,
            "selection_source": "current",
            "target": "dark_dust",
            "match": {"softness": 0.5},
            "transform": {
                "type": "faux_palette",
                "palette": "hoo",
                "amount": 0.25,
                "preserve_brightness": True,
            },
        }
    )
    _write_yaml(project_file, payload)
    project_b_file = project_b / "project.yaml"
    _write_yaml(project_b_file, payload)
    other_payload = _read_yaml(project_b_file)
    other_rules = other_payload["rules"]
    assert isinstance(other_rules, list)
    other_rules[-1]["name"] = "Gold & Cyan"
    other_rules[-1]["transform"]["palette"] = "gold_cyan"
    _write_yaml(project_b_file, other_payload)

    result = diff_projects(project_a, project_b)
    summaries = [change.human_summary for change in result.modified_items]

    assert "Changed palette from Faux HOO to Gold & Cyan." in summaries


def test_dark_nebula_processing_control_change_is_reported_semantically(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    payload = _read_yaml(project_a / "project.yaml")
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
        {
            "id": "dark-nebula",
            "name": "Dark Nebula Processing",
            "enabled": True,
            "selection_source": "current",
            "target": "dark_dust",
            "match": {"softness": 0.5},
            "transform": {
                "type": "dark_nebula_processing",
                "amount": 0.55,
                "reveal_dust": 0.30,
                "dust_contrast": 0.25,
                "core_depth": 0.55,
                "dust_colour": 0.15,
                "softness": 0.20,
                "preserve_bright_areas": True,
            },
        }
    )
    _write_yaml(project_a / "project.yaml", payload)
    _write_yaml(project_b / "project.yaml", payload)

    other_payload = _read_yaml(project_b / "project.yaml")
    other_rules = other_payload["rules"]
    assert isinstance(other_rules, list)
    other_rules[-1]["transform"]["reveal_dust"] = 0.45
    _write_yaml(project_b / "project.yaml", other_payload)

    result = diff_projects(project_a, project_b)
    summaries = [change.human_summary for change in result.modified_items]

    assert "Changed Reveal Dust from 30% to 45%." in summaries


def test_feather_only_region_change_is_distinguished(tmp_path: Path) -> None:
    project_a = _copy_example("lion-natural", tmp_path)
    project_b = _copy_example("lion-natural", tmp_path / "second")
    region_file = project_b / "regions" / "lower-right.yaml"
    payload = _read_yaml(region_file)
    payload["feather"] = {"radius": 0.2}
    _write_yaml(region_file, payload)

    result = diff_projects(project_a, project_b)
    assert [change.code for change in result.modified_items] == ["region.feather_changed"]


def test_stable_json_ordering_for_strong_blue_diff() -> None:
    result = diff_projects(EXAMPLES / "lion-natural", EXAMPLES / "lion-strong-blue")
    payload = result.model_dump(mode="json")

    assert [item["code"] for item in payload["modified_items"]] == [
        "project.name_changed",
        "colour_point.moved",
        "region.geometry_changed",
        "region.feather_changed",
        "rule.transform_changed",
        "rule.disabled",
    ]
    assert [item["code"] for item in payload["reordered_rules"]] == [
        "rule.reordered",
        "rule.reordered",
    ]


def test_human_output_contains_plain_language_explanations() -> None:
    result = RUNNER.invoke(
        app,
        [
            "diff",
            str(EXAMPLES / "lion-natural"),
            str(EXAMPLES / "lion-strong-blue"),
        ],
    )

    assert result.exit_code == 0
    assert "More blue will be included" in result.stdout
    assert "region was enlarged" in result.stdout
    assert "was disabled" in result.stdout


def test_technical_output_contains_exact_paths_and_values() -> None:
    result = RUNNER.invoke(
        app,
        [
            "diff",
            str(EXAMPLES / "lion-natural"),
            str(EXAMPLES / "lion-strong-blue"),
            "--technical",
        ],
    )

    assert result.exit_code == 0
    assert "path=rules.reveal-faint-blue.transform" in result.stdout
    assert "old=" in result.stdout
    assert "new=" in result.stdout


def test_json_output_is_machine_readable() -> None:
    result = RUNNER.invoke(
        app,
        [
            "diff",
            str(EXAMPLES / "lion-strong-blue"),
            str(EXAMPLES / "lion-print"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["summary"]["modified"] >= 4
    assert any(item["code"] == "source.changed" for item in payload["modified_items"])


def test_invalid_projects_fail_before_comparison() -> None:
    result = RUNNER.invoke(
        app,
        [
            "diff",
            str(ROOT / "tests/fixtures/invalid/missing-source"),
            str(EXAMPLES / "lion-natural"),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_VALIDATION_ERROR
    payload = json.loads(result.stdout)
    assert payload["status"] == "validation-error"
    assert payload["project_a"]["valid"] is False

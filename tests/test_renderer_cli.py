from __future__ import annotations

import json
from pathlib import Path

from engine import EXIT_VALIDATION_ERROR, EXIT_VALIDATION_SUCCESS
from renderer_cli.main import app
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def test_validate_command_success() -> None:
    result = RUNNER.invoke(app, ["validate", str(ROOT / "examples/valid/minimal-project")])

    assert result.exit_code == EXIT_VALIDATION_SUCCESS
    assert "Project is valid" in result.stdout


def test_validate_command_failure_json() -> None:
    result = RUNNER.invoke(
        app,
        ["validate", str(ROOT / "tests/fixtures/invalid/missing-source"), "--json"],
    )

    assert result.exit_code == EXIT_VALIDATION_ERROR
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert any(issue["code"] == "missing-source-image" for issue in payload["issues"])


def test_preview_command_requires_output(tmp_path: Path) -> None:
    output_path = tmp_path / "preview.png"
    result = RUNNER.invoke(
        app,
        [
            "preview",
            str(ROOT / "tests/fixtures/invalid/missing-source"),
            "--output",
            str(output_path),
            "--json",
        ],
    )

    assert result.exit_code == EXIT_VALIDATION_ERROR

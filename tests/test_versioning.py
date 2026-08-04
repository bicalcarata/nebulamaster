from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from renderer_cli.main import app
from typer.testing import CliRunner
from versioning import discover_repository

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "diff"
RUNNER = CliRunner()


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _copy_example(example_name: str, destination: Path) -> None:
    shutil.copytree(EXAMPLES / example_name, destination)


def _replace_project(project_dir: Path, example_name: str) -> None:
    shutil.rmtree(project_dir)
    _copy_example(example_name, project_dir)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_history_repo(
    tmp_path: Path,
    *,
    with_spaces: bool = False,
) -> tuple[Path, Path, list[str]]:
    repo_name = "repo with spaces" if with_spaces else "repo"
    project_name = "lion project" if with_spaces else "lion-project"
    repo_root = tmp_path / repo_name
    repo_root.mkdir(parents=True, exist_ok=True)
    _git(repo_root, "init")
    _git(repo_root, "config", "user.name", "Nebula Tester")
    _git(repo_root, "config", "user.email", "nebula@example.com")

    _write_text(repo_root / "README.md", "unrelated\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "Initial repository note")

    project_dir = repo_root / "projects" / project_name
    _copy_example("lion-natural", project_dir)

    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Initial natural version",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.stdout

    _replace_project(project_dir, "lion-strong-blue")
    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Stronger blue version",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.stdout

    _replace_project(project_dir, "lion-print")
    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Print version",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.stdout

    log_output = _git(
        repo_root,
        "log",
        "--format=%H",
        "--",
        project_dir.relative_to(repo_root).as_posix(),
    )
    commits = [line for line in log_output.stdout.splitlines() if line.strip()]
    return repo_root, project_dir, commits


def test_repository_discovery_from_nested_project_path(tmp_path: Path) -> None:
    repo_root, project_dir, _commits = _create_history_repo(tmp_path)

    context = discover_repository(project_dir)

    assert context.repo_root == repo_root.resolve()


def test_save_version_refuses_to_init_without_flag(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _copy_example("lion-natural", project_dir)

    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Initial natural version",
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert payload["status"] == "safety-refusal"


def test_save_version_can_init_repository_explicitly(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _copy_example("lion-natural", project_dir)

    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Initial natural version",
            "--yes",
            "--init",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "commit_hash" in payload
    assert (project_dir / ".git").exists()


def test_save_version_init_sets_local_identity_when_global_git_config_is_missing(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    _copy_example("lion-natural", project_dir)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Initial natural version",
            "--yes",
            "--init",
        ],
    )

    assert result.exit_code == 0
    assert (
        _git(project_dir, "config", "--local", "--get", "user.name").stdout.strip()
        == "NebulaMaster"
    )
    assert (
        _git(project_dir, "config", "--local", "--get", "user.email").stdout.strip()
        == "nebula-master@local.invalid"
    )


def test_unrelated_repository_changes_block_save_version(tmp_path: Path) -> None:
    repo_root, project_dir, _commits = _create_history_repo(tmp_path)
    _write_text(repo_root / "README.md", "changed unrelated\n")
    _replace_project(project_dir, "lion-natural")

    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Back to natural",
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert "unrelated repository changes" in payload["message"]


def test_generated_files_are_ignored_after_init(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _copy_example("lion-natural", project_dir)
    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Initial natural version",
            "--yes",
            "--init",
        ],
    )
    assert result.exit_code == 0

    _write_text(project_dir / "previews" / "preview.png", "preview")
    status_result = RUNNER.invoke(app, ["status", str(project_dir), "--json"])
    assert status_result.exit_code == 0
    payload = json.loads(status_result.stdout)
    assert any("previews/preview.png" in item for item in payload["ignored_project_files"])


def test_empty_commit_is_refused_without_allow_empty(tmp_path: Path) -> None:
    _repo_root, project_dir, _commits = _create_history_repo(tmp_path)
    result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "No changes",
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 6
    payload = json.loads(result.stdout)
    assert "no project changes" in payload["message"]


def test_versions_lists_only_project_commits(tmp_path: Path) -> None:
    repo_root, project_dir, _commits = _create_history_repo(tmp_path)
    _write_text(repo_root / "README.md", "repo note 2\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "Unrelated repo update")

    result = RUNNER.invoke(app, ["versions", str(project_dir), "--json", "--limit", "10"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    subjects = [entry["subject"] for entry in payload]
    assert subjects == [
        "Print version",
        "Stronger blue version",
        "Initial natural version",
    ]


def test_compare_materialises_history_without_changing_head_or_working_tree(tmp_path: Path) -> None:
    repo_root, project_dir, commits = _create_history_repo(tmp_path)
    before_head = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    before_status = _git(repo_root, "status", "--porcelain=v1").stdout

    result = RUNNER.invoke(
        app,
        [
            "compare",
            str(project_dir),
            commits[-1],
            commits[-2],
        ],
    )

    assert result.exit_code == 0
    after_head = _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    after_status = _git(repo_root, "status", "--porcelain=v1").stdout
    assert before_head == after_head
    assert before_status == after_status


def test_restore_refuses_over_unsaved_project_changes(tmp_path: Path) -> None:
    _repo_root, project_dir, commits = _create_history_repo(tmp_path)
    _write_text(project_dir / "regions" / "scratch.txt", "not source of truth")
    project_file = project_dir / "project.yaml"
    project_file.write_text(project_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    result = RUNNER.invoke(app, ["restore", str(project_dir), commits[-1]])

    assert result.exit_code == 6
    assert "overwrite unsaved project changes" in result.stdout


def test_restore_changes_project_files_only(tmp_path: Path) -> None:
    repo_root, project_dir, commits = _create_history_repo(tmp_path, with_spaces=True)
    readme_before = (repo_root / "README.md").read_text(encoding="utf-8")

    result = RUNNER.invoke(app, ["restore", str(project_dir), commits[-1], "--force"])

    assert result.exit_code == 0
    assert "Restored project files" in result.stdout
    project_text = (project_dir / "project.yaml").read_text(encoding="utf-8")
    assert "Lion Natural" in project_text
    assert (repo_root / "README.md").read_text(encoding="utf-8") == readme_before


def test_status_and_save_output_include_semantic_summary(tmp_path: Path) -> None:
    _repo_root, project_dir, _commits = _create_history_repo(tmp_path)
    _replace_project(project_dir, "lion-natural")

    status_result = RUNNER.invoke(app, ["status", str(project_dir)])
    assert status_result.exit_code == 0
    assert "The Lower Right region was reduced." in status_result.stdout

    save_result = RUNNER.invoke(
        app,
        [
            "save-version",
            str(project_dir),
            "--message",
            "Return to natural",
            "--yes",
        ],
    )
    assert save_result.exit_code == 0
    assert "Semantic changes:" in save_result.stdout


def test_boundary_command_and_paths_with_spaces_work(tmp_path: Path) -> None:
    _repo_root, project_dir, _commits = _create_history_repo(tmp_path, with_spaces=True)
    result = RUNNER.invoke(app, ["boundary", str(project_dir), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert any("project.yaml" in item for item in payload["files"])


def test_git_command_failures_are_reported_usefully(tmp_path: Path) -> None:
    _repo_root, project_dir, _commits = _create_history_repo(tmp_path)
    result = RUNNER.invoke(
        app,
        [
            "compare",
            str(project_dir),
            "does-not-exist",
            "HEAD",
            "--json",
        ],
    )

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["status"] == "git-error"

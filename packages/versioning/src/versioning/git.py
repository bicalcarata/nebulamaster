from __future__ import annotations

import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal

from engine.validation import load_valid_project_bundle
from project_io import load_project_file, locate_project_file
from project_model import SCHEMA_VERSION, ProjectBundle, ProjectFile
from pydantic import BaseModel, ConfigDict, Field

EXIT_GIT_ERROR = 5
EXIT_SAFETY_REFUSAL = 6
IGNORED_OUTPUT_PATTERNS = ["generated/", "previews/", "cache/", "debug/"]


class GitCommandError(Exception):
    def __init__(
        self,
        message: str,
        *,
        args: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        super().__init__(message)
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SafetyRefusalError(Exception):
    pass


class GitRepositoryContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_root: Path
    project_dir: Path
    project_file: Path


class ProjectBoundary(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_root: Path
    project_dir: Path
    project_file: Path
    relative_project_dir: str
    files: list[str]
    tracked_source_files: list[str] = Field(default_factory=list)


class GitStatusEntry(BaseModel):
    path: str
    status_code: str
    kind: Literal[
        "modified",
        "added",
        "deleted",
        "renamed",
        "copied",
        "untracked",
        "ignored",
        "conflict",
        "unknown",
    ]
    inside_project: bool
    inside_boundary: bool


class ProjectStatus(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repository_root: Path
    project_dir: Path
    boundary: ProjectBoundary
    head_commit: str | None = None
    project_changes: list[GitStatusEntry] = Field(default_factory=list)
    unrelated_changes: list[GitStatusEntry] = Field(default_factory=list)
    ignored_project_files: list[str] = Field(default_factory=list)


StatusKind = Literal[
    "modified",
    "added",
    "deleted",
    "renamed",
    "copied",
    "untracked",
    "ignored",
    "conflict",
    "unknown",
]


class SaveVersionResult(BaseModel):
    commit_hash: str
    project_path: str
    schema_version: int
    planned_files: list[str]
    semantic_summary: list[str]


class VersionEntry(BaseModel):
    commit_hash: str
    short_hash: str
    committed_at: str
    author: str
    subject: str
    semantic_summary: list[str] = Field(default_factory=list)


def _run_git(
    repo_root: Path,
    args: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise GitCommandError(
            f"git command failed: {' '.join(args)}",
            args=args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
    )
    return completed


def _git_config_value(repo_root: Path, key: str) -> str | None:
    completed = _run_git(repo_root, ["config", "--get", key], check=False)
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _ensure_local_commit_identity(repo_root: Path) -> None:
    if _git_config_value(repo_root, "user.name") is None:
        _run_git(repo_root, ["config", "user.name", "Nebula Master"])
    if _git_config_value(repo_root, "user.email") is None:
        _run_git(repo_root, ["config", "user.email", "nebula-master@local.invalid"])


def _classify_status(code: str) -> StatusKind:
    if code == "??":
        return "untracked"
    if code == "!!":
        return "ignored"
    if "U" in code:
        return "conflict"
    if "R" in code:
        return "renamed"
    if "C" in code:
        return "copied"
    if "A" in code:
        return "added"
    if "D" in code:
        return "deleted"
    if "M" in code:
        return "modified"
    return "unknown"


def _parse_porcelain_line(line: str) -> tuple[str, str]:
    return line[:2], line[3:]


def _ensure_relative_to_repo(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _relative_project_dir(repo_root: Path, project_dir: Path) -> str:
    return _ensure_relative_to_repo(repo_root, project_dir)


def _bundle_boundary_files(
    bundle: ProjectBundle,
    *,
    repo_root: Path,
) -> tuple[list[str], list[str]]:
    boundary_files = [_ensure_relative_to_repo(repo_root, bundle.project_file)]
    tracked_sources: list[str] = []

    for reference in bundle.project.palettes:
        boundary_files.append(
            _ensure_relative_to_repo(repo_root, (bundle.project_dir / reference.path).resolve())
        )
    for reference in bundle.project.regions:
        boundary_files.append(
            _ensure_relative_to_repo(repo_root, (bundle.project_dir / reference.path).resolve())
        )
    for reference in bundle.project.render_profiles:
        boundary_files.append(
            _ensure_relative_to_repo(repo_root, (bundle.project_dir / reference.path).resolve())
        )

    boundary_files.append(
        _ensure_relative_to_repo(
            repo_root,
            (bundle.project_dir / bundle.project.plugins.path).resolve(),
        )
    )

    for source in bundle.project.sources:
        if source.checksum is None:
            continue
        relative = _ensure_relative_to_repo(repo_root, (bundle.project_dir / source.path).resolve())
        boundary_files.append(relative)
        tracked_sources.append(relative)

    return sorted(set(boundary_files)), sorted(set(tracked_sources))


def discover_repository(project_path: Path) -> GitRepositoryContext:
    project_file = locate_project_file(project_path)
    project_dir = project_file.parent.resolve()
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        raise SafetyRefusalError(
            "no Git repository was found for this project; rerun save-version with --init"
        )
    repo_root = Path(probe.stdout.strip()).resolve()
    return GitRepositoryContext(
        repo_root=repo_root,
        project_dir=project_dir,
        project_file=project_file.resolve(),
    )


def init_repository(project_path: Path) -> GitRepositoryContext:
    project_file = locate_project_file(project_path)
    project_dir = project_file.parent.resolve()
    completed = subprocess.run(
        ["git", "init"],
        cwd=project_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GitCommandError(
            "git init failed",
            args=["init"],
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    info_exclude = project_dir / ".git" / "info" / "exclude"
    existing = info_exclude.read_text(encoding="utf-8") if info_exclude.exists() else ""
    additions = [pattern for pattern in IGNORED_OUTPUT_PATTERNS if pattern not in existing]
    if additions:
        with info_exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            for pattern in additions:
                handle.write(f"{pattern}\n")
    return discover_repository(project_dir)


def build_project_boundary(bundle: ProjectBundle, repo_root: Path) -> ProjectBoundary:
    files, tracked_sources = _bundle_boundary_files(bundle, repo_root=repo_root)
    return ProjectBoundary(
        repo_root=repo_root,
        project_dir=bundle.project_dir.resolve(),
        project_file=bundle.project_file.resolve(),
        relative_project_dir=_relative_project_dir(repo_root, bundle.project_dir.resolve()),
        files=files,
        tracked_source_files=tracked_sources,
    )


def project_boundary_from_path(
    project_path: Path,
    repo_root: Path | None = None,
) -> ProjectBoundary:
    bundle, report = load_valid_project_bundle(project_path)
    if bundle is None or not report.valid:
        raise SafetyRefusalError("project boundary requires a valid project")
    if repo_root is None:
        repo_root = discover_repository(project_path).repo_root
    return build_project_boundary(bundle, repo_root)


def _current_head(repo_root: Path) -> str | None:
    completed = _run_git(repo_root, ["rev-parse", "--verify", "HEAD"], check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _project_file_from_version(context: GitRepositoryContext, version: str) -> ProjectFile:
    resolved_version = _version_exists(context.repo_root, version)
    relative_project_path = _ensure_relative_to_repo(context.repo_root, context.project_file)
    with tempfile.TemporaryDirectory(prefix="nebula-version-project-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        project_bytes = _git_show_bytes(context.repo_root, resolved_version, relative_project_path)
        project_file = temp_dir / "project.yaml"
        project_file.write_bytes(project_bytes)
        return load_project_file(project_file)


def project_boundary_files_for_version(project_path: Path, version: str) -> list[str]:
    context = discover_repository(project_path)
    project = _project_file_from_version(context, version)
    relative_project_dir = PurePosixPath(
        context.project_dir.relative_to(context.repo_root).as_posix()
    )

    def join(relative_path: Path) -> str:
        return (relative_project_dir / PurePosixPath(relative_path.as_posix())).as_posix()

    files = [join(Path("project.yaml"))]
    files.extend(join(reference.path) for reference in project.palettes)
    files.extend(join(reference.path) for reference in project.regions)
    files.extend(join(reference.path) for reference in project.render_profiles)
    files.append(join(project.plugins.path))
    files.extend(join(source.path) for source in project.sources if source.checksum is not None)
    return sorted(set(files))


def status_for_project(
    project_path: Path,
    *,
    additional_boundary_files: list[str] | None = None,
) -> ProjectStatus:
    context = discover_repository(project_path)
    boundary = project_boundary_from_path(project_path, context.repo_root)
    boundary_set = set(boundary.files)
    if additional_boundary_files is not None:
        boundary_set.update(additional_boundary_files)
    project_prefix = f"{boundary.relative_project_dir}/"
    status_output = _run_git(
        context.repo_root,
        ["status", "--porcelain=v1", "--ignored=matching", "--untracked-files=all"],
    )

    project_changes: list[GitStatusEntry] = []
    unrelated_changes: list[GitStatusEntry] = []
    ignored_project_files: list[str] = []

    for raw_line in status_output.stdout.splitlines():
        if not raw_line:
            continue
        code, path_text = _parse_porcelain_line(raw_line)
        path_text = path_text.strip().strip('"')
        if boundary.relative_project_dir == ".":
            inside_project = True
        else:
            inside_project = (
                path_text == boundary.relative_project_dir
                or path_text.startswith(project_prefix)
                or path_text in boundary_set
            )
        inside_boundary = path_text in boundary_set
        entry = GitStatusEntry(
            path=path_text,
            status_code=code,
            kind=_classify_status(code),
            inside_project=inside_project,
            inside_boundary=inside_boundary,
        )
        if entry.kind == "ignored" and inside_project:
            ignored_path = context.repo_root / path_text
            if ignored_path.is_dir():
                ignored_project_files.extend(
                    sorted(
                        _ensure_relative_to_repo(context.repo_root, child)
                        for child in ignored_path.rglob("*")
                        if child.is_file()
                    )
                )
            else:
                ignored_project_files.append(path_text)
        elif inside_boundary:
            project_changes.append(entry)
        elif inside_project or entry.kind != "ignored":
            unrelated_changes.append(entry)

    return ProjectStatus(
        repository_root=context.repo_root,
        project_dir=context.project_dir,
        boundary=boundary,
        head_commit=_current_head(context.repo_root),
        project_changes=project_changes,
        unrelated_changes=unrelated_changes,
        ignored_project_files=ignored_project_files,
    )


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def snapshot_working_project(project_path: Path, target_dir: Path) -> Path:
    context = discover_repository(project_path)
    boundary = project_boundary_from_path(project_path, context.repo_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    for relative in boundary.files:
        source = context.repo_root / relative
        destination = target_dir / Path(relative).relative_to(boundary.relative_project_dir)
        _copy_file(source, destination)
    return target_dir


def _version_exists(repo_root: Path, version: str) -> str:
    completed = _run_git(repo_root, ["rev-parse", "--verify", version], check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise GitCommandError(
            f"unknown Git version reference: {version}",
            args=["rev-parse", "--verify", version],
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    return completed.stdout.strip()


def _git_show_bytes(repo_root: Path, version: str, repo_relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{version}:{repo_relative_path}"],
        cwd=repo_root,
        text=False,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GitCommandError(
            f"unable to materialize {repo_relative_path} from {version}",
            args=["show", f"{version}:{repo_relative_path}"],
            returncode=completed.returncode,
            stdout=completed.stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
        )
    return completed.stdout


def _write_readonly_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    current_mode = path.stat().st_mode
    path.chmod(current_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def _load_project_from_materialized(project_file: Path) -> ProjectFile:
    return load_project_file(project_file)


def materialize_project_version(
    project_path: Path,
    version: str,
    target_dir: Path,
) -> Path:
    context = discover_repository(project_path)
    resolved_version = _version_exists(context.repo_root, version)
    relative_project_path = _ensure_relative_to_repo(context.repo_root, context.project_file)
    project_bytes = _git_show_bytes(context.repo_root, resolved_version, relative_project_path)
    project_file = target_dir / "project.yaml"
    _write_readonly_file(project_file, project_bytes)
    project = _load_project_from_materialized(project_file)

    def repo_path(relative_path: Path) -> str:
        joined = PurePosixPath(
            context.project_dir.relative_to(context.repo_root).as_posix()
        ) / PurePosixPath(relative_path.as_posix())
        return joined.as_posix()

    for reference in project.palettes:
        _write_readonly_file(
            target_dir / reference.path,
            _git_show_bytes(context.repo_root, resolved_version, repo_path(reference.path)),
        )
    for reference in project.regions:
        _write_readonly_file(
            target_dir / reference.path,
            _git_show_bytes(context.repo_root, resolved_version, repo_path(reference.path)),
        )
    for reference in project.render_profiles:
        _write_readonly_file(
            target_dir / reference.path,
            _git_show_bytes(context.repo_root, resolved_version, repo_path(reference.path)),
        )

    _write_readonly_file(
        target_dir / project.plugins.path,
        _git_show_bytes(context.repo_root, resolved_version, repo_path(project.plugins.path)),
    )

    for source in project.sources:
        if source.checksum is None:
            continue
        _write_readonly_file(
            target_dir / source.path,
            _git_show_bytes(context.repo_root, resolved_version, repo_path(source.path)),
        )

    return target_dir


def _project_history_pathspec(boundary: ProjectBoundary) -> str:
    return boundary.relative_project_dir


def project_head_commit(project_path: Path) -> str | None:
    context = discover_repository(project_path)
    boundary = project_boundary_from_path(project_path, context.repo_root)
    completed = _run_git(
        context.repo_root,
        ["log", "-n", "1", "--format=%H", "--", _project_history_pathspec(boundary)],
        check=False,
    )
    value = completed.stdout.strip()
    return value or None


def _project_commit_for_boundary(repo_root: Path, boundary: ProjectBoundary) -> str | None:
    completed = _run_git(
        repo_root,
        ["log", "-n", "1", "--format=%H", "--", _project_history_pathspec(boundary)],
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _tracked_changes_outside_boundary(status: ProjectStatus) -> list[GitStatusEntry]:
    return [entry for entry in status.unrelated_changes if entry.kind != "ignored"]


def _stage_boundary_changes(repo_root: Path, files: list[str]) -> None:
    if not files:
        return
    _run_git(repo_root, ["add", "--", *files])


def _boundary_changed_files(status: ProjectStatus) -> list[str]:
    return sorted({entry.path for entry in status.project_changes})


def _git_diff_files(repo_root: Path, files: list[str]) -> list[str]:
    if not files:
        return []
    completed = _run_git(repo_root, ["diff", "--name-only", "HEAD", "--", *files], check=False)
    if completed.returncode != 0:
        return []
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return sorted(set(lines))


def create_version_commit(
    project_path: Path,
    message: str,
    *,
    yes: bool,
    init: bool,
    allow_empty: bool,
    include_all_project_changes: bool,
    semantic_summary: list[str],
) -> SaveVersionResult:
    try:
        context = discover_repository(project_path)
    except SafetyRefusalError:
        if not init:
            raise
        context = init_repository(project_path)

    bundle, report = load_valid_project_bundle(project_path)
    if bundle is None or not report.valid:
        raise SafetyRefusalError("project must validate before save-version can run")

    boundary = build_project_boundary(bundle, context.repo_root)
    previous_boundary_files: list[str] = []
    previous_project_commit = _project_commit_for_boundary(context.repo_root, boundary)
    if previous_project_commit is not None:
        previous_boundary_files = project_boundary_files_for_version(
            project_path,
            previous_project_commit,
        )

    status = status_for_project(project_path, additional_boundary_files=previous_boundary_files)
    unrelated = _tracked_changes_outside_boundary(status)
    if unrelated:
        raise SafetyRefusalError("there are unrelated repository changes outside this project")

    changed_files = (
        boundary.files if include_all_project_changes else _boundary_changed_files(status)
    )
    head_commit = _current_head(context.repo_root)
    if head_commit is not None:
        changed_files = sorted(
            set(changed_files)
            | set(_git_diff_files(context.repo_root, boundary.files + previous_boundary_files))
        )

    if not changed_files and not allow_empty:
        raise SafetyRefusalError("there are no project changes to save")

    if not yes:
        raise SafetyRefusalError("save-version requires --yes for non-interactive execution")

    _stage_boundary_changes(context.repo_root, changed_files or boundary.files)
    _ensure_local_commit_identity(context.repo_root)
    commit_lines = [
        message,
        "",
        f"Nebula-Project: {boundary.relative_project_dir}",
        f"Nebula-Schema: {SCHEMA_VERSION}",
        "Nebula-Changes:",
    ]
    if semantic_summary:
        commit_lines.extend(f"- {line}" for line in semantic_summary)
    else:
        commit_lines.append("- Initial project version.")
    commit_message = "\n".join(commit_lines) + "\n"

    commit_args = ["commit", "-F", "-"]
    if allow_empty:
        commit_args.append("--allow-empty")
    _run_git(context.repo_root, commit_args, input_text=commit_message)
    commit_hash = _run_git(context.repo_root, ["rev-parse", "--verify", "HEAD"]).stdout.strip()
    return SaveVersionResult(
        commit_hash=commit_hash,
        project_path=boundary.relative_project_dir,
        schema_version=bundle.project.schema_version,
        planned_files=changed_files or boundary.files,
        semantic_summary=semantic_summary or ["Initial project version."],
    )


def _extract_semantic_summary(body: str) -> list[str]:
    lines = body.splitlines()
    summary: list[str] = []
    collecting = False
    for line in lines:
        if line.strip() == "Nebula-Changes:":
            collecting = True
            continue
        if collecting:
            if line.startswith("- "):
                summary.append(line[2:].strip())
            elif line.strip():
                break
    return summary


def list_project_versions(project_path: Path, *, limit: int = 10) -> list[VersionEntry]:
    context = discover_repository(project_path)
    boundary = project_boundary_from_path(project_path, context.repo_root)
    separator = "\x1f"
    terminator = "\x1e"
    pretty = f"%H{separator}%h{separator}%cI{separator}%an{separator}%s{separator}%B{terminator}"
    completed = _run_git(
        context.repo_root,
        [
            "log",
            f"--max-count={limit}",
            f"--pretty=format:{pretty}",
            "--",
            _project_history_pathspec(boundary),
        ],
    )
    entries: list[VersionEntry] = []
    for record in completed.stdout.split(terminator):
        if not record.strip():
            continue
        parts = record.split(separator)
        if len(parts) < 6:
            continue
        entries.append(
            VersionEntry(
                commit_hash=parts[0].strip(),
                short_hash=parts[1].strip(),
                committed_at=parts[2].strip(),
                author=parts[3].strip(),
                subject=parts[4].strip(),
                semantic_summary=_extract_semantic_summary(parts[5]),
            )
        )
    return entries


def restore_project_version(project_path: Path, version: str, *, force: bool) -> Path:
    context = discover_repository(project_path)
    status = status_for_project(project_path)
    if status.project_changes and not force:
        raise SafetyRefusalError(
            "restore would overwrite unsaved project changes; rerun with --force"
        )

    with tempfile.TemporaryDirectory(prefix="nebula-restore-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        snapshot_dir = materialize_project_version(project_path, version, temp_dir / "snapshot")
        target_boundary_files = set(project_boundary_files_for_version(project_path, version))

        current_files = set(status.boundary.files)
        for relative in current_files - target_boundary_files:
            target_path = context.repo_root / relative
            if target_path.exists():
                target_path.unlink()

        for relative in target_boundary_files:
            source = snapshot_dir / Path(relative).relative_to(status.boundary.relative_project_dir)
            destination = context.repo_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copy2(source, destination)

    return context.project_dir

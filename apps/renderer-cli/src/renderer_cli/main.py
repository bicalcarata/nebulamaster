from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import typer
from engine import (
    EXIT_INPUT_ERROR,
    EXIT_RENDER_ERROR,
    EXIT_RUNTIME_ERROR,
    PreparedSourcesResult,
    ProjectDiffValidationError,
    RenderExecutionError,
    RenderInputError,
    SourcePreparationError,
    ValidationRuntimeError,
    diff_projects,
    inspect_sources,
    load_valid_project_bundle,
    render_output,
    validate_project,
    write_aligned_bundle,
)
from engine.preview import PreviewInputError, PreviewRenderError, render_preview
from project_model import CropDeclaration
from versioning import (
    EXIT_GIT_ERROR,
    EXIT_SAFETY_REFUSAL,
    GitCommandError,
    SafetyRefusalError,
    create_version_commit,
    list_project_versions,
    materialize_project_version,
    project_boundary_from_path,
    project_head_commit,
    restore_project_version,
    snapshot_working_project,
    status_for_project,
)

app = typer.Typer(help="NebulaMaster renderer CLI.")
PROJECT_PATH_ARGUMENT = typer.Argument(..., exists=True, readable=True, resolve_path=True)
JSON_OPTION = typer.Option(False, "--json", help="Return machine-readable JSON output.")
OUTPUT_PATH_OPTION = typer.Option(..., "--output", resolve_path=True)
FORCE_OPTION = typer.Option(False, "--force", help="Overwrite existing preview output.")
PROFILE_OPTION = typer.Option(..., "--profile", help="Render profile identifier.")
DRY_RUN_OPTION = typer.Option(
    False,
    "--dry-run",
    help="Validate and plan the render without creating output files.",
)
TECHNICAL_OPTION = typer.Option(
    False,
    "--technical",
    help="Include exact paths and old/new values in human-readable output.",
)
DEBUG_MASKS_OPTION = typer.Option(
    None,
    "--write-debug-masks",
    help="Write debug mask artefacts to a directory.",
    resolve_path=True,
)
CROP_OPTION = typer.Option(
    None,
    "--crop",
    help="Normalized crop rectangle as x,y,width,height applied after mastering and before resize.",
)
YES_OPTION = typer.Option(False, "--yes", help="Confirm the operation without prompting.")
INIT_OPTION = typer.Option(
    False,
    "--init",
    help="Initialise a local Git repository if this project is not already in one.",
)
ALLOW_EMPTY_OPTION = typer.Option(False, "--allow-empty", help="Allow an empty version commit.")
INCLUDE_ALL_PROJECT_CHANGES_OPTION = typer.Option(
    False,
    "--include-all-project-changes",
    help="Stage all source-of-truth files inside the project boundary.",
)
LIMIT_OPTION = typer.Option(10, "--limit", min=1, help="Maximum number of versions to list.")


@app.callback()
def renderer_cli() -> None:
    """NebulaMaster renderer CLI."""


def _format_issue(issue: dict[str, Any]) -> str:
    location = issue.get("location", [])
    location_text = ".".join(str(item) for item in location) if location else "-"
    file_text = issue.get("file", "-")
    return f"[{issue['code']}] {issue['message']} (file={file_text}, location={location_text})"


def _format_change(change: dict[str, Any], *, technical: bool) -> list[str]:
    lines = [f" - {change['human_summary']}"]
    if technical:
        path = change.get("technical_path") or "-"
        old_value = json.dumps(change.get("old_value"), sort_keys=True)
        new_value = json.dumps(change.get("new_value"), sort_keys=True)
        lines.append(f"   code={change['code']} path={path}")
        lines.append(f"   old={old_value}")
        lines.append(f"   new={new_value}")
    return lines


def _render_diff_result(result: Any, *, technical: bool, json_output: bool) -> None:
    payload = result.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    if (
        not result.added_items
        and not result.removed_items
        and not result.modified_items
        and not result.reordered_rules
    ):
        typer.echo("No semantic differences found.")
        return

    typer.echo(
        f"Semantic differences between {result.project_a.project_name} "
        f"and {result.project_b.project_name}:"
    )
    sections: list[list[Any]] = [
        result.modified_items,
        result.reordered_rules,
        result.added_items,
        result.removed_items,
    ]
    for section in sections:
        for change in section:
            change_payload = change.model_dump(mode="json")
            for line in _format_change(change_payload, technical=technical):
                typer.echo(line)


def _render_source_report(
    result: PreparedSourcesResult,
    *,
    technical: bool,
    json_output: bool,
) -> None:
    payload = result.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    for report in payload["alignment_reports"]:
        typer.echo(
            f"{report['source_id']} ({report['role']}): "
            f"offset=({report['estimated_x_px']:.2f}, {report['estimated_y_px']:.2f}) "
            f"confidence={report['confidence']:.2f}"
        )
        typer.echo(f"- {report['explanation']}")
        if technical:
            typer.echo(
                f"  applied=({report['applied_x_px']:.2f}, {report['applied_y_px']:.2f}) "
                f"residual={report['residual_error']:.4f} compatible={report['compatible']}"
            )


def _semantic_summary_since_last_version(project_path: Path) -> list[str]:
    head_commit = project_head_commit(project_path)
    if head_commit is None:
        return []

    with tempfile.TemporaryDirectory(prefix="nebula-status-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        previous = materialize_project_version(project_path, head_commit, temp_dir / "previous")
        result = diff_projects(previous, project_path)
    return [entry.summary for entry in result.explanations]


def _parse_crop_option(value: str | None) -> CropDeclaration | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter("--crop must be formatted as x,y,width,height")
    try:
        x, y, width, height = (float(part) for part in parts)
    except ValueError as exc:
        raise typer.BadParameter("--crop values must be numeric") from exc
    try:
        return CropDeclaration.model_validate(
            {
                "enabled": True,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "aspect_ratio": "custom",
                "lock_aspect_ratio": False,
            }
        )
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("validate")
def validate(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        report = validate_project(project_path)
    except ValidationRuntimeError as exc:
        payload = {
            "valid": False,
            "project_file": str(project_path),
            "issues": [
                {
                    "code": "runtime-error",
                    "message": str(exc),
                    "file": str(project_path),
                    "location": [],
                }
            ],
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Validation could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc

    payload = report.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        if report.valid:
            typer.echo(f"Project is valid: {report.project_file}")
        else:
            typer.echo(f"Validation failed: {report.project_file}")
            issue_payloads = payload["issues"]
            if isinstance(issue_payloads, list):
                for issue in issue_payloads:
                    if isinstance(issue, dict):
                        typer.echo(f" - {_format_issue(issue)}")

    raise typer.Exit(report.exit_code)


@app.command("preview")
def preview(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    output_path: Path = OUTPUT_PATH_OPTION,
    force: bool = FORCE_OPTION,
    write_debug_masks: Path | None = DEBUG_MASKS_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        report = validate_project(project_path)
    except ValidationRuntimeError as exc:
        payload = {
            "valid": False,
            "project_file": str(project_path),
            "issues": [
                {
                    "code": "runtime-error",
                    "message": str(exc),
                    "file": str(project_path),
                    "location": [],
                }
            ],
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Preview could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc

    if not report.valid:
        payload = report.model_dump(mode="json")
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Preview validation failed: {report.project_file}")
            issue_payloads = payload["issues"]
            if isinstance(issue_payloads, list):
                for issue in issue_payloads:
                    if isinstance(issue, dict):
                        typer.echo(f" - {_format_issue(issue)}")
        raise typer.Exit(report.exit_code)

    try:
        result = render_preview(
            project_path,
            output_path,
            force=force,
            write_debug_masks_dir=write_debug_masks,
        )
    except PreviewInputError as exc:
        payload = {
            "status": "input-error",
            "message": str(exc),
            "output_path": str(output_path),
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Preview input error: {exc}", err=True)
        raise typer.Exit(EXIT_INPUT_ERROR) from exc
    except PreviewRenderError as exc:
        payload = {
            "status": "render-error",
            "message": str(exc),
            "output_path": str(output_path),
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Preview render error: {exc}", err=True)
        raise typer.Exit(EXIT_RENDER_ERROR) from exc

    payload = result.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Preview written: {result.output_path}")
        typer.echo(f"Manifest written: {result.manifest_path}")

    raise typer.Exit(0)


@app.command("inspect-sources")
def inspect_project_sources(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    technical: bool = TECHNICAL_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        report = validate_project(project_path)
        if not report.valid:
            payload = report.model_dump(mode="json")
            if json_output:
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo(f"Source inspection validation failed: {report.project_file}")
            raise typer.Exit(report.exit_code)
        engine_bundle, engine_report = load_valid_project_bundle(project_path)
        assert engine_report.valid and engine_bundle is not None
        result = inspect_sources(engine_bundle)
    except ValidationRuntimeError as exc:
        typer.echo(f"Inspect-sources could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc
    except SourcePreparationError as exc:
        payload = {"status": "input-error", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INPUT_ERROR) from exc

    _render_source_report(result, technical=technical, json_output=json_output)
    raise typer.Exit(0)


@app.command("align-sources")
def align_sources(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    output_path: Path = OUTPUT_PATH_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        bundle, report = load_valid_project_bundle(project_path)
        if not report.valid or bundle is None:
            payload = report.model_dump(mode="json")
            if json_output:
                typer.echo(json.dumps(payload, indent=2))
            else:
                typer.echo(f"Alignment validation failed: {report.project_file}")
            raise typer.Exit(report.exit_code)
        manifest_path = write_aligned_bundle(bundle, output_path)
    except ValidationRuntimeError as exc:
        typer.echo(f"Align-sources could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc
    except SourcePreparationError as exc:
        payload = {"status": "input-error", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INPUT_ERROR) from exc

    payload = {"output_path": str(output_path), "manifest_path": str(manifest_path)}
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Aligned sources written: {output_path}")
        typer.echo(f"Manifest written: {manifest_path}")
    raise typer.Exit(0)


@app.command("render")
def render(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    profile_id: str = PROFILE_OPTION,
    output_path: Path = OUTPUT_PATH_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    write_debug_masks: Path | None = DEBUG_MASKS_OPTION,
    crop: str | None = CROP_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        report = validate_project(project_path)
    except ValidationRuntimeError as exc:
        payload = {
            "valid": False,
            "project_file": str(project_path),
            "issues": [
                {
                    "code": "runtime-error",
                    "message": str(exc),
                    "file": str(project_path),
                    "location": [],
                }
            ],
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Render could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc

    if not report.valid:
        payload = report.model_dump(mode="json")
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Render validation failed: {report.project_file}")
            issue_payloads = payload["issues"]
            if isinstance(issue_payloads, list):
                for issue in issue_payloads:
                    if isinstance(issue, dict):
                        typer.echo(f" - {_format_issue(issue)}")
        raise typer.Exit(report.exit_code)

    try:
        crop_override = _parse_crop_option(crop)
        result = render_output(
            project_path,
            profile_id=profile_id,
            output_path=output_path,
            force=force,
            dry_run=dry_run,
            write_debug_masks_dir=write_debug_masks,
            crop_override=crop_override,
        )
    except RenderInputError as exc:
        payload = {
            "status": "input-error",
            "message": str(exc),
            "output_path": str(output_path),
            "profile_id": profile_id,
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Render input error: {exc}", err=True)
        raise typer.Exit(EXIT_INPUT_ERROR) from exc
    except RenderExecutionError as exc:
        payload = {
            "status": "render-error",
            "message": str(exc),
            "output_path": str(output_path),
            "profile_id": profile_id,
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Render error: {exc}", err=True)
        raise typer.Exit(EXIT_RENDER_ERROR) from exc

    payload = result.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        if result.dry_run:
            typer.echo(f"Render plan ready for profile {result.profile_id}.")
        else:
            typer.echo(f"Render written: {result.output_path}")
            typer.echo(f"Manifest written: {result.manifest_path}")
        typer.echo(
            f"Output dimensions: {result.output_dimensions.width} x "
            f"{result.output_dimensions.height}"
        )
        typer.echo(result.guidance)

    raise typer.Exit(0)


@app.command("diff")
def diff(
    project_a: Path = PROJECT_PATH_ARGUMENT,
    project_b: Path = PROJECT_PATH_ARGUMENT,
    technical: bool = TECHNICAL_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        result = diff_projects(project_a, project_b)
    except ValidationRuntimeError as exc:
        runtime_payload = {
            "status": "runtime-error",
            "message": str(exc),
            "project_a": str(project_a),
            "project_b": str(project_b),
        }
        if json_output:
            typer.echo(json.dumps(runtime_payload, indent=2))
        else:
            typer.echo(f"Diff could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc
    except ProjectDiffValidationError as exc:
        payload: dict[str, Any] = {
            "status": "validation-error",
            "project_a": exc.report_a.model_dump(mode="json"),
            "project_b": exc.report_b.model_dump(mode="json"),
        }
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo("Diff validation failed.")
            if not exc.report_a.valid:
                typer.echo(f"Project A: {exc.report_a.project_file}")
                for issue in exc.report_a.model_dump(mode="json")["issues"]:
                    if isinstance(issue, dict):
                        typer.echo(f" - {_format_issue(issue)}")
            if not exc.report_b.valid:
                typer.echo(f"Project B: {exc.report_b.project_file}")
                for issue in exc.report_b.model_dump(mode="json")["issues"]:
                    if isinstance(issue, dict):
                        typer.echo(f" - {_format_issue(issue)}")
        raise typer.Exit(1) from exc

    payload = result.model_dump(mode="json")
    _render_diff_result(result, technical=technical, json_output=json_output)

    raise typer.Exit(0)


@app.command("status")
def status(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        status_result = status_for_project(project_path)
        semantic_summary = _semantic_summary_since_last_version(project_path)
    except ValidationRuntimeError as exc:
        typer.echo(f"Status could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc
    except SafetyRefusalError as exc:
        payload = {"status": "safety-refusal", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_SAFETY_REFUSAL) from exc
    except GitCommandError as exc:
        payload = {"status": "git-error", "message": str(exc), "stderr": exc.stderr}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Git error: {exc.stderr or exc}", err=True)
        raise typer.Exit(EXIT_GIT_ERROR) from exc

    status_payload: dict[str, Any] = {
        "repository_root": str(status_result.repository_root),
        "project_dir": str(status_result.project_dir),
        "boundary_files": status_result.boundary.files,
        "head_commit": status_result.head_commit,
        "project_changes": [
            entry.model_dump(mode="json") for entry in status_result.project_changes
        ],
        "unrelated_changes": [
            entry.model_dump(mode="json") for entry in status_result.unrelated_changes
        ],
        "ignored_project_files": status_result.ignored_project_files,
        "semantic_summary": semantic_summary,
    }
    if json_output:
        typer.echo(json.dumps(status_payload, indent=2))
    else:
        if semantic_summary:
            for line in semantic_summary:
                typer.echo(f"- {line}")
        else:
            typer.echo("No unsaved mastering changes.")
        if status_result.ignored_project_files:
            count = len(status_result.ignored_project_files)
            typer.echo(f"{count} generated project file{'s are' if count != 1 else ' is'} ignored.")
        if status_result.unrelated_changes:
            typer.echo("There are unrelated repository changes outside this project.")

    raise typer.Exit(0)


@app.command("save-version")
def save_version(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    message: str = typer.Option(..., "--message", help="Commit message subject."),
    yes: bool = YES_OPTION,
    init: bool = INIT_OPTION,
    allow_empty: bool = ALLOW_EMPTY_OPTION,
    include_all_project_changes: bool = INCLUDE_ALL_PROJECT_CHANGES_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        report = validate_project(project_path)
    except ValidationRuntimeError as exc:
        typer.echo(f"Save-version could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc

    if not report.valid:
        payload = report.model_dump(mode="json")
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Save-version validation failed: {report.project_file}")
            for issue in payload["issues"]:
                if isinstance(issue, dict):
                    typer.echo(f" - {_format_issue(issue)}")
        raise typer.Exit(report.exit_code)

    try:
        semantic_summary = _semantic_summary_since_last_version(project_path)
    except SafetyRefusalError:
        semantic_summary = []
    except GitCommandError as exc:
        payload = {"status": "git-error", "message": str(exc), "stderr": exc.stderr}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Git error: {exc.stderr or exc}", err=True)
        raise typer.Exit(EXIT_GIT_ERROR) from exc

    if not yes and not typer.confirm("Save this project version?"):
        raise typer.Exit(EXIT_SAFETY_REFUSAL)

    try:
        result = create_version_commit(
            project_path,
            message,
            yes=True,
            init=init,
            allow_empty=allow_empty,
            include_all_project_changes=include_all_project_changes,
            semantic_summary=semantic_summary,
        )
    except SafetyRefusalError as exc:
        payload = {"status": "safety-refusal", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_SAFETY_REFUSAL) from exc
    except GitCommandError as exc:
        payload = {"status": "git-error", "message": str(exc), "stderr": exc.stderr}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Git error: {exc.stderr or exc}", err=True)
        raise typer.Exit(EXIT_GIT_ERROR) from exc

    payload = result.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.echo(f"Saved version: {result.commit_hash}")
        typer.echo("Planned files:")
        for path_text in result.planned_files:
            typer.echo(f"- {path_text}")
        if result.semantic_summary:
            typer.echo("Semantic changes:")
            for line in result.semantic_summary:
                typer.echo(f"- {line}")

    raise typer.Exit(0)


@app.command("versions")
def versions(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    limit: int = LIMIT_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        entries = list_project_versions(project_path, limit=limit)
    except SafetyRefusalError as exc:
        payload = {"status": "safety-refusal", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_SAFETY_REFUSAL) from exc
    except GitCommandError as exc:
        payload = {"status": "git-error", "message": str(exc), "stderr": exc.stderr}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Git error: {exc.stderr or exc}", err=True)
        raise typer.Exit(EXIT_GIT_ERROR) from exc

    if json_output:
        typer.echo(json.dumps([entry.model_dump(mode="json") for entry in entries], indent=2))
    else:
        for entry in entries:
            typer.echo(f"{entry.short_hash}  {entry.committed_at}  {entry.author}  {entry.subject}")
            for summary in entry.semantic_summary:
                typer.echo(f"- {summary}")

    raise typer.Exit(0)


@app.command("compare")
def compare(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    version_a: str = typer.Argument(...),
    version_b: str = typer.Argument(...),
    technical: bool = TECHNICAL_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="nebula-compare-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            snapshot_a = materialize_project_version(project_path, version_a, temp_dir / "a")
            snapshot_b = materialize_project_version(project_path, version_b, temp_dir / "b")
            result = diff_projects(snapshot_a, snapshot_b)
    except ValidationRuntimeError as exc:
        typer.echo(f"Compare could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc
    except GitCommandError as exc:
        payload = {"status": "git-error", "message": str(exc), "stderr": exc.stderr}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(f"Git error: {exc.stderr or exc}", err=True)
        raise typer.Exit(EXIT_GIT_ERROR) from exc

    _render_diff_result(result, technical=technical, json_output=json_output)
    raise typer.Exit(0)


@app.command("restore")
def restore(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    version: str = typer.Argument(...),
    force: bool = FORCE_OPTION,
) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="nebula-pre-restore-") as temp_dir_name:
            before_snapshot = snapshot_working_project(project_path, Path(temp_dir_name) / "before")
            restore_project_version(project_path, version, force=force)
            result = diff_projects(before_snapshot, project_path)
    except ValidationRuntimeError as exc:
        typer.echo(f"Restore could not start: {exc}", err=True)
        raise typer.Exit(EXIT_RUNTIME_ERROR) from exc
    except SafetyRefusalError as exc:
        typer.echo(str(exc))
        raise typer.Exit(EXIT_SAFETY_REFUSAL) from exc
    except GitCommandError as exc:
        typer.echo(f"Git error: {exc.stderr or exc}", err=True)
        raise typer.Exit(EXIT_GIT_ERROR) from exc

    typer.echo(f"Restored project files from {version}.")
    _render_diff_result(result, technical=False, json_output=False)
    raise typer.Exit(0)


@app.command("boundary", hidden=True)
def boundary(
    project_path: Path = PROJECT_PATH_ARGUMENT,
    json_output: bool = JSON_OPTION,
) -> None:
    try:
        boundary_result = project_boundary_from_path(project_path)
    except SafetyRefusalError as exc:
        payload = {"status": "safety-refusal", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, indent=2))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_SAFETY_REFUSAL) from exc

    payload = boundary_result.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        for item in boundary_result.files:
            typer.echo(item)

    raise typer.Exit(0)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

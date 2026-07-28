from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from image_io import CanonicalImage, resize_to_max_edge, save_png, sha256_file
from project_model import ProjectBundle
from pydantic import BaseModel, ConfigDict, Field

from .executor import RuleExecutionTrace
from .render import apply_crop, execute_project_image
from .validation import ValidationRuntimeError, load_valid_project_bundle

PREVIEW_MAX_EDGE = 1024


class PreviewInputError(Exception):
    pass


class PreviewRenderError(Exception):
    pass


class PreviewRenderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_path: str
    manifest_path: str
    width: int
    height: int
    declared_rule_ids: list[str]
    enabled_rule_ids: list[str]
    applied_rule_ids: list[str]
    skipped_rules: list[dict[str, str]]
    execution_trace: list[RuleExecutionTrace]
    source_path: str
    source_sha256: str
    project_file: str
    project_sha256: str
    renderer_version: str
    render_timestamp: datetime


class PreviewImageResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    image: CanonicalImage = Field(exclude=True)
    width: int
    height: int
    declared_rule_ids: list[str]
    enabled_rule_ids: list[str]
    applied_rule_ids: list[str]
    skipped_rules: list[dict[str, str]]
    execution_trace: list[RuleExecutionTrace]
    source_path: str
    source_sha256: str
    project_file: str
    project_sha256: str
    renderer_version: str
    render_timestamp: datetime
    manifest_payload: dict[str, object]


def _renderer_version() -> str:
    try:
        return version("nebula-renderer-cli")
    except PackageNotFoundError:
        return "0.4.0"


def _ensure_output_path(output_path: Path, force: bool) -> Path:
    if output_path.suffix.lower() != ".png":
        raise PreviewInputError("preview output must use a .png extension")
    if output_path.exists() and not force:
        raise PreviewInputError("preview output already exists; use --force to overwrite it")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def _manifest_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.manifest.json")


def render_preview_image(
    bundle: ProjectBundle,
    *,
    max_edge: int = PREVIEW_MAX_EDGE,
    write_debug_masks_dir: Path | None = None,
    include_provenance: bool = True,
    use_cached_sources: bool = True,
) -> PreviewImageResult:
    source, source_path, canonical, execution, prepared_sources = execute_project_image(
        bundle,
        write_debug_masks_dir=write_debug_masks_dir,
        use_cached_sources=use_cached_sources,
    )
    mastered = CanonicalImage(
        data=execution.image,
        width=canonical.width,
        height=canonical.height,
    )
    cropped = apply_crop(mastered, bundle.project.crop)
    preview = resize_to_max_edge(cropped, max_edge)
    timestamp = datetime.now(tz=UTC)
    source_sha256 = sha256_file(source_path) if include_provenance else ""
    project_sha256 = sha256_file(bundle.project_file) if include_provenance else ""
    manifest_payload: dict[str, object] = {
        "project_schema_version": bundle.project.schema_version,
        "source_file_path": source.path.as_posix(),
        "source_file_sha256": source_sha256,
        "project_file_sha256": project_sha256,
        "renderer_version": _renderer_version(),
        "output_dimensions": {"width": preview.width, "height": preview.height},
        "declared_rule_ids": execution.declared_rule_ids,
        "enabled_rule_ids": execution.enabled_rule_ids,
        "applied_rule_ids": execution.applied_rule_ids,
        "skipped_rule_ids": execution.skipped_rules,
        "execution_trace": [trace.model_dump(mode="json") for trace in execution.traces],
        "declared_source_ids": prepared_sources.declared_source_ids,
        "enabled_source_ids": prepared_sources.enabled_source_ids,
        "reference_source_id": prepared_sources.reference_source_id,
        "source_mix_mode": prepared_sources.source_mix_mode,
        "source_mix_execution_order": prepared_sources.source_order,
        "source_contribution_matrix": prepared_sources.contribution_matrix,
        "source_alignment": [
            report.model_dump(mode="json") for report in prepared_sources.alignment_reports
        ],
        "render_timestamp": timestamp.isoformat(),
    }
    return PreviewImageResult(
        image=preview,
        width=preview.width,
        height=preview.height,
        declared_rule_ids=execution.declared_rule_ids,
        enabled_rule_ids=execution.enabled_rule_ids,
        applied_rule_ids=execution.applied_rule_ids,
        skipped_rules=execution.skipped_rules,
        execution_trace=execution.traces,
        source_path=source.path.as_posix(),
        source_sha256=source_sha256,
        project_file=str(bundle.project_file),
        project_sha256=project_sha256,
        renderer_version=_renderer_version(),
        render_timestamp=timestamp,
        manifest_payload=manifest_payload,
    )


def render_preview(
    project_path: Path,
    output_path: Path,
    force: bool = False,
    write_debug_masks_dir: Path | None = None,
) -> PreviewRenderResult:
    try:
        bundle, report = load_valid_project_bundle(project_path)
    except ValidationRuntimeError:
        raise

    if not report.valid or bundle is None:
        raise PreviewInputError("project validation failed")

    output_path = _ensure_output_path(output_path, force)
    manifest_path = _manifest_path(output_path)
    if manifest_path.exists() and not force:
        raise PreviewInputError("preview manifest already exists; use --force to overwrite it")

    try:
        image_result = render_preview_image(
            bundle,
            max_edge=PREVIEW_MAX_EDGE,
            write_debug_masks_dir=write_debug_masks_dir,
        )
        save_png(output_path, image_result.image.data)
    except PreviewInputError:
        raise
    except Exception as exc:  # pragma: no cover
        raise PreviewRenderError(f"failed to render preview: {exc}") from exc

    result = PreviewRenderResult(
        output_path=str(output_path),
        manifest_path=str(manifest_path),
        width=image_result.width,
        height=image_result.height,
        declared_rule_ids=image_result.declared_rule_ids,
        enabled_rule_ids=image_result.enabled_rule_ids,
        applied_rule_ids=image_result.applied_rule_ids,
        skipped_rules=image_result.skipped_rules,
        execution_trace=image_result.execution_trace,
        source_path=image_result.source_path,
        source_sha256=image_result.source_sha256,
        project_file=image_result.project_file,
        project_sha256=image_result.project_sha256,
        renderer_version=image_result.renderer_version,
        render_timestamp=image_result.render_timestamp,
    )
    manifest_path.write_text(
        json.dumps(image_result.manifest_payload, indent=2),
        encoding="utf-8",
    )
    return result

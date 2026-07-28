from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from image_io import (
    CanonicalImage,
    SaveImageOptions,
    crop_image,
    inspect_image,
    resize_exact,
    save_image,
    sha256_file,
)
from project_io import resolve_reference_path
from project_model import (
    ArchiveRenderProfile,
    CropDeclaration,
    PrintRenderProfile,
    ProjectBundle,
    RenderProfileDeclaration,
    ScreenRenderProfile,
    SourceImage,
)
from pydantic import BaseModel, ConfigDict

from .executor import RuleExecutionResult, RuleExecutionTrace, execute_rule_stack
from .sources import PreparedSourcesResult, SourcePreparationError, inspect_sources
from .validation import ValidationRuntimeError, load_valid_project_bundle

ENLARGEMENT_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (1.0, "native"),
    (1.5, "light enlargement"),
    (2.5, "moderate enlargement"),
)


class RenderInputError(Exception):
    pass


class RenderExecutionError(Exception):
    pass


class OutputSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int
    height: int


class PhysicalDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: float
    height: float
    units: Literal["cm", "inches"]
    ppi: int


class RenderPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    profile_type: str
    output_size: OutputSize
    cropped_source_size: OutputSize
    crop_box: tuple[int, int, int, int]
    interpolation: str
    enlargement_factor: float
    enlargement_classification: str
    guidance: str
    physical_dimensions: PhysicalDimensions | None = None
    perform_fill_crop: bool = False


class RenderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_path: str
    manifest_path: str
    output_sha256: str | None = None
    output_dimensions: OutputSize
    cropped_source_dimensions: OutputSize
    profile_id: str
    profile_type: str
    color_space: str
    output_format: str
    bit_depth: int
    interpolation: str
    enlargement_factor: float
    enlargement_classification: str
    guidance: str
    physical_dimensions: PhysicalDimensions | None = None
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
    dry_run: bool = False


def _renderer_version() -> str:
    try:
        return version("nebula-renderer-cli")
    except PackageNotFoundError:
        return "0.4.1"


def _enabled_sources(bundle: ProjectBundle) -> list[SourceImage]:
    return [source for source in bundle.project.sources if source.enabled]


def _reference_source(bundle: ProjectBundle) -> SourceImage:
    enabled_sources = _enabled_sources(bundle)
    references = [source for source in enabled_sources if source.reference]
    if len(enabled_sources) == 1 and not references:
        return enabled_sources[0]
    if len(references) == 1:
        return references[0]
    raise RenderInputError("exactly one reference source is required")


def _resolve_profile(bundle: ProjectBundle, profile_id: str) -> RenderProfileDeclaration:
    render_profile = bundle.render_profiles.get(profile_id)
    if render_profile is None:
        raise RenderInputError(f"render profile '{profile_id}' was not found")
    return render_profile.profile


def calculate_crop_box(crop: CropDeclaration, width: int, height: int) -> tuple[int, int, int, int]:
    left = int(round(crop.x * width))
    top = int(round(crop.y * height))
    right = int(round((crop.x + crop.width) * width))
    bottom = int(round((crop.y + crop.height) * height))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    return left, top, right, bottom


def apply_crop(image: CanonicalImage, crop: CropDeclaration) -> CanonicalImage:
    left, top, right, bottom = calculate_crop_box(crop, image.width, image.height)
    return crop_image(image, left=left, top=top, right=right, bottom=bottom)


def _fit_dimensions(
    source_width: int,
    source_height: int,
    box_width: int,
    box_height: int,
) -> OutputSize:
    scale = min(box_width / source_width, box_height / source_height)
    width = max(1, int(round(source_width * scale)))
    height = max(1, int(round(source_height * scale)))
    return OutputSize(width=width, height=height)


def _fill_crop_size(
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> OutputSize:
    source_aspect = source_width / source_height
    target_aspect = target_width / target_height
    if source_aspect > target_aspect:
        width = max(1, int(round(source_height * target_aspect)))
        return OutputSize(width=width, height=source_height)
    height = max(1, int(round(source_width / target_aspect)))
    return OutputSize(width=source_width, height=height)


def _center_fill_crop(
    image: CanonicalImage,
    target_width: int,
    target_height: int,
) -> CanonicalImage:
    crop_size = _fill_crop_size(image.width, image.height, target_width, target_height)
    left = max(0, (image.width - crop_size.width) // 2)
    top = max(0, (image.height - crop_size.height) // 2)
    return crop_image(
        image,
        left=left,
        top=top,
        right=left + crop_size.width,
        bottom=top + crop_size.height,
    )


def _round_print_pixels(value: float) -> int:
    return max(1, int(round(value)))


def _print_target_dimensions(profile: PrintRenderProfile) -> OutputSize:
    if profile.units == "cm":
        width = _round_print_pixels(profile.width / 2.54 * profile.ppi)
        height = _round_print_pixels(profile.height / 2.54 * profile.ppi)
    else:
        width = _round_print_pixels(profile.width * profile.ppi)
        height = _round_print_pixels(profile.height * profile.ppi)
    return OutputSize(width=width, height=height)


def _enlargement_classification(factor: float) -> tuple[str, str]:
    for threshold, label in ENLARGEMENT_THRESHOLDS:
        if factor <= threshold:
            if label == "native":
                return label, "This render uses the available source resolution."
            if label == "light enlargement":
                return label, "This crop requires light enlargement for the requested output."
            return label, "This crop requires moderate enlargement and may appear softer."
    return (
        "heavy enlargement",
        "This crop requires substantial enlargement and may appear softer when viewed closely.",
    )


def plan_render(
    profile: RenderProfileDeclaration,
    *,
    source_width: int,
    source_height: int,
    crop: CropDeclaration,
) -> RenderPlan:
    crop_box = calculate_crop_box(crop, source_width, source_height)
    cropped_width = crop_box[2] - crop_box[0]
    cropped_height = crop_box[3] - crop_box[1]
    cropped_size = OutputSize(width=cropped_width, height=cropped_height)
    physical_dimensions: PhysicalDimensions | None = None
    perform_fill_crop = False

    if isinstance(profile, ScreenRenderProfile):
        if profile.width_px is not None and profile.height_px is not None:
            output_size = OutputSize(width=profile.width_px, height=profile.height_px)
        elif profile.width_px is not None:
            output_size = OutputSize(
                width=profile.width_px,
                height=max(1, int(round(cropped_height * (profile.width_px / cropped_width)))),
            )
        elif profile.height_px is not None:
            output_size = OutputSize(
                width=max(1, int(round(cropped_width * (profile.height_px / cropped_height)))),
                height=profile.height_px,
            )
        else:
            output_size = cropped_size
    elif isinstance(profile, PrintRenderProfile):
        requested = _print_target_dimensions(profile)
        physical_dimensions = PhysicalDimensions(
            width=profile.width,
            height=profile.height,
            units=profile.units,
            ppi=profile.ppi,
        )
        if profile.crop_mode == "fit":
            output_size = _fit_dimensions(
                cropped_width,
                cropped_height,
                requested.width,
                requested.height,
            )
        elif profile.crop_mode == "fill":
            output_size = requested
            perform_fill_crop = True
        else:
            output_size = requested
    else:
        assert isinstance(profile, ArchiveRenderProfile)
        if profile.width_px is not None and profile.height_px is not None:
            output_size = OutputSize(width=profile.width_px, height=profile.height_px)
        elif profile.width_px is not None:
            output_size = OutputSize(
                width=profile.width_px,
                height=max(1, int(round(cropped_height * (profile.width_px / cropped_width)))),
            )
        elif profile.height_px is not None:
            output_size = OutputSize(
                width=max(1, int(round(cropped_width * (profile.height_px / cropped_height)))),
                height=profile.height_px,
            )
        else:
            output_size = cropped_size

    effective_source = (
        _fill_crop_size(cropped_width, cropped_height, output_size.width, output_size.height)
        if perform_fill_crop
        else cropped_size
    )
    enlargement_factor = max(
        output_size.width / effective_source.width,
        output_size.height / effective_source.height,
    )
    enlargement_classification, guidance = _enlargement_classification(enlargement_factor)

    return RenderPlan(
        profile_id=profile.id if hasattr(profile, "id") else "",
        profile_type=profile.type,
        output_size=output_size,
        cropped_source_size=cropped_size,
        crop_box=crop_box,
        interpolation=profile.interpolation,
        enlargement_factor=float(enlargement_factor),
        enlargement_classification=enlargement_classification,
        guidance=guidance,
        physical_dimensions=physical_dimensions,
        perform_fill_crop=perform_fill_crop,
    )


def _manifest_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.name}.manifest.json")


def _ensure_output_path(output_path: Path, force: bool) -> tuple[Path, Path]:
    if output_path.exists() and not force:
        raise RenderInputError("render output already exists; use --force to overwrite it")
    manifest_path = _manifest_path(output_path)
    if manifest_path.exists() and not force:
        raise RenderInputError("render manifest already exists; use --force to overwrite it")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path, manifest_path


def execute_project_image(
    bundle: ProjectBundle,
    *,
    write_debug_masks_dir: Path | None = None,
    use_cached_sources: bool = True,
) -> tuple[SourceImage, Path, CanonicalImage, RuleExecutionResult, PreparedSourcesResult]:
    prepared_sources = inspect_sources(bundle, use_cache=use_cached_sources)
    reference_source = next(
        source
        for source in bundle.project.sources
        if source.id == prepared_sources.reference_source_id
    )
    source_path = resolve_reference_path(bundle.project_dir, reference_source.path)
    canonical = prepared_sources.image
    execution = execute_rule_stack(
        bundle,
        prepared_sources.image.data,
        write_debug_masks_dir=write_debug_masks_dir,
    )
    return reference_source, source_path, canonical, execution, prepared_sources


def render_output(
    project_path: Path,
    *,
    profile_id: str,
    output_path: Path,
    force: bool = False,
    dry_run: bool = False,
    write_debug_masks_dir: Path | None = None,
) -> RenderResult:
    try:
        bundle, report = load_valid_project_bundle(project_path)
    except ValidationRuntimeError:
        raise

    if not report.valid or bundle is None:
        raise RenderInputError("project validation failed")

    profile = _resolve_profile(bundle, profile_id)
    return render_bundle_output(
        bundle,
        profile_id=profile_id,
        profile=profile,
        output_path=output_path,
        force=force,
        dry_run=dry_run,
        write_debug_masks_dir=write_debug_masks_dir,
    )


def render_bundle_output(
    bundle: ProjectBundle,
    *,
    profile_id: str,
    profile: RenderProfileDeclaration,
    output_path: Path,
    force: bool = False,
    dry_run: bool = False,
    write_debug_masks_dir: Path | None = None,
) -> RenderResult:
    output_path, manifest_path = _ensure_output_path(output_path, force)
    source = _reference_source(bundle)
    source_path = resolve_reference_path(bundle.project_dir, source.path)

    if isinstance(profile, ArchiveRenderProfile) and profile.format == "jpeg":
        raise RenderInputError("archive profiles do not support lossy jpeg output")
    if (
        isinstance(profile, ScreenRenderProfile)
        and profile.format == "jpeg"
        and profile.bit_depth != 8
    ):
        raise RenderInputError("jpeg screen renders require 8-bit output")

    metadata = inspect_image(source_path)
    plan = plan_render(
        profile,
        source_width=metadata.width,
        source_height=metadata.height,
        crop=bundle.project.crop,
    )

    if dry_run:
        timestamp = datetime.now(tz=UTC)
        return RenderResult(
            output_path=str(output_path),
            manifest_path=str(manifest_path),
            output_dimensions=plan.output_size,
            cropped_source_dimensions=plan.cropped_source_size,
            profile_id=profile_id,
            profile_type=profile.type,
            color_space=profile.color_space,
            output_format=profile.format,
            bit_depth=profile.bit_depth,
            interpolation=plan.interpolation,
            enlargement_factor=plan.enlargement_factor,
            enlargement_classification=plan.enlargement_classification,
            guidance=plan.guidance,
            physical_dimensions=plan.physical_dimensions,
            declared_rule_ids=[rule.id for rule in bundle.project.rules],
            enabled_rule_ids=[rule.id for rule in bundle.project.rules if rule.enabled],
            applied_rule_ids=[],
            skipped_rules=[],
            execution_trace=[],
            source_path=source.path.as_posix(),
            source_sha256=sha256_file(source_path),
            project_file=str(bundle.project_file),
            project_sha256=sha256_file(bundle.project_file),
            renderer_version=_renderer_version(),
            render_timestamp=timestamp,
            dry_run=True,
        )

    try:
        source_decl, resolved_source_path, canonical, execution, prepared_sources = (
            execute_project_image(
            bundle,
                write_debug_masks_dir=write_debug_masks_dir,
            )
        )
        mastered = CanonicalImage(
            data=execution.image,
            width=canonical.width,
            height=canonical.height,
        )
        cropped = apply_crop(mastered, bundle.project.crop)
        if plan.perform_fill_crop:
            cropped = _center_fill_crop(cropped, plan.output_size.width, plan.output_size.height)
        if cropped.width != plan.output_size.width or cropped.height != plan.output_size.height:
            final_image = resize_exact(
                cropped,
                plan.output_size.width,
                plan.output_size.height,
                method=plan.interpolation,
            )
        else:
            final_image = cropped
        save_image(
            output_path,
            final_image,
            options=SaveImageOptions(
                format=profile.format,
                bit_depth=profile.bit_depth,
                jpeg_quality=profile.jpeg_quality,
            ),
        )
    except (RenderInputError, SourcePreparationError):
        raise
    except Exception as exc:  # pragma: no cover
        raise RenderExecutionError(f"failed to render output: {exc}") from exc

    timestamp = datetime.now(tz=UTC)
    result = RenderResult(
        output_path=str(output_path),
        manifest_path=str(manifest_path),
        output_sha256=sha256_file(output_path),
        output_dimensions=plan.output_size,
        cropped_source_dimensions=plan.cropped_source_size,
        profile_id=profile_id,
        profile_type=profile.type,
        color_space=profile.color_space,
        output_format=profile.format,
        bit_depth=profile.bit_depth,
        interpolation=plan.interpolation,
        enlargement_factor=plan.enlargement_factor,
        enlargement_classification=plan.enlargement_classification,
        guidance=plan.guidance,
        physical_dimensions=plan.physical_dimensions,
        declared_rule_ids=execution.declared_rule_ids,
        enabled_rule_ids=execution.enabled_rule_ids,
        applied_rule_ids=execution.applied_rule_ids,
        skipped_rules=execution.skipped_rules,
        execution_trace=execution.traces,
        source_path=source_decl.path.as_posix(),
        source_sha256=sha256_file(resolved_source_path),
        project_file=str(bundle.project_file),
        project_sha256=sha256_file(bundle.project_file),
        renderer_version=_renderer_version(),
        render_timestamp=timestamp,
    )

    manifest_payload = {
        "project_schema_version": bundle.project.schema_version,
        "project_file_sha256": result.project_sha256,
        "source_file_path": result.source_path,
        "source_file_sha256": result.source_sha256,
        "renderer_version": result.renderer_version,
        "render_profile_id": result.profile_id,
        "render_profile_type": result.profile_type,
        "crop_declaration": bundle.project.crop.model_dump(mode="json"),
        "cropped_source_dimensions": result.cropped_source_dimensions.model_dump(mode="json"),
        "output_dimensions": result.output_dimensions.model_dump(mode="json"),
        "physical_dimensions": (
            result.physical_dimensions.model_dump(mode="json")
            if result.physical_dimensions is not None
            else None
        ),
        "interpolation_method": result.interpolation,
        "enlargement_factor": result.enlargement_factor,
        "enlargement_classification": result.enlargement_classification,
        "color_space": result.color_space,
        "output_format": result.output_format,
        "bit_depth": result.bit_depth,
        "declared_rule_ids": result.declared_rule_ids,
        "enabled_rule_ids": result.enabled_rule_ids,
        "applied_rule_ids": result.applied_rule_ids,
        "skipped_rule_ids": result.skipped_rules,
        "execution_trace": [trace.model_dump(mode="json") for trace in result.execution_trace],
        "declared_source_ids": prepared_sources.declared_source_ids,
        "enabled_source_ids": prepared_sources.enabled_source_ids,
        "reference_source_id": prepared_sources.reference_source_id,
        "source_mix_mode": prepared_sources.source_mix_mode,
        "source_mix_execution_order": prepared_sources.source_order,
        "source_contribution_matrix": prepared_sources.contribution_matrix,
        "source_alignment": [
            report.model_dump(mode="json") for report in prepared_sources.alignment_reports
        ],
        "output_sha256": result.output_sha256,
        "render_timestamp": result.render_timestamp.isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    return result

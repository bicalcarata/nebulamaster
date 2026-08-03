from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from project_io import (
    ProjectPathError,
    YamlFormatError,
    load_model_file,
    load_project_file,
    locate_project_file,
    resolve_reference_path,
)
from project_model import (
    SCHEMA_VERSION,
    BrightnessTransform,
    ChannelContributionSourceMix,
    ColourAmountTransform,
    ColourSmoothingTransform,
    ColourTemperatureTransform,
    DarkNebulaProcessingTransform,
    FauxPaletteTransform,
    LevelsTransform,
    LocalContrastTransform,
    ManualAlignment,
    PaletteFile,
    PluginLockFile,
    ProjectBundle,
    RegionFile,
    RenderProfileFile,
    SaturationTransform,
    ShiftColourPointTransform,
    ToneShapingTransform,
    VibranceTransform,
)
from pydantic import BaseModel, ConfigDict, ValidationError

EXIT_VALIDATION_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_RUNTIME_ERROR = 2
EXIT_INPUT_ERROR = 3
EXIT_RENDER_ERROR = 4


class ValidationRuntimeError(Exception):
    pass


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    file: str | None = None
    location: list[str] = []


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    project_file: str
    issues: list[ValidationIssue]

    @property
    def exit_code(self) -> int:
        return EXIT_VALIDATION_SUCCESS if self.valid else EXIT_VALIDATION_ERROR


def _issue(
    code: str,
    message: str,
    *,
    file: Path | None = None,
    location: tuple[Any, ...] = (),
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        file=str(file) if file is not None else None,
        location=[str(part) for part in location],
    )


def _issues_from_validation_error(
    error: ValidationError,
    *,
    code: str,
    file: Path,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for item in error.errors():
        issues.append(
            _issue(
                code,
                item["msg"],
                file=file,
                location=tuple(item["loc"]),
            )
        )
    return issues


def _validate_referenced_schema_version(
    name: str,
    schema_version: int | None,
    root_schema_version: int,
    file: Path,
) -> list[ValidationIssue]:
    if schema_version is None:
        return []
    if schema_version != root_schema_version:
        return [
            _issue(
                "schema-version-mismatch",
                f"{name} schema version {schema_version} does not match "
                f"project schema version {root_schema_version}",
                file=file,
            )
        ]
    return []


def _load_referenced_model(
    model_type: type[BaseModel],
    project_dir: Path,
    relative_path: Path,
    *,
    code: str,
) -> tuple[BaseModel | None, list[ValidationIssue], Path]:
    resolved = resolve_reference_path(project_dir, relative_path)
    if not resolved.is_file():
        return (
            None,
            [_issue("missing-file", "referenced file does not exist", file=resolved)],
            resolved,
        )

    try:
        model = load_model_file(model_type, resolved)
    except YamlFormatError as exc:
        return None, [_issue("invalid-yaml", str(exc), file=resolved)], resolved
    except ValidationError as exc:
        return None, _issues_from_validation_error(exc, code=code, file=resolved), resolved

    return model, [], resolved


def _collect_unique_ids(items: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        if item in seen:
            duplicates.append(item)
        seen.add(item)
    return duplicates


def _validate_project_cross_references(bundle: ProjectBundle) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    semantic_channel_ids = {channel.id for channel in bundle.project.semantic_channels}
    region_ids = set(bundle.regions)
    colour_point_ids = {
        colour_point.id
        for palette in bundle.palettes.values()
        for colour_point in palette.colour_points
    }

    for rule in bundle.project.rules:
        if rule.target not in semantic_channel_ids:
            issues.append(
                _issue(
                    "unknown-semantic-channel",
                    f"rule target '{rule.target}' does not match a declared semantic channel",
                    file=bundle.project_file,
                    location=("rules", rule.id, "target"),
                )
            )

        if rule.match.colour_point is not None and rule.match.colour_point not in colour_point_ids:
            issues.append(
                _issue(
                    "unknown-colour-point",
                    f"rule colour point '{rule.match.colour_point}' was not found "
                    "in loaded palettes",
                    file=bundle.project_file,
                    location=("rules", rule.id, "match", "colour_point"),
                )
            )

        for region_id in rule.regions:
            if region_id not in region_ids:
                issues.append(
                    _issue(
                        "unknown-region",
                        f"rule region '{region_id}' was not found in loaded regions",
                        file=bundle.project_file,
                        location=("rules", rule.id, "regions"),
                    )
                )

        if isinstance(rule.transform, ShiftColourPointTransform):
            if rule.transform.target_colour_point not in colour_point_ids:
                issues.append(
                    _issue(
                        "unknown-colour-point",
                        f"transform colour point '{rule.transform.target_colour_point}' "
                        "was not found in loaded palettes",
                        file=bundle.project_file,
                        location=("rules", rule.id, "transform", "target_colour_point"),
                    )
                )

        if not isinstance(
            rule.transform,
            (
                ColourAmountTransform,
                ShiftColourPointTransform,
                BrightnessTransform,
                SaturationTransform,
                LevelsTransform,
                ToneShapingTransform,
                LocalContrastTransform,
                VibranceTransform,
                ColourTemperatureTransform,
                ColourSmoothingTransform,
                FauxPaletteTransform,
                DarkNebulaProcessingTransform,
            ),
        ):
            issues.append(
                _issue(
                    "unknown-transformation-type",
                    "rule transform type is not supported",
                    file=bundle.project_file,
                    location=("rules", rule.id, "transform"),
                )
            )

    duplicate_colour_points = _collect_unique_ids(
        [
            colour_point.id
            for palette in bundle.palettes.values()
            for colour_point in palette.colour_points
        ]
    )
    for duplicate in duplicate_colour_points:
        issues.append(
            _issue(
                "duplicate-colour-point",
                f"colour point '{duplicate}' is declared more than once across palettes",
                file=bundle.project_file,
            )
        )

    duplicate_rule_ids = _collect_unique_ids([rule.id for rule in bundle.project.rules])
    for duplicate in duplicate_rule_ids:
        issues.append(
            _issue(
                "duplicate-rule-id",
                f"rule id '{duplicate}' is declared more than once",
                file=bundle.project_file,
            )
        )

    source_ids = [source.id for source in bundle.project.sources]
    duplicate_source_ids = _collect_unique_ids(source_ids)
    for duplicate in duplicate_source_ids:
        issues.append(
            _issue(
                "duplicate-source-id",
                f"source id '{duplicate}' is declared more than once",
                file=bundle.project_file,
            )
        )

    enabled_sources = [source for source in bundle.project.sources if source.enabled]
    if not enabled_sources:
        issues.append(
            _issue(
                "no-enabled-sources",
                "project must contain at least one enabled source",
                file=bundle.project_file,
                location=("sources",),
            )
        )

    enabled_references = [source for source in enabled_sources if source.reference]
    if len(enabled_sources) > 1 and len(enabled_references) != 1:
        issues.append(
            _issue(
                "invalid-reference-source",
                "exactly one reference source is required when multiple sources are enabled",
                file=bundle.project_file,
                location=("sources",),
            )
        )
    if len(enabled_sources) == 1 and len(enabled_references) > 1:
        issues.append(
            _issue(
                "invalid-reference-source",
                "at most one reference source may be declared",
                file=bundle.project_file,
                location=("sources",),
            )
        )

    for source in bundle.project.sources:
        if not math.isfinite(source.weight):
            issues.append(
                _issue(
                    "invalid-source-weight",
                    "source weight must be finite",
                    file=bundle.project_file,
                    location=("sources", source.id, "weight"),
                )
            )
        if isinstance(source.alignment, ManualAlignment):
            if not math.isfinite(source.alignment.x_px):
                issues.append(
                    _issue(
                        "invalid-manual-offset",
                        "manual alignment x offset must be finite",
                        file=bundle.project_file,
                        location=("sources", source.id, "alignment", "x_px"),
                    )
                )
            if not math.isfinite(source.alignment.y_px):
                issues.append(
                    _issue(
                        "invalid-manual-offset",
                        "manual alignment y offset must be finite",
                        file=bundle.project_file,
                        location=("sources", source.id, "alignment", "y_px"),
                    )
                )

    if isinstance(bundle.project.source_mix, ChannelContributionSourceMix):
        contribution_sources = {entry.source for entry in bundle.project.source_mix.contributions}
        source_lookup = {source.id: source for source in bundle.project.sources}
        for contribution in bundle.project.source_mix.contributions:
            if contribution.source not in source_ids:
                issues.append(
                    _issue(
                        "unknown-source",
                        f"source mix contribution source '{contribution.source}' was not found",
                        file=bundle.project_file,
                        location=("source_mix", "contributions", contribution.source),
                    )
                )
            else:
                source = source_lookup[contribution.source]
                values = [
                    contribution.red,
                    contribution.green,
                    contribution.blue,
                ]
                if any(not math.isfinite(value) for value in values):
                    issues.append(
                        _issue(
                            "invalid-source-contribution",
                            (
                                f"source mix contribution for '{contribution.source}' "
                                "must use finite values"
                            ),
                            file=bundle.project_file,
                            location=("source_mix", "contributions", contribution.source),
                        )
                    )
                if not source.enabled and any(value > 0.0 for value in values):
                    issues.append(
                        _issue(
                            "disabled-source-contribution",
                            (
                                f"disabled source '{contribution.source}' "
                                "contributes to the source mix"
                            ),
                            file=bundle.project_file,
                            location=("source_mix", "contributions", contribution.source),
                        )
                    )
        if not contribution_sources:
            issues.append(
                _issue(
                    "empty-source-mix",
                    "source mix must include at least one contribution",
                    file=bundle.project_file,
                    location=("source_mix",),
                )
            )

    return issues


def validate_project(project_path: Path) -> ValidationReport:
    _bundle, report = load_valid_project_bundle(project_path)
    return report


def load_valid_project_bundle(project_path: Path) -> tuple[ProjectBundle | None, ValidationReport]:
    try:
        project_file = locate_project_file(project_path)
    except ProjectPathError as exc:
        raise ValidationRuntimeError(str(exc)) from exc

    try:
        project = load_project_file(project_file)
    except YamlFormatError as exc:
        raise ValidationRuntimeError(str(exc)) from exc
    except ValidationError as exc:
        validation_issues = _issues_from_validation_error(
            exc,
            code="project-schema",
            file=project_file,
        )
        return None, ValidationReport(
            valid=False,
            project_file=str(project_file),
            issues=validation_issues,
        )

    issues: list[ValidationIssue] = []
    project_dir = project_file.parent
    bundle = ProjectBundle(project_dir=project_dir, project_file=project_file, project=project)

    if project.schema_version != SCHEMA_VERSION:
        issues.append(
            _issue(
                "unsupported-schema-version",
                f"unsupported schema version: {project.schema_version}",
                file=project_file,
                location=("schema_version",),
            )
        )

    for source in project.sources:
        source_path = resolve_reference_path(project_dir, source.path)
        if not source_path.is_file():
            issues.append(
                _issue(
                    "missing-source-image",
                    f"source image '{source.id}' does not exist at {source.path}",
                    file=project_file,
                    location=("sources", source.id, "path"),
                )
            )

    for palette_ref in project.palettes:
        palette, palette_issues, palette_path = _load_referenced_model(
            PaletteFile,
            project_dir,
            palette_ref.path,
            code="palette-schema",
        )
        issues.extend(palette_issues)
        if isinstance(palette, PaletteFile):
            if palette.id != palette_ref.id:
                issues.append(
                    _issue(
                        "reference-id-mismatch",
                        f"palette reference id '{palette_ref.id}' does not match "
                        f"file id '{palette.id}'",
                        file=palette_path,
                    )
                )
            issues.extend(
                _validate_referenced_schema_version(
                    "palette",
                    palette.schema_version,
                    project.schema_version,
                    palette_path,
                )
            )
            bundle.palettes[palette.id] = palette

    for region_ref in project.regions:
        region, region_issues, region_path = _load_referenced_model(
            RegionFile,
            project_dir,
            region_ref.path,
            code="region-schema",
        )
        issues.extend(region_issues)
        if isinstance(region, RegionFile):
            if region.id != region_ref.id:
                issues.append(
                    _issue(
                        "reference-id-mismatch",
                        f"region reference id '{region_ref.id}' does not match "
                        f"file id '{region.id}'",
                        file=region_path,
                    )
                )
            issues.extend(
                _validate_referenced_schema_version(
                    "region",
                    region.schema_version,
                    project.schema_version,
                    region_path,
                )
            )
            bundle.regions[region.id] = region

    for render_profile_ref in project.render_profiles:
        render_profile, profile_issues, render_profile_path = _load_referenced_model(
            RenderProfileFile,
            project_dir,
            render_profile_ref.path,
            code="render-profile-schema",
        )
        issues.extend(profile_issues)
        if isinstance(render_profile, RenderProfileFile):
            if render_profile.id != render_profile_ref.id:
                issues.append(
                    _issue(
                        "reference-id-mismatch",
                        f"render profile reference id '{render_profile_ref.id}' "
                        f"does not match file id '{render_profile.id}'",
                        file=render_profile_path,
                    )
                )
            issues.extend(
                _validate_referenced_schema_version(
                    "render profile",
                    render_profile.schema_version,
                    project.schema_version,
                    render_profile_path,
                )
            )
            bundle.render_profiles[render_profile.id] = render_profile

    plugin_lock, plugin_issues, plugin_lock_path = _load_referenced_model(
        PluginLockFile,
        project_dir,
        project.plugins.path,
        code="plugin-lock-schema",
    )
    issues.extend(plugin_issues)
    if isinstance(plugin_lock, PluginLockFile):
        issues.extend(
            _validate_referenced_schema_version(
                "plugin lock",
                plugin_lock.schema_version,
                project.schema_version,
                plugin_lock_path,
            )
        )
        bundle.plugin_lock = plugin_lock

    issues.extend(_validate_project_cross_references(bundle))

    report = ValidationReport(valid=not issues, project_file=str(project_file), issues=issues)
    if report.valid:
        return bundle, report
    return None, report

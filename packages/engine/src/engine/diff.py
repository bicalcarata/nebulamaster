from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from project_model import (
    FAUX_PALETTE_COLOUR_BALANCE_LABELS,
    BrightnessTransform,
    ColourAmountTransform,
    ColourPoint,
    ColourSmoothingTransform,
    ColourTemperatureTransform,
    DarkNebulaProcessingTransform,
    DeclarativeRule,
    DiffExplanationEntry,
    DiffProjectIdentity,
    FauxPaletteTransform,
    LevelsTransform,
    LocalContrastTransform,
    PluginLockEntry,
    ProjectBundle,
    ProjectDiffChange,
    ProjectDiffDocument,
    ProjectDiffSummary,
    RangeSelection,
    RuleReorderChange,
    SaturationTransform,
    ShiftColourPointTransform,
    SourceImage,
    ToneShapingTransform,
    VibranceTransform,
)

from .validation import ValidationReport, load_valid_project_bundle

ChangeLists = tuple[
    list[ProjectDiffChange],
    list[ProjectDiffChange],
    list[ProjectDiffChange],
]
RuleChangeLists = tuple[
    list[ProjectDiffChange],
    list[ProjectDiffChange],
    list[ProjectDiffChange],
    list[RuleReorderChange],
]


class ProjectDiffValidationError(Exception):
    def __init__(self, report_a: ValidationReport, report_b: ValidationReport) -> None:
        self.report_a = report_a
        self.report_b = report_b
        super().__init__("project validation failed before comparison")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_project_identity(bundle: ProjectBundle) -> DiffProjectIdentity:
    return DiffProjectIdentity(
        project_file=bundle.project_file,
        project_id=bundle.project.project.id,
        project_name=bundle.project.project.name,
        schema_version=bundle.project.schema_version,
        project_file_sha256=_file_sha256(bundle.project_file),
    )


def _change(
    code: str,
    entity_type: str,
    *,
    entity_id: str | None = None,
    entity_name: str | None = None,
    old_value: Any | None = None,
    new_value: Any | None = None,
    significance: list[str],
    human_summary: str,
    technical_path: str | None = None,
) -> ProjectDiffChange:
    return ProjectDiffChange(
        code=code,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        old_value=old_value,
        new_value=new_value,
        significance=cast(list[Any], significance),
        human_summary=human_summary,
        technical_path=technical_path,
    )


def _rule_reorder(
    rule: DeclarativeRule,
    old_position: int,
    new_position: int,
    *,
    previous_rule_name: str | None = None,
) -> RuleReorderChange:
    if previous_rule_name is not None:
        summary = f"The {rule.name} step now runs before {previous_rule_name}."
    else:
        summary = f"The {rule.name} step moved from position {old_position} to {new_position}."
    return RuleReorderChange(
        entity_id=rule.id,
        entity_name=rule.name,
        old_position=old_position,
        new_position=new_position,
        human_summary=summary,
        technical_path=f"rules[{new_position - 1}]",
    )


def _flatten_colour_points(bundle: ProjectBundle) -> dict[str, tuple[ColourPoint, str]]:
    flattened: dict[str, tuple[ColourPoint, str]] = {}
    for palette in bundle.palettes.values():
        for colour_point in palette.colour_points:
            flattened[colour_point.id] = (colour_point, palette.id)
    return flattened


def _range_payload(selection: RangeSelection | None) -> dict[str, float] | None:
    if selection is None:
        return None
    return {"min": selection.min, "max": selection.max}


def _source_payload(bundle: ProjectBundle, source: SourceImage) -> dict[str, Any]:
    source_path = (bundle.project_dir / source.path).resolve()
    actual_sha256 = _file_sha256(source_path) if source_path.is_file() else None
    return {
        "path": str(source.path),
        "name": source.name,
        "role": source.role,
        "reference": source.reference,
        "enabled": source.enabled,
        "weight": source.weight,
        "alignment": (
            source.alignment.model_dump(mode="json") if source.alignment is not None else None
        ),
        "declared_checksum": source.checksum,
        "actual_sha256": actual_sha256,
    }


def _rule_payload(rule: DeclarativeRule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "enabled": rule.enabled,
        "selection_source": rule.selection_source,
        "target": rule.target,
        "regions": list(rule.regions),
        "match": rule.match.model_dump(mode="json"),
        "transform": rule.transform.model_dump(mode="json"),
    }


def _polygon_area(polygon: list[tuple[float, float]]) -> float:
    area = 0.0
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) / 2.0


def _approx_equal(a: float, b: float, *, epsilon: float = 1e-6) -> bool:
    return abs(a - b) <= epsilon


def _crop_enabled(profile: Any) -> bool:
    crop = getattr(profile.profile, "crop", None)
    return bool(crop is not None and crop.enabled and not crop.is_full_frame())


def _crop_label(profile: Any) -> str:
    crop = getattr(profile.profile, "crop", None)
    if crop is None or not crop.enabled or crop.is_full_frame():
        return "Full Frame"
    aspect_ratio = crop.aspect_ratio or "custom"
    return "Original" if aspect_ratio == "original" else str(aspect_ratio)


def _crop_payload(profile: Any) -> dict[str, Any] | None:
    crop = getattr(profile.profile, "crop", None)
    if crop is None or not crop.enabled or crop.is_full_frame():
        return None
    return cast(dict[str, Any], crop.model_dump(mode="json"))


def _render_profile_dimensions(profile: Any) -> str | None:
    declaration = profile.profile
    if hasattr(declaration, "width_px") or hasattr(declaration, "height_px"):
        width = getattr(declaration, "width_px", None)
        height = getattr(declaration, "height_px", None)
        if width is not None and height is not None:
            return f"{width} x {height}"
    if hasattr(declaration, "width") and hasattr(declaration, "height"):
        width = getattr(declaration, "width", None)
        height = getattr(declaration, "height", None)
        units = getattr(declaration, "units", None)
        if width is not None and height is not None and units is not None:
            return f"{width:g} x {height:g} {units}"
    return None


def _dominant_colour_name(channels: tuple[float, float, float]) -> str:
    red, green, blue = channels
    saturation = max(channels) - min(channels)
    if saturation < 0.08:
        return "grey"
    if blue >= red and blue >= green:
        if green - red > 0.12:
            return "cyan"
        return "blue"
    if red >= green and red >= blue:
        if green - blue > 0.12:
            return "orange"
        return "red"
    if blue - red > 0.12:
        return "teal"
    return "green"


def _describe_colour_movement(
    old_channels: tuple[float, float, float],
    new_channels: tuple[float, float, float],
) -> str:
    old_saturation = max(old_channels) - min(old_channels)
    new_saturation = max(new_channels) - min(new_channels)
    old_brightness = sum(old_channels) / 3.0
    new_brightness = sum(new_channels) / 3.0

    if new_saturation < old_saturation - 0.12:
        return "towards less saturated grey"

    brightness_text = ""
    if new_brightness > old_brightness + 0.05:
        brightness_text = "brighter "
    elif new_brightness < old_brightness - 0.05:
        brightness_text = "darker "

    return f"towards {brightness_text}{_dominant_colour_name(new_channels)}".strip()


def _percentage_amount(value: float) -> str:
    return f"{round((value - 1.0) * 100)}%"


def _colour_amount_transform_summary(
    name: str,
    old_transform: ColourAmountTransform,
    new_transform: ColourAmountTransform,
) -> str:
    family_label = new_transform.channel.replace("_", " ").title()
    if old_transform.amount != new_transform.amount:
        return (
            f"The {name} rule was changed from "
            f"{_percentage_amount(old_transform.amount)} to "
            f"{_percentage_amount(new_transform.amount)}."
        )
    if old_transform.faint_colour_sensitivity != new_transform.faint_colour_sensitivity:
        return (
            f"Changed {family_label} Faint Colour Sensitivity from "
            f"{_unit_percentage(old_transform.faint_colour_sensitivity)} to "
            f"{_unit_percentage(new_transform.faint_colour_sensitivity)}."
        )
    if old_transform.faint_range != new_transform.faint_range:
        return (
            f"Changed {family_label} Faint Range from "
            f"{_unit_percentage(old_transform.faint_range)} to "
            f"{_unit_percentage(new_transform.faint_range)}."
        )
    if old_transform.structure_size != new_transform.structure_size:
        return (
            f"Changed {family_label} Structure Size from "
            f"{old_transform.structure_size.replace('_', ' ').title()} to "
            f"{new_transform.structure_size.replace('_', ' ').title()}."
        )
    if old_transform.reveal_faint_colour != new_transform.reveal_faint_colour:
        return (
            f"Changed Reveal Faint {family_label} from "
            f"{_unit_percentage(old_transform.reveal_faint_colour)} to "
            f"{_unit_percentage(new_transform.reveal_faint_colour)}."
        )
    if old_transform.bright_colour_protection != new_transform.bright_colour_protection:
        return (
            f"Changed Bright {family_label} Protection from "
            f"{_unit_percentage(old_transform.bright_colour_protection)} to "
            f"{_unit_percentage(new_transform.bright_colour_protection)}."
        )
    if old_transform.highlight_protection != new_transform.highlight_protection:
        return (
            f"Changed {family_label} Highlight Protection from "
            f"{_unit_percentage(old_transform.highlight_protection)} to "
            f"{_unit_percentage(new_transform.highlight_protection)}."
        )
    if old_transform.extended_range != new_transform.extended_range:
        state = "enabled" if new_transform.extended_range else "disabled"
        return f"{family_label} Extended Range was {state}."
    if old_transform.response_version != new_transform.response_version:
        return f"{family_label} colour response was updated."
    return f"{name} colour controls changed."


def _faux_palette_percentage(value: float) -> str:
    return f"{round(value * 100)}%"


def _unit_percentage(value: float) -> str:
    return f"{round(value * 100)}%"


def _faux_palette_name(palette: str) -> str:
    return {
        "hubble": "Faux Hubble",
        "hoo": "Faux HOO",
        "foraxx": "Foraxx-Inspired",
        "gold_cyan": "Gold & Cyan",
        "natural_bicolour": "Natural Bi-colour",
    }.get(palette, palette.replace("_", " ").title())


def _faux_palette_balance_summary(
    name: str,
    old_transform: FauxPaletteTransform,
    new_transform: FauxPaletteTransform,
) -> str | None:
    if old_transform.palette != new_transform.palette:
        return None
    old_balance = old_transform.supported_colour_balance()
    new_balance = new_transform.supported_colour_balance()
    changed_keys = [
        key
        for key in old_balance
        if old_balance.get(key) != new_balance.get(key)
    ]
    if not changed_keys:
        return None
    fragments = [
        (
            f"{FAUX_PALETTE_COLOUR_BALANCE_LABELS[key]} "
            f"from {round(old_balance[key])}% to {round(new_balance[key])}%"
        )
        for key in changed_keys
    ]
    if len(fragments) == 1:
        details = fragments[0]
    else:
        details = ", ".join(fragments[:-1]) + f" and {fragments[-1]}"
    return f"Changed {name} colour balance: {details}."


def _format_range_summary(
    name: str,
    old_value: RangeSelection | None,
    new_value: RangeSelection | None,
) -> str:
    if old_value is None and new_value is not None:
        return f"{name} filtering was added."
    if old_value is not None and new_value is None:
        return f"{name} filtering was removed."
    assert old_value is not None and new_value is not None
    old_width = old_value.max - old_value.min
    new_width = new_value.max - new_value.min
    if new_width > old_width:
        return f"{name} selection was widened."
    if new_width < old_width:
        return f"{name} selection was narrowed."
    return f"{name} selection bounds changed."


def _target_display_name(target: str) -> str:
    return target.replace("_", " ").title()


def _added_removed_changes(
    entity_type: str,
    code_added: str,
    code_removed: str,
    items_a: dict[str, Any],
    items_b: dict[str, Any],
    name_getter: Callable[[Any], str | None],
    payload_getter: Callable[[Any], Any],
    significance: list[str],
) -> tuple[list[ProjectDiffChange], list[ProjectDiffChange]]:
    added: list[ProjectDiffChange] = []
    removed: list[ProjectDiffChange] = []

    for entity_id in [key for key in items_b if key not in items_a]:
        item = items_b[entity_id]
        entity_name = name_getter(item)
        added.append(
            _change(
                code_added,
                entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                new_value=payload_getter(item),
                significance=significance,
                human_summary=f"{entity_name or entity_id} was added.",
                technical_path=f"{entity_type}s.{entity_id}",
            )
        )

    for entity_id in [key for key in items_a if key not in items_b]:
        item = items_a[entity_id]
        entity_name = name_getter(item)
        removed.append(
            _change(
                code_removed,
                entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                old_value=payload_getter(item),
                significance=significance,
                human_summary=f"{entity_name or entity_id} was removed.",
                technical_path=f"{entity_type}s.{entity_id}",
            )
        )

    return added, removed


def _compare_semantic_channels(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    channels_a = {channel.id: channel for channel in bundle_a.project.semantic_channels}
    channels_b = {channel.id: channel for channel in bundle_b.project.semantic_channels}
    added, removed = _added_removed_changes(
        "semantic_channel",
        "semantic_channel.added",
        "semantic_channel.removed",
        channels_a,
        channels_b,
        lambda item: item.name,
        lambda item: item.model_dump(mode="json"),
        ["structural"],
    )
    modified: list[ProjectDiffChange] = []
    for channel_id in [key for key in channels_a if key in channels_b]:
        channel_a = channels_a[channel_id]
        channel_b = channels_b[channel_id]
        if channel_a.model_dump(mode="json") != channel_b.model_dump(mode="json"):
            modified.append(
                _change(
                    "semantic_channel.changed",
                    "semantic_channel",
                    entity_id=channel_id,
                    entity_name=channel_b.name,
                    old_value=channel_a.model_dump(mode="json"),
                    new_value=channel_b.model_dump(mode="json"),
                    significance=["structural"],
                    human_summary=f"Semantic channel {channel_b.name} changed.",
                    technical_path=f"semantic_channels.{channel_id}",
                )
            )
    return added, removed, modified


def _compare_project_metadata(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> list[ProjectDiffChange]:
    changes: list[ProjectDiffChange] = []
    meta_a = bundle_a.project.project
    meta_b = bundle_b.project.project

    if meta_a.name != meta_b.name:
        changes.append(
            _change(
                "project.name_changed",
                "project",
                entity_id=meta_a.id,
                entity_name=meta_b.name,
                old_value=meta_a.name,
                new_value=meta_b.name,
                significance=["informational"],
                human_summary=f"Project title changed from {meta_a.name} to {meta_b.name}.",
                technical_path="project.name",
            )
        )

    if bundle_a.project.schema_version != bundle_b.project.schema_version:
        changes.append(
            _change(
                "project.schema_version_changed",
                "project",
                entity_id=meta_a.id,
                entity_name=meta_b.name,
                old_value=bundle_a.project.schema_version,
                new_value=bundle_b.project.schema_version,
                significance=["compatibility"],
                human_summary=(
                    f"Project schema version changed from {bundle_a.project.schema_version} "
                    f"to {bundle_b.project.schema_version}."
                ),
                technical_path="schema_version",
            )
        )

    dark_dust_a = bundle_a.project.dark_dust.model_dump(mode="json")
    dark_dust_b = bundle_b.project.dark_dust.model_dump(mode="json")
    if dark_dust_a != dark_dust_b:
        changes.append(
            _change(
                "project.dark_dust_changed",
                "project",
                entity_id=meta_a.id,
                entity_name=meta_b.name,
                old_value=dark_dust_a,
                new_value=dark_dust_b,
                significance=["visual", "structural"],
                human_summary="Dark Dust detection settings changed.",
                technical_path="dark_dust",
            )
        )

    return changes


def _compare_sources(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    sources_a = {source.id: source for source in bundle_a.project.sources}
    sources_b = {source.id: source for source in bundle_b.project.sources}
    added, removed = _added_removed_changes(
        "source",
        "source.added",
        "source.removed",
        sources_a,
        sources_b,
        lambda item: item.id,
        lambda item: _source_payload(bundle_b if item.id in sources_b else bundle_a, item),
        ["structural", "visual"],
    )

    modified: list[ProjectDiffChange] = []
    for source_id in [key for key in sources_a if key in sources_b]:
        source_a = sources_a[source_id]
        source_b = sources_b[source_id]
        payload_a = _source_payload(bundle_a, source_a)
        payload_b = _source_payload(bundle_b, source_b)
        if payload_a != payload_b:
            if payload_a["reference"] != payload_b["reference"]:
                summary = f"The {source_b.name} source is now used as the alignment reference."
                code = "source.reference_changed"
            elif payload_a["weight"] != payload_b["weight"]:
                direction = (
                    "more strongly"
                    if payload_b["weight"] > payload_a["weight"]
                    else "less strongly"
                )
                summary = f"The {source_b.role.capitalize()} source now contributes {direction}."
                code = "source.weight_changed"
            elif payload_a["role"] != payload_b["role"]:
                summary = (
                    f"Source {source_b.name} role changed from "
                    f"{payload_a['role']} to {payload_b['role']}."
                )
                code = "source.role_changed"
            elif payload_a["alignment"] != payload_b["alignment"]:
                summary = f"The {source_b.name} source alignment changed."
                code = "source.alignment_changed"
            elif payload_a["path"] != payload_b["path"]:
                summary = (
                    f"Source {source_id} now points to {payload_b['path']} "
                    f"instead of {payload_a['path']}."
                )
                code = "source.changed"
            else:
                summary = f"Source {source_id} declaration changed."
                code = "source.changed"
            modified.append(
                _change(
                    code,
                    "source",
                    entity_id=source_id,
                    entity_name=source_b.name,
                    old_value=payload_a,
                    new_value=payload_b,
                    significance=["structural", "visual"],
                    human_summary=summary,
                    technical_path=f"sources.{source_id}",
                )
            )
    return added, removed, modified


def _compare_source_mix(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> list[ProjectDiffChange]:
    mix_a = bundle_a.project.source_mix.model_dump(mode="json")
    mix_b = bundle_b.project.source_mix.model_dump(mode="json")
    if mix_a == mix_b:
        return []

    if mix_a["mode"] != mix_b["mode"]:
        summary = (
            f"The source mix changed from {mix_a['mode'].replace('_', ' ')} "
            f"to {mix_b['mode'].replace('_', ' ')}."
        )
        code = "source_mix.mode_changed"
    else:
        summary = "The source mix contribution settings changed."
        code = "source_mix.contribution_changed"

    return [
        _change(
            code,
            "source_mix",
            entity_id="source-mix",
            entity_name="Source Mix",
            old_value=mix_a,
            new_value=mix_b,
            significance=["visual", "structural"],
            human_summary=summary,
            technical_path="source_mix",
        )
    ]


def _compare_colour_points(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    colour_points_a = _flatten_colour_points(bundle_a)
    colour_points_b = _flatten_colour_points(bundle_b)
    added, removed = _added_removed_changes(
        "colour_point",
        "colour_point.added",
        "colour_point.removed",
        colour_points_a,
        colour_points_b,
        lambda item: item[0].name,
        lambda item: item[0].model_dump(mode="json"),
        ["visual"],
    )

    modified: list[ProjectDiffChange] = []
    for colour_point_id in [key for key in colour_points_a if key in colour_points_b]:
        colour_point_a, _palette_a = colour_points_a[colour_point_id]
        colour_point_b, _palette_b = colour_points_b[colour_point_id]
        if colour_point_a.value.channels != colour_point_b.value.channels:
            direction = _describe_colour_movement(
                colour_point_a.value.channels,
                colour_point_b.value.channels,
            )
            modified.append(
                _change(
                    "colour_point.moved",
                    "colour_point",
                    entity_id=colour_point_id,
                    entity_name=colour_point_b.name,
                    old_value=colour_point_a.model_dump(mode="json"),
                    new_value=colour_point_b.model_dump(mode="json"),
                    significance=["visual"],
                    human_summary=(
                        f"More {_dominant_colour_name(colour_point_b.value.channels)} "
                        "will be included "
                        f"because the {colour_point_b.name} was moved {direction}."
                    ),
                    technical_path=f"palettes.*.colour_points.{colour_point_id}.value.channels",
                )
            )
        elif colour_point_a.name != colour_point_b.name:
            modified.append(
                _change(
                    "colour_point.renamed",
                    "colour_point",
                    entity_id=colour_point_id,
                    entity_name=colour_point_b.name,
                    old_value=colour_point_a.name,
                    new_value=colour_point_b.name,
                    significance=["informational"],
                    human_summary=(
                        f"Colour point {colour_point_a.name} was renamed to {colour_point_b.name}."
                    ),
                    technical_path=f"palettes.*.colour_points.{colour_point_id}.name",
                )
            )
    return added, removed, modified


def _compare_regions(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    regions_a = bundle_a.regions
    regions_b = bundle_b.regions
    added, removed = _added_removed_changes(
        "region",
        "region.added",
        "region.removed",
        regions_a,
        regions_b,
        lambda item: item.name,
        lambda item: item.model_dump(mode="json"),
        ["structural", "visual"],
    )

    modified: list[ProjectDiffChange] = []
    for region_id in [key for key in regions_a if key in regions_b]:
        region_a = regions_a[region_id]
        region_b = regions_b[region_id]
        if region_a.polygon != region_b.polygon:
            area_a = _polygon_area(region_a.polygon)
            area_b = _polygon_area(region_b.polygon)
            if area_b > area_a:
                summary = f"The {region_b.name} region was enlarged."
            elif area_b < area_a:
                summary = f"The {region_b.name} region was reduced."
            else:
                summary = f"The {region_b.name} region shape changed."
            modified.append(
                _change(
                    "region.geometry_changed",
                    "region",
                    entity_id=region_id,
                    entity_name=region_b.name,
                    old_value={"polygon": region_a.polygon},
                    new_value={"polygon": region_b.polygon},
                    significance=["visual", "structural"],
                    human_summary=summary,
                    technical_path=f"regions.{region_id}.polygon",
                )
            )
        feather_a = region_a.feather.radius if region_a.feather is not None else 0.0
        feather_b = region_b.feather.radius if region_b.feather is not None else 0.0
        if not _approx_equal(feather_a, feather_b):
            summary = (
                f"The {region_b.name} region feather changed from {round(feather_a * 100)}% "
                f"to {round(feather_b * 100)}% of the shorter edge."
            )
            modified.append(
                _change(
                    "region.feather_changed",
                    "region",
                    entity_id=region_id,
                    entity_name=region_b.name,
                    old_value=feather_a,
                    new_value=feather_b,
                    significance=["visual"],
                    human_summary=summary,
                    technical_path=f"regions.{region_id}.feather.radius",
                )
            )
    return added, removed, modified


def _compare_rules(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> RuleChangeLists:
    rules_a = {rule.id: rule for rule in bundle_a.project.rules}
    rules_b = {rule.id: rule for rule in bundle_b.project.rules}
    added, removed = _added_removed_changes(
        "rule",
        "rule.added",
        "rule.removed",
        rules_a,
        rules_b,
        lambda item: item.name,
        lambda item: _rule_payload(item),
        ["structural", "visual"],
    )

    modified: list[ProjectDiffChange] = []
    reordered: list[RuleReorderChange] = []
    common_rule_ids = [rule.id for rule in bundle_a.project.rules if rule.id in rules_b]

    positions_a = {rule.id: index for index, rule in enumerate(bundle_a.project.rules, start=1)}
    positions_b = {rule.id: index for index, rule in enumerate(bundle_b.project.rules, start=1)}

    for rule_id in common_rule_ids:
        rule_a = rules_a[rule_id]
        rule_b = rules_b[rule_id]

        if rule_a.enabled != rule_b.enabled:
            enabled = rule_b.enabled
            modified.append(
                _change(
                    "rule.enabled" if enabled else "rule.disabled",
                    "rule",
                    entity_id=rule_id,
                    entity_name=rule_b.name,
                    old_value=rule_a.enabled,
                    new_value=rule_b.enabled,
                    significance=["visual"],
                    human_summary=f"{rule_b.name} was {'enabled' if enabled else 'disabled'}.",
                    technical_path=f"rules.{rule_id}.enabled",
                )
            )

        if rule_a.selection_source != rule_b.selection_source:
            modified.append(
                _change(
                    "rule.selection_source_changed",
                    "rule",
                    entity_id=rule_id,
                    entity_name=rule_b.name,
                    old_value=rule_a.selection_source,
                    new_value=rule_b.selection_source,
                    significance=["visual", "structural"],
                    human_summary=(
                        f"{rule_b.name} now selects pixels from the "
                        f"{rule_b.selection_source} image "
                        f"instead of the {rule_a.selection_source} image."
                    ),
                    technical_path=f"rules.{rule_id}.selection_source",
                )
            )

        if rule_a.target != rule_b.target:
            modified.append(
                _change(
                    "rule.target_changed",
                    "rule",
                    entity_id=rule_id,
                    entity_name=rule_b.name,
                    old_value=rule_a.target,
                    new_value=rule_b.target,
                    significance=["visual", "structural"],
                    human_summary=(
                        f"{rule_b.name} now affects {_target_display_name(rule_b.target)} "
                        f"instead of {_target_display_name(rule_a.target)}."
                    ),
                    technical_path=f"rules.{rule_id}.target",
                )
            )

        match_a = rule_a.match.model_dump(mode="json")
        match_b = rule_b.match.model_dump(mode="json")
        if match_a != match_b or rule_a.regions != rule_b.regions:
            if rule_a.match.colour_range != rule_b.match.colour_range:
                summary = (
                    f"{rule_b.name} colour selection changed from "
                    f"{rule_a.match.colour_range:.2f} to {rule_b.match.colour_range:.2f}."
                )
                code = "colour_point.range_changed"
            elif rule_a.match.brightness != rule_b.match.brightness:
                summary = _format_range_summary(
                    "Brightness",
                    rule_a.match.brightness,
                    rule_b.match.brightness,
                )
                code = "rule.match_changed"
            elif rule_a.match.softness != rule_b.match.softness:
                direction = (
                    "softened" if rule_b.match.softness > rule_a.match.softness else "strengthened"
                )
                summary = f"{rule_b.name} selection was {direction}."
                code = "rule.match_changed"
            elif rule_a.regions != rule_b.regions:
                summary = f"{rule_b.name} now targets different regions."
                code = "rule.match_changed"
            else:
                summary = f"{rule_b.name} match settings changed."
                code = "rule.match_changed"
            modified.append(
                _change(
                    code,
                    "rule",
                    entity_id=rule_id,
                    entity_name=rule_b.name,
                    old_value={
                        "match": match_a,
                        "regions": list(rule_a.regions),
                    },
                    new_value={
                        "match": match_b,
                        "regions": list(rule_b.regions),
                    },
                    significance=["visual"],
                    human_summary=summary,
                    technical_path=f"rules.{rule_id}.match",
                )
            )

        transform_a = rule_a.transform.model_dump(mode="json")
        transform_b = rule_b.transform.model_dump(mode="json")
        if transform_a != transform_b:
            if (
                isinstance(rule_a.transform, ColourAmountTransform)
                and isinstance(rule_b.transform, ColourAmountTransform)
                and rule_a.transform.channel == rule_b.transform.channel
            ):
                summary = _colour_amount_transform_summary(
                    rule_b.name or rule_b.id,
                    rule_a.transform,
                    rule_b.transform,
                )
            elif isinstance(rule_a.transform, ShiftColourPointTransform) and isinstance(
                rule_b.transform, ShiftColourPointTransform
            ):
                summary = f"The {rule_b.name} colour shift changed."
            elif isinstance(rule_a.transform, BrightnessTransform) and isinstance(
                rule_b.transform, BrightnessTransform
            ):
                direction = (
                    "increased" if rule_b.transform.amount > rule_a.transform.amount else "reduced"
                )
                summary = f"{rule_b.name} brightness was {direction}."
            elif isinstance(rule_a.transform, SaturationTransform) and isinstance(
                rule_b.transform, SaturationTransform
            ):
                direction = (
                    "increased" if rule_b.transform.amount > rule_a.transform.amount else "reduced"
                )
                summary = f"{rule_b.name} saturation was {direction}."
            elif isinstance(rule_a.transform, LevelsTransform) and isinstance(
                rule_b.transform, LevelsTransform
            ):
                summary = f"{rule_b.name} levels changed."
            elif isinstance(rule_a.transform, ToneShapingTransform) and isinstance(
                rule_b.transform, ToneShapingTransform
            ):
                if rule_a.transform.shadows != rule_b.transform.shadows:
                    summary = (
                        f"Changed Tone Shaping Shadows from "
                        f"{_unit_percentage(rule_a.transform.shadows)} to "
                        f"{_unit_percentage(rule_b.transform.shadows)}."
                    )
                elif rule_a.transform.midtones != rule_b.transform.midtones:
                    summary = (
                        f"Changed Tone Shaping Midtones from "
                        f"{_unit_percentage(rule_a.transform.midtones)} to "
                        f"{_unit_percentage(rule_b.transform.midtones)}."
                    )
                elif rule_a.transform.highlights != rule_b.transform.highlights:
                    summary = (
                        f"Changed Tone Shaping Highlights from "
                        f"{_unit_percentage(rule_a.transform.highlights)} to "
                        f"{_unit_percentage(rule_b.transform.highlights)}."
                    )
                elif rule_a.transform.contrast != rule_b.transform.contrast:
                    summary = (
                        f"Changed Tone Shaping Contrast from "
                        f"{_unit_percentage(rule_a.transform.contrast)} to "
                        f"{_unit_percentage(rule_b.transform.contrast)}."
                    )
                elif (
                    rule_a.transform.black_protection
                    != rule_b.transform.black_protection
                ):
                    summary = (
                        f"Changed Tone Shaping Black Protection from "
                        f"{_unit_percentage(rule_a.transform.black_protection)} to "
                        f"{_unit_percentage(rule_b.transform.black_protection)}."
                    )
                elif (
                    rule_a.transform.highlight_protection
                    != rule_b.transform.highlight_protection
                ):
                    summary = (
                        f"Changed Tone Shaping Highlight Protection from "
                        f"{_unit_percentage(rule_a.transform.highlight_protection)} to "
                        f"{_unit_percentage(rule_b.transform.highlight_protection)}."
                    )
                else:
                    summary = "Tone Shaping changed."
            elif isinstance(rule_a.transform, LocalContrastTransform) and isinstance(
                rule_b.transform, LocalContrastTransform
            ):
                if rule_a.transform.amount != rule_b.transform.amount:
                    summary = (
                        f"Changed Local Contrast Amount from "
                        f"{_unit_percentage(rule_a.transform.amount)} to "
                        f"{_unit_percentage(rule_b.transform.amount)}."
                    )
                elif rule_a.transform.structure_size != rule_b.transform.structure_size:
                    summary = (
                        f"Changed Local Contrast Structure Size from "
                        f"{rule_a.transform.structure_size.replace('_', ' ').title()} to "
                        f"{rule_b.transform.structure_size.replace('_', ' ').title()}."
                    )
                elif (
                    rule_a.transform.background_protection
                    != rule_b.transform.background_protection
                ):
                    summary = (
                        f"Changed Local Contrast Background Protection from "
                        f"{_unit_percentage(rule_a.transform.background_protection)} to "
                        f"{_unit_percentage(rule_b.transform.background_protection)}."
                    )
                elif (
                    rule_a.transform.highlight_protection
                    != rule_b.transform.highlight_protection
                ):
                    summary = (
                        f"Changed Local Contrast Highlight Protection from "
                        f"{_unit_percentage(rule_a.transform.highlight_protection)} to "
                        f"{_unit_percentage(rule_b.transform.highlight_protection)}."
                    )
                elif rule_a.transform.softness != rule_b.transform.softness:
                    summary = (
                        f"Changed Local Contrast Softness from "
                        f"{_unit_percentage(rule_a.transform.softness)} to "
                        f"{_unit_percentage(rule_b.transform.softness)}."
                    )
                else:
                    summary = "Local Contrast changed."
            elif isinstance(rule_a.transform, VibranceTransform) and isinstance(
                rule_b.transform, VibranceTransform
            ):
                if rule_a.transform.amount != rule_b.transform.amount:
                    summary = (
                        f"Changed Vibrance Amount from "
                        f"{_unit_percentage(rule_a.transform.amount)} to "
                        f"{_unit_percentage(rule_b.transform.amount)}."
                    )
                elif (
                    rule_a.transform.protect_strong_colours
                    != rule_b.transform.protect_strong_colours
                ):
                    summary = (
                        f"Changed Protect Strong Colours from "
                        f"{_unit_percentage(rule_a.transform.protect_strong_colours)} to "
                        f"{_unit_percentage(rule_b.transform.protect_strong_colours)}."
                    )
                elif (
                    rule_a.transform.protect_bright_areas
                    != rule_b.transform.protect_bright_areas
                ):
                    summary = (
                        f"Changed Protect Bright Areas from "
                        f"{_unit_percentage(rule_a.transform.protect_bright_areas)} to "
                        f"{_unit_percentage(rule_b.transform.protect_bright_areas)}."
                    )
                else:
                    summary = "Vibrance changed."
            elif isinstance(rule_a.transform, ColourTemperatureTransform) and isinstance(
                rule_b.transform, ColourTemperatureTransform
            ):
                if rule_a.transform.warmth != rule_b.transform.warmth:
                    summary = (
                        f"Changed Warmth from "
                        f"{_unit_percentage(rule_a.transform.warmth)} to "
                        f"{_unit_percentage(rule_b.transform.warmth)}."
                    )
                elif rule_a.transform.tint != rule_b.transform.tint:
                    summary = (
                        f"Changed Tint from "
                        f"{_unit_percentage(rule_a.transform.tint)} to "
                        f"{_unit_percentage(rule_b.transform.tint)}."
                    )
                elif (
                    rule_a.transform.preserve_brightness
                    != rule_b.transform.preserve_brightness
                ):
                    state = (
                        "enabled" if rule_b.transform.preserve_brightness else "disabled"
                    )
                    summary = f"Preserve Brightness was {state}."
                elif (
                    rule_a.transform.protect_neutral_background
                    != rule_b.transform.protect_neutral_background
                ):
                    summary = (
                        f"Changed Protect Neutral Background from "
                        f"{_unit_percentage(rule_a.transform.protect_neutral_background)} to "
                        f"{_unit_percentage(rule_b.transform.protect_neutral_background)}."
                    )
                else:
                    summary = "Colour Temperature changed."
            elif isinstance(rule_a.transform, FauxPaletteTransform) and isinstance(
                rule_b.transform, FauxPaletteTransform
            ):
                balance_summary = _faux_palette_balance_summary(
                    rule_b.name or rule_b.id,
                    rule_a.transform,
                    rule_b.transform,
                )
                if balance_summary is not None:
                    summary = balance_summary
                elif (
                    rule_a.transform.palette == rule_b.transform.palette
                    and rule_a.transform.amount != rule_b.transform.amount
                    and rule_a.transform.preserve_brightness
                    == rule_b.transform.preserve_brightness
                ):
                    summary = (
                        f"Changed {rule_b.name} amount from "
                        f"{_faux_palette_percentage(rule_a.transform.amount)} to "
                        f"{_faux_palette_percentage(rule_b.transform.amount)}."
                    )
                elif (
                    rule_a.transform.palette == rule_b.transform.palette
                    and rule_a.transform.amount == rule_b.transform.amount
                    and rule_a.transform.preserve_brightness
                    != rule_b.transform.preserve_brightness
                ):
                    state = (
                        "enabled"
                        if rule_b.transform.preserve_brightness
                        else "disabled"
                    )
                    summary = f"{rule_b.name} brightness preservation was {state}."
                elif rule_a.transform.palette != rule_b.transform.palette:
                    summary = (
                        f"Changed palette from {_faux_palette_name(rule_a.transform.palette)} "
                        f"to {_faux_palette_name(rule_b.transform.palette)}."
                    )
                else:
                    summary = f"{rule_b.name} faux palette changed."
            elif isinstance(rule_a.transform, ColourSmoothingTransform) and isinstance(
                rule_b.transform, ColourSmoothingTransform
            ):
                direction = (
                    "strengthened"
                    if rule_b.transform.strength > rule_a.transform.strength
                    else "reduced"
                )
                summary = f"{rule_b.name} smoothing was {direction}."
            elif isinstance(rule_a.transform, DarkNebulaProcessingTransform) and isinstance(
                rule_b.transform, DarkNebulaProcessingTransform
            ):
                if rule_a.transform.amount != rule_b.transform.amount:
                    summary = (
                        f"Changed {rule_b.name} amount from "
                        f"{_unit_percentage(rule_a.transform.amount)} to "
                        f"{_unit_percentage(rule_b.transform.amount)}."
                    )
                elif rule_a.transform.reveal_dust != rule_b.transform.reveal_dust:
                    summary = (
                        f"Changed Reveal Dust from "
                        f"{_unit_percentage(rule_a.transform.reveal_dust)} to "
                        f"{_unit_percentage(rule_b.transform.reveal_dust)}."
                    )
                elif rule_a.transform.dust_contrast != rule_b.transform.dust_contrast:
                    summary = (
                        f"Changed Dust Contrast from "
                        f"{_unit_percentage(rule_a.transform.dust_contrast)} to "
                        f"{_unit_percentage(rule_b.transform.dust_contrast)}."
                    )
                elif rule_a.transform.core_depth != rule_b.transform.core_depth:
                    summary = (
                        f"Changed Core Depth from "
                        f"{_unit_percentage(rule_a.transform.core_depth)} to "
                        f"{_unit_percentage(rule_b.transform.core_depth)}."
                    )
                elif rule_a.transform.dust_colour != rule_b.transform.dust_colour:
                    summary = (
                        f"Changed Dust Colour from "
                        f"{_unit_percentage(rule_a.transform.dust_colour)} to "
                        f"{_unit_percentage(rule_b.transform.dust_colour)}."
                    )
                elif rule_a.transform.softness != rule_b.transform.softness:
                    summary = (
                        f"Changed Softness from "
                        f"{_unit_percentage(rule_a.transform.softness)} to "
                        f"{_unit_percentage(rule_b.transform.softness)}."
                    )
                elif (
                    rule_a.transform.preserve_bright_areas
                    != rule_b.transform.preserve_bright_areas
                ):
                    state = (
                        "enabled" if rule_b.transform.preserve_bright_areas else "disabled"
                    )
                    summary = f"{rule_b.name} bright-area protection was {state}."
                else:
                    summary = f"{rule_b.name} processing changed."
            else:
                summary = f"{rule_b.name} transformation changed."
            modified.append(
                _change(
                    "rule.transform_changed",
                    "rule",
                    entity_id=rule_id,
                    entity_name=rule_b.name,
                    old_value=transform_a,
                    new_value=transform_b,
                    significance=["visual"],
                    human_summary=summary,
                    technical_path=f"rules.{rule_id}.transform",
                )
            )

        if positions_a[rule_id] != positions_b[rule_id]:
            current_position = positions_b[rule_id]
            previous_name = None
            if current_position > 1:
                previous_name = bundle_b.project.rules[current_position - 2].name
            reordered.append(
                _rule_reorder(
                    rule_b,
                    positions_a[rule_id],
                    current_position,
                    previous_rule_name=previous_name,
                )
            )

    return added, removed, modified, reordered


def _compare_palettes(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    palettes_a = {palette.id: palette for palette in bundle_a.palettes.values()}
    palettes_b = {palette.id: palette for palette in bundle_b.palettes.values()}
    added, removed = _added_removed_changes(
        "palette",
        "palette.added",
        "palette.removed",
        palettes_a,
        palettes_b,
        lambda item: item.id,
        lambda item: item.model_dump(mode="json"),
        ["structural"],
    )
    return added, removed, []


def _compare_render_profiles(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    profiles_a = bundle_a.render_profiles
    profiles_b = bundle_b.render_profiles
    added, removed = _added_removed_changes(
        "render_profile",
        "render_profile.added",
        "render_profile.removed",
        profiles_a,
        profiles_b,
        lambda item: item.name,
        lambda item: item.model_dump(mode="json"),
        ["structural", "visual"],
    )
    modified: list[ProjectDiffChange] = []
    for profile_id in [key for key in profiles_a if key in profiles_b]:
        profile_a = profiles_a[profile_id]
        profile_b = profiles_b[profile_id]
        if profile_a.model_dump(mode="json") != profile_b.model_dump(mode="json"):
            bit_depth_a = profile_a.profile.bit_depth
            bit_depth_b = profile_b.profile.bit_depth
            summary = f"{profile_b.name} output settings changed."
            code = "render_profile.changed"
            technical_path = f"render_profiles.{profile_id}"
            if bit_depth_a != bit_depth_b:
                summary = (
                    f"{profile_b.name} bit depth changed from {bit_depth_a} to {bit_depth_b}."
                )
            else:
                crop_a = _crop_payload(profile_a)
                crop_b = _crop_payload(profile_b)
                if crop_a is None and crop_b is not None:
                    summary = f"Added {_crop_label(profile_b)} crop to {profile_b.name} output."
                    code = "render_profile.crop_added"
                elif crop_a is not None and crop_b is None:
                    summary = f"Disabled crop for {profile_b.name} output."
                    code = "render_profile.crop_disabled"
                elif crop_a != crop_b:
                    summary = f"Changed {profile_b.name} crop framing."
                    code = "render_profile.crop_changed"
                    if (
                        crop_a is not None
                        and crop_b is not None
                        and crop_a["width"] == crop_b["width"]
                        and crop_a["height"] == crop_b["height"]
                        and (
                            crop_a["x"] != crop_b["x"]
                            or crop_a["y"] != crop_b["y"]
                        )
                    ):
                        summary = f"Changed {profile_b.name} crop position."
                else:
                    dimensions_a = _render_profile_dimensions(profile_a)
                    dimensions_b = _render_profile_dimensions(profile_b)
                    if (
                        dimensions_a is not None
                        and dimensions_b is not None
                        and dimensions_a != dimensions_b
                    ):
                        summary = (
                            f"Changed {profile_b.name} output dimensions from "
                            f"{dimensions_a} to {dimensions_b}."
                        )
                        code = "render_profile.dimensions_changed"
            modified.append(
                _change(
                    code,
                    "render_profile",
                    entity_id=profile_id,
                    entity_name=profile_b.name,
                    old_value=profile_a.model_dump(mode="json"),
                    new_value=profile_b.model_dump(mode="json"),
                    significance=["visual", "structural"],
                    human_summary=summary,
                    technical_path=technical_path,
                )
            )
    return added, removed, modified


def _plugin_entries(entries: list[PluginLockEntry]) -> dict[str, PluginLockEntry]:
    return {entry.id: entry for entry in entries}


def _compare_plugin_locks(
    bundle_a: ProjectBundle,
    bundle_b: ProjectBundle,
) -> ChangeLists:
    entries_a = _plugin_entries(bundle_a.plugin_lock.plugins if bundle_a.plugin_lock else [])
    entries_b = _plugin_entries(bundle_b.plugin_lock.plugins if bundle_b.plugin_lock else [])
    added, removed = _added_removed_changes(
        "plugin_lock",
        "plugin_lock.added",
        "plugin_lock.removed",
        entries_a,
        entries_b,
        lambda item: item.id,
        lambda item: item.model_dump(mode="json"),
        ["compatibility"],
    )
    modified: list[ProjectDiffChange] = []
    for plugin_id in [key for key in entries_a if key in entries_b]:
        entry_a = entries_a[plugin_id]
        entry_b = entries_b[plugin_id]
        if entry_a.version != entry_b.version:
            modified.append(
                _change(
                    "plugin_lock.changed",
                    "plugin_lock",
                    entity_id=plugin_id,
                    entity_name=plugin_id,
                    old_value=entry_a.version,
                    new_value=entry_b.version,
                    significance=["compatibility"],
                    human_summary=(
                        f"Plugin lock {plugin_id} changed from {entry_a.version} "
                        f"to {entry_b.version}."
                    ),
                    technical_path=f"plugins.{plugin_id}.version",
                )
            )
    return added, removed, modified


def _build_summary(
    added_items: list[ProjectDiffChange],
    removed_items: list[ProjectDiffChange],
    modified_items: list[ProjectDiffChange],
    reordered_rules: list[RuleReorderChange],
) -> ProjectDiffSummary:
    summary = ProjectDiffSummary(
        added=len(added_items),
        removed=len(removed_items),
        modified=len(modified_items),
        reordered_rules=len(reordered_rules),
    )
    for change in [*added_items, *removed_items, *modified_items]:
        for significance in change.significance:
            setattr(summary, significance, getattr(summary, significance) + 1)
    for reorder in reordered_rules:
        for significance in reorder.significance:
            setattr(summary, significance, getattr(summary, significance) + 1)
    return summary


def _build_explanations(
    added_items: list[ProjectDiffChange],
    removed_items: list[ProjectDiffChange],
    modified_items: list[ProjectDiffChange],
    reordered_rules: list[RuleReorderChange],
) -> list[DiffExplanationEntry]:
    explanations: list[DiffExplanationEntry] = []
    ordered_changes: list[ProjectDiffChange | RuleReorderChange] = [
        *modified_items,
        *reordered_rules,
        *added_items,
        *removed_items,
    ]
    for change in ordered_changes:
        explanations.append(
            DiffExplanationEntry(
                code=change.code,
                entity_type=change.entity_type,
                entity_id=getattr(change, "entity_id", None),
                summary=change.human_summary,
            )
        )
    return explanations


def diff_bundles(bundle_a: ProjectBundle, bundle_b: ProjectBundle) -> ProjectDiffDocument:
    added_items: list[ProjectDiffChange] = []
    removed_items: list[ProjectDiffChange] = []
    modified_items: list[ProjectDiffChange] = []

    modified_items.extend(_compare_project_metadata(bundle_a, bundle_b))

    added, removed, modified = _compare_sources(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)
    modified_items.extend(_compare_source_mix(bundle_a, bundle_b))

    added, removed, modified = _compare_semantic_channels(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    added, removed, modified = _compare_palettes(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    added, removed, modified = _compare_colour_points(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    added, removed, modified = _compare_regions(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    added, removed, modified, reordered_rules = _compare_rules(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    added, removed, modified = _compare_render_profiles(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    added, removed, modified = _compare_plugin_locks(bundle_a, bundle_b)
    added_items.extend(added)
    removed_items.extend(removed)
    modified_items.extend(modified)

    summary = _build_summary(added_items, removed_items, modified_items, reordered_rules)
    rendering_significant_changes: list[ProjectDiffChange | RuleReorderChange] = [
        change
        for change in [*added_items, *removed_items, *modified_items]
        if any(significance != "informational" for significance in change.significance)
    ]
    rendering_significant_changes.extend(reordered_rules)

    return ProjectDiffDocument(
        project_a=_build_project_identity(bundle_a),
        project_b=_build_project_identity(bundle_b),
        summary=summary,
        added_items=added_items,
        removed_items=removed_items,
        modified_items=modified_items,
        reordered_rules=reordered_rules,
        rendering_significant_changes=rendering_significant_changes,
        explanations=_build_explanations(
            added_items,
            removed_items,
            modified_items,
            reordered_rules,
        ),
    )


def diff_projects(project_a: Path, project_b: Path) -> ProjectDiffDocument:
    bundle_a, report_a = load_valid_project_bundle(project_a)
    bundle_b, report_b = load_valid_project_bundle(project_b)

    if not report_a.valid or not report_b.valid or bundle_a is None or bundle_b is None:
        raise ProjectDiffValidationError(report_a, report_b)

    return diff_bundles(bundle_a, bundle_b)

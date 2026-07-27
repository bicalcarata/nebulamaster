from __future__ import annotations

import re
from pathlib import Path
from time import perf_counter

import numpy as np
from project_model import (
    BrightnessTransform,
    ColourAmountTransform,
    ColourPoint,
    ColourSmoothingTransform,
    DeclarativeRule,
    LevelsTransform,
    ProjectBundle,
    SaturationTransform,
    ShiftColourPointTransform,
)
from pydantic import BaseModel, ConfigDict

from .regions import resolve_region_influence, write_debug_mask
from .selection import (
    apply_brightness_transform,
    apply_colour_amount,
    apply_colour_smoothing,
    apply_levels_transform,
    apply_saturation_transform,
    apply_shift_colour_point,
    brightness_weight,
    colour_weight,
    compute_luminance,
    saturation_weight,
)
from .semantic import semantic_target_influence


class RuleExecutionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    name: str
    declared_order: int
    enabled: bool
    selection_source: str
    region_ids: list[str]
    transformation_type: str
    ran: bool
    skip_reason: str | None = None
    affected_pixel_count: int
    mean_selection_weight: float
    max_selection_weight: float
    duration_seconds: float


class RuleExecutionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    image: np.ndarray
    traces: list[RuleExecutionTrace]
    declared_rule_ids: list[str]
    enabled_rule_ids: list[str]
    applied_rule_ids: list[str]
    skipped_rules: list[dict[str, str]]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "rule"


def _resolve_colour_point(bundle: ProjectBundle, colour_point_id: str) -> ColourPoint:
    for palette in bundle.palettes.values():
        for colour_point in palette.colour_points:
            if colour_point.id == colour_point_id:
                return colour_point
    raise ValueError(f"colour point '{colour_point_id}' was not found in loaded palettes")


def _selection_weights(
    bundle: ProjectBundle,
    rule: DeclarativeRule,
    selection_image: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    colour_weights = np.ones(selection_image.shape[:2], dtype=np.float32)
    if rule.match.colour_point is not None:
        colour_point = _resolve_colour_point(bundle, rule.match.colour_point)
        target_rgb = np.asarray(colour_point.value.channels, dtype=np.float32)
        colour_weights = colour_weight(
            selection_image,
            target_rgb,
            colour_range=rule.match.colour_range,
            softness=rule.match.softness,
        )

    brightness_weights = np.ones_like(colour_weights, dtype=np.float32)
    if rule.match.brightness is not None:
        luminance = compute_luminance(selection_image)
        brightness_weights = brightness_weight(
            luminance,
            minimum=rule.match.brightness.min,
            maximum=rule.match.brightness.max,
            softness=rule.match.softness,
        )

    saturation_weights = np.ones_like(colour_weights, dtype=np.float32)
    if rule.match.saturation is not None:
        saturation_weights = saturation_weight(
            selection_image,
            minimum=rule.match.saturation.min,
            maximum=rule.match.saturation.max,
            softness=rule.match.softness,
        )

    region_weights, region_ids = resolve_region_influence(
        bundle,
        rule.regions,
        selection_image.shape[1],
        selection_image.shape[0],
    )
    target_weights = semantic_target_influence(
        selection_image,
        rule.target,
        bundle.project.dark_dust,
    )
    combined = (
        colour_weights
        * brightness_weights
        * saturation_weights
        * region_weights
        * target_weights
    ).astype(
        np.float32,
        copy=False,
    )
    return colour_weights, brightness_weights, region_weights, target_weights, combined, region_ids


def _apply_transform(
    current_image: np.ndarray,
    weights: np.ndarray,
    rule: DeclarativeRule,
    bundle: ProjectBundle,
) -> np.ndarray:
    transform = rule.transform
    if isinstance(transform, ColourAmountTransform):
        return apply_colour_amount(
            current_image,
            weights,
            channel=transform.channel,
            amount=transform.amount,
            preserve_luminance=transform.preserve_luminance,
        )
    if isinstance(transform, ShiftColourPointTransform):
        target = _resolve_colour_point(bundle, transform.target_colour_point)
        target_rgb = np.asarray(target.value.channels, dtype=np.float32)
        return apply_shift_colour_point(
            current_image,
            weights,
            target_rgb=target_rgb,
            amount=transform.amount,
            preserve_luminance=transform.preserve_luminance,
        )
    if isinstance(transform, BrightnessTransform):
        return apply_brightness_transform(current_image, weights, amount=transform.amount)
    if isinstance(transform, SaturationTransform):
        return apply_saturation_transform(current_image, weights, amount=transform.amount)
    if isinstance(transform, LevelsTransform):
        return apply_levels_transform(
            current_image,
            weights,
            darkest=transform.darkest,
            dark=transform.dark,
            mid=transform.mid,
            light=transform.light,
            brightest=transform.brightest,
        )
    if isinstance(transform, ColourSmoothingTransform):
        return apply_colour_smoothing(
            current_image,
            weights,
            radius_fraction=transform.radius,
            strength=transform.strength,
        )
    raise ValueError(f"unsupported transform type: {transform.type}")


def _write_rule_debug_masks(
    debug_root: Path,
    order: int,
    rule: DeclarativeRule,
    *,
    colour_weights: np.ndarray,
    brightness_weights: np.ndarray,
    region_weights: np.ndarray,
    target_weights: np.ndarray,
    combined_weights: np.ndarray,
) -> None:
    rule_dir = debug_root / f"{order:03d}-{_slugify(rule.name or rule.id)}"
    rule_dir.mkdir(parents=True, exist_ok=True)
    write_debug_mask(rule_dir / "colour-weight.png", colour_weights)
    write_debug_mask(rule_dir / "brightness-weight.png", brightness_weights)
    write_debug_mask(rule_dir / "region-weight.png", region_weights)
    write_debug_mask(rule_dir / "target-weight.png", target_weights)
    write_debug_mask(rule_dir / "combined-weight.png", combined_weights)


def execute_rule_stack(
    bundle: ProjectBundle,
    source_image: np.ndarray,
    *,
    write_debug_masks_dir: Path | None = None,
) -> RuleExecutionResult:
    current_image = source_image.astype(np.float32, copy=True)
    original_image = source_image.astype(np.float32, copy=True)
    traces: list[RuleExecutionTrace] = []
    declared_rule_ids: list[str] = [rule.id for rule in bundle.project.rules]
    enabled_rule_ids: list[str] = [rule.id for rule in bundle.project.rules if rule.enabled]
    applied_rule_ids: list[str] = []
    skipped_rules: list[dict[str, str]] = []

    for order, rule in enumerate(bundle.project.rules, start=1):
        transform_type = rule.transform.type
        if not rule.enabled:
            trace = RuleExecutionTrace(
                rule_id=rule.id,
                name=rule.name or rule.id,
                declared_order=order,
                enabled=False,
                selection_source=rule.selection_source,
                region_ids=list(rule.regions),
                transformation_type=transform_type,
                ran=False,
                skip_reason="disabled",
                affected_pixel_count=0,
                mean_selection_weight=0.0,
                max_selection_weight=0.0,
                duration_seconds=0.0,
            )
            traces.append(trace)
            skipped_rules.append({"id": rule.id, "reason": "disabled"})
            continue

        selection_image = original_image if rule.selection_source == "original" else current_image
        start_time = perf_counter()
        (
            colour_weights,
            brightness_weights,
            region_weights,
            target_weights,
            combined_weights,
            region_ids,
        ) = _selection_weights(
            bundle,
            rule,
            selection_image,
        )
        current_image = _apply_transform(current_image, combined_weights, rule, bundle)
        duration = perf_counter() - start_time

        if write_debug_masks_dir is not None:
            _write_rule_debug_masks(
                write_debug_masks_dir,
                order,
                rule,
                colour_weights=colour_weights,
                brightness_weights=brightness_weights,
                region_weights=region_weights,
                target_weights=target_weights,
                combined_weights=combined_weights,
            )

        applied_rule_ids.append(rule.id)
        non_zero = combined_weights > 0.0
        if np.any(non_zero):
            mean_weight = float(np.mean(combined_weights[non_zero]))
            max_weight = float(np.max(combined_weights))
            affected_pixels = int(np.count_nonzero(non_zero))
        else:
            mean_weight = 0.0
            max_weight = 0.0
            affected_pixels = 0

        traces.append(
            RuleExecutionTrace(
                rule_id=rule.id,
                name=rule.name or rule.id,
                declared_order=order,
                enabled=True,
                selection_source=rule.selection_source,
                region_ids=region_ids,
                transformation_type=transform_type,
                ran=True,
                skip_reason=None,
                affected_pixel_count=affected_pixels,
                mean_selection_weight=mean_weight,
                max_selection_weight=max_weight,
                duration_seconds=duration,
            )
        )

    clipped = np.clip(current_image, 0.0, 1.0).astype(np.float32, copy=False)
    return RuleExecutionResult(
        image=np.asarray(clipped, dtype=np.float32),
        traces=traces,
        declared_rule_ids=declared_rule_ids,
        enabled_rule_ids=enabled_rule_ids,
        applied_rule_ids=applied_rule_ids,
        skipped_rules=skipped_rules,
    )

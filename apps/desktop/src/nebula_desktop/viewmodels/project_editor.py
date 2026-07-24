from __future__ import annotations

import colorsys
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from engine import (
    PreviewImageResult,
    ValidationReport,
    diff_bundles,
    load_valid_project_bundle,
    render_preview_image,
    semantic_target_influence,
    validate_project,
)
from image_io import CanonicalImage, load_canonical_image
from nebula_desktop.views.image_preview import ImageSample, OverlayRegion, SemanticOverlay
from nebula_desktop.workers.preview import PreviewRenderWorker
from project_io import read_yaml_mapping, resolve_reference_path, write_yaml_mapping
from project_model import (
    BrightnessTransform,
    ColourAmountTransform,
    ColourPoint,
    ColourSmoothingTransform,
    DeclarativeRule,
    Feather,
    FileReference,
    ProjectBundle,
    ProjectDiffChange,
    ProjectDiffDocument,
    RangeSelection,
    RegionFile,
    RuleMatch,
    RuleReorderChange,
    SaturationTransform,
    ShiftColourPointTransform,
)
from project_model.models import ColourValue
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

PREVIEW_MAX_EDGE = 1200
SelectionKind = Literal["adjustment", "region"]
AdjustmentKind = Literal[
    "blue",
    "red",
    "green",
    "cyan",
    "yellow",
    "brightness",
    "saturation",
    "smoothness",
]
SamplingPurpose = Literal["colour_point", "create_adjustment"]
SemanticOverlaySelection = Literal["off", "stars", "nebula"]


@dataclass(frozen=True)
class AdjustmentSummary:
    rule_id: str
    name: str
    enabled: bool
    type_label: str
    transform_type: str
    target_id: str
    target_label: str
    point_label: str | None
    scope_label: str
    editable: bool
    supports_colour_point: bool
    colour_point_id: str | None
    colour_point_name: str | None
    swatch_rgb: tuple[float, float, float] | None
    black_point_value: float | None
    primary_label: str | None
    primary_value: float | None
    secondary_label: str | None
    secondary_value: float | None
    helper_text: str
    region_ids: list[str]

    @property
    def amount(self) -> float:
        return self.primary_value if self.primary_value is not None else 0.0


@dataclass(frozen=True)
class RegionSummary:
    region_id: str
    name: str
    enabled: bool
    softness: float
    polygon: list[tuple[float, float]]
    adjustment_count: int


@dataclass(frozen=True)
class ChangeSummary:
    key: str
    summary: str
    entity_type: str
    entity_id: str | None
    selectable_kind: SelectionKind | None


@dataclass
class ProjectDocuments:
    bundle: ProjectBundle

    def clone(self) -> ProjectDocuments:
        return ProjectDocuments(bundle=self.bundle.model_copy(deep=True))


def _rgb_tuple(channels: tuple[float, float, float]) -> tuple[float, float, float]:
    red, green, blue = channels
    return float(red), float(green), float(blue)


def _srgb_channel_to_linear(value: float) -> float:
    if value <= 0.04045:
        return value / 12.92
    return float(((value + 0.055) / 1.055) ** 2.4)


def _sample_luminance(rgb: tuple[float, float, float]) -> float:
    red, green, blue = (_srgb_channel_to_linear(channel) for channel in rgb)
    return float((0.2126 * red) + (0.7152 * green) + (0.0722 * blue))


def _sample_saturation(rgb: tuple[float, float, float]) -> float:
    maximum = max(rgb)
    minimum = min(rgb)
    if maximum <= 0.0:
        return 0.0
    return float((maximum - minimum) / maximum)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def _type_label(rule: DeclarativeRule) -> str:
    transform = rule.transform
    if isinstance(transform, ColourAmountTransform):
        return transform.channel.capitalize()
    if isinstance(transform, ShiftColourPointTransform):
        return _label_from_colour_point_id(transform.target_colour_point)
    if isinstance(transform, BrightnessTransform):
        return "Brightness"
    if isinstance(transform, SaturationTransform):
        return "Saturation"
    if isinstance(transform, ColourSmoothingTransform):
        return "Smoothing"
    return "Saved adjustment"


def _helper_text(rule: DeclarativeRule) -> str:
    transform = rule.transform
    if isinstance(transform, ColourAmountTransform):
        return (
            f"Controls how strongly the selected {transform.channel} glow appears "
            "in the final image."
        )
    if isinstance(transform, ShiftColourPointTransform):
        target = _label_from_colour_point_id(transform.target_colour_point).lower()
        return f"Shifts the selected glow towards a more {target} appearance."
    if isinstance(transform, BrightnessTransform):
        return "Controls how bright this selected area appears in the final image."
    if isinstance(transform, SaturationTransform):
        return "Controls how vivid the selected colours appear in the final image."
    if isinstance(transform, ColourSmoothingTransform):
        return "Softens colour variations so the glow blends more naturally."
    return "This saved adjustment is preserved and continues to render."


def _point_label(rule: DeclarativeRule) -> str:
    transform = rule.transform
    if isinstance(transform, ColourAmountTransform):
        return f"{transform.channel.capitalize()} Point"
    if isinstance(transform, ShiftColourPointTransform):
        return f"{_label_from_colour_point_id(transform.target_colour_point)} Point"
    return "Colour Point"


def _supports_colour_point(transform: object) -> bool:
    return isinstance(transform, (ColourAmountTransform, ShiftColourPointTransform))


def _label_from_colour_point_id(colour_point_id: str) -> str:
    label = colour_point_id.replace("_", "-").split("-")[-1]
    return label.capitalize()


def _colour_family_hue(family: str) -> float | None:
    return {
        "red": 0.0,
        "yellow": 60.0 / 360.0,
        "green": 120.0 / 360.0,
        "cyan": 180.0 / 360.0,
        "blue": 240.0 / 360.0,
    }.get(family)


def _default_colour_point_tokens(kind: AdjustmentKind) -> tuple[str, ...]:
    return {
        "blue": ("nebula blue", "blue"),
        "red": ("nebula red", "red"),
        "green": ("nebula green", "green"),
        "cyan": ("nebula cyan", "cyan"),
        "yellow": ("nebula yellow", "yellow"),
        "brightness": (),
        "saturation": (),
        "smoothness": (),
    }[kind]


def _shift_target_colour_point_id(kind: AdjustmentKind) -> str | None:
    return {
        "cyan": "nebula-cyan",
        "yellow": "nebula-yellow",
    }.get(kind)


def _selection_family_for_rule(rule: DeclarativeRule) -> str | None:
    transform = rule.transform
    if isinstance(transform, ColourAmountTransform):
        return transform.channel
    if isinstance(transform, ShiftColourPointTransform):
        return transform.target_colour_point.replace("_", "-").split("-")[-1]
    return None


def _target_options() -> tuple[tuple[str, str], ...]:
    return (
        ("combined", "Combined Image"),
        ("nebula", "Nebula"),
        ("stars", "Stars"),
    )


def _target_label(target_id: str) -> str:
    for option_id, label in _target_options():
        if option_id == target_id:
            return label
    return target_id.replace("_", " ").title()


class ProjectEditorViewModel(QObject):
    projectLoaded = Signal(str)
    previewChanged = Signal()
    sourceChanged = Signal()
    adjustmentsChanged = Signal()
    regionsChanged = Signal()
    changesChanged = Signal()
    dirtyChanged = Signal(bool)
    statusChanged = Signal(str)
    errorRaised = Signal(str, str)
    samplingModeChanged = Signal(bool)
    busyChanged = Signal(bool)
    selectionChanged = Signal(str)
    drawingModeChanged = Signal(bool)
    regionVisibilityChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._saved_documents: ProjectDocuments | None = None
        self._working_documents: ProjectDocuments | None = None
        self._saved_preview: PreviewImageResult | None = None
        self._current_preview: PreviewImageResult | None = None
        self._source_image: CanonicalImage | None = None
        self._selected_adjustment_id: str | None = None
        self._selected_region_id: str | None = None
        self._selection_kind: SelectionKind = "adjustment"
        self._compare_saved = False
        self._show_source = False
        self._sampling_mode = False
        self._sampling_purpose: SamplingPurpose | None = None
        self._sampling_dirty_snapshot: bool | None = None
        self._is_drawing_region = False
        self._drawing_region_points: list[tuple[float, float]] = []
        self._show_regions = True
        self._semantic_overlay_mode: SemanticOverlaySelection = "off"
        self._dirty = False
        self._active_job_id = 0
        self._thread_pool = QThreadPool(self)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(180)
        self._debounce_timer.timeout.connect(self._launch_preview_render)

    @property
    def project_path(self) -> Path | None:
        if self._working_documents is None:
            return None
        return self._working_documents.bundle.project_dir

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def compare_saved(self) -> bool:
        return self._compare_saved

    @property
    def show_source(self) -> bool:
        return self._show_source

    @property
    def selection_kind(self) -> SelectionKind:
        return self._selection_kind

    @property
    def selected_adjustment_id(self) -> str | None:
        return self._selected_adjustment_id

    @property
    def selected_region_id(self) -> str | None:
        return self._selected_region_id

    @property
    def show_regions(self) -> bool:
        return self._show_regions

    @property
    def semantic_overlay_mode(self) -> SemanticOverlaySelection:
        return self._semantic_overlay_mode

    @property
    def is_sampling(self) -> bool:
        return self._sampling_mode

    @property
    def sampling_purpose(self) -> SamplingPurpose | None:
        return self._sampling_purpose

    @property
    def is_drawing_region(self) -> bool:
        return self._is_drawing_region

    def open_project(self, project_path: Path) -> bool:
        report = validate_project(project_path)
        if not report.valid:
            self._raise_validation_error(report)
            return False

        bundle, valid_report = load_valid_project_bundle(project_path)
        if bundle is None or not valid_report.valid:
            self._raise_validation_error(valid_report)
            return False

        documents = ProjectDocuments(bundle=bundle)
        self._saved_documents = documents
        self._working_documents = documents.clone()
        self._saved_preview = None
        self._current_preview = None
        self._show_source = False
        self._compare_saved = False
        self._sampling_mode = False
        self._sampling_purpose = None
        self._is_drawing_region = False
        self._drawing_region_points = []
        self._show_regions = True
        self._selected_adjustment_id = self._first_adjustment_id()
        self._selected_region_id = self._first_region_id()
        self._selection_kind = "adjustment" if self._selected_adjustment_id else "region"
        self._source_image = self._load_reference_source(bundle)
        self._set_dirty(False)
        self.projectLoaded.emit(bundle.project.project.name)
        self.sourceChanged.emit()
        self.adjustmentsChanged.emit()
        self.regionsChanged.emit()
        self.changesChanged.emit()
        self.selectionChanged.emit(self._selection_kind)
        self.regionVisibilityChanged.emit(self._show_regions)
        self.statusChanged.emit("Rendering preview...")
        self.render_saved_preview()
        return True

    def current_display_image(self) -> CanonicalImage | None:
        if self._show_source:
            return self._source_image
        if self._compare_saved and self._saved_preview is not None:
            return self._saved_preview.image
        if self._current_preview is not None:
            return self._current_preview.image
        return self._saved_preview.image if self._saved_preview is not None else None

    def current_semantic_overlay(self) -> SemanticOverlay | None:
        if self._semantic_overlay_mode == "off":
            return None
        image = self.current_display_image()
        if image is None:
            return None
        mask = semantic_target_influence(image.data, self._semantic_overlay_mode)
        label = {
            "stars": "Star Split Overlay",
            "nebula": "Nebula Split Overlay",
        }[self._semantic_overlay_mode]
        return SemanticOverlay(mode=self._semantic_overlay_mode, label=label, mask=mask)

    def adjustment_summaries(self) -> list[AdjustmentSummary]:
        if self._working_documents is None:
            return []

        summaries: list[AdjustmentSummary] = []
        for rule in self._working_documents.bundle.project.rules:
            colour_point = None
            swatch_rgb: tuple[float, float, float] | None = None
            colour_point_name: str | None = None
            if rule.match.colour_point is not None:
                colour_point = self._find_colour_point(
                    self._working_documents.bundle,
                    rule.match.colour_point,
                )
                if colour_point is not None:
                    swatch_rgb = _rgb_tuple(colour_point.value.channels)
                    colour_point_name = colour_point.name

            primary_label: str | None = None
            primary_value: float | None = None
            secondary_label: str | None = None
            secondary_value: float | None = None
            editable = False
            transform = rule.transform
            supports_colour_point = _supports_colour_point(transform)
            if isinstance(transform, ColourAmountTransform):
                editable = True
                primary_label = "Amount"
                primary_value = transform.amount
            elif isinstance(transform, ShiftColourPointTransform):
                editable = True
                primary_label = "Amount"
                primary_value = transform.amount
            elif isinstance(transform, BrightnessTransform):
                editable = True
                primary_label = "Less / More"
                primary_value = transform.amount
            elif isinstance(transform, SaturationTransform):
                editable = True
                primary_label = "Less / More"
                primary_value = transform.amount
            elif isinstance(transform, ColourSmoothingTransform):
                editable = True
                primary_label = "Smoothness"
                primary_value = transform.strength
                secondary_label = "Reach"
                secondary_value = transform.radius

            summaries.append(
                AdjustmentSummary(
                    rule_id=rule.id,
                    name=rule.name or rule.id,
                    enabled=rule.enabled,
                    type_label=_type_label(rule),
                    transform_type=transform.type,
                    target_id=rule.target,
                    target_label=_target_label(rule.target),
                    point_label=_point_label(rule) if supports_colour_point else None,
                    scope_label=self._scope_label(rule.regions),
                    editable=editable,
                    supports_colour_point=supports_colour_point,
                    colour_point_id=colour_point.id if colour_point is not None else None,
                    colour_point_name=colour_point_name,
                    swatch_rgb=swatch_rgb,
                    black_point_value=(
                        rule.match.brightness.min
                        if supports_colour_point and rule.match.brightness is not None
                        else (0.0 if supports_colour_point else None)
                    ),
                    primary_label=primary_label,
                    primary_value=primary_value,
                    secondary_label=secondary_label,
                    secondary_value=secondary_value,
                    helper_text=_helper_text(rule),
                    region_ids=list(rule.regions),
                )
            )
        return summaries

    def selected_adjustment_summary(self) -> AdjustmentSummary | None:
        selected_id = self._selected_adjustment_id
        if selected_id is None:
            return None
        for summary in self.adjustment_summaries():
            if summary.rule_id == selected_id:
                return summary
        return None

    def region_summaries(self) -> list[RegionSummary]:
        if self._working_documents is None:
            return []
        summaries: list[RegionSummary] = []
        for region_id, region in self._working_documents.bundle.regions.items():
            count = sum(
                1
                for rule in self._working_documents.bundle.project.rules
                if region_id in rule.regions
            )
            summaries.append(
                RegionSummary(
                    region_id=region_id,
                    name=region.name,
                    enabled=region.enabled,
                    softness=region.feather.radius if region.feather is not None else 0.0,
                    polygon=list(region.polygon),
                    adjustment_count=count,
                )
            )
        return summaries

    def selected_region_summary(self) -> RegionSummary | None:
        selected_id = self._selected_region_id
        if selected_id is None:
            return None
        for summary in self.region_summaries():
            if summary.region_id == selected_id:
                return summary
        return None

    def overlay_regions(self) -> list[OverlayRegion]:
        selected_region_id = self._selected_region_id if self._selection_kind == "region" else None
        highlighted_region_ids: set[str] = set()
        selected_adjustment = self._selected_rule_model()
        if selected_adjustment is not None:
            highlighted_region_ids = set(selected_adjustment.regions)

        overlays: list[OverlayRegion] = []
        for summary in self.region_summaries():
            overlays.append(
                OverlayRegion(
                    region_id=summary.region_id,
                    name=summary.name,
                    polygon=summary.polygon,
                    enabled=summary.enabled,
                    selected=summary.region_id == selected_region_id,
                    highlighted=summary.region_id in highlighted_region_ids,
                )
            )
        return overlays

    def drawing_points(self) -> list[tuple[float, float]]:
        return list(self._drawing_region_points)

    def unsaved_changes(self) -> list[ChangeSummary]:
        diff = self._semantic_diff()
        if diff is None:
            return []
        ordered_changes: list[ProjectDiffChange | RuleReorderChange] = [
            *diff.modified_items,
            *diff.reordered_rules,
            *diff.added_items,
            *diff.removed_items,
        ]
        changes: list[ChangeSummary] = []
        for index, change in enumerate(ordered_changes):
            entity_type = change.entity_type
            selectable_kind: SelectionKind | None = None
            if entity_type == "rule":
                selectable_kind = "adjustment"
            elif entity_type == "region":
                selectable_kind = "region"
            elif entity_type == "colour_point":
                selectable_kind = "adjustment"
            changes.append(
                ChangeSummary(
                    key=f"{change.code}:{change.entity_id or '-'}:{index}",
                    summary=change.human_summary,
                    entity_type=entity_type,
                    entity_id=getattr(change, "entity_id", None),
                    selectable_kind=selectable_kind,
                )
            )
        return changes

    def semantic_change_lines(self) -> list[str]:
        diff = self._semantic_diff()
        if diff is None:
            return []
        return [entry.summary for entry in diff.explanations]

    def set_show_source(self, show_source: bool) -> None:
        self._show_source = show_source
        self.previewChanged.emit()

    def set_compare_saved(self, compare_saved: bool) -> None:
        self._compare_saved = compare_saved
        self.previewChanged.emit()

    def set_show_regions(self, show_regions: bool) -> None:
        self._show_regions = show_regions
        self.regionVisibilityChanged.emit(show_regions)
        self.previewChanged.emit()

    def set_semantic_overlay_mode(self, mode: SemanticOverlaySelection) -> None:
        if mode not in {"off", "stars", "nebula"}:
            return
        self._semantic_overlay_mode = mode
        self.previewChanged.emit()

    def select_adjustment(self, rule_id: str) -> None:
        self._selected_adjustment_id = rule_id
        self._selection_kind = "adjustment"
        self.adjustmentsChanged.emit()
        self.regionsChanged.emit()
        self.selectionChanged.emit("adjustment")

    def select_region(self, region_id: str) -> None:
        self._selected_region_id = region_id
        self._selection_kind = "region"
        self.regionsChanged.emit()
        self.adjustmentsChanged.emit()
        self.selectionChanged.emit("region")

    def select_change_target(self, change_key: str) -> None:
        change = self._find_change(change_key)
        if change is None or change.entity_id is None or change.selectable_kind is None:
            return
        if change.selectable_kind == "adjustment":
            if change.entity_type == "colour_point":
                rule_id = self._rule_id_for_colour_point(change.entity_id)
                if rule_id is not None:
                    self.select_adjustment(rule_id)
            else:
                self.select_adjustment(change.entity_id)
        elif change.selectable_kind == "region":
            self.select_region(change.entity_id)

    def begin_sampling(self) -> None:
        summary = self.selected_adjustment_summary()
        if summary is None or not summary.supports_colour_point:
            return
        point_label = summary.point_label or "Colour Point"
        self._begin_sampling_session(
            purpose="colour_point",
            status_message=f"Click the colour you want to use as the {point_label}.",
        )

    def begin_adjustment_creation_sampling(self) -> None:
        if self._working_documents is None:
            return
        self._begin_sampling_session(
            purpose="create_adjustment",
            status_message="Click a visible feature to create an adjustment from its colour.",
        )

    def _begin_sampling_session(
        self,
        *,
        purpose: SamplingPurpose,
        status_message: str,
    ) -> None:
        if not self._sampling_mode:
            self._sampling_dirty_snapshot = self._dirty
        self._sampling_mode = True
        self._sampling_purpose = purpose
        self._selection_kind = "adjustment"
        self.samplingModeChanged.emit(True)
        self.selectionChanged.emit("adjustment")
        self.statusChanged.emit(status_message)

    def finish_sampling(self, *, status_message: str | None = None) -> None:
        if not self._sampling_mode:
            return
        self._sampling_mode = False
        self._sampling_purpose = None
        self._sampling_dirty_snapshot = None
        self.samplingModeChanged.emit(False)
        if status_message is not None:
            self.statusChanged.emit(status_message)

    def cancel_sampling(self) -> None:
        dirty_snapshot = (
            self._fingerprint(self._working_documents)
            != self._fingerprint(self._saved_documents)
        )
        self.finish_sampling(status_message="Selection cancelled.")
        self._set_dirty(dirty_snapshot)

    def apply_image_sample(self, sample: ImageSample) -> None:
        if self._sampling_purpose == "colour_point":
            self.apply_colour_sample(sample)

    def apply_colour_sample(self, sample: ImageSample) -> None:
        if not self._sampling_mode or self._working_documents is None:
            return
        summary = self.selected_adjustment_summary()
        if summary is None or summary.colour_point_id is None:
            return
        rule = self._selected_rule_model()
        colour_point = self._find_colour_point(
            self._working_documents.bundle,
            summary.colour_point_id,
        )
        if colour_point is None:
            self.errorRaised.emit(
                "This adjustment refers to a colour point that no longer exists.",
                f"adjustment={summary.rule_id}",
            )
            return
        sampled_rgb = sample.rgb
        if rule is not None:
            sampled_rgb = self._normalized_colour_sample(rule, sample.rgb)
        colour_point.value.channels = sampled_rgb
        if rule is not None:
            self._configure_colour_selection_from_sample(rule, sampled_rgb)
        self.finish_sampling()
        self._after_metadata_change(render=True)
        point_label = summary.point_label or "Colour Point"
        self.statusChanged.emit(f"{point_label} updated from the image.")

    def create_adjustment(self, kind: AdjustmentKind) -> None:
        if self._working_documents is None:
            return
        rule = self._build_adjustment_rule(
            kind=kind,
            rule_name=self._default_adjustment_name(kind),
            colour_point_id=self._default_colour_point_id(kind),
        )
        insert_index = self._selected_adjustment_index()
        if insert_index is None:
            self._working_documents.bundle.project.rules.append(rule)
        else:
            self._working_documents.bundle.project.rules.insert(insert_index + 1, rule)
        self._selected_adjustment_id = rule.id
        self._selection_kind = "adjustment"
        self._after_metadata_change(render=True)

    def create_adjustment_from_selection(
        self,
        kind: AdjustmentKind,
        sample: ImageSample,
    ) -> str | None:
        if self._working_documents is None:
            return None
        colour_point_id: str | None = None
        if _default_colour_point_tokens(kind):
            colour_point_id = self._create_sampled_colour_point(kind, sample.rgb)
        if _default_colour_point_tokens(kind) and colour_point_id is None:
            self.errorRaised.emit(
                "This project cannot create a sampled adjustment because no palette is available.",
                "",
            )
            return None
        rule_name = self._unique_rule_name(self._selected_adjustment_name(kind))
        rule = self._build_adjustment_rule(
            kind=kind,
            rule_name=rule_name,
            colour_point_id=colour_point_id,
        )
        if colour_point_id is not None:
            colour_point = self._find_colour_point(self._working_documents.bundle, colour_point_id)
            if colour_point is not None:
                normalized_rgb = self._normalized_colour_sample(rule, sample.rgb)
                colour_point.value.channels = normalized_rgb
                self._configure_colour_selection_from_sample(rule, normalized_rgb)
        self._working_documents.bundle.project.rules.append(rule)
        self._selected_adjustment_id = rule.id
        self._selection_kind = "adjustment"
        self._after_metadata_change(render=True)
        self.statusChanged.emit(f'{rule_name} was created from the selected image feature.')
        return rule.id

    def duplicate_selected_adjustment(self) -> None:
        if self._working_documents is None:
            return
        rule = self._selected_rule_model()
        if rule is None:
            return
        duplicate = rule.model_copy(deep=True)
        duplicate.id = self._unique_rule_id(f"{rule.id}-copy")
        duplicate.name = f"{rule.name or rule.id} Copy"
        index = self._selected_adjustment_index()
        if index is None:
            self._working_documents.bundle.project.rules.append(duplicate)
        else:
            self._working_documents.bundle.project.rules.insert(index + 1, duplicate)
        self._selected_adjustment_id = duplicate.id
        self._selection_kind = "adjustment"
        self._after_metadata_change(render=True)

    def remove_selected_adjustment(self) -> None:
        if self._working_documents is None or self._selected_adjustment_id is None:
            return
        rules = self._working_documents.bundle.project.rules
        next_rules = [rule for rule in rules if rule.id != self._selected_adjustment_id]
        if len(next_rules) == len(rules):
            return
        self._working_documents.bundle.project.rules = next_rules
        self._prune_unreferenced_working_colour_points()
        self._selected_adjustment_id = self._first_adjustment_id()
        self._selection_kind = "adjustment" if self._selected_adjustment_id else "region"
        self._after_metadata_change(render=True)

    def move_selected_adjustment(self, direction: Literal["earlier", "later"]) -> None:
        if self._working_documents is None or self._selected_adjustment_id is None:
            return
        index = self._selected_adjustment_index()
        if index is None:
            return
        new_index = index - 1 if direction == "earlier" else index + 1
        if new_index < 0 or new_index >= len(self._working_documents.bundle.project.rules):
            return
        rules = self._working_documents.bundle.project.rules
        rules[index], rules[new_index] = rules[new_index], rules[index]
        self._after_metadata_change(render=True)

    def reset_selected_adjustment(self) -> None:
        if self._saved_documents is None or self._selected_adjustment_id is None:
            return
        self._revert_adjustment(self._selected_adjustment_id)

    def set_selected_adjustment_enabled(self, enabled: bool) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        rule.enabled = enabled
        self._after_metadata_change(render=True)

    def set_selected_adjustment_primary_value(self, value: float) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        transform = rule.transform
        if isinstance(transform, ColourAmountTransform):
            transform.amount = max(1.0, min(2.0, value))
        elif isinstance(transform, ShiftColourPointTransform):
            transform.amount = max(0.0, min(1.0, value))
        elif isinstance(transform, (BrightnessTransform, SaturationTransform)):
            transform.amount = max(0.0, min(2.0, value))
        elif isinstance(transform, ColourSmoothingTransform):
            transform.strength = max(0.0, min(1.0, value))
        else:
            return
        self._after_metadata_change(render=True)

    def set_selected_adjustment_secondary_value(self, value: float) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        if isinstance(rule.transform, ColourSmoothingTransform):
            rule.transform.radius = value
            self._after_metadata_change(render=True)

    def set_selected_adjustment_black_point(self, value: float) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        current_max = 1.0
        if rule.match.brightness is not None:
            current_max = max(rule.match.brightness.max, value)
        rule.match.brightness = RangeSelection(min=value, max=current_max)
        self._after_metadata_change(render=True)

    def set_selected_adjustment_apply_everywhere(self, apply_everywhere: bool) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        if apply_everywhere:
            rule.regions = []
            self._after_metadata_change(render=True)
            return
        if not self._working_documents or not self._working_documents.bundle.regions:
            self.errorRaised.emit(
                "Create a region first before applying this adjustment to a selected area.",
                "",
            )
            return
        if not rule.regions:
            default_region_id = self._selected_region_id or self._first_region_id()
            if default_region_id is None:
                self.errorRaised.emit(
                    "Create a region first before applying this adjustment to a selected area.",
                    "",
                )
                return
            rule.regions = [default_region_id]
            self._after_metadata_change(render=True)

    def set_selected_adjustment_target(self, target_id: str) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        if target_id not in {option_id for option_id, _label in _target_options()}:
            return
        rule.target = target_id
        self._after_metadata_change(render=True)

    def set_selected_adjustment_regions(self, region_ids: list[str]) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        if not region_ids:
            self.errorRaised.emit(
                "Choose at least one region or apply this adjustment everywhere.",
                "",
            )
            return
        rule.regions = list(region_ids)
        self._after_metadata_change(render=True)

    def begin_region_drawing(self) -> None:
        self._sampling_mode = False
        self._sampling_purpose = None
        self._drawing_region_points = []
        self._selection_kind = "region"
        self._selected_region_id = None
        self._is_drawing_region = True
        self.drawingModeChanged.emit(True)
        self.samplingModeChanged.emit(False)
        self.selectionChanged.emit("region")
        self.previewChanged.emit()
        self.statusChanged.emit(
            "Click points to outline a region. Double-click or press Enter to finish."
        )

    def add_region_point(self, x: float, y: float) -> None:
        self._drawing_region_points.append((self._clamp(x), self._clamp(y)))
        self.regionsChanged.emit()
        self.previewChanged.emit()

    def finish_region_drawing(self) -> None:
        if self._working_documents is None or len(self._drawing_region_points) < 3:
            return
        region_id = self._unique_region_id("selected-area")
        region = RegionFile(
            id=region_id,
            name=self._unique_region_name("Selected Area"),
            enabled=True,
            feather=Feather(radius=0.05),
            polygon=list(self._drawing_region_points),
        )
        self._working_documents.bundle.regions[region_id] = region
        self._working_documents.bundle.project.regions.append(
            FileReference(id=region_id, path=Path(f"regions/{region_id}.yaml"))
        )
        self._is_drawing_region = False
        self._drawing_region_points = []
        self._selected_region_id = region_id
        self._selection_kind = "region"
        self.drawingModeChanged.emit(False)
        self._after_metadata_change(render=True)

    def cancel_region_drawing(self) -> None:
        self._is_drawing_region = False
        self._drawing_region_points = []
        self.drawingModeChanged.emit(False)
        self.regionsChanged.emit()
        self.previewChanged.emit()
        self.statusChanged.emit("Region drawing cancelled.")

    def set_selected_region_name(self, name: str) -> None:
        summary = self.selected_region_summary()
        if summary is None or not name.strip():
            return
        documents = self._working_documents
        assert documents is not None
        region = documents.bundle.regions[summary.region_id]
        region.name = name.strip()
        self._after_metadata_change(render=False)

    def set_selected_region_enabled(self, enabled: bool) -> None:
        summary = self.selected_region_summary()
        if summary is None:
            return
        documents = self._working_documents
        assert documents is not None
        documents.bundle.regions[summary.region_id].enabled = enabled
        self._after_metadata_change(render=True)

    def set_selected_region_softness(self, softness: float) -> None:
        summary = self.selected_region_summary()
        if summary is None:
            return
        documents = self._working_documents
        assert documents is not None
        region = documents.bundle.regions[summary.region_id]
        region.feather = Feather(radius=softness)
        self._after_metadata_change(render=True)

    def move_region_vertex(self, region_id: str, index: int, x: float, y: float) -> None:
        region = self._region_model(region_id)
        if region is None or index >= len(region.polygon):
            return
        polygon = list(region.polygon)
        polygon[index] = (self._clamp(x), self._clamp(y))
        region.polygon = polygon
        self._after_metadata_change(render=False)

    def insert_region_vertex(self, region_id: str, index: int, x: float, y: float) -> None:
        region = self._region_model(region_id)
        if region is None:
            return
        polygon = list(region.polygon)
        polygon.insert(index, (self._clamp(x), self._clamp(y)))
        region.polygon = polygon
        self._after_metadata_change(render=True)

    def delete_region_vertex(self, region_id: str, index: int) -> None:
        region = self._region_model(region_id)
        if region is None or len(region.polygon) <= 3:
            return
        polygon = list(region.polygon)
        if index >= len(polygon):
            return
        del polygon[index]
        region.polygon = polygon
        self._after_metadata_change(render=True)

    def move_region(self, region_id: str, dx: float, dy: float) -> None:
        region = self._region_model(region_id)
        if region is None:
            return
        polygon = list(region.polygon)
        min_dx = min(0.0 - point[0] for point in polygon)
        max_dx = max(1.0 - point[0] for point in polygon)
        min_dy = min(0.0 - point[1] for point in polygon)
        max_dy = max(1.0 - point[1] for point in polygon)
        safe_dx = min(max(dx, min_dx), max_dx)
        safe_dy = min(max(dy, min_dy), max_dy)
        region.polygon = [
            (self._clamp(point[0] + safe_dx), self._clamp(point[1] + safe_dy))
            for point in polygon
        ]
        self._after_metadata_change(render=False)

    def remove_selected_region(self) -> None:
        if self._working_documents is None or self._selected_region_id is None:
            return
        region_id = self._selected_region_id
        self._working_documents.bundle.regions.pop(region_id, None)
        self._working_documents.bundle.project.regions = [
            ref for ref in self._working_documents.bundle.project.regions if ref.id != region_id
        ]
        for rule in self._working_documents.bundle.project.rules:
            if region_id in rule.regions:
                rule.regions = [current for current in rule.regions if current != region_id]
        self._selected_region_id = self._first_region_id()
        self._after_metadata_change(render=True)
        self.statusChanged.emit("Selected region removed.")

    def revert_selected_region(self) -> None:
        if self._selected_region_id is None:
            return
        self._revert_region(self._selected_region_id)

    def revert_change(self, change_key: str) -> None:
        change = self._find_change(change_key)
        if change is None or change.entity_id is None:
            return
        if change.entity_type == "rule":
            self._revert_adjustment(change.entity_id)
        elif change.entity_type == "region":
            self._revert_region(change.entity_id)
        elif change.entity_type == "colour_point":
            self._revert_colour_point(change.entity_id)

    def revert_unsaved_changes(self) -> None:
        if self._saved_documents is None:
            return
        self._working_documents = self._saved_documents.clone()
        self._current_preview = self._saved_preview
        self._selected_adjustment_id = self._first_adjustment_id()
        self._selected_region_id = self._first_region_id()
        self._selection_kind = "adjustment" if self._selected_adjustment_id else "region"
        self._show_source = False
        self._compare_saved = False
        self._sampling_mode = False
        self._sampling_purpose = None
        self._is_drawing_region = False
        self._drawing_region_points = []
        self._set_dirty(False)
        self.adjustmentsChanged.emit()
        self.regionsChanged.emit()
        self.changesChanged.emit()
        self.previewChanged.emit()
        self.selectionChanged.emit(self._selection_kind)
        self.statusChanged.emit("Unsaved changes were reverted.")

    def save_changes(self) -> bool:
        if self._working_documents is None or self._saved_documents is None:
            return False
        try:
            render_preview_image(
                self._working_documents.bundle.model_copy(deep=True),
                include_provenance=False,
                use_cached_sources=True,
            )
            self._write_project_metadata(self._working_documents, self._saved_documents)
        except Exception as exc:  # pragma: no cover
            self.errorRaised.emit(
                "The project could not be saved. Your source images were not changed.",
                repr(exc),
            )
            return False

        self._saved_documents = self._working_documents.clone()
        self._saved_preview = self._current_preview
        self._set_dirty(False)
        self.changesChanged.emit()
        self.statusChanged.emit("Project metadata saved.")
        return True

    def request_preview_render(self, *, immediate: bool = False) -> None:
        if self._working_documents is None:
            return
        if immediate:
            self._launch_preview_render()
            return
        self._debounce_timer.start()

    def render_saved_preview(self) -> None:
        if self._saved_documents is None:
            return
        try:
            self._saved_preview = render_preview_image(
                self._saved_documents.bundle.model_copy(deep=True),
                include_provenance=False,
                use_cached_sources=True,
            )
        except Exception as exc:  # pragma: no cover
            self.errorRaised.emit(
                "The preview could not be created. Your project has not been changed.",
                repr(exc),
            )
            return
        if self._current_preview is None:
            self._current_preview = self._saved_preview
        self.previewChanged.emit()

    def apply_preview_result(self, job_id: int, result: PreviewImageResult) -> bool:
        if job_id != self._active_job_id:
            return False
        self._current_preview = result
        self.busyChanged.emit(False)
        self.statusChanged.emit("Preview updated.")
        self.previewChanged.emit()
        return True

    def handle_preview_failure(self, job_id: int, message: str, details: str) -> None:
        if job_id != self._active_job_id:
            return
        self.busyChanged.emit(False)
        self.errorRaised.emit(
            "The preview could not be created. Your project has not been changed.",
            f"{message}\n{details}",
        )

    def snapshot_contains_generated_state(self) -> bool:
        if self._working_documents is None:
            return False
        payload = self._working_documents.bundle.project.model_dump(mode="json")
        text = json.dumps(payload, sort_keys=True)
        return any(token in text for token in ["generated/", "previews/", "cache/"])

    def _after_metadata_change(self, *, render: bool) -> None:
        self._set_dirty(
            self._fingerprint(self._working_documents)
            != self._fingerprint(self._saved_documents)
        )
        self.adjustmentsChanged.emit()
        self.regionsChanged.emit()
        self.changesChanged.emit()
        self.previewChanged.emit()
        if render:
            self.statusChanged.emit("Rendering preview...")
            self.request_preview_render()

    def _launch_preview_render(self) -> None:
        if self._working_documents is None:
            return
        self._active_job_id += 1
        job_id = self._active_job_id
        self.busyChanged.emit(True)
        worker = PreviewRenderWorker(
            job_id=job_id,
            bundle=self._working_documents.bundle.model_copy(deep=True),
            max_edge=PREVIEW_MAX_EDGE,
        )
        worker.signals.completed.connect(self.apply_preview_result)
        worker.signals.failed.connect(self.handle_preview_failure)
        self._thread_pool.start(worker)

    def _raise_validation_error(self, report: ValidationReport) -> None:
        issue = report.issues[0] if report.issues else None
        summary = "This project could not be opened."
        details = ""
        if issue is not None:
            summary = f"This project could not be opened because {issue.message.rstrip('.')}."
            details = json.dumps(report.model_dump(mode="json"), indent=2)
        self.errorRaised.emit(summary, details)

    def _load_reference_source(self, bundle: ProjectBundle) -> CanonicalImage:
        enabled_sources = [source for source in bundle.project.sources if source.enabled]
        reference = next((source for source in enabled_sources if source.reference), None)
        source = reference if reference is not None else enabled_sources[0]
        return load_canonical_image(resolve_reference_path(bundle.project_dir, source.path))

    def _region_model(self, region_id: str) -> RegionFile | None:
        if self._working_documents is None:
            return None
        return self._working_documents.bundle.regions.get(region_id)

    def _find_colour_point(self, bundle: ProjectBundle, colour_point_id: str) -> ColourPoint | None:
        for palette in bundle.palettes.values():
            for colour_point in palette.colour_points:
                if colour_point.id == colour_point_id:
                    return colour_point
        return None

    def _rule_id_for_colour_point(self, colour_point_id: str) -> str | None:
        if self._working_documents is None:
            return None
        for rule in self._working_documents.bundle.project.rules:
            if rule.match.colour_point == colour_point_id:
                return rule.id
        return None

    def _selected_rule_model(self) -> DeclarativeRule | None:
        if self._working_documents is None or self._selected_adjustment_id is None:
            return None
        for rule in self._working_documents.bundle.project.rules:
            if rule.id == self._selected_adjustment_id:
                return rule
        return None

    def _selected_adjustment_index(self) -> int | None:
        if self._working_documents is None or self._selected_adjustment_id is None:
            return None
        for index, rule in enumerate(self._working_documents.bundle.project.rules):
            if rule.id == self._selected_adjustment_id:
                return index
        return None

    def _first_adjustment_id(self) -> str | None:
        if self._working_documents is None or not self._working_documents.bundle.project.rules:
            return None
        return self._working_documents.bundle.project.rules[0].id

    def _first_region_id(self) -> str | None:
        if self._working_documents is None or not self._working_documents.bundle.regions:
            return None
        return next(iter(self._working_documents.bundle.regions))

    def _scope_label(self, region_ids: list[str]) -> str:
        if not region_ids:
            return "Entire image"
        if len(region_ids) == 1 and self._working_documents is not None:
            region = self._working_documents.bundle.regions.get(region_ids[0])
            if region is not None:
                return region.name
        return "Multiple regions"

    def _default_target(self) -> str:
        return "combined"

    def _normalized_colour_sample(
        self,
        rule: DeclarativeRule,
        rgb: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        family = _selection_family_for_rule(rule)
        hue = _colour_family_hue(family or "")
        if hue is None:
            return rgb
        _sample_hue, saturation, value = colorsys.rgb_to_hsv(*rgb)
        adjusted_saturation = max(0.35, saturation)
        red, green, blue = colorsys.hsv_to_rgb(hue, adjusted_saturation, value)
        return float(red), float(green), float(blue)

    def _configure_colour_selection_from_sample(
        self,
        rule: DeclarativeRule,
        rgb: tuple[float, float, float],
    ) -> None:
        if not isinstance(rule.transform, (ColourAmountTransform, ShiftColourPointTransform)):
            return
        luminance = _sample_luminance(rgb)
        saturation = _sample_saturation(rgb)
        rule.match.colour_range = 0.08
        rule.match.softness = 0.30
        rule.match.brightness = RangeSelection(
            min=max(0.0, luminance - 0.12),
            max=min(1.0, luminance + 0.12),
        )
        rule.match.saturation = RangeSelection(
            min=max(0.18, saturation - 0.18),
            max=min(1.0, max(0.45, saturation + 0.18)),
        )

    def _default_colour_point_id(self, kind: AdjustmentKind) -> str | None:
        if self._working_documents is None:
            return None
        tokens = _default_colour_point_tokens(kind)
        if not tokens:
            return None
        for palette in self._working_documents.bundle.palettes.values():
            for colour_point in palette.colour_points:
                haystack = f"{colour_point.id} {colour_point.name}".lower()
                if any(token in haystack for token in tokens):
                    return colour_point.id
        return None

    def _default_adjustment_name(self, kind: AdjustmentKind) -> str:
        return {
            "blue": "Blue",
            "red": "Red",
            "green": "Green",
            "cyan": "Cyan",
            "yellow": "Yellow",
            "brightness": "Brightness",
            "saturation": "Saturation",
            "smoothness": "Colour Smoothness",
        }[kind]

    def _selected_adjustment_name(self, kind: AdjustmentKind) -> str:
        return {
            "blue": "Selected Blue",
            "red": "Selected Red",
            "green": "Selected Green",
            "cyan": "Selected Cyan",
            "yellow": "Selected Yellow",
            "brightness": "Selected Brightness",
            "saturation": "Selected Saturation",
            "smoothness": "Selected Smoothing",
        }[kind]

    def _unique_rule_id(self, base: str) -> str:
        if self._working_documents is None:
            return _slugify(base)
        existing = {rule.id for rule in self._working_documents.bundle.project.rules}
        slug = _slugify(base)
        candidate = slug
        counter = 2
        while candidate in existing:
            candidate = f"{slug}-{counter}"
            counter += 1
        return candidate

    def _unique_rule_name(self, base: str) -> str:
        if self._working_documents is None:
            return base
        existing = {rule.name or rule.id for rule in self._working_documents.bundle.project.rules}
        if base not in existing:
            return base
        counter = 2
        candidate = f"{base} {counter}"
        while candidate in existing:
            counter += 1
            candidate = f"{base} {counter}"
        return candidate

    def _build_adjustment_rule(
        self,
        *,
        kind: AdjustmentKind,
        rule_name: str,
        colour_point_id: str | None,
    ) -> DeclarativeRule:
        transform: (
            ColourAmountTransform
            | ShiftColourPointTransform
            | BrightnessTransform
            | SaturationTransform
            | ColourSmoothingTransform
        )
        if kind == "blue":
            transform = ColourAmountTransform(type="colour_amount", channel="blue", amount=1.2)
            match = RuleMatch(
                colour_point=colour_point_id,
                colour_range=0.10,
                brightness=RangeSelection(min=0.0, max=1.0),
                softness=0.35,
            )
        elif kind == "red":
            transform = ColourAmountTransform(type="colour_amount", channel="red", amount=1.2)
            match = RuleMatch(
                colour_point=colour_point_id,
                colour_range=0.10,
                brightness=RangeSelection(min=0.0, max=1.0),
                softness=0.35,
            )
        elif kind == "green":
            transform = ColourAmountTransform(type="colour_amount", channel="green", amount=1.2)
            match = RuleMatch(
                colour_point=colour_point_id,
                colour_range=0.10,
                brightness=RangeSelection(min=0.0, max=1.0),
                softness=0.35,
            )
        elif kind == "cyan":
            transform = ShiftColourPointTransform(
                type="shift_colour_point",
                target_colour_point=_shift_target_colour_point_id(kind) or "nebula-cyan",
                amount=0.35,
                preserve_luminance=True,
            )
            match = RuleMatch(
                colour_point=colour_point_id,
                colour_range=0.10,
                brightness=RangeSelection(min=0.0, max=1.0),
                softness=0.35,
            )
        elif kind == "yellow":
            transform = ShiftColourPointTransform(
                type="shift_colour_point",
                target_colour_point=_shift_target_colour_point_id(kind) or "nebula-yellow",
                amount=0.35,
                preserve_luminance=True,
            )
            match = RuleMatch(
                colour_point=colour_point_id,
                colour_range=0.10,
                brightness=RangeSelection(min=0.0, max=1.0),
                softness=0.35,
            )
        elif kind == "brightness":
            transform = BrightnessTransform(type="brightness", amount=1.12)
            match = RuleMatch(
                colour_point=None,
                softness=0.45,
            )
        elif kind == "saturation":
            transform = SaturationTransform(type="saturation", amount=1.25)
            match = RuleMatch(
                colour_point=None,
                softness=0.45,
            )
        else:
            transform = ColourSmoothingTransform(
                type="colour_smoothing",
                radius=0.02,
                strength=0.15,
            )
            match = RuleMatch(
                colour_point=None,
                softness=0.45,
            )

        return DeclarativeRule(
            id=self._unique_rule_id(rule_name),
            name=rule_name,
            enabled=True,
            selection_source="current",
            target=self._default_target(),
            match=match,
            regions=[],
            transform=transform,
        )

    def _create_sampled_colour_point(
        self,
        kind: AdjustmentKind,
        rgb: tuple[float, float, float],
    ) -> str | None:
        if self._working_documents is None:
            return None
        palette = next(iter(self._working_documents.bundle.palettes.values()), None)
        if palette is None:
            return None
        point_name = self._unique_colour_point_name(
            {
                "blue": "Selected Blue Point",
                "red": "Selected Red Point",
                "green": "Selected Green Point",
                "cyan": "Selected Cyan Point",
                "yellow": "Selected Yellow Point",
                "brightness": "Selected Brightness Point",
                "saturation": "Selected Saturation Point",
                "smoothness": "Selected Smoothing Point",
            }[kind]
        )
        point_id = self._unique_colour_point_id(point_name)
        palette.colour_points.append(
            ColourPoint(
                id=point_id,
                name=point_name,
                value=ColourValue(model="working-rgb", channels=rgb),
            )
        )
        return point_id

    def _unique_colour_point_id(self, base: str) -> str:
        if self._working_documents is None:
            return _slugify(base)
        existing_ids = {
            colour_point.id
            for palette in self._working_documents.bundle.palettes.values()
            for colour_point in palette.colour_points
        }
        slug = _slugify(base)
        candidate = slug
        counter = 2
        while candidate in existing_ids:
            candidate = f"{slug}-{counter}"
            counter += 1
        return candidate

    def _unique_colour_point_name(self, base: str) -> str:
        if self._working_documents is None:
            return base
        existing_names = {
            colour_point.name
            for palette in self._working_documents.bundle.palettes.values()
            for colour_point in palette.colour_points
        }
        if base not in existing_names:
            return base
        counter = 2
        candidate = f"{base} {counter}"
        while candidate in existing_names:
            counter += 1
            candidate = f"{base} {counter}"
        return candidate

    def _unique_region_id(self, base: str) -> str:
        if self._working_documents is None:
            return _slugify(base)
        existing = set(self._working_documents.bundle.regions)
        slug = _slugify(base)
        candidate = slug
        counter = 2
        while candidate in existing:
            candidate = f"{slug}-{counter}"
            counter += 1
        return candidate

    def _unique_region_name(self, base: str) -> str:
        existing = {summary.name for summary in self.region_summaries()}
        if base not in existing:
            return base
        counter = 2
        candidate = f"{base} {counter}"
        while candidate in existing:
            counter += 1
            candidate = f"{base} {counter}"
        return candidate

    def _semantic_diff(self) -> ProjectDiffDocument | None:
        if self._saved_documents is None or self._working_documents is None:
            return None
        return diff_bundles(
            self._saved_documents.bundle.model_copy(deep=True),
            self._working_documents.bundle.model_copy(deep=True),
        )

    def _find_change(self, change_key: str) -> ChangeSummary | None:
        for change in self.unsaved_changes():
            if change.key == change_key:
                return change
        return None

    def _revert_adjustment(self, rule_id: str) -> None:
        if self._saved_documents is None or self._working_documents is None:
            return
        saved_rules = self._saved_documents.bundle.project.rules
        working_rules = self._working_documents.bundle.project.rules
        saved_rule = next((rule for rule in saved_rules if rule.id == rule_id), None)
        working_index = next(
            (index for index, rule in enumerate(working_rules) if rule.id == rule_id),
            None,
        )

        if saved_rule is None and working_index is not None:
            del working_rules[working_index]
            self._prune_unreferenced_working_colour_points()
        elif saved_rule is not None and working_index is None:
            insert_index = next(
                (index for index, rule in enumerate(saved_rules) if rule.id == rule_id),
                len(working_rules),
            )
            working_rules.insert(insert_index, saved_rule.model_copy(deep=True))
        elif saved_rule is not None and working_index is not None:
            working_rules[working_index] = saved_rule.model_copy(deep=True)
            self._move_rule_to_saved_position(rule_id)
            colour_point_id = saved_rule.match.colour_point
            if colour_point_id is not None:
                self._revert_colour_point(colour_point_id, trigger_change=False)

        self._selected_adjustment_id = (
            rule_id
            if any(
                rule.id == rule_id for rule in self._working_documents.bundle.project.rules
            )
            else self._first_adjustment_id()
        )
        self._selection_kind = "adjustment"
        self._after_metadata_change(render=True)

    def _prune_unreferenced_working_colour_points(self) -> None:
        if self._working_documents is None:
            return
        saved_point_ids: set[str] = set()
        if self._saved_documents is not None:
            saved_point_ids = {
                colour_point.id
                for palette in self._saved_documents.bundle.palettes.values()
                for colour_point in palette.colour_points
            }
        referenced_ids = {
            rule.match.colour_point
            for rule in self._working_documents.bundle.project.rules
            if rule.match.colour_point is not None
        }
        for palette in self._working_documents.bundle.palettes.values():
            palette.colour_points = [
                colour_point
                for colour_point in palette.colour_points
                if colour_point.id in saved_point_ids or colour_point.id in referenced_ids
            ]

    def _move_rule_to_saved_position(self, rule_id: str) -> None:
        if self._saved_documents is None or self._working_documents is None:
            return
        saved_order = [rule.id for rule in self._saved_documents.bundle.project.rules]
        if rule_id not in saved_order:
            return
        target_index = saved_order.index(rule_id)
        current_rules = self._working_documents.bundle.project.rules
        current_index = next(
            (index for index, rule in enumerate(current_rules) if rule.id == rule_id),
            None,
        )
        if current_index is None:
            return
        rule = current_rules.pop(current_index)
        target_index = min(target_index, len(current_rules))
        current_rules.insert(target_index, rule)

    def _revert_region(self, region_id: str) -> None:
        if self._saved_documents is None or self._working_documents is None:
            return
        saved_region = self._saved_documents.bundle.regions.get(region_id)
        working_regions = self._working_documents.bundle.regions
        if saved_region is None:
            working_regions.pop(region_id, None)
            self._working_documents.bundle.project.regions = [
                ref for ref in self._working_documents.bundle.project.regions if ref.id != region_id
            ]
            for rule in self._working_documents.bundle.project.rules:
                if region_id in rule.regions:
                    rule.regions = [current for current in rule.regions if current != region_id]
        else:
            working_regions[region_id] = saved_region.model_copy(deep=True)
            if region_id not in {ref.id for ref in self._working_documents.bundle.project.regions}:
                saved_ref = next(
                    ref
                    for ref in self._saved_documents.bundle.project.regions
                    if ref.id == region_id
                )
                self._working_documents.bundle.project.regions.append(
                    saved_ref.model_copy(deep=True)
                )
        self._selected_region_id = (
            region_id if saved_region is not None else self._first_region_id()
        )
        self._selection_kind = "region"
        self._after_metadata_change(render=True)

    def _revert_colour_point(self, colour_point_id: str, *, trigger_change: bool = True) -> None:
        if self._saved_documents is None or self._working_documents is None:
            return
        saved_point = self._find_colour_point(self._saved_documents.bundle, colour_point_id)
        working_point = self._find_colour_point(self._working_documents.bundle, colour_point_id)
        if saved_point is None or working_point is None:
            return
        working_point.value.channels = saved_point.value.channels
        if trigger_change:
            self._after_metadata_change(render=True)

    def _set_dirty(self, dirty: bool) -> None:
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self.dirtyChanged.emit(dirty)

    def _fingerprint(self, documents: ProjectDocuments | None) -> str:
        if documents is None:
            return ""
        payload = {
            "project": documents.bundle.project.model_dump(mode="json"),
            "palettes": {
                key: value.model_dump(mode="json")
                for key, value in sorted(documents.bundle.palettes.items())
            },
            "regions": {
                key: value.model_dump(mode="json")
                for key, value in sorted(documents.bundle.regions.items())
            },
        }
        return json.dumps(payload, sort_keys=True)

    def _write_project_metadata(
        self,
        documents: ProjectDocuments,
        saved_documents: ProjectDocuments,
    ) -> None:
        project_payload = documents.bundle.project.model_dump(mode="json", exclude_none=True)
        current_project_payload = read_yaml_mapping(documents.bundle.project_file)
        if project_payload != current_project_payload:
            write_yaml_mapping(documents.bundle.project_file, project_payload)

        for palette_ref in documents.bundle.project.palettes:
            palette_path = resolve_reference_path(documents.bundle.project_dir, palette_ref.path)
            palette_payload = documents.bundle.palettes[palette_ref.id].model_dump(
                mode="json",
                exclude_none=True,
            )
            if not palette_path.exists() or read_yaml_mapping(palette_path) != palette_payload:
                write_yaml_mapping(palette_path, palette_payload)

        current_region_refs = {ref.id: ref.path for ref in documents.bundle.project.regions}
        for region_ref in documents.bundle.project.regions:
            region_path = resolve_reference_path(documents.bundle.project_dir, region_ref.path)
            region_payload = documents.bundle.regions[region_ref.id].model_dump(
                mode="json",
                exclude_none=True,
            )
            if not region_path.exists() or read_yaml_mapping(region_path) != region_payload:
                write_yaml_mapping(region_path, region_payload)

        saved_region_refs = {ref.id: ref.path for ref in saved_documents.bundle.project.regions}
        for region_id, region_path in saved_region_refs.items():
            if region_id in current_region_refs:
                continue
            resolved_path = resolve_reference_path(documents.bundle.project_dir, region_path)
            if resolved_path.exists():
                resolved_path.unlink()

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    # Compatibility shims for the previous desktop slice tests and call sites.
    def selected_rule(self) -> AdjustmentSummary | None:
        return self.selected_adjustment_summary()

    def set_rule_amount(self, amount: float) -> None:
        rule = self._selected_rule_model()
        if rule is None:
            return
        transform = rule.transform
        if isinstance(
            transform,
            (
                ColourAmountTransform,
                ShiftColourPointTransform,
                BrightnessTransform,
                SaturationTransform,
            ),
        ):
            transform.amount = amount
        elif isinstance(transform, ColourSmoothingTransform):
            transform.strength = amount
        else:
            return
        self._after_metadata_change(render=True)

    def set_rule_enabled(self, enabled: bool) -> None:
        self.set_selected_adjustment_enabled(enabled)

    def _find_rule(self, bundle: ProjectBundle, rule_id: str) -> DeclarativeRule | None:
        for rule in bundle.project.rules:
            if rule.id == rule_id:
                return rule
        return None

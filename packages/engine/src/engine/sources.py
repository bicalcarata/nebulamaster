from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
from image_io import (
    CanonicalImage,
    SaveImageOptions,
    load_canonical_image,
    save_image,
    sha256_file,
    translate_image,
)
from project_io import resolve_reference_path
from project_model import (
    ChannelContributionSourceMix,
    InspectAlignment,
    ManualAlignment,
    NoAlignment,
    ProjectBundle,
    SourceImage,
    TranslationAlignment,
    WeightedAverageSourceMix,
)
from pydantic import BaseModel, ConfigDict, Field


class SourcePreparationError(Exception):
    pass


class SourceAlignmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_name: str
    role: str
    reference: bool
    enabled: bool
    declared_weight: float
    alignment_mode: str
    source_path: str
    source_sha256: str
    dimensions: tuple[int, int]
    estimated_x_px: float
    estimated_y_px: float
    applied_x_px: float
    applied_y_px: float
    confidence: float
    residual_error: float
    compatible: bool
    explanation: str


class PreparedSourcesResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    image: CanonicalImage = Field(exclude=True)
    declared_source_ids: list[str]
    enabled_source_ids: list[str]
    reference_source_id: str
    source_mix_mode: str
    source_order: list[str]
    alignment_reports: list[SourceAlignmentReport]
    contribution_matrix: list[dict[str, float | str]]


_PREPARED_SOURCES_CACHE: dict[str, PreparedSourcesResult] = {}
_PREPARED_SOURCES_CACHE_LOCK = threading.Lock()


def clear_prepared_sources_cache() -> None:
    with _PREPARED_SOURCES_CACHE_LOCK:
        _PREPARED_SOURCES_CACHE.clear()


def _prepared_sources_cache_key(bundle: ProjectBundle) -> str:
    sources_payload: list[dict[str, object]] = []
    for source in bundle.project.sources:
        entry: dict[str, object] = {
            "id": source.id,
            "enabled": source.enabled,
            "reference": source.reference,
            "role": source.role,
            "weight": source.weight,
            "path": source.path.as_posix(),
            "alignment": (
                source.alignment.model_dump(mode="json")
                if source.alignment is not None
                else None
            ),
        }
        if source.enabled:
            resolved = resolve_reference_path(bundle.project_dir, source.path)
            stat_result = resolved.stat()
            entry["file_size"] = stat_result.st_size
            entry["file_mtime_ns"] = stat_result.st_mtime_ns
        sources_payload.append(entry)
    payload = {
        "project_dir": str(bundle.project_dir),
        "sources": sources_payload,
        "source_mix": bundle.project.source_mix.model_dump(mode="json"),
    }
    return json.dumps(payload, sort_keys=True)


def _luminance(image: np.ndarray) -> np.ndarray:
    return (
        0.2126 * image[:, :, 0]
        + 0.7152 * image[:, :, 1]
        + 0.0722 * image[:, :, 2]
    ).astype(np.float32, copy=False)


def _high_pass(data: np.ndarray) -> np.ndarray:
    centered = data - float(np.mean(data))
    spectrum = np.fft.fft2(centered)
    height, width = data.shape
    y = np.fft.fftfreq(height).reshape(-1, 1)
    x = np.fft.fftfreq(width).reshape(1, -1)
    radius = np.sqrt(x * x + y * y)
    mask = radius > 0.03
    filtered = np.fft.ifft2(spectrum * mask).real.astype(np.float32, copy=False)
    return filtered


def _phase_correlation(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float, float]:
    reference_hp = _high_pass(reference)
    candidate_hp = _high_pass(candidate)
    ref_fft = np.fft.fft2(reference_hp)
    cand_fft = np.fft.fft2(candidate_hp)
    cross_power = ref_fft * np.conj(cand_fft)
    magnitude = np.abs(cross_power)
    cross_power /= np.maximum(magnitude, 1e-9)
    response = np.fft.ifft2(cross_power).real.astype(np.float32, copy=False)
    peak_index = np.unravel_index(int(np.argmax(response)), response.shape)
    peak_value = float(response[peak_index])
    mean_other = float((np.sum(response) - peak_value) / max(response.size - 1, 1))
    confidence = peak_value / max(mean_other + 1e-6, 1e-6)

    y_shift = float(peak_index[0])
    x_shift = float(peak_index[1])
    height, width = response.shape
    if y_shift > height / 2:
        y_shift -= height
    if x_shift > width / 2:
        x_shift -= width

    def refine(axis_value: float, axis: int) -> float:
        idx = int(axis_value if axis_value >= 0 else axis_value + (height if axis == 0 else width))
        max_index = height if axis == 0 else width
        prev_index = (idx - 1) % max_index
        next_index = (idx + 1) % max_index
        if axis == 0:
            y, x = peak_index
            prev_value = float(response[prev_index, x])
            current_value = peak_value
            next_value = float(response[next_index, x])
        else:
            y, x = peak_index
            prev_value = float(response[y, prev_index])
            current_value = peak_value
            next_value = float(response[y, next_index])
        denominator = prev_value - 2 * current_value + next_value
        if abs(denominator) < 1e-6:
            return axis_value
        return axis_value + 0.5 * (prev_value - next_value) / denominator

    y_shift = refine(y_shift, 0)
    x_shift = refine(x_shift, 1)
    return x_shift, y_shift, confidence


def _residual_error(reference: np.ndarray, shifted: np.ndarray) -> float:
    diff = np.abs(_high_pass(reference) - _high_pass(shifted))
    return float(np.mean(diff))


def _enabled_sources(bundle: ProjectBundle) -> list[SourceImage]:
    return [source for source in bundle.project.sources if source.enabled]


def _resolve_reference_source(bundle: ProjectBundle) -> SourceImage:
    enabled_sources = _enabled_sources(bundle)
    if not enabled_sources:
        raise SourcePreparationError("project must contain at least one enabled source")
    references = [source for source in enabled_sources if source.reference]
    if len(enabled_sources) == 1 and not references:
        return enabled_sources[0]
    if len(references) != 1:
        raise SourcePreparationError("exactly one reference source is required")
    return references[0]


def _load_sources(bundle: ProjectBundle) -> dict[str, CanonicalImage]:
    loaded: dict[str, CanonicalImage] = {}
    expected_dimensions: tuple[int, int] | None = None
    for source in _enabled_sources(bundle):
        canonical = load_canonical_image(resolve_reference_path(bundle.project_dir, source.path))
        dimensions = (canonical.width, canonical.height)
        if expected_dimensions is None:
            expected_dimensions = dimensions
        elif expected_dimensions != dimensions:
            raise SourcePreparationError("The source dimensions do not match.")
        loaded[source.id] = canonical
    return loaded


def inspect_sources(bundle: ProjectBundle, *, use_cache: bool = True) -> PreparedSourcesResult:
    cache_key = _prepared_sources_cache_key(bundle)
    if use_cache:
        with _PREPARED_SOURCES_CACHE_LOCK:
            cached = _PREPARED_SOURCES_CACHE.get(cache_key)
        if cached is not None:
            return cached

    enabled_sources = _enabled_sources(bundle)
    reference = _resolve_reference_source(bundle)
    loaded = _load_sources(bundle)
    reference_image = loaded[reference.id]
    reference_luminance = _luminance(reference_image.data)
    reports: list[SourceAlignmentReport] = []
    aligned_data: dict[str, CanonicalImage] = {}

    for source in bundle.project.sources:
        if not source.enabled:
            continue
        canonical = loaded[source.id]
        alignment = source.alignment or NoAlignment()
        estimated_x = 0.0
        estimated_y = 0.0
        applied_x = 0.0
        applied_y = 0.0
        confidence = 1.0
        residual = 0.0
        compatible = True
        explanation = "This source matches the project framing."

        if source.id != reference.id:
            if isinstance(alignment, (InspectAlignment, TranslationAlignment)):
                estimated_x, estimated_y, confidence = _phase_correlation(
                    reference_luminance,
                    _luminance(canonical.data),
                )
                max_shift = alignment.max_shift_px
                if max(abs(estimated_x), abs(estimated_y)) > max_shift:
                    compatible = False
                    explanation = f"The {source.name} source is offset too far from the reference."
                elif confidence < 5.0:
                    compatible = False
                    explanation = (
                        "Automatic alignment is uncertain; use a manual offset "
                        "or recapture with the same framing."
                    )
                residual = _residual_error(
                    reference_luminance,
                    translate_image(
                        canonical,
                        x_px=estimated_x,
                        y_px=estimated_y,
                    ).data[:, :, 0],
                )
                if isinstance(alignment, TranslationAlignment) and compatible:
                    applied_x = estimated_x
                    applied_y = estimated_y
            elif isinstance(alignment, ManualAlignment):
                applied_x = alignment.x_px
                applied_y = alignment.y_px
                residual = _residual_error(
                    reference_luminance,
                    translate_image(canonical, x_px=applied_x, y_px=applied_y).data[:, :, 0],
                )
            elif isinstance(alignment, NoAlignment):
                pass

        aligned = translate_image(canonical, x_px=applied_x, y_px=applied_y)
        aligned_data[source.id] = aligned
        reports.append(
            SourceAlignmentReport(
                source_id=source.id,
                source_name=source.name or source.id,
                role=source.role,
                reference=source.id == reference.id,
                enabled=source.enabled,
                declared_weight=source.weight,
                alignment_mode=alignment.mode,
                source_path=source.path.as_posix(),
                source_sha256=sha256_file(resolve_reference_path(bundle.project_dir, source.path)),
                dimensions=(canonical.width, canonical.height),
                estimated_x_px=float(estimated_x),
                estimated_y_px=float(estimated_y),
                applied_x_px=float(applied_x),
                applied_y_px=float(applied_y),
                confidence=float(confidence),
                residual_error=float(residual),
                compatible=compatible,
                explanation=explanation,
            )
        )

    mixed = mix_sources(bundle, aligned_data)
    result = PreparedSourcesResult(
        image=mixed,
        declared_source_ids=[source.id for source in bundle.project.sources],
        enabled_source_ids=[source.id for source in enabled_sources],
        reference_source_id=reference.id,
        source_mix_mode=bundle.project.source_mix.mode,
        source_order=[source.id for source in enabled_sources],
        alignment_reports=reports,
        contribution_matrix=contribution_matrix_for_project(bundle),
    )
    if use_cache:
        with _PREPARED_SOURCES_CACHE_LOCK:
            _PREPARED_SOURCES_CACHE[cache_key] = result
    return result


def contribution_matrix_for_project(bundle: ProjectBundle) -> list[dict[str, float | str]]:
    if isinstance(bundle.project.source_mix, ChannelContributionSourceMix):
        return [entry.model_dump(mode="json") for entry in bundle.project.source_mix.contributions]
    return [
        {
            "source": source.id,
            "red": float(source.weight),
            "green": float(source.weight),
            "blue": float(source.weight),
        }
        for source in _enabled_sources(bundle)
    ]


def mix_sources(bundle: ProjectBundle, aligned_data: dict[str, CanonicalImage]) -> CanonicalImage:
    enabled_sources = _enabled_sources(bundle)
    if len(enabled_sources) == 1:
        return aligned_data[enabled_sources[0].id]

    source_mix = bundle.project.source_mix
    source_order = [source.id for source in enabled_sources]
    data = [aligned_data[source_id].data for source_id in source_order]
    weights = np.asarray([source.weight for source in enabled_sources], dtype=np.float32)

    if isinstance(source_mix, WeightedAverageSourceMix):
        total = float(np.sum(weights))
        if total <= 0.0:
            raise SourcePreparationError("zero total contribution is invalid")
        normalized = weights / total
        mixed = np.zeros_like(data[0], dtype=np.float32)
        for source_data, weight in zip(data, normalized, strict=True):
            mixed += source_data * weight
    elif source_mix.mode == "lighten":
        mixed = np.zeros_like(data[0], dtype=np.float32)
        for source_data, weight in zip(data, weights, strict=True):
            mixed = np.maximum(mixed, source_data * weight)
    elif source_mix.mode == "screen":
        mixed = np.zeros_like(data[0], dtype=np.float32)
        total = np.maximum(float(np.max(weights)), 1.0)
        for source_data, weight in zip(data, weights, strict=True):
            weighted = np.clip(source_data * (weight / total), 0.0, 1.0)
            mixed = 1.0 - (1.0 - mixed) * (1.0 - weighted)
    else:
        assert isinstance(source_mix, ChannelContributionSourceMix)
        mixed = np.zeros_like(data[0], dtype=np.float32)
        for contribution in source_mix.contributions:
            source_data = aligned_data[contribution.source].data
            mixed[:, :, 0] += source_data[:, :, 0] * contribution.red
            mixed[:, :, 1] += source_data[:, :, 1] * contribution.green
            mixed[:, :, 2] += source_data[:, :, 2] * contribution.blue

    return CanonicalImage(
        data=np.asarray(mixed, dtype=np.float32),
        width=aligned_data[source_order[0]].width,
        height=aligned_data[source_order[0]].height,
    )


def write_aligned_bundle(bundle: ProjectBundle, output_dir: Path) -> Path:
    prepared = inspect_sources(bundle)
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_id = prepared.reference_source_id
    for report in prepared.alignment_reports:
        source = next(source for source in bundle.project.sources if source.id == report.source_id)
        canonical = load_canonical_image(resolve_reference_path(bundle.project_dir, source.path))
        aligned = translate_image(
            canonical,
            x_px=report.applied_x_px,
            y_px=report.applied_y_px,
        )
        if report.source_id == reference_id:
            destination = output_dir / "reference.tiff"
        else:
            destination = output_dir / "aligned" / f"{report.source_id}.tiff"
            destination.parent.mkdir(parents=True, exist_ok=True)
        save_image(
            destination,
            aligned,
            options=SaveImageOptions(format="tiff", bit_depth=16, jpeg_quality=None),
        )

    manifest_path = output_dir / "alignment-manifest.json"
    manifest_path.write_text(
        json.dumps(prepared.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return manifest_path

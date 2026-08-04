from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from project_model import DarkDustSettings

from .selection import box_blur, compute_luminance


@dataclass(frozen=True)
class DarkDustAnalysis:
    final_mask: np.ndarray
    veil_mask: np.ndarray
    core_mask: np.ndarray
    relative_darkness: np.ndarray
    local_illumination: np.ndarray
    background_support: np.ndarray

    @property
    def coverage_percent(self) -> float:
        return float(np.mean(self.final_mask) * 100.0)


def star_influence(image_rgb: np.ndarray) -> np.ndarray:
    height, width = image_rgb.shape[:2]
    # Compare each pixel against a broader local baseline so compact stars
    # separate from diffuse nebula glow even when the source is relatively dim.
    radius_pixels = max(2, int(round(min(height, width) * 0.02)))

    luminance = compute_luminance(image_rgb)
    luminance_rgb = np.repeat(luminance[..., None], 3, axis=-1)
    local_average = box_blur(luminance_rgb, radius_pixels)[..., 0]

    peak = np.max(image_rgb, axis=-1)
    minimum = np.min(image_rgb, axis=-1)
    ratio = np.divide(luminance, np.maximum(local_average, 1e-4))
    delta = np.clip(luminance - local_average, 0.0, None)
    neutrality = 1.0 - np.divide(peak - minimum, np.maximum(peak, 1e-4))

    compact_ratio = np.clip((ratio - 1.03) / 0.25, 0.0, 1.0)
    compact_delta = np.clip(delta / 0.025, 0.0, 1.0)
    compact_peak = np.clip((peak - 0.12) / 0.22, 0.0, 1.0)
    compact_neutrality = np.clip((neutrality - 0.86) / 0.12, 0.0, 1.0)

    core_weights = np.clip(
        compact_ratio * compact_delta * compact_peak * compact_neutrality,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    # Protect the visible halo around bright stars as well as the compact core.
    # This keeps nebula-targeted colour treatments from tinting stellar halos
    # cyan, gold or red while still leaving broad nebula structure untouched.
    halo_radius = max(3, min(6, int(round(min(height, width) * 0.004))))
    halo_seed = box_blur(
        np.repeat(core_weights[..., None], 3, axis=-1),
        halo_radius,
    )[..., 0]
    halo_seed = np.clip(halo_seed * 5.0, 0.0, 1.0).astype(np.float32, copy=False)
    halo_peak = np.clip((peak - 0.10) / 0.25, 0.0, 1.0).astype(np.float32, copy=False)
    halo_lift = np.clip((peak - local_average) / 0.18, 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )
    halo_weights = np.clip(
        halo_seed * halo_peak * halo_lift,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    weights = np.maximum(core_weights, halo_weights).astype(np.float32, copy=False)
    return np.asarray(weights, dtype=np.float32)


def _radius_from_fraction(
    shorter: int,
    fraction: float,
    *,
    minimum: int,
    maximum: int,
) -> int:
    radius = int(round(shorter * fraction))
    return max(minimum, min(maximum, radius))


def _weighted_blur(
    plane: np.ndarray,
    weights: np.ndarray,
    radius_pixels: int,
) -> np.ndarray:
    weighted_plane = box_blur(
        np.repeat((plane * weights)[..., None], 3, axis=-1),
        radius_pixels,
    )[..., 0]
    blurred_weights = box_blur(
        np.repeat(weights[..., None], 3, axis=-1),
        radius_pixels,
    )[..., 0]
    averaged = np.divide(
        weighted_plane,
        np.maximum(blurred_weights, 1e-6),
        out=np.zeros_like(weighted_plane, dtype=np.float32),
        where=blurred_weights > 1e-6,
    )
    return np.asarray(averaged, dtype=np.float32)


def _smoothstep(value: np.ndarray, edge0: float, edge1: float) -> np.ndarray:
    if edge1 <= edge0:
        binary = np.where(value >= edge1, 1.0, 0.0).astype(np.float32)
        return np.asarray(binary, dtype=np.float32)
    t = np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0).astype(np.float32, copy=False)
    smoothed = (t * t * (3.0 - 2.0 * t)).astype(np.float32, copy=False)
    return np.asarray(smoothed, dtype=np.float32)


def analyze_dark_dust(
    image_rgb: np.ndarray,
    settings: DarkDustSettings | None = None,
) -> DarkDustAnalysis:
    resolved = settings or DarkDustSettings()
    if not resolved.enabled:
        zero = np.zeros(image_rgb.shape[:2], dtype=np.float32)
        return DarkDustAnalysis(
            final_mask=zero,
            veil_mask=zero,
            core_mask=zero,
            relative_darkness=zero,
            local_illumination=zero,
            background_support=zero,
        )

    height, width = image_rgb.shape[:2]
    shorter = min(height, width)
    luminance = compute_luminance(image_rgb).astype(np.float32, copy=False)
    stars = star_influence(image_rgb)
    non_star = np.clip(1.0 - stars, 0.0, 1.0).astype(np.float32, copy=False)

    structure = resolved.structure_size
    medium_radius = _radius_from_fraction(
        shorter,
        0.008 + (0.040 * structure),
        minimum=3,
        maximum=max(6, int(round(shorter * 0.05))),
    )
    broad_radius = _radius_from_fraction(
        shorter,
        0.32 + (0.24 * structure),
        minimum=max(medium_radius + 6, int(round(shorter * 0.24))),
        maximum=max(24, int(round(shorter * 0.48))),
    )
    suppression_radius = max(1, int(round(medium_radius * 0.5)))
    veil_feather_radius = max(
        1,
        int(round((medium_radius * 0.7) + (broad_radius * resolved.softness * 0.4))),
    )
    core_feather_radius = max(
        1,
        int(round((medium_radius * 0.35) + (medium_radius * resolved.softness * 0.25))),
    )

    medium_illumination = _weighted_blur(luminance, non_star, medium_radius)
    broad_illumination = _weighted_blur(luminance, non_star, broad_radius)
    local_illumination = np.maximum(medium_illumination, broad_illumination).astype(
        np.float32,
        copy=False,
    )

    medium_relative_darkness = np.clip(
        (medium_illumination - luminance) / np.maximum(medium_illumination, 1e-6),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    broad_relative_darkness = np.clip(
        (broad_illumination - luminance) / np.maximum(broad_illumination, 1e-6),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    relative_darkness = np.maximum(medium_relative_darkness, broad_relative_darkness).astype(
        np.float32,
        copy=False,
    )

    low_frequency_structure = np.clip(
        np.abs(medium_illumination - broad_illumination) / np.maximum(broad_illumination, 1e-6),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    local_variance = _weighted_blur(
        np.abs(luminance - medium_illumination),
        non_star,
        max(1, int(round(medium_radius * 0.8))),
    )

    illumination_floor = 0.003 + (0.06 * resolved.background_protection)
    illumination_support = _smoothstep(
        broad_illumination,
        illumination_floor,
        illumination_floor + 0.10,
    )
    structure_support = _smoothstep(
        low_frequency_structure,
        0.0015,
        0.022 + (0.050 * structure),
    )
    variance_support = _smoothstep(
        local_variance,
        0.0008,
        0.012,
    )
    darkness_support = _smoothstep(
        np.maximum(broad_relative_darkness, medium_relative_darkness),
        0.010,
        0.055,
    )
    non_star_support = np.power(non_star, 1.15).astype(np.float32, copy=False)
    background_support = np.clip(
        illumination_support
        * np.maximum(np.maximum(structure_support, variance_support), darkness_support)
        * non_star_support,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    core_support = np.clip(
        illumination_support
        * np.maximum(darkness_support, np.maximum(variance_support, structure_support * 0.5))
        * non_star_support,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    veil_signal = np.clip(
        ((0.55 * broad_relative_darkness) + (0.45 * medium_relative_darkness))
        * background_support
        * (0.70 + (0.30 * structure_support)),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    core_signal = np.clip(
        np.maximum(medium_relative_darkness, broad_relative_darkness)
        * core_support
        * (0.55 + (0.45 * np.maximum(veil_signal, structure_support))),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    veil_threshold = np.clip(
        0.10 - (0.06 * resolved.sensitivity) - (0.04 * resolved.veil_strength),
        0.01,
        0.16,
    )
    core_threshold = np.clip(
        0.08 - (0.05 * resolved.sensitivity) - (0.04 * resolved.core_strength),
        0.015,
        0.14,
    )
    edge_softness = 0.025 + (0.10 * resolved.softness)
    veil_mask = _smoothstep(
        veil_signal,
        max(0.0, veil_threshold - edge_softness),
        veil_threshold + edge_softness,
    )
    core_mask = _smoothstep(
        core_signal,
        max(0.0, core_threshold - edge_softness),
        core_threshold + edge_softness,
    )

    veil_cluster = _weighted_blur(veil_mask, non_star, suppression_radius)
    core_cluster = _weighted_blur(core_mask, non_star, suppression_radius)
    veil_mask = np.where(veil_cluster >= 0.012, veil_mask, 0.0).astype(np.float32, copy=False)
    core_mask = np.where(core_cluster >= 0.018, core_mask, 0.0).astype(np.float32, copy=False)

    veil_mask = _weighted_blur(veil_mask, non_star, veil_feather_radius)
    core_mask = _weighted_blur(core_mask, non_star, core_feather_radius)
    core_mask = np.clip(
        core_mask * (0.45 + (0.55 * np.maximum(veil_mask, structure_support))),
        0.0,
        1.0,
    )

    balance = resolved.veil_core_balance
    veil_weight = resolved.veil_strength * (1.20 - (0.60 * balance))
    core_weight = resolved.core_strength * (0.65 + (0.70 * balance))
    final_mask = np.clip((veil_weight * veil_mask) + (core_weight * core_mask), 0.0, 1.0)
    final_mask = np.clip(final_mask * non_star, 0.0, 1.0).astype(np.float32, copy=False)
    veil_mask = np.clip(veil_mask * non_star, 0.0, 1.0).astype(np.float32, copy=False)
    core_mask = np.clip(core_mask * non_star, 0.0, 1.0).astype(np.float32, copy=False)

    return DarkDustAnalysis(
        final_mask=np.asarray(final_mask, dtype=np.float32),
        veil_mask=np.asarray(veil_mask, dtype=np.float32),
        core_mask=np.asarray(core_mask, dtype=np.float32),
        relative_darkness=np.asarray(relative_darkness, dtype=np.float32),
        local_illumination=np.asarray(local_illumination, dtype=np.float32),
        background_support=np.asarray(background_support, dtype=np.float32),
    )


def dark_dust_influence(
    image_rgb: np.ndarray,
    settings: DarkDustSettings | None = None,
) -> np.ndarray:
    return analyze_dark_dust(image_rgb, settings).final_mask


def semantic_target_influence(
    image_rgb: np.ndarray,
    target: str,
    dark_dust_settings: DarkDustSettings | None = None,
) -> np.ndarray:
    target_id = target.lower()
    if target_id == "combined":
        return np.ones(image_rgb.shape[:2], dtype=np.float32)
    if target_id == "stars":
        return star_influence(image_rgb)
    if target_id == "nebula":
        return np.asarray(1.0 - star_influence(image_rgb), dtype=np.float32)
    if target_id == "dark_dust":
        return dark_dust_influence(image_rgb, dark_dust_settings)
    return np.ones(image_rgb.shape[:2], dtype=np.float32)

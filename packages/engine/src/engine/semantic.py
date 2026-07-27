from __future__ import annotations

import numpy as np
from project_model import DarkDustSettings

from .selection import box_blur, compute_luminance


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

    weights = np.clip(
        compact_ratio * compact_delta * compact_peak * compact_neutrality,
        0.0,
        1.0,
    )
    return np.asarray(weights.astype(np.float32, copy=False), dtype=np.float32)


def dark_dust_influence(
    image_rgb: np.ndarray,
    settings: DarkDustSettings | None = None,
) -> np.ndarray:
    resolved = settings or DarkDustSettings()
    if not resolved.enabled:
        return np.zeros(image_rgb.shape[:2], dtype=np.float32)

    height, width = image_rgb.shape[:2]
    shorter = min(height, width)
    luminance = compute_luminance(image_rgb).astype(np.float32, copy=False)
    stars = star_influence(image_rgb)
    non_star = np.clip(1.0 - stars, 0.0, 1.0).astype(np.float32, copy=False)

    structure_radius = max(3, int(round(shorter * resolved.structure_size)))
    local_illumination = box_blur(
        np.repeat(luminance[..., None], 3, axis=-1),
        structure_radius,
    )[..., 0].astype(np.float32, copy=False)
    broad_illumination = box_blur(
        np.repeat(luminance[..., None], 3, axis=-1),
        max(structure_radius + 4, int(round(structure_radius * 4.0))),
    )[..., 0].astype(np.float32, copy=False)
    local_illumination = np.maximum(local_illumination, broad_illumination).astype(
        np.float32,
        copy=False,
    )
    relative_darkness = np.clip(local_illumination - luminance, 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )

    sensitivity_floor = max(0.0025, 0.055 * (1.0 - resolved.sensitivity))
    sensitivity_span = max(0.01, 0.12 - (0.08 * resolved.sensitivity))
    base = np.clip(
        (relative_darkness - sensitivity_floor) / sensitivity_span,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    background_floor = 0.015 + (0.18 * resolved.background_protection)
    background_span = max(0.02, 0.22 - (0.10 * resolved.background_protection))
    background_guard = np.clip(
        (local_illumination - background_floor) / background_span,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    isolation_radius = max(1, int(round(structure_radius * 0.35)))
    clustered = box_blur(
        np.repeat(base[..., None], 3, axis=-1),
        isolation_radius,
    )[..., 0].astype(np.float32, copy=False)
    cluster_floor = 0.025 + (0.04 * (1.0 - resolved.sensitivity))
    cluster_span = max(0.02, 0.16 - (0.05 * resolved.background_protection))
    cluster_guard = np.clip(
        (clustered - cluster_floor) / cluster_span,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    softened = box_blur(
        np.repeat((base * background_guard * cluster_guard)[..., None], 3, axis=-1),
        max(1, int(round(structure_radius * max(resolved.softness, 0.05)))),
    )[..., 0].astype(np.float32, copy=False)
    feather_floor = max(0.0, 0.18 - (0.12 * resolved.softness))
    feathered = np.clip(
        (softened - feather_floor) / max(0.04, 1.0 - feather_floor),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    result = np.clip(feathered * non_star, 0.0, 1.0).astype(np.float32, copy=False)
    return np.asarray(result, dtype=np.float32)


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

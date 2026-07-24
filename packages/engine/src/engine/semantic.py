from __future__ import annotations

import numpy as np

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


def semantic_target_influence(image_rgb: np.ndarray, target: str) -> np.ndarray:
    target_id = target.lower()
    if target_id == "combined":
        return np.ones(image_rgb.shape[:2], dtype=np.float32)
    if target_id == "stars":
        return star_influence(image_rgb)
    if target_id == "nebula":
        return np.asarray(1.0 - star_influence(image_rgb), dtype=np.float32)
    return np.ones(image_rgb.shape[:2], dtype=np.float32)

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from project_model import (
    FAUX_PALETTE_SUPPORTED_COLOUR_BALANCE_KEYS as PROJECT_FAUX_PALETTE_SUPPORTED_KEYS,
)

LINEAR_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
LUMA_WEIGHT = 0.25
EPSILON = 1e-6
CHANNEL_INDEX = {"red": 0, "green": 1, "blue": 2}
FAUX_PALETTE_SUPPORTED_COLOUR_BALANCE_KEYS: dict[str, tuple[str, ...]] = {
    key: value for key, value in PROJECT_FAUX_PALETTE_SUPPORTED_KEYS.items()
}


@dataclass(frozen=True)
class FauxPaletteColourControlDefinition:
    key: str
    component_weights: tuple[float, float, float, float]


@dataclass(frozen=True)
class FauxPaletteDefinition:
    warm_target: tuple[float, float, float]
    red_target: tuple[float, float, float]
    cool_target: tuple[float, float, float]
    neutral_target: tuple[float, float, float]
    warm_weight: float
    red_weight: float
    cool_weight: float
    neutral_weight: float
    separation: float
    green_reduction: float
    saturation_scale: float
    original_chroma_mix: float
    colour_controls: tuple[FauxPaletteColourControlDefinition, ...]


FAUX_PALETTES: dict[str, FauxPaletteDefinition] = {
    "hubble": FauxPaletteDefinition(
        warm_target=(1.00, 0.12, 0.06),
        red_target=(0.16, 0.86, 0.20),
        cool_target=(0.06, 0.58, 1.00),
        neutral_target=(0.28, 0.26, 0.30),
        warm_weight=1.00,
        red_weight=1.05,
        cool_weight=1.00,
        neutral_weight=0.22,
        separation=0.70,
        green_reduction=0.35,
        saturation_scale=1.02,
        original_chroma_mix=0.06,
        colour_controls=(
            FauxPaletteColourControlDefinition("gold", (1.0, 0.0, 0.0, 0.0)),
            FauxPaletteColourControlDefinition("green", (0.0, 1.0, 0.0, 0.0)),
            FauxPaletteColourControlDefinition("cyan", (0.0, 0.0, 1.0, 0.0)),
        ),
    ),
    "hoo": FauxPaletteDefinition(
        warm_target=(1.00, 0.18, 0.08),
        red_target=(0.95, 0.10, 0.12),
        cool_target=(0.04, 0.72, 1.00),
        neutral_target=(0.40, 0.28, 0.34),
        warm_weight=1.00,
        red_weight=0.98,
        cool_weight=0.92,
        neutral_weight=0.24,
        separation=0.72,
        green_reduction=0.32,
        saturation_scale=1.00,
        original_chroma_mix=0.08,
        colour_controls=(
            FauxPaletteColourControlDefinition("red", (1.0, 1.0, 0.0, 0.0)),
            FauxPaletteColourControlDefinition("cyan", (0.0, 0.0, 1.0, 0.0)),
        ),
    ),
    "foraxx": FauxPaletteDefinition(
        warm_target=(1.00, 0.48, 0.05),
        red_target=(0.88, 0.28, 0.04),
        cool_target=(0.02, 0.52, 1.00),
        neutral_target=(0.34, 0.24, 0.24),
        warm_weight=1.08,
        red_weight=0.96,
        cool_weight=1.06,
        neutral_weight=0.18,
        separation=0.95,
        green_reduction=0.26,
        saturation_scale=1.08,
        original_chroma_mix=0.04,
        colour_controls=(
            FauxPaletteColourControlDefinition("amber", (1.0, 1.0, 0.0, 0.0)),
            FauxPaletteColourControlDefinition("cyan", (0.0, 0.0, 1.0, 0.0)),
        ),
    ),
    "gold_cyan": FauxPaletteDefinition(
        warm_target=(1.00, 0.62, 0.10),
        red_target=(0.84, 0.42, 0.08),
        cool_target=(0.02, 0.78, 0.90),
        neutral_target=(0.38, 0.34, 0.30),
        warm_weight=0.98,
        red_weight=0.90,
        cool_weight=0.92,
        neutral_weight=0.28,
        separation=0.58,
        green_reduction=0.22,
        saturation_scale=0.94,
        original_chroma_mix=0.12,
        colour_controls=(
            FauxPaletteColourControlDefinition("gold", (1.0, 1.0, 0.0, 0.0)),
            FauxPaletteColourControlDefinition("cyan", (0.0, 0.0, 1.0, 0.0)),
        ),
    ),
    "natural_bicolour": FauxPaletteDefinition(
        warm_target=(0.92, 0.28, 0.18),
        red_target=(0.82, 0.22, 0.28),
        cool_target=(0.12, 0.62, 0.82),
        neutral_target=(0.46, 0.44, 0.45),
        warm_weight=0.92,
        red_weight=0.88,
        cool_weight=0.84,
        neutral_weight=0.36,
        separation=0.42,
        green_reduction=0.18,
        saturation_scale=0.82,
        original_chroma_mix=0.28,
        colour_controls=(
            FauxPaletteColourControlDefinition("warm", (1.0, 1.0, 0.0, 0.0)),
            FauxPaletteColourControlDefinition("cool", (0.0, 0.0, 1.0, 0.0)),
        ),
    ),
}


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    threshold = 0.04045
    linear = np.where(
        rgb <= threshold,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    ).astype(np.float32, copy=False)
    return np.asarray(linear, dtype=np.float32)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    threshold = 0.0031308
    encoded = np.where(
        rgb <= threshold,
        rgb * 12.92,
        1.055 * np.power(np.clip(rgb, 0.0, None), 1.0 / 2.4) - 0.055,
    ).astype(np.float32, copy=False)
    return np.asarray(encoded, dtype=np.float32)


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    linear = srgb_to_linear(rgb)
    l_channel = (
        0.4122214708 * linear[..., 0]
        + 0.5363325363 * linear[..., 1]
        + 0.0514459929 * linear[..., 2]
    )
    m_channel = (
        0.2119034982 * linear[..., 0]
        + 0.6806995451 * linear[..., 1]
        + 0.1073969566 * linear[..., 2]
    )
    s_channel = (
        0.0883024619 * linear[..., 0]
        + 0.2817188376 * linear[..., 1]
        + 0.6299787005 * linear[..., 2]
    )

    l_root = np.cbrt(np.clip(l_channel, 0.0, None))
    m_root = np.cbrt(np.clip(m_channel, 0.0, None))
    s_root = np.cbrt(np.clip(s_channel, 0.0, None))

    lab_l = 0.2104542553 * l_root + 0.7936177850 * m_root - 0.0040720468 * s_root
    lab_a = 1.9779984951 * l_root - 2.4285922050 * m_root + 0.4505937099 * s_root
    lab_b = 0.0259040371 * l_root + 0.7827717662 * m_root - 0.8086757660 * s_root

    stacked = np.stack([lab_l, lab_a, lab_b], axis=-1).astype(np.float32, copy=False)
    return np.asarray(stacked, dtype=np.float32)


def smooth_falloff(value: np.ndarray, limit: float, softness: float) -> np.ndarray:
    if limit <= 0.0:
        binary = np.where(value <= 0.0, 1.0, 0.0).astype(np.float32)
        return np.asarray(binary, dtype=np.float32)

    softness_width = limit * softness
    inner_limit = max(0.0, limit - softness_width)

    if inner_limit == limit:
        binary = (value <= limit).astype(np.float32)
        return np.asarray(binary, dtype=np.float32)

    t = np.clip((value - inner_limit) / max(limit - inner_limit, EPSILON), 0.0, 1.0)
    falloff = (1.0 - (t * t * (3.0 - 2.0 * t))).astype(np.float32, copy=False)
    return np.asarray(falloff, dtype=np.float32)


def brightness_weight(
    luminance: np.ndarray,
    minimum: float,
    maximum: float,
    softness: float,
) -> np.ndarray:
    inside = np.logical_and(luminance >= minimum, luminance <= maximum)
    if softness <= 0.0:
        binary = inside.astype(np.float32)
        return np.asarray(binary, dtype=np.float32)

    width = max(maximum - minimum, EPSILON)
    edge = width * softness

    lower = np.ones_like(luminance, dtype=np.float32)
    if edge > 0.0:
        lower_zone = np.logical_and(luminance >= minimum - edge, luminance < minimum)
        lower[lower_zone] = ((luminance[lower_zone] - (minimum - edge)) / edge).astype(np.float32)
        lower[luminance < minimum - edge] = 0.0
    else:
        lower[luminance < minimum] = 0.0

    upper = np.ones_like(luminance, dtype=np.float32)
    if edge > 0.0:
        upper_zone = np.logical_and(luminance > maximum, luminance <= maximum + edge)
        upper[upper_zone] = (1.0 - ((luminance[upper_zone] - maximum) / edge)).astype(np.float32)
        upper[luminance > maximum + edge] = 0.0
    else:
        upper[luminance > maximum] = 0.0

    merged = np.clip(np.minimum(lower, upper), 0.0, 1.0).astype(np.float32, copy=False)
    return np.asarray(merged, dtype=np.float32)


def saturation_weight(
    image_rgb: np.ndarray,
    minimum: float,
    maximum: float,
    softness: float,
) -> np.ndarray:
    channel_max = np.max(image_rgb, axis=-1)
    channel_min = np.min(image_rgb, axis=-1)
    saturation = np.divide(
        channel_max - channel_min,
        channel_max,
        out=np.zeros_like(channel_max, dtype=np.float32),
        where=channel_max > 0.0,
    )
    return brightness_weight(saturation.astype(np.float32), minimum, maximum, softness)


def colour_weight(
    image_rgb: np.ndarray,
    target_rgb: np.ndarray,
    colour_range: float,
    softness: float,
) -> np.ndarray:
    image_lab = rgb_to_oklab(image_rgb)
    target_lab = rgb_to_oklab(target_rgb.reshape(1, 1, 3))[0, 0]

    delta_l = (image_lab[..., 0] - target_lab[0]) * LUMA_WEIGHT
    delta_a = image_lab[..., 1] - target_lab[1]
    delta_b = image_lab[..., 2] - target_lab[2]
    distance = np.sqrt(delta_l * delta_l + delta_a * delta_a + delta_b * delta_b)
    weight = smooth_falloff(distance.astype(np.float32, copy=False), colour_range, softness)
    return np.asarray(weight, dtype=np.float32)


def compute_luminance(image_rgb: np.ndarray) -> np.ndarray:
    linear = srgb_to_linear(image_rgb)
    luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0])).astype(np.float32, copy=False)
    return np.asarray(luminance, dtype=np.float32)


def _preserve_luminance(transformed: np.ndarray, original_luminance: np.ndarray) -> np.ndarray:
    transformed_luminance = np.tensordot(transformed, LINEAR_LUMA, axes=([-1], [0]))
    scale = np.divide(original_luminance, np.maximum(transformed_luminance, EPSILON))
    adjusted = transformed * scale[..., None]
    clipped = np.clip(adjusted, 0.0, 1.0).astype(np.float32, copy=False)
    return np.asarray(clipped, dtype=np.float32)


def apply_weighted_image_blend(
    current_rgb: np.ndarray,
    transformed_linear: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    current_linear = srgb_to_linear(current_rgb)
    mixed = (
        current_linear * (1.0 - weights[..., None])
    ) + (transformed_linear * weights[..., None])
    output = np.clip(linear_to_srgb(mixed), 0.0, 1.0).astype(np.float32, copy=False)
    return np.asarray(output, dtype=np.float32)


def apply_weighted_channel_transform(
    image_rgb: np.ndarray,
    weights: np.ndarray,
    channel_index: int,
    delta: float,
    preserve_luminance: bool,
) -> np.ndarray:
    linear = srgb_to_linear(image_rgb)
    original_luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0]))

    transformed = linear.copy()
    transformed[..., channel_index] = np.clip(
        transformed[..., channel_index] + (delta * weights),
        0.0,
        1.0,
    )

    if preserve_luminance:
        transformed = _preserve_luminance(transformed, original_luminance)

    return apply_weighted_image_blend(image_rgb, transformed, weights)


def apply_colour_amount(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    channel: str,
    amount: float,
    preserve_luminance: bool,
) -> np.ndarray:
    linear = srgb_to_linear(current_rgb)
    original_luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0]))
    transformed = linear.copy()
    channel_index = CHANNEL_INDEX[channel]
    delta = amount - 1.0
    transformed[..., channel_index] = np.clip(
        transformed[..., channel_index] + (delta * weights),
        0.0,
        1.0,
    )
    if preserve_luminance:
        transformed = _preserve_luminance(transformed, original_luminance)
    return apply_weighted_image_blend(current_rgb, transformed, weights)


def apply_shift_colour_point(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    target_rgb: np.ndarray,
    amount: float,
    preserve_luminance: bool,
) -> np.ndarray:
    linear = srgb_to_linear(current_rgb)
    target_linear = srgb_to_linear(target_rgb.reshape(1, 1, 3))[0, 0]
    original_luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0]))

    target_image = np.broadcast_to(target_linear, linear.shape).copy()
    if preserve_luminance:
        target_image = _preserve_luminance(target_image, original_luminance)

    transformed = (linear * (1.0 - amount)) + (target_image * amount)
    transformed = np.clip(transformed, 0.0, 1.0).astype(np.float32, copy=False)
    return apply_weighted_image_blend(current_rgb, transformed, weights)


def apply_brightness_transform(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    amount: float,
) -> np.ndarray:
    linear = srgb_to_linear(current_rgb)
    transformed = np.clip(linear * amount, 0.0, 1.0).astype(np.float32, copy=False)
    return apply_weighted_image_blend(current_rgb, transformed, weights)


def apply_saturation_transform(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    amount: float,
) -> np.ndarray:
    linear = srgb_to_linear(current_rgb)
    luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0]))
    gray = np.repeat(luminance[..., None], 3, axis=-1)
    transformed = np.clip(
        gray + ((linear - gray) * amount),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    return apply_weighted_image_blend(current_rgb, transformed, weights)


def apply_levels_transform(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    *,
    darkest: float,
    dark: float,
    mid: float,
    light: float,
    brightest: float,
) -> np.ndarray:
    linear = srgb_to_linear(current_rgb)
    luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0])).astype(np.float32, copy=False)
    centers = np.asarray([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    amounts = np.asarray([darkest, dark, mid, light, brightest], dtype=np.float32)

    factor = np.zeros_like(luminance, dtype=np.float32)
    factor[luminance <= centers[0]] = amounts[0]
    factor[luminance >= centers[-1]] = amounts[-1]

    for index in range(len(centers) - 1):
        left = centers[index]
        right = centers[index + 1]
        in_segment = np.logical_and(luminance >= left, luminance <= right)
        if not np.any(in_segment):
            continue
        t = ((luminance[in_segment] - left) / max(right - left, EPSILON)).astype(
            np.float32,
            copy=False,
        )
        factor[in_segment] = ((1.0 - t) * amounts[index]) + (t * amounts[index + 1])

    transformed = np.clip(linear * factor[..., None], 0.0, 1.0).astype(np.float32, copy=False)
    return apply_weighted_image_blend(current_rgb, transformed, weights)


def box_blur(image_rgb: np.ndarray, radius_pixels: int) -> np.ndarray:
    if radius_pixels <= 0:
        return image_rgb.astype(np.float32, copy=True)

    padded = np.pad(
        image_rgb,
        ((radius_pixels, radius_pixels), (radius_pixels, radius_pixels), (0, 0)),
        mode="edge",
    ).astype(np.float32, copy=False)
    window_size = (radius_pixels * 2) + 1

    integral = padded.cumsum(axis=0, dtype=np.float32).cumsum(axis=1, dtype=np.float32)
    integral = np.pad(integral, ((1, 0), (1, 0), (0, 0)), mode="constant")

    window_sum = (
        integral[window_size:, window_size:]
        - integral[:-window_size, window_size:]
        - integral[window_size:, :-window_size]
        + integral[:-window_size, :-window_size]
    )
    blurred = (window_sum / float(window_size * window_size)).astype(np.float32, copy=False)
    return np.asarray(blurred, dtype=np.float32)


def apply_colour_smoothing(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    radius_fraction: float,
    strength: float,
) -> np.ndarray:
    radius_pixels = int(
        round(radius_fraction * float(min(current_rgb.shape[0], current_rgb.shape[1])))
    )
    if radius_pixels <= 0 or strength <= 0.0:
        return current_rgb.astype(np.float32, copy=True)

    blurred = box_blur(current_rgb, radius_pixels)
    mix = np.clip(weights * strength, 0.0, 1.0).astype(np.float32, copy=False)
    output = (current_rgb * (1.0 - mix[..., None])) + (blurred * mix[..., None])
    clipped = np.clip(output, 0.0, 1.0).astype(np.float32, copy=False)
    return np.asarray(clipped, dtype=np.float32)


def apply_dark_nebula_processing(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    *,
    veil_mask: np.ndarray,
    core_mask: np.ndarray,
    local_illumination: np.ndarray,
    relative_darkness: np.ndarray,
    amount: float,
    reveal_dust: float,
    dust_contrast: float,
    core_depth: float,
    dust_colour: float,
    softness: float,
    preserve_bright_areas: bool,
) -> np.ndarray:
    if amount <= 0.0:
        return current_rgb.astype(np.float32, copy=True)

    linear = srgb_to_linear(current_rgb)
    luminance = np.tensordot(linear, LINEAR_LUMA, axes=([-1], [0])).astype(np.float32, copy=False)
    shorter = float(min(current_rgb.shape[0], current_rgb.shape[1]))
    smoothing_radius = max(1, int(round(shorter * (0.003 + (0.012 * softness)))))

    bright_protection = np.ones_like(luminance, dtype=np.float32)
    if preserve_bright_areas:
        highlight_t = np.clip((luminance - 0.14) / 0.16, 0.0, 1.0).astype(
            np.float32,
            copy=False,
        )
        bright_protection = (
            1.0 - (highlight_t * highlight_t * (3.0 - (2.0 * highlight_t)))
        ).astype(np.float32, copy=False)

    process_mask = np.maximum(veil_mask, core_mask).astype(np.float32, copy=False)
    if softness > 0.0:
        process_mask = box_blur(
            np.repeat(process_mask[..., None], 3, axis=-1),
            smoothing_radius,
        )[..., 0].astype(np.float32, copy=False)
    process_mask = np.clip(
        process_mask * bright_protection,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    veil_lift = (
        reveal_dust
        * bright_protection
        * veil_mask
        * (0.06 + (0.14 * relative_darkness))
    ).astype(np.float32, copy=False)
    veil_luminance = np.clip(luminance + veil_lift, 0.0, 1.0).astype(np.float32, copy=False)

    contrast_radius = max(2, int(round(shorter * 0.01)))
    local_field = box_blur(
        np.repeat(veil_luminance[..., None], 3, axis=-1),
        contrast_radius,
    )[..., 0].astype(np.float32, copy=False)
    low_frequency_delta = (veil_luminance - local_field).astype(np.float32, copy=False)
    veil_contrast = (
        veil_luminance
        + (low_frequency_delta * dust_contrast * 0.65 * veil_mask * bright_protection)
    ).astype(np.float32, copy=False)

    veil_field = box_blur(
        np.repeat(veil_contrast[..., None], 3, axis=-1),
        max(contrast_radius + 2, int(round(contrast_radius * 1.8))),
    )[..., 0].astype(np.float32, copy=False)
    relative_core_depth = np.clip(veil_field - luminance, 0.0, 1.0).astype(np.float32, copy=False)
    core_luminance = np.clip(
        veil_contrast
        - (core_depth * core_mask * (0.02 + (0.16 * relative_core_depth))),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    scale = np.divide(
        core_luminance,
        np.maximum(luminance, EPSILON),
        out=np.ones_like(core_luminance, dtype=np.float32),
        where=luminance > EPSILON,
    )
    scaled = np.clip(linear * scale[..., None], 0.0, 1.0).astype(np.float32, copy=False)

    if dust_colour > 0.0:
        gray = np.repeat(core_luminance[..., None], 3, axis=-1).astype(np.float32, copy=False)
        saturation_scale = 1.0 + (
            dust_colour
            * 0.90
            * veil_mask[..., None]
            * bright_protection[..., None]
        )
        scaled = np.clip(
            gray + ((scaled - gray) * saturation_scale),
            0.0,
            1.0,
        ).astype(np.float32, copy=False)

    if softness > 0.0:
        blurred = box_blur(linear_to_srgb(scaled), smoothing_radius)
        blurred_linear = srgb_to_linear(
            np.clip(blurred, 0.0, 1.0).astype(np.float32, copy=False)
        )
        chroma_mix = (
            0.08 * softness * veil_mask * bright_protection
        ).astype(np.float32, copy=False)
        scaled = np.clip(
            (scaled * (1.0 - chroma_mix[..., None])) + (blurred_linear * chroma_mix[..., None]),
            0.0,
            1.0,
        ).astype(np.float32, copy=False)

    wet_mask = np.clip(weights * amount * process_mask, 0.0, 1.0).astype(np.float32, copy=False)
    return apply_weighted_image_blend(current_rgb, scaled, wet_mask)


def _rgb_hsv_planes(image_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    red = image_rgb[..., 0]
    green = image_rgb[..., 1]
    blue = image_rgb[..., 2]

    maximum = np.max(image_rgb, axis=-1)
    minimum = np.min(image_rgb, axis=-1)
    delta = maximum - minimum

    hue = np.zeros_like(maximum, dtype=np.float32)
    mask = delta > EPSILON
    red_max = mask & (maximum == red)
    green_max = mask & (maximum == green)
    blue_max = mask & (maximum == blue)

    hue[red_max] = np.mod((green[red_max] - blue[red_max]) / delta[red_max], 6.0)
    hue[green_max] = ((blue[green_max] - red[green_max]) / delta[green_max]) + 2.0
    hue[blue_max] = ((red[blue_max] - green[blue_max]) / delta[blue_max]) + 4.0
    hue = np.mod(hue / 6.0, 1.0).astype(np.float32, copy=False)

    saturation = np.zeros_like(maximum, dtype=np.float32)
    non_zero = maximum > EPSILON
    saturation[non_zero] = delta[non_zero] / maximum[non_zero]
    value = maximum.astype(np.float32, copy=False)
    return hue, saturation, value


def _hue_proximity(hue: np.ndarray, target: float, width: float) -> np.ndarray:
    distance = np.abs(hue - target)
    wrapped = np.minimum(distance, 1.0 - distance)
    return np.clip(1.0 - (wrapped / max(width, EPSILON)), 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )


def _apply_saturation_scale(rgb: np.ndarray, scale: float) -> np.ndarray:
    luminance = compute_luminance(rgb)[..., None]
    scaled = np.clip(luminance + ((rgb - luminance) * scale), 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )
    return np.asarray(scaled, dtype=np.float32)


def _faux_palette_component_multipliers(
    palette: str,
    definition: FauxPaletteDefinition,
    colour_balance: dict[str, float] | None,
) -> tuple[tuple[float, float, float, float], bool]:
    supported = FAUX_PALETTE_SUPPORTED_COLOUR_BALANCE_KEYS.get(palette, ())
    if not supported:
        return (1.0, 1.0, 1.0, 1.0), True
    if colour_balance is None:
        colour_balance = {}
    resolved = {key: float(colour_balance.get(key, 100.0)) / 100.0 for key in supported}
    if max(resolved.values(), default=0.0) <= EPSILON:
        return (1.0, 1.0, 1.0, 1.0), False

    component_totals = np.zeros(4, dtype=np.float32)
    component_weights = np.zeros(4, dtype=np.float32)
    for control in definition.colour_controls:
        multiplier = resolved.get(control.key, 1.0)
        weights = np.asarray(control.component_weights, dtype=np.float32)
        component_totals += weights * multiplier
        component_weights += weights
    multipliers = np.divide(
        component_totals,
        np.maximum(component_weights, EPSILON),
        out=np.ones_like(component_totals),
        where=component_weights > EPSILON,
    ).astype(np.float32, copy=False)
    return (
        float(multipliers[0]),
        float(multipliers[1]),
        float(multipliers[2]),
        float(multipliers[3]),
    ), True


def _map_faux_palette(
    current_rgb: np.ndarray,
    definition: FauxPaletteDefinition,
    *,
    component_multipliers: tuple[float, float, float, float],
) -> np.ndarray:
    red = current_rgb[..., 0].astype(np.float32, copy=False)
    green = current_rgb[..., 1].astype(np.float32, copy=False)
    blue = current_rgb[..., 2].astype(np.float32, copy=False)
    hue, saturation, value = _rgb_hsv_planes(current_rgb)

    warm = np.clip((0.85 * red) + (0.25 * green) - (0.45 * blue), 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )
    orange = _hue_proximity(hue, 32.0 / 360.0, 0.16)
    magenta = _hue_proximity(hue, 338.0 / 360.0, 0.18)
    cyan = _hue_proximity(hue, 200.0 / 360.0, 0.18)
    blue_cyan = np.clip((0.78 * blue) + (0.24 * green) - (0.30 * red), 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )

    warmth = np.clip(warm * (0.55 + (0.45 * saturation)), 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )
    cool_match = np.maximum(cyan, _hue_proximity(hue, 224.0 / 360.0, 0.16))
    neutral = np.clip((1.0 - (0.82 * saturation)) * (0.55 + (0.45 * value)), 0.0, 1.0).astype(
        np.float32,
        copy=False,
    )

    warm_proxy = np.clip(
        warmth
        * (0.52 + (0.48 * orange))
        * (0.70 + (0.30 * value))
        * (1.0 + (definition.separation * orange * 0.30))
        * (1.0 - (definition.separation * cool_match * 0.18)),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    red_proxy = np.clip(
        warmth
        * (0.48 + (0.52 * magenta))
        * (0.78 + (0.22 * (1.0 - orange)))
        * (1.0 + (definition.separation * magenta * 0.34)),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    cool_proxy = np.clip(
        blue_cyan
        * (0.54 + (0.46 * np.maximum(cool_match, saturation)))
        * (1.0 + (definition.separation * cool_match * 0.28))
        * (1.0 - (definition.separation * warm * 0.12)),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    dominant_proxy = np.maximum(np.maximum(warm_proxy, red_proxy), cool_proxy)
    neutral_proxy = np.clip(
        neutral * definition.neutral_weight * (1.0 - (0.72 * dominant_proxy)),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    warm_target = np.asarray(definition.warm_target, dtype=np.float32)
    red_target = np.asarray(definition.red_target, dtype=np.float32)
    cool_target = np.asarray(definition.cool_target, dtype=np.float32)
    neutral_target = np.asarray(definition.neutral_target, dtype=np.float32)
    warm_multiplier, red_multiplier, cool_multiplier, neutral_multiplier = component_multipliers
    warm_weight = definition.warm_weight * warm_multiplier
    red_weight = definition.red_weight * red_multiplier
    cool_weight = definition.cool_weight * cool_multiplier
    neutral_weight = neutral_multiplier

    numerator = (
        (warm_target * warm_proxy[..., None] * warm_weight)
        + (red_target * red_proxy[..., None] * red_weight)
        + (cool_target * cool_proxy[..., None] * cool_weight)
        + (neutral_target * neutral_proxy[..., None] * neutral_weight)
    ).astype(np.float32, copy=False)
    denominator = (
        (warm_proxy * warm_weight)
        + (red_proxy * red_weight)
        + (cool_proxy * cool_weight)
        + (neutral_proxy * neutral_weight)
    )[..., None]
    mapped = np.divide(
        numerator,
        np.maximum(denominator, EPSILON),
    ).astype(np.float32, copy=False)

    if definition.original_chroma_mix > EPSILON:
        mapped = (
            (mapped * (1.0 - definition.original_chroma_mix))
            + (current_rgb * definition.original_chroma_mix)
        ).astype(np.float32, copy=False)

    mapped = _apply_saturation_scale(mapped, definition.saturation_scale)

    green_excess = np.clip(
        mapped[..., 1]
        - ((0.78 + (0.10 * definition.separation)) * np.maximum(mapped[..., 0], mapped[..., 2]))
        - 0.04,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    mapped[..., 1] = np.clip(mapped[..., 1] - (green_excess * definition.green_reduction), 0.0, 1.0)
    remaining_green = green_excess * definition.green_reduction
    mapped[..., 0] = np.clip(mapped[..., 0] + (remaining_green * 0.56), 0.0, 1.0)
    mapped[..., 2] = np.clip(mapped[..., 2] + (remaining_green * 0.44), 0.0, 1.0)
    return np.asarray(mapped, dtype=np.float32)


def apply_faux_palette(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    *,
    palette: str,
    amount: float,
    preserve_brightness: bool,
    colour_balance: dict[str, float] | None = None,
) -> np.ndarray:
    clamped_amount = max(0.0, min(1.0, amount))
    if clamped_amount <= EPSILON:
        return np.asarray(current_rgb.astype(np.float32, copy=True), dtype=np.float32)
    definition = FAUX_PALETTES.get(palette)
    if definition is None:
        raise ValueError(f"unsupported faux palette: {palette}")
    component_multipliers, has_active_colour = _faux_palette_component_multipliers(
        palette,
        definition,
        colour_balance,
    )
    if not has_active_colour:
        return np.asarray(current_rgb.astype(np.float32, copy=True), dtype=np.float32)

    current_linear = srgb_to_linear(current_rgb)
    original_luminance = np.tensordot(current_linear, LINEAR_LUMA, axes=([-1], [0]))
    mapped_srgb = _map_faux_palette(
        current_rgb,
        definition,
        component_multipliers=component_multipliers,
    )
    mapped_linear = srgb_to_linear(mapped_srgb)
    if preserve_brightness:
        mapped_linear = _preserve_luminance(mapped_linear, original_luminance)

    mapped_rgb = np.clip(linear_to_srgb(mapped_linear), 0.0, 1.0).astype(np.float32, copy=False)
    blended_rgb = (
        current_rgb * (1.0 - clamped_amount)
    ) + (mapped_rgb * clamped_amount)
    blended_linear = srgb_to_linear(np.clip(blended_rgb, 0.0, 1.0).astype(np.float32, copy=False))
    return apply_weighted_image_blend(current_rgb, blended_linear, weights)

from __future__ import annotations

import numpy as np

LINEAR_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
LUMA_WEIGHT = 0.25
EPSILON = 1e-6
CHANNEL_INDEX = {"red": 0, "green": 1, "blue": 2}


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
    saturation = np.where(channel_max > 0.0, (channel_max - channel_min) / channel_max, 0.0)
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


def box_blur(image_rgb: np.ndarray, radius_pixels: int) -> np.ndarray:
    if radius_pixels <= 0:
        return image_rgb.astype(np.float32, copy=True)

    height, width, _ = image_rgb.shape
    padded = np.pad(
        image_rgb,
        ((radius_pixels, radius_pixels), (radius_pixels, radius_pixels), (0, 0)),
        mode="edge",
    )
    accum = np.zeros((height, width, 3), dtype=np.float32)
    samples = 0

    for dy in range(-radius_pixels, radius_pixels + 1):
        y_start = radius_pixels + dy
        y_end = y_start + height
        for dx in range(-radius_pixels, radius_pixels + 1):
            x_start = radius_pixels + dx
            x_end = x_start + width
            accum += padded[y_start:y_end, x_start:x_end]
            samples += 1

    blurred = (accum / float(samples)).astype(np.float32, copy=False)
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

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


def _map_faux_hubble(current_rgb: np.ndarray) -> np.ndarray:
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
    faux_sii = np.clip(
        warmth * ((0.55 + (0.45 * orange)) * (0.65 + (0.35 * value))),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    faux_ha = np.clip(
        warmth * ((0.50 + (0.50 * magenta)) * (0.80 + (0.20 * (1.0 - orange)))),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    faux_oiii = np.clip(
        blue_cyan * (0.55 + (0.45 * np.maximum(cyan, saturation))),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    mapped = np.empty_like(current_rgb, dtype=np.float32)
    mapped[..., 0] = np.clip((1.00 * faux_sii) + (0.14 * faux_ha), 0.0, 1.0)
    mapped[..., 1] = np.clip(
        (0.82 * faux_ha) + (0.24 * faux_oiii) + (0.08 * faux_sii),
        0.0,
        1.0,
    )
    mapped[..., 2] = np.clip((0.96 * faux_oiii) + (0.12 * faux_ha), 0.0, 1.0)

    green_excess = np.clip(
        mapped[..., 1] - (0.78 * np.maximum(mapped[..., 0], mapped[..., 2])) - 0.04,
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    mapped[..., 1] = np.clip(mapped[..., 1] - (green_excess * 0.35), 0.0, 1.0)
    mapped[..., 0] = np.clip(mapped[..., 0] + (green_excess * 0.20), 0.0, 1.0)
    mapped[..., 2] = np.clip(mapped[..., 2] + (green_excess * 0.15), 0.0, 1.0)
    return np.asarray(mapped, dtype=np.float32)


def apply_faux_palette(
    current_rgb: np.ndarray,
    weights: np.ndarray,
    *,
    palette: str,
    amount: float,
    preserve_brightness: bool,
) -> np.ndarray:
    clamped_amount = max(0.0, min(1.0, amount))
    if clamped_amount <= EPSILON:
        return np.asarray(current_rgb.astype(np.float32, copy=True), dtype=np.float32)
    if palette != "hubble":
        raise ValueError(f"unsupported faux palette: {palette}")

    current_linear = srgb_to_linear(current_rgb)
    original_luminance = np.tensordot(current_linear, LINEAR_LUMA, axes=([-1], [0]))
    mapped_srgb = _map_faux_hubble(current_rgb)
    mapped_linear = srgb_to_linear(mapped_srgb)
    if preserve_brightness:
        mapped_linear = _preserve_luminance(mapped_linear, original_luminance)

    mapped_rgb = np.clip(linear_to_srgb(mapped_linear), 0.0, 1.0).astype(np.float32, copy=False)
    blended_rgb = (
        current_rgb * (1.0 - clamped_amount)
    ) + (mapped_rgb * clamped_amount)
    blended_linear = srgb_to_linear(np.clip(blended_rgb, 0.0, 1.0).astype(np.float32, copy=False))
    return apply_weighted_image_blend(current_rgb, blended_linear, weights)

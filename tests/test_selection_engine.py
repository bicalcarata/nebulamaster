from __future__ import annotations

import numpy as np
from engine.selection import (
    apply_colour_amount,
    box_blur,
    colour_weight,
    compute_luminance,
    faint_colour_weight,
)


def _naive_box_blur(image_rgb: np.ndarray, radius_pixels: int) -> np.ndarray:
    if radius_pixels <= 0:
        return image_rgb.astype(np.float32, copy=True)

    height, width, _ = image_rgb.shape
    padded = np.pad(
        image_rgb,
        ((radius_pixels, radius_pixels), (radius_pixels, radius_pixels), (0, 0)),
        mode="edge",
    ).astype(np.float32, copy=False)
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

    return np.asarray(accum / float(samples), dtype=np.float32)


def _red_strength_fixture() -> np.ndarray:
    image = np.full((24, 24, 3), [0.05, 0.05, 0.055], dtype=np.float32)

    for y in range(4, 10):
        for x in range(4, 10):
            image[y, x] = [
                0.56 + ((x - 4) * 0.03),
                0.14 + ((y - 4) * 0.01),
                0.13 + ((x - 4) * 0.005),
            ]

    for y in range(14, 21):
        for x in range(3, 11):
            image[y, x] = [
                0.21 + ((x - 3) * 0.008),
                0.17 + ((y - 14) * 0.003),
                0.16 + ((x - 3) * 0.002),
            ]

    image[11, 20] = [0.23, 0.18, 0.18]
    return np.asarray(np.clip(image, 0.0, 1.0), dtype=np.float32)


def _blue_strength_fixture() -> np.ndarray:
    red_fixture = _red_strength_fixture()
    return np.asarray(red_fixture[..., [2, 1, 0]], dtype=np.float32)


def test_box_blur_matches_naive_reference() -> None:
    rng = np.random.default_rng(42)
    image = rng.random((7, 9, 3), dtype=np.float32)

    for radius in (1, 2, 3):
        expected = _naive_box_blur(image, radius)
        actual = box_blur(image, radius)
        np.testing.assert_allclose(actual, expected, atol=1e-6)


def test_box_blur_with_zero_radius_returns_copy() -> None:
    image = np.arange(27, dtype=np.float32).reshape(3, 3, 3) / 26.0
    blurred = box_blur(image, 0)

    np.testing.assert_allclose(blurred, image, atol=0.0)
    assert blurred is not image


def test_colour_amount_reduction_does_not_flip_warm_red_pixels_green() -> None:
    image = np.asarray([[[0.78, 0.18, 0.16]]], dtype=np.float32)
    weights = np.ones((1, 1), dtype=np.float32)

    output = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=0.4,
        preserve_luminance=True,
    )

    assert float(output[0, 0, 0]) > float(output[0, 0, 1])
    assert float(output[0, 0, 0]) > float(output[0, 0, 2])
    np.testing.assert_allclose(output[0, 0, 1:], image[0, 0, 1:], atol=1e-5)


def test_colour_amount_respects_weighted_blend_once() -> None:
    image = np.asarray([[[0.60, 0.20, 0.20]]], dtype=np.float32)
    weights = np.asarray([[0.5]], dtype=np.float32)

    output = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=2.0,
        preserve_luminance=False,
    )
    fully_transformed = apply_colour_amount(
        image,
        np.ones((1, 1), dtype=np.float32),
        channel="red",
        amount=2.0,
        preserve_luminance=False,
    )

    assert float(output[0, 0, 0]) > float(image[0, 0, 0])
    assert float(output[0, 0, 0]) < float(fully_transformed[0, 0, 0])


def test_enhanced_colour_amount_is_neutral_at_zero_percent() -> None:
    image = _red_strength_fixture()
    weights = np.ones(image.shape[:2], dtype=np.float32)

    output = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.0,
        preserve_luminance=True,
        response_version="enhanced",
    )

    np.testing.assert_allclose(output, image, atol=1e-6)


def test_enhanced_colour_amount_remains_subtle_near_zero_and_monotonic() -> None:
    image = np.asarray([[[0.62, 0.15, 0.14]]], dtype=np.float32)
    weights = np.ones((1, 1), dtype=np.float32)

    neutral = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.0,
        preserve_luminance=False,
        response_version="enhanced",
    )
    subtle = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.10,
        preserve_luminance=False,
        response_version="enhanced",
    )
    medium = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.40,
        preserve_luminance=False,
        response_version="enhanced",
    )
    strong = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=2.0,
        preserve_luminance=False,
        response_version="enhanced",
    )

    subtle_delta = float(subtle[0, 0, 0] - neutral[0, 0, 0])
    medium_delta = float(medium[0, 0, 0] - neutral[0, 0, 0])
    strong_delta = float(strong[0, 0, 0] - neutral[0, 0, 0])

    assert subtle_delta > 0.0
    assert subtle_delta < medium_delta < strong_delta
    assert subtle_delta < (strong_delta * 0.25)


def test_enhanced_colour_amount_is_stronger_than_legacy_maximum() -> None:
    image = _red_strength_fixture()
    weights = np.ones(image.shape[:2], dtype=np.float32)

    legacy = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=2.0,
        preserve_luminance=False,
        response_version="legacy",
    )
    enhanced = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=2.0,
        preserve_luminance=False,
        response_version="enhanced",
    )

    bright_legacy = float((legacy[4:10, 4:10, 0] - image[4:10, 4:10, 0]).mean())
    bright_enhanced = float((enhanced[4:10, 4:10, 0] - image[4:10, 4:10, 0]).mean())
    faint_legacy = float((legacy[14:21, 3:11, 0] - image[14:21, 3:11, 0]).mean())
    faint_enhanced = float((enhanced[14:21, 3:11, 0] - image[14:21, 3:11, 0]).mean())

    assert bright_enhanced > (bright_legacy * 1.35)
    assert faint_enhanced > (faint_legacy * 1.35)


def test_colour_range_broadens_faint_red_selection_without_global_pickup() -> None:
    image = _red_strength_fixture()
    target = np.asarray([0.72, 0.18, 0.15], dtype=np.float32)

    narrow = colour_weight(image, target, colour_range=0.08, softness=0.40)
    broad = colour_weight(image, target, colour_range=0.28, softness=0.40)

    faint_narrow = float(narrow[17, 6])
    faint_broad = float(broad[17, 6])
    neutral_broad = float(broad[1, 1])
    bright_broad = float(broad[6, 6])

    assert bright_broad > 0.95
    assert faint_broad > faint_narrow
    assert faint_broad > neutral_broad
    assert faint_broad > neutral_broad + 0.10


def test_faint_colour_sensitivity_prefers_coherent_red_structure_over_noise() -> None:
    image = _red_strength_fixture()
    target = np.asarray([0.24, 0.18, 0.17], dtype=np.float32)

    faint_weights = faint_colour_weight(
        image,
        target,
        "red",
        0.85,
        faint_range=0.65,
        structure_size="broad",
        bright_colour_protection=0.75,
    )

    coherent_faint = float(faint_weights[17, 6])
    isolated_noise = float(faint_weights[11, 20])
    neutral_background = float(faint_weights[1, 1])

    assert coherent_faint > 0.10
    assert coherent_faint > isolated_noise
    assert coherent_faint > neutral_background
    assert neutral_background < 0.05


def test_reveal_faint_red_mask_differs_from_colour_strength_and_prefers_dim_structure() -> None:
    image = _red_strength_fixture()
    target = np.asarray([0.24, 0.18, 0.17], dtype=np.float32)

    colour_strength = colour_weight(image, target, colour_range=0.18, softness=0.40)
    faint_weights = faint_colour_weight(
        image,
        target,
        "red",
        0.85,
        faint_range=0.65,
        structure_size="broad",
        bright_colour_protection=0.75,
    )

    bright_red = float(faint_weights[6, 6])
    faint_red = float(faint_weights[17, 6])
    bright_strength = float(colour_strength[6, 6])
    faint_strength = float(colour_strength[17, 6])

    assert faint_red > bright_red
    assert (faint_red / max(bright_red, 1e-6)) > (faint_strength / max(bright_strength, 1e-6))


def test_reveal_faint_blue_uses_the_same_shared_behaviour() -> None:
    image = _blue_strength_fixture()
    target = np.asarray([0.17, 0.18, 0.24], dtype=np.float32)

    faint_weights = faint_colour_weight(
        image,
        target,
        "blue",
        0.85,
        faint_range=0.65,
        structure_size="broad",
        bright_colour_protection=0.75,
    )

    coherent_faint = float(faint_weights[17, 6])
    bright_blue = float(faint_weights[6, 6])
    isolated_noise = float(faint_weights[11, 20])
    neutral_background = float(faint_weights[1, 1])

    assert coherent_faint > bright_blue
    assert coherent_faint > isolated_noise
    assert neutral_background < 0.05


def test_reveal_faint_red_lifts_selected_structure_without_raising_background() -> None:
    image = _red_strength_fixture()
    weights = np.ones(image.shape[:2], dtype=np.float32)
    target = np.asarray([0.24, 0.18, 0.17], dtype=np.float32)
    faint_support = faint_colour_weight(
        image,
        target,
        "red",
        0.85,
        faint_range=0.65,
        structure_size="broad",
        bright_colour_protection=0.75,
    )

    output = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.0,
        preserve_luminance=True,
        response_version="enhanced",
        reveal_faint_colour=0.80,
        reveal_mask=faint_support,
        structure_size="broad",
    )

    source_luminance = compute_luminance(image)
    output_luminance = compute_luminance(output)
    faint_delta = float((output_luminance[14:21, 3:11] - source_luminance[14:21, 3:11]).mean())
    background_delta = float(output_luminance[0:4, 0:4].mean() - source_luminance[0:4, 0:4].mean())

    assert faint_delta > 0.003
    assert abs(background_delta) < 5e-4


def test_bright_colour_protection_reduces_reveal_effect_on_bright_regions() -> None:
    image = _red_strength_fixture()
    target = np.asarray([0.24, 0.18, 0.17], dtype=np.float32)
    weights = np.ones(image.shape[:2], dtype=np.float32)

    low_protection_mask = faint_colour_weight(
        image,
        target,
        "red",
        0.85,
        faint_range=0.65,
        structure_size="broad",
        bright_colour_protection=0.0,
    )
    high_protection_mask = faint_colour_weight(
        image,
        target,
        "red",
        0.85,
        faint_range=0.65,
        structure_size="broad",
        bright_colour_protection=1.0,
    )

    low_protection = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.0,
        preserve_luminance=True,
        response_version="enhanced",
        reveal_faint_colour=0.80,
        reveal_mask=low_protection_mask,
        structure_size="broad",
    )
    high_protection = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=1.0,
        preserve_luminance=True,
        response_version="enhanced",
        reveal_faint_colour=0.80,
        reveal_mask=high_protection_mask,
        structure_size="broad",
    )

    source_luminance = compute_luminance(image)
    low_protection_luminance = compute_luminance(low_protection)
    high_protection_luminance = compute_luminance(high_protection)

    bright_delta_low = float(
        (low_protection_luminance[4:10, 4:10] - source_luminance[4:10, 4:10]).mean()
    )
    bright_delta_high = float(
        (high_protection_luminance[4:10, 4:10] - source_luminance[4:10, 4:10]).mean()
    )

    assert bright_delta_high < bright_delta_low


def test_highlight_protection_reduces_peak_push_and_remains_finite() -> None:
    image = np.asarray([[[0.92, 0.82, 0.78]]], dtype=np.float32)
    weights = np.ones((1, 1), dtype=np.float32)

    unprotected = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=2.0,
        preserve_luminance=False,
        response_version="enhanced",
        highlight_protection=0.0,
    )
    protected = apply_colour_amount(
        image,
        weights,
        channel="red",
        amount=2.0,
        preserve_luminance=False,
        response_version="enhanced",
        highlight_protection=1.0,
    )

    assert np.isfinite(unprotected).all()
    assert np.isfinite(protected).all()
    assert float(protected[0, 0, 0]) < float(unprotected[0, 0, 0])

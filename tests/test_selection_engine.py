from __future__ import annotations

import numpy as np
from engine.selection import apply_colour_amount, box_blur


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

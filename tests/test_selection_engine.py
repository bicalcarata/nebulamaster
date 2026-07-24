from __future__ import annotations

import numpy as np
from engine.selection import box_blur


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

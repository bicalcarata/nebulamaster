from __future__ import annotations

from pathlib import Path

import numpy as np
from image_io import save_mask_png
from PIL import Image, ImageDraw
from project_model import ProjectBundle, RegionFile

from .selection import smooth_falloff


def normalized_polygon_to_pixels(
    polygon: list[tuple[float, float]],
    width: int,
    height: int,
) -> np.ndarray:
    scale_x = max(width - 1, 1)
    scale_y = max(height - 1, 1)
    points = np.asarray(polygon, dtype=np.float32)
    pixel_points = np.empty_like(points)
    pixel_points[:, 0] = points[:, 0] * scale_x
    pixel_points[:, 1] = points[:, 1] * scale_y
    return pixel_points


def _polygon_mask(region: RegionFile, width: int, height: int) -> np.ndarray:
    points = normalized_polygon_to_pixels(region.polygon, width, height)
    image = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.polygon([tuple(point) for point in points], fill=255)
    return (np.asarray(image, dtype=np.float32) / 255.0).astype(np.float32, copy=False)


def _point_segment_distance(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> np.ndarray:
    segment = end - start
    squared_length = float(np.dot(segment, segment))
    if squared_length == 0.0:
        distance = np.sqrt((x_coords - start[0]) ** 2 + (y_coords - start[1]) ** 2)
        return np.asarray(distance, dtype=np.float32)

    projection = (
        ((x_coords - start[0]) * segment[0]) + ((y_coords - start[1]) * segment[1])
    ) / squared_length
    projection = np.clip(projection, 0.0, 1.0)
    nearest_x = start[0] + projection * segment[0]
    nearest_y = start[1] + projection * segment[1]
    distance = np.sqrt((x_coords - nearest_x) ** 2 + (y_coords - nearest_y) ** 2)
    return np.asarray(distance, dtype=np.float32)


def region_influence(region: RegionFile, width: int, height: int) -> np.ndarray:
    inside = _polygon_mask(region, width, height)
    feather_fraction = region.feather.radius if region.feather is not None else 0.0
    if feather_fraction <= 0.0:
        return inside

    feather_pixels = feather_fraction * float(min(width, height))
    if feather_pixels <= 0.0:
        return inside

    points = normalized_polygon_to_pixels(region.polygon, width, height)
    min_x = max(0, int(np.floor(points[:, 0].min() - feather_pixels - 1)))
    max_x = min(width - 1, int(np.ceil(points[:, 0].max() + feather_pixels + 1)))
    min_y = max(0, int(np.floor(points[:, 1].min() - feather_pixels - 1)))
    max_y = min(height - 1, int(np.ceil(points[:, 1].max() + feather_pixels + 1)))

    if min_x > max_x or min_y > max_y:
        return inside

    x_coords, y_coords = np.meshgrid(
        np.arange(min_x, max_x + 1, dtype=np.float32),
        np.arange(min_y, max_y + 1, dtype=np.float32),
    )
    distances = np.full(x_coords.shape, np.inf, dtype=np.float32)

    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        segment_distance = _point_segment_distance(x_coords, y_coords, start, end)
        distances = np.minimum(distances, segment_distance.astype(np.float32, copy=False))

    influence = inside.copy()
    inside_window = inside[min_y : max_y + 1, min_x : max_x + 1]
    outside_window = inside_window < 1.0
    feather_window = smooth_falloff(distances, feather_pixels, softness=1.0)
    influence[min_y : max_y + 1, min_x : max_x + 1] = np.maximum(
        inside_window,
        feather_window * outside_window.astype(np.float32),
    )
    clipped = np.clip(influence, 0.0, 1.0).astype(np.float32, copy=False)
    return np.asarray(clipped, dtype=np.float32)


def resolve_region_influence(
    bundle: ProjectBundle,
    region_ids: list[str],
    width: int,
    height: int,
) -> tuple[np.ndarray, list[str]]:
    if not region_ids:
        return np.ones((height, width), dtype=np.float32), []

    influence = np.zeros((height, width), dtype=np.float32)
    applied_region_ids: list[str] = []

    for region_id in region_ids:
        region = bundle.regions[region_id]
        if not region.enabled:
            continue
        influence = np.maximum(influence, region_influence(region, width, height))
        applied_region_ids.append(region_id)

    return influence, applied_region_ids


def write_debug_mask(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_mask_png(path, mask)

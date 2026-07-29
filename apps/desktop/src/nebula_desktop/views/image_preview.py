from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
from image_io import CanonicalImage
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

InteractionMode = Literal["navigate", "sampling", "draw_region", "edit_region"]
SemanticOverlayMode = Literal["stars", "nebula", "dark_dust"]
OVERLAY_TINTS: dict[SemanticOverlayMode, tuple[float, float, float]] = {
    "stars": (0.35, 0.78, 1.0),
    "nebula": (0.64, 0.9, 1.0),
    "dark_dust": (0.94, 0.78, 0.26),
}
OVERLAY_FILL_ALPHA: dict[SemanticOverlayMode, float] = {
    "stars": 0.14,
    "nebula": 0.06,
    "dark_dust": 0.10,
}
OVERLAY_EDGE_ALPHA: dict[SemanticOverlayMode, float] = {
    "stars": 0.44,
    "nebula": 0.24,
    "dark_dust": 0.34,
}
OVERLAY_NON_TARGET_ALPHA: dict[SemanticOverlayMode, float] = {
    "stars": 0.82,
    "nebula": 0.72,
    "dark_dust": 0.74,
}


@dataclass(frozen=True)
class ImageSample:
    x: int
    y: int
    rgb: tuple[float, float, float]


@dataclass(frozen=True)
class OverlayRegion:
    region_id: str
    name: str
    polygon: list[tuple[float, float]]
    enabled: bool
    selected: bool = False
    highlighted: bool = False


@dataclass(frozen=True)
class SampleMarker:
    x: int
    y: int
    rgb: tuple[float, float, float]


@dataclass(frozen=True)
class SemanticOverlay:
    mode: SemanticOverlayMode
    label: str
    mask: np.ndarray
    display_mode: Literal["overlay", "mask"] = "overlay"
    coverage_percent: float | None = None


def canonical_image_to_qimage(image: CanonicalImage) -> QImage:
    clipped = np.clip(image.data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    contiguous = np.ascontiguousarray(clipped)
    height, width, _channels = contiguous.shape
    bytes_per_line = width * 3
    qimage = QImage(
        contiguous.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGB888,
    )
    return qimage.copy()


def semantic_overlay_rgba(mask: np.ndarray, mode: SemanticOverlayMode) -> np.ndarray:
    clipped_mask = np.clip(mask, 0.0, 1.0).astype(np.float32, copy=False)
    if mode == "stars":
        display_mask = np.power(clipped_mask, 0.55).astype(np.float32, copy=False)
    else:
        display_mask = clipped_mask

    edge_strength = np.maximum.reduce(
        [
            np.abs(display_mask - np.roll(display_mask, 1, axis=0)),
            np.abs(display_mask - np.roll(display_mask, -1, axis=0)),
            np.abs(display_mask - np.roll(display_mask, 1, axis=1)),
            np.abs(display_mask - np.roll(display_mask, -1, axis=1)),
        ]
    ).astype(np.float32, copy=False)
    edge_strength[0, :] = 0.0
    edge_strength[-1, :] = 0.0
    edge_strength[:, 0] = 0.0
    edge_strength[:, -1] = 0.0

    tint = np.asarray(OVERLAY_TINTS[mode], dtype=np.float32)
    fill_alpha = display_mask * OVERLAY_FILL_ALPHA[mode]
    edge_alpha = np.clip(edge_strength * OVERLAY_EDGE_ALPHA[mode] * 4.0, 0.0, 1.0)
    suppress_alpha = np.power(
        np.clip(1.0 - display_mask, 0.0, 1.0),
        0.85,
    ) * OVERLAY_NON_TARGET_ALPHA[mode]
    tint_alpha = np.maximum(fill_alpha, edge_alpha)
    alpha = np.clip(np.maximum(tint_alpha, suppress_alpha), 0.0, 1.0).astype(np.float32, copy=False)
    rgba = np.empty((*display_mask.shape, 4), dtype=np.uint8)
    tint_rgb = np.clip(tint[None, None, :] * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    use_tint = np.logical_and(display_mask >= 0.35, tint_alpha >= suppress_alpha)
    rgba[..., :3] = 0
    rgba[..., :3][use_tint] = tint_rgb
    rgba[..., 3] = np.clip(alpha * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    return np.ascontiguousarray(rgba)


def semantic_overlay_mask_rgba(mask: np.ndarray) -> np.ndarray:
    clipped = np.clip(mask, 0.0, 1.0).astype(np.float32, copy=False)
    alpha = np.clip(clipped * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8, copy=False)
    luminance = np.clip(clipped * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8, copy=False)
    rgba = np.empty((*clipped.shape, 4), dtype=np.uint8)
    rgba[..., 0] = luminance
    rgba[..., 1] = luminance
    rgba[..., 2] = luminance
    rgba[..., 3] = alpha
    return np.ascontiguousarray(rgba)


class ImagePreviewWidget(QWidget):
    sampleClicked = Signal(object)
    samplingCancelled = Signal()
    regionPointAdded = Signal(float, float)
    regionDrawingFinished = Signal()
    regionDrawingCancelled = Signal()
    regionSelected = Signal(str)
    regionVertexMoved = Signal(str, int, float, float)
    regionEdgeInserted = Signal(str, int, float, float)
    regionVertexDeleted = Signal(str, int)
    regionMoved = Signal(str, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._image: CanonicalImage | None = None
        self._pixmap: QPixmap | None = None
        self._auto_fit = True
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag_start: QPoint | None = None
        self._mode: InteractionMode = "navigate"
        self._regions: list[OverlayRegion] = []
        self._drawing_points: list[tuple[float, float]] = []
        self._show_regions = True
        self._selected_region_id: str | None = None
        self._active_vertex: tuple[str, int] | None = None
        self._active_region_move_id: str | None = None
        self._last_region_position: tuple[float, float] | None = None
        self._sample_marker: SampleMarker | None = None
        self._semantic_overlay: SemanticOverlay | None = None
        self._semantic_overlay_pixmap: QPixmap | None = None

    def set_image(self, image: CanonicalImage | None) -> None:
        self._image = image
        self._pixmap = (
            QPixmap.fromImage(canonical_image_to_qimage(image))
            if image is not None
            else None
        )
        self._refresh_semantic_overlay_pixmap()
        self.update()

    def set_semantic_overlay(self, overlay: SemanticOverlay | None) -> None:
        self._semantic_overlay = overlay
        self._refresh_semantic_overlay_pixmap()
        self.update()

    def semantic_overlay(self) -> SemanticOverlay | None:
        return self._semantic_overlay

    def set_interaction_mode(self, mode: InteractionMode) -> None:
        self._mode = mode
        if mode == "sampling":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "draw_region":
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == "edit_region":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def set_regions(
        self,
        regions: list[OverlayRegion],
        *,
        selected_region_id: str | None,
        drawing_points: list[tuple[float, float]] | None = None,
        show_regions: bool = True,
    ) -> None:
        self._regions = list(regions)
        self._selected_region_id = selected_region_id
        self._drawing_points = list(drawing_points or [])
        self._show_regions = show_regions
        self.update()

    def set_sample_marker(self, marker: SampleMarker | None) -> None:
        self._sample_marker = marker
        self.update()

    def sample_marker(self) -> SampleMarker | None:
        return self._sample_marker

    def fit_to_view(self) -> None:
        self._auto_fit = True
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def actual_size(self) -> None:
        self._auto_fit = False
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def zoom_in(self) -> None:
        self._auto_fit = False
        self._zoom *= 1.2
        self.update()

    def zoom_out(self) -> None:
        self._auto_fit = False
        self._zoom = max(0.1, self._zoom / 1.2)
        self.update()

    def map_widget_to_image(self, position: QPointF) -> tuple[int, int] | None:
        if self._image is None:
            return None
        rect, scale = self._target_rect()
        if rect is None or scale <= 0.0 or not rect.contains(position):
            return None
        x = int((position.x() - rect.left()) / scale)
        y = int((position.y() - rect.top()) / scale)
        x = max(0, min(self._image.width - 1, x))
        y = max(0, min(self._image.height - 1, y))
        return x, y

    def sample_at_widget_position(self, position: QPointF) -> ImageSample | None:
        coordinates = self.map_widget_to_image(position)
        if coordinates is None or self._image is None:
            return None
        x, y = coordinates
        channels = cast(
            tuple[float, float, float],
            tuple(float(channel) for channel in self._image.data[y, x]),
        )
        return ImageSample(x=x, y=y, rgb=channels)

    def map_widget_to_normalized(self, position: QPointF) -> tuple[float, float] | None:
        coordinates = self.map_widget_to_image(position)
        if coordinates is None or self._image is None:
            return None
        x, y = coordinates
        width_denominator = max(1, self._image.width - 1)
        height_denominator = max(1, self._image.height - 1)
        return x / width_denominator, y / height_denominator

    def map_normalized_to_widget(self, point: tuple[float, float]) -> QPointF | None:
        rect, scale = self._target_rect()
        if self._image is None or rect is None:
            return None
        width_denominator = max(1, self._image.width - 1)
        height_denominator = max(1, self._image.height - 1)
        image_x = point[0] * width_denominator
        image_y = point[1] * height_denominator
        return QPointF(rect.left() + image_x * scale, rect.top() + image_y * scale)

    def _target_rect(self) -> tuple[QRectF | None, float]:
        if self._pixmap is None or self._image is None:
            return None, 0.0

        if self._auto_fit:
            base_scale = min(
                self.width() / max(self._image.width, 1),
                self.height() / max(self._image.height, 1),
            )
        else:
            base_scale = 1.0
        scale = max(0.01, base_scale * self._zoom)
        draw_width = self._image.width * scale
        draw_height = self._image.height * scale
        center = QPointF(self.width() / 2.0, self.height() / 2.0) + self._pan
        rect = QRectF(
            center.x() - draw_width / 2.0,
            center.y() - draw_height / 2.0,
            draw_width,
            draw_height,
        )
        return rect, scale

    def _refresh_semantic_overlay_pixmap(self) -> None:
        if self._semantic_overlay is None or self._image is None:
            self._semantic_overlay_pixmap = None
            return

        if self._semantic_overlay.display_mode == "mask":
            rgba = semantic_overlay_mask_rgba(self._semantic_overlay.mask)
        else:
            rgba = semantic_overlay_rgba(self._semantic_overlay.mask, self._semantic_overlay.mode)
        height, width, _channels = rgba.shape
        qimage = QImage(
            rgba.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        )
        self._semantic_overlay_pixmap = QPixmap.fromImage(qimage.copy())

    def _region_vertices(self, region: OverlayRegion) -> list[QPointF]:
        vertices: list[QPointF] = []
        for point in region.polygon:
            widget_point = self.map_normalized_to_widget(point)
            if widget_point is not None:
                vertices.append(widget_point)
        return vertices

    def _find_region(self, region_id: str | None) -> OverlayRegion | None:
        if region_id is None:
            return None
        for region in self._regions:
            if region.region_id == region_id:
                return region
        return None

    def _nearest_vertex(
        self,
        position: QPointF,
        *,
        region: OverlayRegion | None = None,
    ) -> tuple[str, int] | None:
        candidate_regions = [region] if region is not None else self._regions
        for current_region in candidate_regions:
            if current_region is None:
                continue
            for index, vertex in enumerate(self._region_vertices(current_region)):
                if self._distance(position, vertex) <= 8.0:
                    return current_region.region_id, index
        return None

    def _point_in_polygon(self, position: QPointF, region: OverlayRegion) -> bool:
        vertices = self._region_vertices(region)
        if len(vertices) < 3:
            return False
        inside = False
        j = len(vertices) - 1
        for index, vertex in enumerate(vertices):
            other = vertices[j]
            intersects = (
                (vertex.y() > position.y()) != (other.y() > position.y())
                and position.x()
                < (other.x() - vertex.x()) * (position.y() - vertex.y())
                / max(other.y() - vertex.y(), 1e-9)
                + vertex.x()
            )
            if intersects:
                inside = not inside
            j = index
        return inside

    def _nearest_edge(
        self,
        position: QPointF,
        region: OverlayRegion,
    ) -> int | None:
        vertices = self._region_vertices(region)
        if len(vertices) < 2:
            return None
        best_index: int | None = None
        best_distance = 10.0
        for index, start in enumerate(vertices):
            end = vertices[(index + 1) % len(vertices)]
            distance = self._distance_to_segment(position, start, end)
            if distance < best_distance:
                best_index = index + 1
                best_distance = distance
        return best_index

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        _ = event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#11161d"))
        if self._pixmap is None:
            painter.setPen(QColor("#d9e2ec"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Open a project to see an image.",
            )
            return
        rect, _scale = self._target_rect()
        if rect is None:
            return
        show_mask_only = (
            self._semantic_overlay is not None
            and self._semantic_overlay.display_mode == "mask"
            and self._semantic_overlay_pixmap is not None
        )
        if not show_mask_only:
            painter.drawPixmap(rect, self._pixmap, self._pixmap.rect())
        if self._semantic_overlay_pixmap is not None and self._semantic_overlay is not None:
            painter.drawPixmap(
                rect,
                self._semantic_overlay_pixmap,
                self._semantic_overlay_pixmap.rect(),
            )
            painter.setPen(QColor("#d9e2ec"))
            painter.drawText(
                QRectF(rect.left() + 12.0, rect.top() + 12.0, 220.0, 24.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._semantic_overlay.label,
            )
        if self._show_regions:
            self._paint_regions(painter)
        if self._mode == "draw_region" and self._drawing_points:
            self._paint_drawing_overlay(painter)
        if self._sample_marker is not None:
            self._paint_sample_marker(painter)

    def _paint_regions(self, painter: QPainter) -> None:
        for region in self._regions:
            vertices = self._region_vertices(region)
            if len(vertices) < 3:
                continue
            selected = region.selected or region.region_id == self._selected_region_id
            outline = QColor("#60a5fa" if selected else "#8aa4bf")
            if not region.enabled:
                outline.setAlpha(120)
            fill = QColor("#60a5fa")
            fill.setAlpha(40 if selected else 18)
            pen = QPen(outline, 2 if selected else 1.5)
            painter.setPen(pen)
            painter.setBrush(fill)
            polygon = [vertex.toPoint() for vertex in vertices]
            painter.drawPolygon(polygon)
            label_point = vertices[0]
            painter.setPen(QColor("#d9e2ec"))
            painter.drawText(label_point + QPointF(6.0, -6.0), region.name)
            if selected and self._mode == "edit_region":
                painter.setBrush(QColor("#f8fafc"))
                for vertex in vertices:
                    painter.drawEllipse(vertex, 4.0, 4.0)

    def _paint_drawing_overlay(self, painter: QPainter) -> None:
        points = [
            widget_point
            for widget_point in (
                self.map_normalized_to_widget(point) for point in self._drawing_points
            )
            if widget_point is not None
        ]
        if not points:
            return
        painter.setPen(QPen(QColor("#f59e0b"), 2.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(245, 158, 11, 32))
        if len(points) > 1:
            painter.drawPolyline([point.toPoint() for point in points])
        for point in points:
            painter.drawEllipse(point, 3.0, 3.0)

    def _paint_sample_marker(self, painter: QPainter) -> None:
        if self._sample_marker is None or self._image is None:
            return
        width_denominator = max(1, self._image.width - 1)
        height_denominator = max(1, self._image.height - 1)
        point = self.map_normalized_to_widget(
            (
                self._sample_marker.x / width_denominator,
                self._sample_marker.y / height_denominator,
            )
        )
        if point is None:
            return
        painter.setPen(QPen(QColor("#f8fafc"), 2.0))
        painter.setBrush(QColor(248, 250, 252, 36))
        painter.drawEllipse(point, 7.0, 7.0)
        painter.setPen(QPen(QColor("#0f172a"), 1.0))
        painter.drawLine(
            QPointF(point.x() - 10.0, point.y()),
            QPointF(point.x() + 10.0, point.y()),
        )
        painter.drawLine(
            QPointF(point.x(), point.y() - 10.0),
            QPointF(point.x(), point.y() + 10.0),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._mode == "sampling":
            sample = self.sample_at_widget_position(event.position())
            if sample is None:
                return
            self.sampleClicked.emit(sample)
            return

        if event.button() == Qt.MouseButton.LeftButton and self._mode == "draw_region":
            normalized = self.map_widget_to_normalized(event.position())
            if normalized is not None:
                self.regionPointAdded.emit(*normalized)
            return

        if event.button() == Qt.MouseButton.RightButton and self._mode == "draw_region":
            self.regionDrawingCancelled.emit()
            return

        if event.button() == Qt.MouseButton.RightButton and self._mode == "edit_region":
            selected_region = self._find_region(self._selected_region_id)
            vertex = self._nearest_vertex(event.position(), region=selected_region)
            if vertex is not None:
                self.regionVertexDeleted.emit(vertex[0], vertex[1])
            return

        if event.button() == Qt.MouseButton.LeftButton and self._mode == "edit_region":
            selected_region = self._find_region(self._selected_region_id)
            vertex = self._nearest_vertex(event.position(), region=selected_region)
            if vertex is not None:
                self._active_vertex = vertex
                return
            if (
                selected_region is not None
                and self._point_in_polygon(event.position(), selected_region)
            ):
                normalized = self.map_widget_to_normalized(event.position())
                if normalized is not None:
                    self._active_region_move_id = selected_region.region_id
                    self._last_region_position = normalized
                return
            for region in reversed(self._regions):
                if self._point_in_polygon(event.position(), region):
                    self.regionSelected.emit(region.region_id)
                    return

        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._active_vertex is not None:
            normalized = self.map_widget_to_normalized(event.position())
            if normalized is None:
                return
            self.regionVertexMoved.emit(
                self._active_vertex[0],
                self._active_vertex[1],
                normalized[0],
                normalized[1],
            )
            return

        if self._active_region_move_id is not None and self._last_region_position is not None:
            normalized = self.map_widget_to_normalized(event.position())
            if normalized is None:
                return
            dx = normalized[0] - self._last_region_position[0]
            dy = normalized[1] - self._last_region_position[1]
            self._last_region_position = normalized
            self.regionMoved.emit(self._active_region_move_id, dx, dy)
            return

        if self._drag_start is None or self._mode in {"draw_region", "edit_region", "sampling"}:
            return
        delta = event.pos() - self._drag_start
        self._drag_start = event.pos()
        self._pan += QPointF(float(delta.x()), float(delta.y()))
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self._active_vertex = None
            self._active_region_move_id = None
            self._last_region_position = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._mode == "draw_region":
            self.regionDrawingFinished.emit()
            return
        if self._mode == "edit_region":
            selected_region = self._find_region(self._selected_region_id)
            if selected_region is None:
                return
            normalized = self.map_widget_to_normalized(event.position())
            edge_index = self._nearest_edge(event.position(), selected_region)
            if normalized is None or edge_index is None:
                return
            self.regionEdgeInserted.emit(
                selected_region.region_id,
                edge_index,
                normalized[0],
                normalized[1],
            )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._mode == "draw_region" and event.key() in {
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        }:
            self.regionDrawingFinished.emit()
            return
        if event.key() == Qt.Key.Key_Escape and self._mode == "draw_region":
            self.regionDrawingCancelled.emit()
            return
        if event.key() == Qt.Key.Key_Escape and self._mode == "sampling":
            self.samplingCancelled.emit()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            return
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    @staticmethod
    def _distance(a: QPointF, b: QPointF) -> float:
        return float(np.hypot(a.x() - b.x(), a.y() - b.y()))

    @staticmethod
    def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> float:
        start_x = start.x()
        start_y = start.y()
        end_x = end.x()
        end_y = end.y()
        point_x = point.x()
        point_y = point.y()
        dx = end_x - start_x
        dy = end_y - start_y
        if dx == 0.0 and dy == 0.0:
            return float(np.hypot(point_x - start_x, point_y - start_y))
        projection = ((point_x - start_x) * dx + (point_y - start_y) * dy) / (dx * dx + dy * dy)
        projection = max(0.0, min(1.0, projection))
        closest_x = start_x + projection * dx
        closest_y = start_y + projection * dy
        return float(np.hypot(point_x - closest_x, point_y - closest_y))

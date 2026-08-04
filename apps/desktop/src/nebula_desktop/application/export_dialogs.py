from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from engine import apply_crop
from engine.render import calculate_crop_box
from image_io import CanonicalImage
from project_model import CropDeclaration
from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nebula_desktop.views.image_preview import ImagePreviewWidget

ScreenInterpolation = Literal["nearest", "bicubic"]
PrintUnits = Literal["cm", "inches"]
CropPreset = Literal[
    "off",
    "original",
    "custom",
    "1:1",
    "4:5",
    "5:4",
    "3:2",
    "2:3",
    "16:9",
    "9:16",
]
CropPreviewMode = Literal["frame", "cropped"]

MIN_CROP_SIZE = 0.02

CROP_PRESET_LABELS: list[tuple[str, CropPreset]] = [
    ("Off / Full Frame", "off"),
    ("Original", "original"),
    ("Custom", "custom"),
    ("1:1", "1:1"),
    ("4:5", "4:5"),
    ("5:4", "5:4"),
    ("3:2", "3:2"),
    ("2:3", "2:3"),
    ("16:9", "16:9"),
    ("9:16", "9:16"),
]

CROP_PRESET_ASPECTS: dict[CropPreset, float] = {
    "1:1": 1.0,
    "4:5": 4.0 / 5.0,
    "5:4": 5.0 / 4.0,
    "3:2": 3.0 / 2.0,
    "2:3": 2.0 / 3.0,
    "16:9": 16.0 / 9.0,
    "9:16": 9.0 / 16.0,
}
KNOWN_CROP_PRESETS: set[CropPreset] = {preset for _, preset in CROP_PRESET_LABELS}

CropHandle = Literal[
    "move",
    "left",
    "right",
    "top",
    "bottom",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
]
VISIBLE_CROP_HANDLES: tuple[CropHandle, ...] = (
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "left",
    "right",
    "top",
    "bottom",
)


@dataclass(frozen=True)
class ScreenExportOptions:
    output_format: Literal["png", "jpeg", "tiff"]
    width_px: int
    height_px: int
    interpolation: ScreenInterpolation
    crop: CropDeclaration

    @property
    def suffix(self) -> str:
        return {"png": ".png", "jpeg": ".jpg", "tiff": ".tiff"}[self.output_format]


@dataclass(frozen=True)
class PrintExportOptions:
    output_format: Literal["png", "tiff"]
    width: float
    height: float
    units: PrintUnits
    ppi: int
    interpolation: ScreenInterpolation
    crop: CropDeclaration

    @property
    def suffix(self) -> str:
        return {"png": ".png", "tiff": ".tiff"}[self.output_format]


def _full_frame_crop(*, enabled: bool = False, aspect_ratio: str = "original") -> CropDeclaration:
    return CropDeclaration.model_validate(
        {
            "enabled": enabled,
            "x": 0.0,
            "y": 0.0,
            "width": 1.0,
            "height": 1.0,
            "aspect_ratio": aspect_ratio,
            "lock_aspect_ratio": aspect_ratio != "custom",
        }
    )


def _native_aspect_ratio(width: int, height: int) -> float:
    return width / max(height, 1)


def _crop_ratio(crop: CropDeclaration, native_width: int, native_height: int) -> float:
    if not crop.enabled or crop.aspect_ratio == "original":
        return _native_aspect_ratio(native_width, native_height)
    if crop.aspect_ratio in CROP_PRESET_ASPECTS:
        return CROP_PRESET_ASPECTS[crop.aspect_ratio]
    return crop.width / max(crop.height, 1e-9)


def _crop_pixel_dimensions(
    crop: CropDeclaration,
    native_width: int,
    native_height: int,
) -> tuple[int, int]:
    left, top, right, bottom = calculate_crop_box(crop, native_width, native_height)
    return right - left, bottom - top


def _clamp_crop_rect(
    x: float,
    y: float,
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    width = max(MIN_CROP_SIZE, min(1.0, width))
    height = max(MIN_CROP_SIZE, min(1.0, height))
    x = max(0.0, min(1.0 - width, x))
    y = max(0.0, min(1.0 - height, y))
    return x, y, width, height


def _fit_crop_to_aspect(crop: CropDeclaration, aspect_ratio: float) -> CropDeclaration:
    center_x = crop.x + crop.width / 2.0
    center_y = crop.y + crop.height / 2.0
    width = crop.width
    height = crop.height
    current_ratio = width / max(height, 1e-9)
    if current_ratio > aspect_ratio:
        width = min(width, height * aspect_ratio)
    else:
        height = min(height, width / aspect_ratio)
    x, y, width, height = _clamp_crop_rect(
        center_x - width / 2.0,
        center_y - height / 2.0,
        width,
        height,
    )
    return crop.model_copy(
        update={
            "enabled": True,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "lock_aspect_ratio": True,
        }
    )


def _crop_description(crop: CropDeclaration, native_width: int, native_height: int) -> str:
    if not crop.enabled or crop.is_full_frame():
        return "Full Frame"
    label = crop.aspect_ratio or "Custom"
    if label == "original":
        label = "Original"
    return f"{label} crop"


class CropPreviewWidget(ImagePreviewWidget):
    cropChanged = Signal(float, float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._crop: CropDeclaration = _full_frame_crop(enabled=True)
        self._locked_aspect_ratio: float | None = None
        self._active_handle: CropHandle | None = None
        self._crop_drag_start: tuple[float, float] | None = None
        self._crop_drag_origin: CropDeclaration | None = None

    def set_crop(self, crop: CropDeclaration, *, locked_aspect_ratio: float | None) -> None:
        self._crop = crop
        self._locked_aspect_ratio = locked_aspect_ratio
        self.update()

    def crop(self) -> CropDeclaration:
        return self._crop

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._image is None or not self._crop.enabled:
            return
        target_rect = self.image_target_rect()
        if target_rect is None:
            return
        crop_rect = self._crop_widget_rect()
        if crop_rect is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dim = QColor(0, 0, 0, 122)
        painter.fillRect(
            QRectF(
                target_rect.left(),
                target_rect.top(),
                target_rect.width(),
                crop_rect.top() - target_rect.top(),
            ),
            dim,
        )
        painter.fillRect(
            QRectF(
                target_rect.left(),
                crop_rect.bottom(),
                target_rect.width(),
                target_rect.bottom() - crop_rect.bottom(),
            ),
            dim,
        )
        painter.fillRect(
            QRectF(
                target_rect.left(),
                crop_rect.top(),
                crop_rect.left() - target_rect.left(),
                crop_rect.height(),
            ),
            dim,
        )
        painter.fillRect(
            QRectF(
                crop_rect.right(),
                crop_rect.top(),
                target_rect.right() - crop_rect.right(),
                crop_rect.height(),
            ),
            dim,
        )
        painter.setPen(QPen(QColor("#f8fafc"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(crop_rect)
        third_pen = QPen(QColor(248, 250, 252, 96), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(third_pen)
        for fraction in (1.0 / 3.0, 2.0 / 3.0):
            x = crop_rect.left() + crop_rect.width() * fraction
            y = crop_rect.top() + crop_rect.height() * fraction
            painter.drawLine(QPointF(x, crop_rect.top()), QPointF(x, crop_rect.bottom()))
            painter.drawLine(QPointF(crop_rect.left(), y), QPointF(crop_rect.right(), y))
        painter.setBrush(QColor("#f8fafc"))
        painter.setPen(Qt.PenStyle.NoPen)
        for handle_rect in self._resize_handle_rects().values():
            painter.drawRect(handle_rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        handle = self._handle_at(event.position())
        if handle is None:
            return
        normalized = self.map_widget_to_frame_normalized(event.position())
        if normalized is None:
            return
        self._active_handle = handle
        self._crop_drag_start = normalized
        self._crop_drag_origin = self._crop

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._active_handle is None
            or self._crop_drag_start is None
            or self._crop_drag_origin is None
        ):
            return super().mouseMoveEvent(event)
        normalized = self.map_widget_to_frame_normalized(event.position())
        if normalized is None:
            return
        crop = self._updated_crop(self._active_handle, normalized)
        self._crop = crop
        self.cropChanged.emit(crop.x, crop.y, crop.width, crop.height)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._active_handle = None
        self._crop_drag_start = None
        self._crop_drag_origin = None
        super().mouseReleaseEvent(event)

    def _crop_widget_rect(self) -> QRectF | None:
        top_left = self.map_frame_normalized_to_widget((self._crop.x, self._crop.y))
        bottom_right = self.map_frame_normalized_to_widget(
            (self._crop.x + self._crop.width, self._crop.y + self._crop.height)
        )
        if top_left is None or bottom_right is None:
            return None
        return QRectF(top_left, bottom_right).normalized()

    def _handle_rects(self) -> dict[CropHandle, QRectF]:
        crop_rect = self._crop_widget_rect()
        if crop_rect is None:
            return {}
        size = 10.0
        half = size / 2.0
        center_x = crop_rect.center().x()
        center_y = crop_rect.center().y()
        return {
            "top_left": QRectF(crop_rect.left() - half, crop_rect.top() - half, size, size),
            "top_right": QRectF(crop_rect.right() - half, crop_rect.top() - half, size, size),
            "bottom_left": QRectF(crop_rect.left() - half, crop_rect.bottom() - half, size, size),
            "bottom_right": QRectF(crop_rect.right() - half, crop_rect.bottom() - half, size, size),
            "left": QRectF(crop_rect.left() - half, center_y - half, size, size),
            "right": QRectF(crop_rect.right() - half, center_y - half, size, size),
            "top": QRectF(center_x - half, crop_rect.top() - half, size, size),
            "bottom": QRectF(center_x - half, crop_rect.bottom() - half, size, size),
            "move": crop_rect,
        }

    def _resize_handle_rects(self) -> dict[CropHandle, QRectF]:
        handles = self._handle_rects()
        return {
            handle: rect
            for handle, rect in handles.items()
            if handle in VISIBLE_CROP_HANDLES
        }

    def _handle_at(self, position: QPointF) -> CropHandle | None:
        for handle in (
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
            "left",
            "right",
            "top",
            "bottom",
        ):
            rect = self._handle_rects().get(handle)
            if rect is not None and rect.contains(position):
                return handle
        move_rect = self._handle_rects().get("move")
        if move_rect is not None and move_rect.contains(position):
            return "move"
        return None

    def _updated_crop(self, handle: CropHandle, normalized: tuple[float, float]) -> CropDeclaration:
        assert self._crop_drag_start is not None
        assert self._crop_drag_origin is not None
        origin = self._crop_drag_origin
        x0 = origin.x
        y0 = origin.y
        x1 = origin.x + origin.width
        y1 = origin.y + origin.height
        px, py = normalized

        if handle == "move":
            dx = px - self._crop_drag_start[0]
            dy = py - self._crop_drag_start[1]
            x, y, width, height = _clamp_crop_rect(x0 + dx, y0 + dy, origin.width, origin.height)
            return origin.model_copy(update={"x": x, "y": y, "width": width, "height": height})

        if self._locked_aspect_ratio is None:
            left = x0
            top = y0
            right = x1
            bottom = y1
            if handle in {"left", "top_left", "bottom_left"}:
                left = min(px, right - MIN_CROP_SIZE)
            if handle in {"right", "top_right", "bottom_right"}:
                right = max(px, left + MIN_CROP_SIZE)
            if handle in {"top", "top_left", "top_right"}:
                top = min(py, bottom - MIN_CROP_SIZE)
            if handle in {"bottom", "bottom_left", "bottom_right"}:
                bottom = max(py, top + MIN_CROP_SIZE)
            x, y, width, height = _clamp_crop_rect(left, top, right - left, bottom - top)
            return origin.model_copy(update={"x": x, "y": y, "width": width, "height": height})

        aspect = self._locked_aspect_ratio
        if handle in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            anchor_x = x1 if "left" in handle else x0
            anchor_y = y1 if "top" in handle else y0
            width_from_x = abs(anchor_x - px)
            height_from_y = abs(anchor_y - py)
            width = max(width_from_x, height_from_y * aspect, MIN_CROP_SIZE)
            height = max(width / aspect, MIN_CROP_SIZE)
            if "left" in handle:
                left = anchor_x - width
                right = anchor_x
            else:
                left = anchor_x
                right = anchor_x + width
            if "top" in handle:
                top = anchor_y - height
                bottom = anchor_y
            else:
                top = anchor_y
                bottom = anchor_y + height
        elif handle in {"left", "right"}:
            anchor_x = x1 if handle == "left" else x0
            width = max(abs(anchor_x - px), MIN_CROP_SIZE)
            height = max(width / aspect, MIN_CROP_SIZE)
            center_y = origin.y + origin.height / 2.0
            if handle == "left":
                left = anchor_x - width
                right = anchor_x
            else:
                left = anchor_x
                right = anchor_x + width
            top = center_y - height / 2.0
            bottom = center_y + height / 2.0
        else:
            anchor_y = y1 if handle == "top" else y0
            height = max(abs(anchor_y - py), MIN_CROP_SIZE)
            width = max(height * aspect, MIN_CROP_SIZE)
            center_x = origin.x + origin.width / 2.0
            if handle == "top":
                top = anchor_y - height
                bottom = anchor_y
            else:
                top = anchor_y
                bottom = anchor_y + height
            left = center_x - width / 2.0
            right = center_x + width / 2.0

        x, y, width, height = _clamp_crop_rect(left, top, right - left, bottom - top)
        return origin.model_copy(update={"x": x, "y": y, "width": width, "height": height})


class CropEditorDialog(QDialog):
    def __init__(
        self,
        *,
        image: CanonicalImage,
        crop: CropDeclaration,
        native_width: int,
        native_height: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Crop")
        self._base_image = image
        self._native_width = native_width
        self._native_height = native_height
        self._crop = crop
        self._preview_mode: CropPreviewMode = "frame"

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.preview_mode_selector = QComboBox(self)
        self.preview_mode_selector.addItem("Show Full Frame", "frame")
        self.preview_mode_selector.addItem("Show Cropped Output", "cropped")
        controls.addWidget(QLabel("Crop Preview", self))
        controls.addWidget(self.preview_mode_selector, 1)
        self.aspect_label = QLabel(self)
        controls.addWidget(self.aspect_label)
        layout.addLayout(controls)

        self.preview = CropPreviewWidget(self)
        self.preview.setMinimumSize(720, 480)
        layout.addWidget(self.preview, 1)

        actions = QHBoxLayout()
        self.reset_button = QPushButton("Reset to Full Frame", self)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.preview.cropChanged.connect(self._on_crop_changed)
        self.preview_mode_selector.currentIndexChanged.connect(self._refresh_preview)
        self.reset_button.clicked.connect(self._reset_crop)

        self._refresh_preview()

    def crop(self) -> CropDeclaration:
        return self._crop

    def _on_crop_changed(self, x: float, y: float, width: float, height: float) -> None:
        self._crop = self._crop.model_copy(
            update={"x": x, "y": y, "width": width, "height": height}
        )
        self._refresh_preview()

    def _reset_crop(self) -> None:
        self._crop = _full_frame_crop(
            enabled=True,
            aspect_ratio=self._crop.aspect_ratio or "original",
        )
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._preview_mode = self.preview_mode_selector.currentData()
        self.aspect_label.setText(
            _crop_description(self._crop, self._native_width, self._native_height)
        )
        locked_aspect = (
            _crop_ratio(self._crop, self._native_width, self._native_height)
            if self._crop.lock_aspect_ratio and self._crop.enabled
            else None
        )
        if self._preview_mode == "cropped" and self._crop.enabled:
            self.preview.set_image(apply_crop(self._base_image, self._crop))
            self.preview.set_crop(_full_frame_crop(enabled=False), locked_aspect_ratio=None)
            self.preview.set_interaction_mode("navigate")
        else:
            self.preview.set_image(self._base_image)
            self.preview.set_crop(self._crop, locked_aspect_ratio=locked_aspect)
            self.preview.set_interaction_mode("navigate")


class _BaseExportDialog(QDialog):
    def __init__(
        self,
        *,
        native_width: int,
        native_height: int,
        preview_image: CanonicalImage | None,
        initial_crop: CropDeclaration | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._native_width = native_width
        self._native_height = native_height
        self._preview_image = preview_image
        self._crop = (
            initial_crop.model_copy(deep=True)
            if initial_crop is not None
            else _full_frame_crop()
        )
        self._last_enabled_crop = (
            self._crop if self._crop.enabled else _full_frame_crop(enabled=True)
        )
        self._syncing_dimensions = False
        self.crop_selector: QComboBox
        self.crop_summary_label: QLabel
        self.edit_crop_button: QPushButton
        self.reset_crop_button: QPushButton

    def _current_crop(self) -> CropDeclaration:
        if self._crop.enabled:
            return self._crop
        return _full_frame_crop(enabled=False)

    def _current_ratio(self) -> float:
        return _crop_ratio(self._current_crop(), self._native_width, self._native_height)

    def _crop_dimensions(self) -> tuple[int, int]:
        crop = self._current_crop()
        if not crop.enabled:
            return self._native_width, self._native_height
        return _crop_pixel_dimensions(crop, self._native_width, self._native_height)

    def _apply_crop_preset(self, preset: CropPreset) -> None:
        if preset == "off":
            if self._crop.enabled:
                self._last_enabled_crop = self._crop
            self._crop = self._crop.model_copy(update={"enabled": False})
            self._refresh_crop_labels()
            self._refresh_dimensions_from_ratio()
            return

        base = self._crop if self._crop.enabled else self._last_enabled_crop
        if preset == "custom":
            self._crop = base.model_copy(
                update={"enabled": True, "aspect_ratio": "custom", "lock_aspect_ratio": False}
            )
        elif preset == "original":
            self._crop = _fit_crop_to_aspect(
                base.model_copy(update={"aspect_ratio": "original", "lock_aspect_ratio": True}),
                _native_aspect_ratio(self._native_width, self._native_height),
            )
        else:
            self._crop = _fit_crop_to_aspect(
                base.model_copy(update={"aspect_ratio": preset, "lock_aspect_ratio": True}),
                CROP_PRESET_ASPECTS[preset],
            )
        self._last_enabled_crop = self._crop
        self._refresh_crop_labels()
        self._refresh_dimensions_from_ratio()

    def _edit_crop(self) -> None:
        if self._preview_image is None:
            return
        if not self._crop.enabled:
            self._apply_crop_preset("original")
        dialog = CropEditorDialog(
            image=self._preview_image,
            crop=self._crop.model_copy(deep=True),
            native_width=self._native_width,
            native_height=self._native_height,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._crop = dialog.crop()
        self._last_enabled_crop = self._crop
        self._refresh_crop_labels()
        self._refresh_dimensions_from_ratio()

    def _reset_crop(self) -> None:
        preset = self.crop_selector.currentData()
        if preset == "off":
            self._crop = _full_frame_crop(enabled=False)
        else:
            self._crop = _full_frame_crop(enabled=True, aspect_ratio="original")
            if preset not in {"original", "off"}:
                self._apply_crop_preset(preset)
                return
        self._refresh_crop_labels()
        self._refresh_dimensions_from_ratio()

    def _refresh_crop_labels(self) -> None:
        self.crop_summary_label.setText(
            _crop_description(self._crop, self._native_width, self._native_height)
        )
        self.edit_crop_button.setEnabled(
            self._preview_image is not None and self.crop_selector.currentData() != "off"
        )
        self.reset_crop_button.setEnabled(self._preview_image is not None)

    def _refresh_dimensions_from_ratio(self) -> None:
        raise NotImplementedError


class ScreenExportDialog(_BaseExportDialog):
    def __init__(
        self,
        *,
        native_width: int,
        native_height: int,
        default_width_px: int | None = None,
        default_height_px: int | None = None,
        preview_image: CanonicalImage | None,
        initial_crop: CropDeclaration | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            native_width=native_width,
            native_height=native_height,
            preview_image=preview_image,
            initial_crop=initial_crop,
            parent=parent,
        )
        self.setWindowTitle("Export for Screen")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.format_selector = QComboBox(self)
        self.format_selector.addItem("PNG", "png")
        self.format_selector.addItem("JPEG", "jpeg")
        self.format_selector.addItem("TIFF", "tiff")

        self.crop_selector = QComboBox(self)
        for label, value in CROP_PRESET_LABELS:
            self.crop_selector.addItem(label, value)
        self.edit_crop_button = QPushButton("Edit Crop", self)
        self.reset_crop_button = QPushButton("Reset Crop", self)
        crop_buttons = QHBoxLayout()
        crop_buttons.addWidget(self.crop_selector, 1)
        crop_buttons.addWidget(self.edit_crop_button)
        crop_buttons.addWidget(self.reset_crop_button)
        crop_widget = QWidget(self)
        crop_widget.setLayout(crop_buttons)

        self.crop_summary_label = QLabel(self)
        self.crop_summary_label.setWordWrap(True)

        self.width_input = QSpinBox(self)
        self.width_input.setRange(1, max(native_width * 8, 1))
        self.width_input.setValue(default_width_px or native_width)

        self.height_input = QSpinBox(self)
        self.height_input.setRange(1, max(native_height * 8, 1))
        self.height_input.setValue(default_height_px or native_height)

        self.lock_aspect_checkbox = QCheckBox("Keep crop aspect ratio", self)
        self.lock_aspect_checkbox.setChecked(True)

        self.native_label = QLabel(
            f"Native cropped source: {native_width} x {native_height} px",
            self,
        )

        self.interpolation_selector = QComboBox(self)
        self.interpolation_selector.addItem("Preserve pixels", "nearest")
        self.interpolation_selector.addItem("Smoother edges", "bicubic")

        self.guidance_label = QLabel(
            "Crop chooses which part of the mastered image becomes this output. "
            "The adjustment flow still works on the full image.",
            self,
        )
        self.guidance_label.setWordWrap(True)

        form.addRow("Format", self.format_selector)
        form.addRow("Crop", crop_widget)
        form.addRow("", self.crop_summary_label)
        form.addRow("Target width", self.width_input)
        form.addRow("Target height", self.height_input)
        form.addRow("", self.lock_aspect_checkbox)
        form.addRow("Upscale method", self.interpolation_selector)
        form.addRow("", self.native_label)
        form.addRow("", self.guidance_label)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.crop_selector.currentIndexChanged.connect(
            lambda: self._apply_crop_preset(self.crop_selector.currentData())
        )
        self.edit_crop_button.clicked.connect(self._edit_crop)
        self.reset_crop_button.clicked.connect(self._reset_crop)
        self.width_input.valueChanged.connect(self._width_changed)
        self.height_input.valueChanged.connect(self._height_changed)
        self.lock_aspect_checkbox.toggled.connect(self._refresh_dimensions_from_ratio)
        self._refresh_crop_selector()
        self._refresh_crop_labels()
        self._refresh_dimensions_from_ratio()

    def _refresh_crop_selector(self) -> None:
        value = self._crop.aspect_ratio if self._crop.enabled else "off"
        if value == "original" and not self._crop.enabled:
            value = "off"
        selected_value = value if value in KNOWN_CROP_PRESETS else "custom"
        index = self.crop_selector.findData(selected_value)
        with QSignalBlocker(self.crop_selector):
            self.crop_selector.setCurrentIndex(max(0, index))

    def _refresh_dimensions_from_ratio(self) -> None:
        ratio = self._current_ratio()
        crop_width, crop_height = self._crop_dimensions()
        self.native_label.setText(f"Native cropped source: {crop_width} x {crop_height} px")
        if not self.lock_aspect_checkbox.isChecked():
            return
        with QSignalBlocker(self.height_input):
            self.height_input.setValue(max(1, int(round(self.width_input.value() / ratio))))

    def _width_changed(self, width: int) -> None:
        if self._syncing_dimensions or not self.lock_aspect_checkbox.isChecked():
            return
        self._syncing_dimensions = True
        ratio = self._current_ratio()
        with QSignalBlocker(self.height_input):
            self.height_input.setValue(max(1, int(round(width / ratio))))
        self._syncing_dimensions = False

    def _height_changed(self, height: int) -> None:
        if self._syncing_dimensions or not self.lock_aspect_checkbox.isChecked():
            return
        self._syncing_dimensions = True
        ratio = self._current_ratio()
        with QSignalBlocker(self.width_input):
            self.width_input.setValue(max(1, int(round(height * ratio))))
        self._syncing_dimensions = False

    def _locked_output_dimensions(self) -> tuple[int, int]:
        width = self.width_input.value()
        if not self.lock_aspect_checkbox.isChecked():
            return width, self.height_input.value()
        ratio = self._current_ratio()
        return width, max(1, int(round(width / ratio)))

    def selected_options(self) -> ScreenExportOptions:
        width, height = self._locked_output_dimensions()
        return ScreenExportOptions(
            output_format=self.format_selector.currentData(),
            width_px=width,
            height_px=height,
            interpolation=self.interpolation_selector.currentData(),
            crop=self._current_crop(),
        )


class PrintExportDialog(_BaseExportDialog):
    def __init__(
        self,
        *,
        default_width: float,
        default_height: float,
        default_units: PrintUnits,
        default_ppi: int,
        native_width: int,
        native_height: int,
        preview_image: CanonicalImage | None,
        initial_crop: CropDeclaration | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            native_width=native_width,
            native_height=native_height,
            preview_image=preview_image,
            initial_crop=initial_crop,
            parent=parent,
        )
        self.setWindowTitle("Export for Print")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.format_selector = QComboBox(self)
        self.format_selector.addItem("TIFF", "tiff")
        self.format_selector.addItem("PNG", "png")

        self.crop_selector = QComboBox(self)
        for label, value in CROP_PRESET_LABELS:
            self.crop_selector.addItem(label, value)
        self.edit_crop_button = QPushButton("Edit Crop", self)
        self.reset_crop_button = QPushButton("Reset Crop", self)
        crop_buttons = QHBoxLayout()
        crop_buttons.addWidget(self.crop_selector, 1)
        crop_buttons.addWidget(self.edit_crop_button)
        crop_buttons.addWidget(self.reset_crop_button)
        crop_widget = QWidget(self)
        crop_widget.setLayout(crop_buttons)

        self.crop_summary_label = QLabel(self)
        self.crop_summary_label.setWordWrap(True)

        self.width_input = QDoubleSpinBox(self)
        self.width_input.setRange(0.1, 500.0)
        self.width_input.setDecimals(2)
        self.width_input.setValue(default_width)

        self.height_input = QDoubleSpinBox(self)
        self.height_input.setRange(0.1, 500.0)
        self.height_input.setDecimals(2)
        self.height_input.setValue(default_height)

        self.units_selector = QComboBox(self)
        self.units_selector.addItem("cm", "cm")
        self.units_selector.addItem("inches", "inches")
        self.units_selector.setCurrentIndex(0 if default_units == "cm" else 1)

        self.ppi_input = QSpinBox(self)
        self.ppi_input.setRange(72, 2400)
        self.ppi_input.setValue(default_ppi)

        self.lock_aspect_checkbox = QCheckBox("Keep crop aspect ratio", self)
        self.lock_aspect_checkbox.setChecked(True)

        self.interpolation_selector = QComboBox(self)
        self.interpolation_selector.addItem("Preserve pixels", "nearest")
        self.interpolation_selector.addItem("Smoother edges", "bicubic")

        self.pixel_dimensions_label = QLabel(self)
        self.guidance_label = QLabel(
            "Cropping happens before resizing or upscaling, so pixels outside the crop are "
            "not enlarged unnecessarily.",
            self,
        )
        self.guidance_label.setWordWrap(True)

        form.addRow("Format", self.format_selector)
        form.addRow("Crop", crop_widget)
        form.addRow("", self.crop_summary_label)
        form.addRow("Width", self.width_input)
        form.addRow("Height", self.height_input)
        form.addRow("Units", self.units_selector)
        form.addRow("Target DPI", self.ppi_input)
        form.addRow("", self.lock_aspect_checkbox)
        form.addRow("Upscale method", self.interpolation_selector)
        form.addRow("Output pixels", self.pixel_dimensions_label)
        form.addRow("", self.guidance_label)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.crop_selector.currentIndexChanged.connect(
            lambda: self._apply_crop_preset(self.crop_selector.currentData())
        )
        self.edit_crop_button.clicked.connect(self._edit_crop)
        self.reset_crop_button.clicked.connect(self._reset_crop)
        self.units_selector.currentIndexChanged.connect(self._convert_units)
        self.width_input.valueChanged.connect(self._width_changed)
        self.height_input.valueChanged.connect(self._height_changed)
        self.ppi_input.valueChanged.connect(self._refresh_pixel_dimensions)
        self.lock_aspect_checkbox.toggled.connect(self._refresh_dimensions_from_ratio)
        self._refresh_crop_selector()
        self._refresh_crop_labels()
        self._refresh_dimensions_from_ratio()
        self._refresh_pixel_dimensions()

    def _refresh_crop_selector(self) -> None:
        value = self._crop.aspect_ratio if self._crop.enabled else "off"
        selected_value = value if value in KNOWN_CROP_PRESETS else "custom"
        index = self.crop_selector.findData(selected_value)
        with QSignalBlocker(self.crop_selector):
            self.crop_selector.setCurrentIndex(max(0, index))

    def _convert_units(self) -> None:
        current_units = self.units_selector.currentData()
        factor = 1 / 2.54 if current_units == "inches" else 2.54
        with QSignalBlocker(self.width_input), QSignalBlocker(self.height_input):
            self.width_input.setValue(self.width_input.value() * factor)
            self.height_input.setValue(self.height_input.value() * factor)
        self._refresh_pixel_dimensions()

    def _refresh_dimensions_from_ratio(self) -> None:
        if not self.lock_aspect_checkbox.isChecked():
            self._refresh_pixel_dimensions()
            return
        ratio = self._current_ratio()
        with QSignalBlocker(self.height_input):
            self.height_input.setValue(round(self.width_input.value() / ratio, 2))
        self._refresh_pixel_dimensions()

    def _width_changed(self, width: float) -> None:
        if self._syncing_dimensions or not self.lock_aspect_checkbox.isChecked():
            self._refresh_pixel_dimensions()
            return
        self._syncing_dimensions = True
        ratio = self._current_ratio()
        with QSignalBlocker(self.height_input):
            self.height_input.setValue(round(width / ratio, 2))
        self._syncing_dimensions = False
        self._refresh_pixel_dimensions()

    def _height_changed(self, height: float) -> None:
        if self._syncing_dimensions or not self.lock_aspect_checkbox.isChecked():
            self._refresh_pixel_dimensions()
            return
        self._syncing_dimensions = True
        ratio = self._current_ratio()
        with QSignalBlocker(self.width_input):
            self.width_input.setValue(round(height * ratio, 2))
        self._syncing_dimensions = False
        self._refresh_pixel_dimensions()

    def _refresh_pixel_dimensions(self) -> None:
        width = self.width_input.value()
        height = self.height_input.value()
        ppi = self.ppi_input.value()
        units = self.units_selector.currentData()
        if units == "cm":
            width_px = int(round(width / 2.54 * ppi))
            height_px = int(round(height / 2.54 * ppi))
        else:
            width_px = int(round(width * ppi))
            height_px = int(round(height * ppi))
        self.pixel_dimensions_label.setText(f"{width_px} x {height_px} px")

    def _locked_output_size(self) -> tuple[float, float]:
        width = self.width_input.value()
        if not self.lock_aspect_checkbox.isChecked():
            return width, self.height_input.value()
        ratio = self._current_ratio()
        return width, round(width / ratio, 2)

    def selected_options(self) -> PrintExportOptions:
        width, height = self._locked_output_size()
        return PrintExportOptions(
            output_format=self.format_selector.currentData(),
            width=width,
            height=height,
            units=self.units_selector.currentData(),
            ppi=self.ppi_input.value(),
            interpolation=self.interpolation_selector.currentData(),
            crop=self._current_crop(),
        )

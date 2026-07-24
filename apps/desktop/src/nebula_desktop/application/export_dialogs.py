from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

ScreenInterpolation = Literal["nearest", "bicubic"]
PrintUnits = Literal["cm", "inches"]


@dataclass(frozen=True)
class ScreenExportOptions:
    output_format: Literal["png", "jpeg", "tiff"]
    width_px: int
    interpolation: ScreenInterpolation

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

    @property
    def suffix(self) -> str:
        return {"png": ".png", "tiff": ".tiff"}[self.output_format]


def _scaled_height(width_px: int, native_width: int, native_height: int) -> int:
    return max(1, int(round(native_height * (width_px / native_width))))


class ScreenExportDialog(QDialog):
    def __init__(
        self,
        *,
        native_width: int,
        native_height: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export for Screen")
        self._native_width = native_width
        self._native_height = native_height

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.format_selector = QComboBox(self)
        self.format_selector.addItem("PNG", "png")
        self.format_selector.addItem("JPEG", "jpeg")
        self.format_selector.addItem("TIFF", "tiff")

        self.width_input = QSpinBox(self)
        self.width_input.setRange(1, max(native_width * 8, 1))
        self.width_input.setValue(native_width)

        self.height_label = QLabel(self)
        self.native_label = QLabel(
            f"Native cropped source: {native_width} x {native_height} px",
            self,
        )

        self.interpolation_selector = QComboBox(self)
        self.interpolation_selector.addItem("Preserve pixels", "nearest")
        self.interpolation_selector.addItem("Smoother edges", "bicubic")

        self.guidance_label = QLabel(
            "Preserve pixels maps the mastered image onto a larger pixel grid "
            "without inventing new detail.",
            self,
        )
        self.guidance_label.setWordWrap(True)

        form.addRow("Format", self.format_selector)
        form.addRow("Target width", self.width_input)
        form.addRow("Resulting height", self.height_label)
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

        self.width_input.valueChanged.connect(self._refresh_height)
        self._refresh_height(self.width_input.value())

    def _refresh_height(self, width_px: int) -> None:
        height_px = _scaled_height(width_px, self._native_width, self._native_height)
        upscale_factor = width_px / max(self._native_width, 1)
        note = "Native size" if abs(upscale_factor - 1.0) < 1e-9 else f"{upscale_factor:.2f}x"
        self.height_label.setText(f"{height_px} px ({note})")

    def selected_options(self) -> ScreenExportOptions:
        return ScreenExportOptions(
            output_format=self.format_selector.currentData(),
            width_px=self.width_input.value(),
            interpolation=self.interpolation_selector.currentData(),
        )


class PrintExportDialog(QDialog):
    def __init__(
        self,
        *,
        default_width: float,
        default_height: float,
        default_units: PrintUnits,
        default_ppi: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export for Print")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.format_selector = QComboBox(self)
        self.format_selector.addItem("TIFF", "tiff")
        self.format_selector.addItem("PNG", "png")

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

        self.interpolation_selector = QComboBox(self)
        self.interpolation_selector.addItem("Preserve pixels", "nearest")
        self.interpolation_selector.addItem("Smoother edges", "bicubic")

        self.pixel_dimensions_label = QLabel(self)
        self.guidance_label = QLabel(
            "Target DPI controls print pixel density. Preserve pixels avoids "
            "inventing fine detail during enlargement.",
            self,
        )
        self.guidance_label.setWordWrap(True)

        form.addRow("Format", self.format_selector)
        form.addRow("Width", self.width_input)
        form.addRow("Height", self.height_input)
        form.addRow("Units", self.units_selector)
        form.addRow("Target DPI", self.ppi_input)
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

        self.units_selector.currentIndexChanged.connect(self._convert_units)
        self.width_input.valueChanged.connect(self._refresh_pixel_dimensions)
        self.height_input.valueChanged.connect(self._refresh_pixel_dimensions)
        self.ppi_input.valueChanged.connect(self._refresh_pixel_dimensions)
        self._refresh_pixel_dimensions()

    def _convert_units(self) -> None:
        current_units = self.units_selector.currentData()
        factor = 1 / 2.54 if current_units == "inches" else 2.54
        with QSignalBlocker(self.width_input), QSignalBlocker(self.height_input):
            self.width_input.setValue(self.width_input.value() * factor)
            self.height_input.setValue(self.height_input.value() * factor)
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

    def selected_options(self) -> PrintExportOptions:
        return PrintExportOptions(
            output_format=self.format_selector.currentData(),
            width=self.width_input.value(),
            height=self.height_input.value(),
            units=self.units_selector.currentData(),
            ppi=self.ppi_input.value(),
            interpolation=self.interpolation_selector.currentData(),
        )

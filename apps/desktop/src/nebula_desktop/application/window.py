from __future__ import annotations

from pathlib import Path
from typing import cast

from project_model import PrintRenderProfile, ScreenRenderProfile
from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nebula_desktop.application.export_dialogs import (
    PrintExportDialog,
    ScreenExportDialog,
)
from nebula_desktop.application.project_scaffold import (
    ProjectScaffoldError,
    scaffold_project_from_image,
)
from nebula_desktop.viewmodels.project_editor import (
    AdjustmentKind,
    AdjustmentSummary,
    ProjectEditorViewModel,
    RegionSummary,
    SemanticOverlaySelection,
)
from nebula_desktop.views.image_preview import (
    ImagePreviewWidget,
    ImageSample,
    InteractionMode,
    SampleMarker,
)


def _swatch_pixmap(rgb: tuple[float, float, float], size: int = 20) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor.fromRgbF(*rgb))
    return pixmap


def _allow_horizontal_shrink(widget: QWidget) -> None:
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)


_MULTIPLIER_UI_MIN = -100.0
_MULTIPLIER_UI_MAX = 100.0
_SHIFT_UI_MIN = -100.0
_SHIFT_UI_MAX = 100.0
_SMOOTHING_UI_MIN = 0.0
_SMOOTHING_UI_MAX = 100.0


def _brightness_amount_to_ui(amount: float) -> float:
    return max(_MULTIPLIER_UI_MIN, min(_MULTIPLIER_UI_MAX, (amount - 1.0) * 100.0))


def _brightness_ui_to_amount(value: float) -> float:
    return max(0.0, 1.0 + (value / 100.0))


def _primary_slider_bounds(transform_type: str, type_label: str) -> tuple[int, int]:
    if transform_type == "shift_colour_point":
        return int(_SHIFT_UI_MIN), int(_SHIFT_UI_MAX)
    if type_label == "Smoothing":
        return int(_SMOOTHING_UI_MIN), int(_SMOOTHING_UI_MAX)
    return int(_MULTIPLIER_UI_MIN), int(_MULTIPLIER_UI_MAX)


class MainWindow(QMainWindow):
    def __init__(self, project_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Nebula Master Desktop")
        self._initial_size_applied = False
        self._adjustment_render_timer = QTimer(self)
        self._adjustment_render_timer.setSingleShot(True)
        self._adjustment_render_timer.setInterval(300)
        self._adjustment_render_timer.timeout.connect(self._request_deferred_adjustment_render)
        self.view_model = ProjectEditorViewModel(self)
        self._build_ui()
        self._connect_signals()
        if project_path is not None:
            self.view_model.open_project(project_path, async_preview=True)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self._initial_size_applied:
            return
        self._apply_initial_window_size()
        self._initial_size_applied = True

    def _apply_initial_window_size(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1200, 820)
            return

        available = screen.availableGeometry()
        target_width = min(1500, max(960, int(available.width() * 0.92)))
        target_height = min(960, max(700, int(available.height() * 0.88)))
        width = min(target_width, available.width())
        height = min(target_height, available.height())
        self.resize(width, height)

    def _build_ui(self) -> None:
        new_project_action = QAction("New Project from Image...", self)
        new_project_action.triggered.connect(self._new_project_from_image_dialog)
        open_action = QAction("Open Project...", self)
        open_action.triggered.connect(self._open_project_dialog)
        export_screen_action = QAction("Export for Screen...", self)
        export_screen_action.triggered.connect(self._export_for_screen)
        export_print_action = QAction("Export for Print...", self)
        export_print_action.triggered.connect(self._export_for_print)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(new_project_action)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(export_screen_action)
        file_menu.addAction(export_print_action)

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([320, 860, 360])

        bottom_panel = self._build_bottom_panel()
        root_layout.addWidget(splitter, 1)
        root_layout.addWidget(bottom_panel, 0)
        root_layout.setStretch(0, 5)
        root_layout.setStretch(1, 1)
        self.setCentralWidget(root)

        status = QStatusBar(self)
        self.setStatusBar(status)
        self.status_label = QLabel("Open a project to begin.")
        self.dirty_label = QLabel("Clean")
        status.addWidget(self.status_label, 1)
        status.addPermanentWidget(self.dirty_label)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setMinimumWidth(0)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Project")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.project_name_label = QLabel("No project open")
        self.project_path_label = QLabel("")
        self.project_path_label.setWordWrap(True)
        self.project_path_label.setStyleSheet("color: #7b8794;")

        source_title = QLabel("Sources")
        source_title.setStyleSheet("font-weight: 600;")
        self.sources_list = QListWidget()
        self.sources_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        adjustment_header = QHBoxLayout()
        adjustment_title = QLabel("Adjustments")
        adjustment_title.setStyleSheet("font-weight: 600;")
        self.add_adjustment_button = QPushButton("Add")
        self.move_earlier_button = QPushButton("Move Earlier")
        self.move_later_button = QPushButton("Move Later")
        adjustment_header.addWidget(adjustment_title)
        adjustment_header.addStretch(1)
        adjustment_header.addWidget(self.add_adjustment_button)

        self.adjustments_list = QListWidget()
        self.duplicate_adjustment_button = QPushButton("Duplicate")
        self.remove_adjustment_button = QPushButton("Remove")
        self.reset_adjustment_button = QPushButton("Reset")
        adjustment_actions = QHBoxLayout()
        adjustment_actions.addWidget(self.move_earlier_button)
        adjustment_actions.addWidget(self.move_later_button)
        adjustment_actions.addWidget(self.duplicate_adjustment_button)
        adjustment_actions.addWidget(self.remove_adjustment_button)
        adjustment_actions.addWidget(self.reset_adjustment_button)

        region_header = QHBoxLayout()
        region_title = QLabel("Regions")
        region_title.setStyleSheet("font-weight: 600;")
        self.add_region_button = QPushButton("Add Region")
        self.cancel_region_button = QPushButton("Cancel")
        self.show_regions_checkbox = QCheckBox("Show")
        self.show_regions_checkbox.setChecked(True)
        region_header.addWidget(region_title)
        region_header.addStretch(1)
        region_header.addWidget(self.show_regions_checkbox)
        region_header.addWidget(self.add_region_button)
        region_header.addWidget(self.cancel_region_button)

        self.regions_list = QListWidget()
        self.remove_region_button = QPushButton("Delete Region")

        layout.addWidget(title)
        layout.addWidget(self.project_name_label)
        layout.addWidget(self.project_path_label)
        layout.addWidget(source_title)
        layout.addWidget(self.sources_list, 1)
        layout.addLayout(adjustment_header)
        layout.addWidget(self.adjustments_list, 2)
        layout.addLayout(adjustment_actions)
        layout.addLayout(region_header)
        layout.addWidget(self.regions_list, 1)
        layout.addWidget(self.remove_region_button)
        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setMinimumWidth(0)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        toolbar = QVBoxLayout()
        toolbar.setSpacing(6)
        toolbar_row_primary = QHBoxLayout()
        toolbar_row_primary.setSpacing(6)
        toolbar_row_view = QHBoxLayout()
        toolbar_row_view.setSpacing(6)
        toolbar_row_zoom = QHBoxLayout()
        toolbar_row_zoom.setSpacing(6)
        toolbar_row_secondary = QHBoxLayout()
        toolbar_row_secondary.setSpacing(6)
        self.show_preview_button = QToolButton()
        self.show_preview_button.setText("Show Preview")
        self.show_preview_button.setCheckable(True)
        self.show_preview_button.setChecked(True)
        self.show_source_button = QToolButton()
        self.show_source_button.setText("Show Source")
        self.show_source_button.setCheckable(True)
        self.semantic_overlay_selector = QComboBox()
        self.semantic_overlay_selector.addItem("Overlay: Off", "off")
        self.semantic_overlay_selector.addItem("Overlay: Stars", "stars")
        self.semantic_overlay_selector.addItem("Overlay: Nebula", "nebula")
        self.semantic_overlay_selector.addItem("Overlay: Dark Dust", "dark_dust")
        self.before_after_checkbox = QCheckBox("Before / After")
        self.hold_previous_button = QPushButton("Hold Previous")
        self.fit_button = QPushButton("Fit")
        self.actual_button = QPushButton("100%")
        self.zoom_out_button = QPushButton("−")
        self.zoom_in_button = QPushButton("+")
        self.pick_button = QPushButton("Pick Blue Point")
        self.pick_button.setCheckable(True)
        self.create_from_selection_button = QPushButton("Create Adjustment from Selection")
        self.create_from_selection_button.setCheckable(True)
        self.cancel_selection_button = QPushButton("Cancel Selection")
        self.cancel_selection_button.setVisible(False)
        for widget in [
            self.show_preview_button,
            self.show_source_button,
            self.semantic_overlay_selector,
            self.before_after_checkbox,
            self.hold_previous_button,
        ]:
            _allow_horizontal_shrink(widget)
            toolbar_row_view.addWidget(widget)
        toolbar_row_view.addStretch(1)

        for widget in [
            self.fit_button,
            self.actual_button,
            self.zoom_out_button,
            self.zoom_in_button,
        ]:
            _allow_horizontal_shrink(widget)
            toolbar_row_zoom.addWidget(widget)
        toolbar_row_zoom.addStretch(1)

        toolbar_row_primary.addLayout(toolbar_row_view, 1)
        toolbar_row_primary.addLayout(toolbar_row_zoom, 0)

        for widget in [
            self.pick_button,
            self.create_from_selection_button,
            self.cancel_selection_button,
        ]:
            _allow_horizontal_shrink(widget)
            toolbar_row_secondary.addWidget(widget)
        toolbar_row_secondary.addStretch(1)

        self.preview_widget = ImagePreviewWidget(self)
        self.preview_widget.setMinimumSize(0, 480)
        self.rendering_label = QLabel("")
        self.rendering_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rendering_label.setStyleSheet("color: #9fb3c8;")

        toolbar.addLayout(toolbar_row_primary)
        toolbar.addLayout(toolbar_row_secondary)
        layout.addLayout(toolbar)
        layout.addWidget(self.preview_widget, 1)
        layout.addWidget(self.rendering_label)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setMinimumWidth(0)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.panel_heading = QLabel("Adjustments")
        self.panel_heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(self.panel_heading)

        self.editor_stack = QStackedWidget(self)
        self.editor_stack.addWidget(self._build_adjustment_editor())
        self.editor_stack.addWidget(self._build_region_editor())
        layout.addWidget(self.editor_stack, 1)

        self.dark_dust_group = self._build_dark_dust_settings_panel()
        layout.addWidget(self.dark_dust_group)

        note = QLabel(
            "YAML comments are not preserved yet when saving edited metadata."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #7b8794;")
        layout.addWidget(note)
        return panel

    def _build_adjustment_editor(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.adjustment_name_label = QLabel("No adjustment selected.")
        self.adjustment_name_label.setWordWrap(True)
        self.adjustment_enabled_checkbox = QCheckBox("Enabled")
        self.adjustment_type_label = QLabel("")
        self.adjustment_helper_label = QLabel("")
        self.adjustment_helper_label.setWordWrap(True)
        self.adjustment_helper_label.setStyleSheet("color: #7b8794;")

        self.target_label = QLabel("Affects")
        self.target_label.setStyleSheet("font-weight: 600;")
        self.target_selector = QComboBox()

        self.colour_title_label = QLabel("Colour Point")
        self.colour_title_label.setStyleSheet("font-weight: 600;")
        point_layout = QHBoxLayout()
        self.colour_swatch = QLabel()
        self.colour_swatch.setFixedSize(24, 24)
        self.colour_point_label = QLabel("Not selected")
        point_layout.addWidget(self.colour_swatch)
        point_layout.addWidget(self.colour_point_label, 1)

        self.primary_label = QLabel("Amount")
        self.primary_label.setStyleSheet("font-weight: 600;")
        self.primary_slider = QSlider(Qt.Orientation.Horizontal)
        self.primary_input = QDoubleSpinBox()
        self.primary_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.primary_input.setKeyboardTracking(False)
        primary_controls = QWidget(self)
        primary_controls_layout = QHBoxLayout(primary_controls)
        primary_controls_layout.setContentsMargins(0, 0, 0, 0)
        primary_controls_layout.setSpacing(8)
        primary_controls_layout.addWidget(self.primary_slider, 1)
        primary_controls_layout.addWidget(self.primary_input)
        self.primary_controls = primary_controls

        self.level_inputs_container = QWidget(self)
        levels_layout = QVBoxLayout(self.level_inputs_container)
        levels_layout.setContentsMargins(0, 0, 0, 0)
        levels_layout.setSpacing(8)
        self.level_labels: list[QLabel] = []
        self.level_sliders: list[QSlider] = []
        self.level_inputs: list[QDoubleSpinBox] = []
        for level_name in ["Darkest", "Dark", "Mid", "Light", "Brightest"]:
            label = QLabel(level_name)
            label.setStyleSheet("font-weight: 600;")
            slider = QSlider(Qt.Orientation.Horizontal)
            input_widget = QDoubleSpinBox()
            input_widget.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
            input_widget.setKeyboardTracking(False)
            row = QWidget(self.level_inputs_container)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(input_widget)
            levels_layout.addWidget(label)
            levels_layout.addWidget(row)
            self.level_labels.append(label)
            self.level_sliders.append(slider)
            self.level_inputs.append(input_widget)

        self.secondary_label = QLabel("Reach")
        self.secondary_label.setStyleSheet("font-weight: 600;")
        self.secondary_slider = QSlider(Qt.Orientation.Horizontal)
        self.secondary_value_label = QLabel("")

        scope_title = QLabel("Apply in")
        scope_title.setStyleSheet("font-weight: 600;")
        self.apply_everywhere_checkbox = QCheckBox("Apply everywhere")
        self.region_scope_list = QListWidget()

        layout.addWidget(self.adjustment_name_label)
        layout.addWidget(self.adjustment_enabled_checkbox)
        layout.addWidget(self.adjustment_type_label)
        layout.addWidget(self.adjustment_helper_label)
        layout.addWidget(self.target_label)
        layout.addWidget(self.target_selector)
        layout.addWidget(self.colour_title_label)
        layout.addLayout(point_layout)
        layout.addWidget(self.primary_label)
        layout.addWidget(self.primary_controls)
        layout.addWidget(self.level_inputs_container)
        layout.addWidget(self.secondary_label)
        layout.addWidget(self.secondary_slider)
        layout.addWidget(self.secondary_value_label)
        layout.addWidget(scope_title)
        layout.addWidget(self.apply_everywhere_checkbox)
        layout.addWidget(self.region_scope_list, 1)
        return panel

    def _build_dark_dust_settings_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Dark Dust")
        title.setStyleSheet("font-weight: 600;")
        helper = QLabel(
            "Controls the global Dark Dust semantic mask used by the overlay and any "
            "adjustment that targets Dark Dust."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #7b8794;")

        self.dark_dust_enabled_checkbox = QCheckBox("Enabled")
        self.dark_dust_sensitivity_input = QDoubleSpinBox()
        self.dark_dust_structure_size_input = QDoubleSpinBox()
        self.dark_dust_background_protection_input = QDoubleSpinBox()
        self.dark_dust_softness_input = QDoubleSpinBox()

        controls: list[tuple[str, QDoubleSpinBox]] = [
            ("Sensitivity", self.dark_dust_sensitivity_input),
            ("Structure Size", self.dark_dust_structure_size_input),
            ("Background Protection", self.dark_dust_background_protection_input),
            ("Softness", self.dark_dust_softness_input),
        ]
        for label, widget in controls:
            caption = QLabel(label)
            caption.setStyleSheet("font-weight: 600;")
            widget.setDecimals(2)
            widget.setRange(0.0, 1.0)
            widget.setSingleStep(0.01)
            layout.addWidget(caption)
            layout.addWidget(widget)

        layout.addWidget(title)
        layout.addWidget(helper)
        layout.addWidget(self.dark_dust_enabled_checkbox)
        return panel

    def _build_region_editor(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.region_name_edit = QLineEdit()
        self.region_enabled_checkbox = QCheckBox("Enabled")
        self.region_helper_label = QLabel(
            "Softens the boundary so the adjustment blends naturally into the surrounding image."
        )
        self.region_helper_label.setWordWrap(True)
        self.region_helper_label.setStyleSheet("color: #7b8794;")
        self.region_softness_slider = QSlider(Qt.Orientation.Horizontal)
        self.region_softness_value_label = QLabel("")
        self.region_reference_label = QLabel("")
        self.region_reference_label.setWordWrap(True)

        layout.addWidget(QLabel("Region Name"))
        layout.addWidget(self.region_name_edit)
        layout.addWidget(self.region_enabled_checkbox)
        layout.addWidget(QLabel("Edge Softness"))
        layout.addWidget(self.region_softness_slider)
        layout.addWidget(self.region_softness_value_label)
        layout.addWidget(self.region_helper_label)
        layout.addWidget(self.region_reference_label)
        layout.addStretch(1)
        return panel

    def _build_bottom_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setMaximumHeight(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Unsaved Changes")
        title.setStyleSheet("font-weight: 600;")
        self.changes_list = QListWidget()
        self.changes_list.setMaximumHeight(120)
        self.revert_change_button = QPushButton("Remove Selected Change")
        self.what_changed_button = QPushButton("What Changed?")
        self.revert_all_button = QPushButton("Revert All")
        self.save_button = QPushButton("Keep Change")
        actions = QHBoxLayout()
        actions.addWidget(self.revert_change_button)
        actions.addWidget(self.what_changed_button)
        actions.addWidget(self.revert_all_button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)

        layout.addWidget(title)
        layout.addWidget(self.changes_list)
        layout.addLayout(actions)
        return panel

    def _connect_signals(self) -> None:
        self.view_model.projectLoaded.connect(self._on_project_loaded)
        self.view_model.previewChanged.connect(self._refresh_preview)
        self.view_model.sourceChanged.connect(self._refresh_sources)
        self.view_model.adjustmentsChanged.connect(self._refresh_adjustments)
        self.view_model.regionsChanged.connect(self._refresh_regions)
        self.view_model.changesChanged.connect(self._refresh_changes)
        self.view_model.statusChanged.connect(self.status_label.setText)
        self.view_model.errorRaised.connect(self._show_error)
        self.view_model.dirtyChanged.connect(self._on_dirty_changed)
        self.view_model.samplingModeChanged.connect(self._on_sampling_mode_changed)
        self.view_model.busyChanged.connect(self._on_busy_changed)
        self.view_model.selectionChanged.connect(self._on_selection_changed)
        self.view_model.drawingModeChanged.connect(self._on_drawing_mode_changed)
        self.view_model.regionVisibilityChanged.connect(self._on_region_visibility_changed)

        self.show_preview_button.clicked.connect(self._show_preview)
        self.show_source_button.clicked.connect(self._show_source)
        self.semantic_overlay_selector.currentIndexChanged.connect(self._on_semantic_overlay_changed)
        self.before_after_checkbox.toggled.connect(self.view_model.set_compare_saved)
        self.hold_previous_button.pressed.connect(lambda: self.view_model.set_compare_saved(True))
        self.hold_previous_button.released.connect(
            lambda: self.view_model.set_compare_saved(self.before_after_checkbox.isChecked())
        )
        self.fit_button.clicked.connect(self.preview_widget.fit_to_view)
        self.actual_button.clicked.connect(self.preview_widget.actual_size)
        self.zoom_in_button.clicked.connect(self.preview_widget.zoom_in)
        self.zoom_out_button.clicked.connect(self.preview_widget.zoom_out)
        self.pick_button.clicked.connect(self._toggle_pick_mode)
        self.create_from_selection_button.clicked.connect(self._toggle_create_from_selection_mode)
        self.cancel_selection_button.clicked.connect(self.view_model.cancel_sampling)

        self.preview_widget.sampleClicked.connect(self._apply_sample)
        self.preview_widget.samplingCancelled.connect(self.view_model.cancel_sampling)
        self.preview_widget.regionPointAdded.connect(self.view_model.add_region_point)
        self.preview_widget.regionDrawingFinished.connect(self.view_model.finish_region_drawing)
        self.preview_widget.regionDrawingCancelled.connect(self.view_model.cancel_region_drawing)
        self.preview_widget.regionSelected.connect(self.view_model.select_region)
        self.preview_widget.regionVertexMoved.connect(self.view_model.move_region_vertex)
        self.preview_widget.regionEdgeInserted.connect(self.view_model.insert_region_vertex)
        self.preview_widget.regionVertexDeleted.connect(self.view_model.delete_region_vertex)
        self.preview_widget.regionMoved.connect(self.view_model.move_region)

        self.adjustments_list.currentItemChanged.connect(self._on_adjustment_item_changed)
        self.regions_list.currentItemChanged.connect(self._on_region_item_changed)
        self.changes_list.currentItemChanged.connect(self._on_change_item_changed)

        self.add_adjustment_button.clicked.connect(self._show_add_adjustment_menu)
        self.move_earlier_button.clicked.connect(
            lambda: self.view_model.move_selected_adjustment("earlier")
        )
        self.move_later_button.clicked.connect(
            lambda: self.view_model.move_selected_adjustment("later")
        )
        self.duplicate_adjustment_button.clicked.connect(self.view_model.duplicate_selected_adjustment)
        self.remove_adjustment_button.clicked.connect(self._remove_selected_adjustment)
        self.reset_adjustment_button.clicked.connect(self.view_model.reset_selected_adjustment)

        self.add_region_button.clicked.connect(self.view_model.begin_region_drawing)
        self.cancel_region_button.clicked.connect(self.view_model.cancel_region_drawing)
        self.remove_region_button.clicked.connect(self._remove_selected_region)
        self.show_regions_checkbox.toggled.connect(self.view_model.set_show_regions)

        self.adjustment_enabled_checkbox.toggled.connect(self.view_model.set_selected_adjustment_enabled)
        self.target_selector.currentIndexChanged.connect(self._on_target_changed)
        self.primary_slider.sliderPressed.connect(self._on_adjustment_slider_pressed)
        self.primary_slider.sliderReleased.connect(self._on_adjustment_slider_released)
        self.primary_slider.valueChanged.connect(self._on_primary_slider_value_changed)
        self.primary_input.valueChanged.connect(self._on_primary_value_changed)
        self.primary_input.editingFinished.connect(self._schedule_adjustment_render)
        for index, (slider, input_widget) in enumerate(
            zip(self.level_sliders, self.level_inputs, strict=False)
        ):
            slider.sliderPressed.connect(self._on_adjustment_slider_pressed)
            slider.sliderReleased.connect(self._on_adjustment_slider_released)
            slider.valueChanged.connect(
                lambda value, level_index=index: self._on_level_slider_value_changed(
                    level_index,
                    value,
                )
            )
            input_widget.valueChanged.connect(
                lambda value, level_index=index: self._on_level_value_changed(level_index, value)
            )
            input_widget.editingFinished.connect(self._schedule_adjustment_render)
        self.secondary_slider.sliderPressed.connect(self._on_adjustment_slider_pressed)
        self.secondary_slider.sliderReleased.connect(self._on_adjustment_slider_released)
        self.secondary_slider.valueChanged.connect(self._on_secondary_value_changed)
        self.apply_everywhere_checkbox.toggled.connect(self.view_model.set_selected_adjustment_apply_everywhere)
        self.region_scope_list.itemChanged.connect(self._on_region_scope_item_changed)

        self.region_name_edit.editingFinished.connect(self._on_region_name_changed)
        self.region_enabled_checkbox.toggled.connect(self.view_model.set_selected_region_enabled)
        self.region_softness_slider.valueChanged.connect(
            lambda value: self.view_model.set_selected_region_softness(value / 100.0)
        )

        self.dark_dust_enabled_checkbox.toggled.connect(self.view_model.set_dark_dust_enabled)
        self.dark_dust_sensitivity_input.valueChanged.connect(
            self.view_model.set_dark_dust_sensitivity
        )
        self.dark_dust_structure_size_input.valueChanged.connect(
            self.view_model.set_dark_dust_structure_size
        )
        self.dark_dust_background_protection_input.valueChanged.connect(
            self.view_model.set_dark_dust_background_protection
        )
        self.dark_dust_softness_input.valueChanged.connect(self.view_model.set_dark_dust_softness)

        self.revert_change_button.clicked.connect(self._revert_selected_change)
        self.what_changed_button.clicked.connect(self._show_semantic_changes)
        self.revert_all_button.clicked.connect(self.view_model.revert_unsaved_changes)
        self.save_button.clicked.connect(self.view_model.save_changes)

    def _open_project_dialog(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Open Nebula Master Project",
            "",
            "Nebula Project (project.yaml);;YAML Files (*.yaml *.yml)",
        )
        if selected:
            self.view_model.open_project(Path(selected), async_preview=True)

    def _new_project_from_image_dialog(self) -> None:
        source_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose Source Image",
            "",
            "Images (*.tif *.tiff *.png *.jpg *.jpeg)",
        )
        if not source_path:
            return

        destination_parent = QFileDialog.getExistingDirectory(
            self,
            "Choose Parent Folder",
            "",
        )
        if not destination_parent:
            return

        default_name = Path(source_path).stem
        project_name, accepted = QInputDialog.getText(
            self,
            "Project Name",
            "New project folder name:",
            text=default_name,
        )
        if not accepted:
            return

        try:
            project_file = scaffold_project_from_image(
                source_path=Path(source_path),
                destination_parent=Path(destination_parent),
                project_name=project_name,
            )
        except ProjectScaffoldError as exc:
            QMessageBox.critical(
                self,
                "Project creation failed",
                str(exc),
            )
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Project creation failed",
                f"An unexpected error occurred while creating the project.\n\n{exc}",
            )
            return

        self.view_model.open_project(project_file, async_preview=True)

    def _ensure_project_open(self) -> bool:
        if self.view_model.project_path is not None:
            return True
        QMessageBox.information(self, "No project open", "Open a project before exporting.")
        return False

    def _export_for_screen(self) -> None:
        if not self._ensure_project_open():
            return
        native_dimensions = self.view_model.native_render_dimensions()
        if native_dimensions is None:
            QMessageBox.critical(
                self,
                "Export failed",
                "The source image dimensions could not be resolved for this project.",
            )
            return
        dialog = ScreenExportDialog(
            native_width=native_dimensions[0],
            native_height=native_dimensions[1],
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.selected_options()
        destination = self._choose_export_destination(
            title="Export for Screen",
            default_stem="screen-render",
            suffix=options.suffix,
        )
        if destination is None:
            return
        profile = self.view_model.build_screen_export_profile(
            output_format=options.output_format,
            width_px=options.width_px,
            interpolation=options.interpolation,
        )
        self._run_export(
            output_path=destination,
            profile_id="screen-export",
            profile=profile,
            success_title="Screen export complete",
        )

    def _export_for_print(self) -> None:
        if not self._ensure_project_open():
            return
        default_dimensions = self.view_model.default_print_dimensions(units="cm", ppi=300)
        if default_dimensions is None:
            QMessageBox.critical(
                self,
                "Export failed",
                "The print dimensions could not be derived for this project.",
            )
            return
        dialog = PrintExportDialog(
            default_width=default_dimensions[0],
            default_height=default_dimensions[1],
            default_units="cm",
            default_ppi=300,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.selected_options()
        destination = self._choose_export_destination(
            title="Export for Print",
            default_stem="print-render",
            suffix=options.suffix,
        )
        if destination is None:
            return
        profile = self.view_model.build_print_export_profile(
            output_format=options.output_format,
            width=options.width,
            height=options.height,
            units=options.units,
            ppi=options.ppi,
            interpolation=options.interpolation,
        )
        self._run_export(
            output_path=destination,
            profile_id="print-export",
            profile=profile,
            success_title="Print export complete",
        )

    def _choose_export_destination(
        self,
        *,
        title: str,
        default_stem: str,
        suffix: str,
    ) -> Path | None:
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            title,
            str((self.view_model.project_path or Path.cwd()) / f"{default_stem}{suffix}"),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not selected:
            return None
        output_path = Path(selected)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(suffix)
        if output_path.exists():
            overwrite = QMessageBox.question(
                self,
                "Overwrite existing file?",
                f"{output_path.name} already exists. Replace it?",
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return None
        return output_path

    def _run_export(
        self,
        *,
        output_path: Path,
        profile_id: str,
        profile: ScreenRenderProfile | PrintRenderProfile,
        success_title: str,
    ) -> None:
        self.status_label.setText("Exporting render...")
        try:
            result = self.view_model.export_render(
                output_path=output_path,
                profile_id=profile_id,
                profile=profile,
                force=True,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export failed",
                f"The final render could not be exported.\n\n{exc}",
            )
            self.status_label.setText("Export failed.")
            return

        self.status_label.setText(f"Render exported: {result.output_path}")
        QMessageBox.information(
            self,
            success_title,
            (
                f"Render written to:\n{result.output_path}\n\n"
                f"Output size: {result.output_dimensions.width} x "
                f"{result.output_dimensions.height}\n"
                f"{result.guidance}"
            ),
        )

    def _show_add_adjustment_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(
            "Add Black Point adjustment",
            lambda: self.view_model.create_adjustment("black"),
        )
        menu.addAction(
            "Add Shadows adjustment",
            lambda: self.view_model.create_adjustment("shadows"),
        )
        menu.addAction("Add Blue adjustment", lambda: self.view_model.create_adjustment("blue"))
        menu.addAction("Add Red adjustment", lambda: self.view_model.create_adjustment("red"))
        menu.addAction("Add Green adjustment", lambda: self.view_model.create_adjustment("green"))
        menu.addAction("Add Cyan adjustment", lambda: self.view_model.create_adjustment("cyan"))
        menu.addAction(
            "Add Yellow adjustment",
            lambda: self.view_model.create_adjustment("yellow"),
        )
        menu.addAction(
            "Add Brightness adjustment",
            lambda: self.view_model.create_adjustment("brightness"),
        )
        menu.addAction(
            "Add Levels adjustment",
            lambda: self.view_model.create_adjustment("levels"),
        )
        menu.addAction(
            "Add Saturation adjustment",
            lambda: self.view_model.create_adjustment("saturation"),
        )
        menu.addAction(
            "Add Colour Smoothness adjustment",
            lambda: self.view_model.create_adjustment("smoothness"),
        )
        menu.exec(self.add_adjustment_button.mapToGlobal(self.add_adjustment_button.rect().bottomLeft()))

    def _on_project_loaded(self, project_name: str) -> None:
        self.project_name_label.setText(project_name)
        self.project_path_label.setText(str(self.view_model.project_path or ""))
        self.show_preview_button.setChecked(True)
        self.show_source_button.setChecked(False)
        with QSignalBlocker(self.semantic_overlay_selector):
            self.semantic_overlay_selector.setCurrentIndex(0)
        self._refresh_dark_dust_settings()

    def _refresh_sources(self) -> None:
        self.sources_list.clear()
        documents = self.view_model._working_documents
        if documents is None:
            return
        for source in documents.bundle.project.sources:
            marker = "Reference" if source.reference else source.role.capitalize()
            self.sources_list.addItem(f"{source.name or source.id} • {marker}")

    def _refresh_preview(self) -> None:
        self.preview_widget.set_image(self.view_model.current_display_image())
        overlay_mode = self.semantic_overlay_selector.currentData()
        overlay = (
            None
            if overlay_mode == "off"
            else self.view_model.current_semantic_overlay()
        )
        self.preview_widget.set_semantic_overlay(overlay)
        self.preview_widget.set_regions(
            self.view_model.overlay_regions(),
            selected_region_id=self.view_model.selected_region_id,
            drawing_points=self.view_model.drawing_points(),
            show_regions=self.view_model.show_regions,
        )

    def _refresh_adjustments(self) -> None:
        summaries = self.view_model.adjustment_summaries()
        blocker = QSignalBlocker(self.adjustments_list)
        _ = blocker
        self.adjustments_list.clear()
        selected_row = -1
        for index, summary in enumerate(summaries):
            prefix = "✓" if summary.enabled else "○"
            item = QListWidgetItem(self._adjustment_list_label(prefix, summary))
            item.setData(Qt.ItemDataRole.UserRole, summary.rule_id)
            if not summary.editable:
                item.setForeground(QColor("#94a3b8"))
            self.adjustments_list.addItem(item)
            if summary.rule_id == self.view_model.selected_adjustment_id:
                selected_row = index
        if selected_row >= 0:
            self.adjustments_list.setCurrentRow(selected_row)
        self._apply_adjustment_summary(self.view_model.selected_adjustment_summary())
        self._refresh_dark_dust_settings()

    def _adjustment_list_label(self, prefix: str, summary: AdjustmentSummary) -> str:
        parts = [f"{prefix} {summary.name}", summary.target_label]
        if summary.scope_label != "Entire image":
            parts.append(summary.scope_label)
        return " • ".join(parts)

    def _refresh_regions(self) -> None:
        summaries = self.view_model.region_summaries()
        blocker = QSignalBlocker(self.regions_list)
        _ = blocker
        self.regions_list.clear()
        selected_row = -1
        for index, summary in enumerate(summaries):
            prefix = "✓" if summary.enabled else "○"
            item = QListWidgetItem(
                f"{prefix} {summary.name} • {summary.adjustment_count} adjustments"
            )
            item.setData(Qt.ItemDataRole.UserRole, summary.region_id)
            self.regions_list.addItem(item)
            if summary.region_id == self.view_model.selected_region_id:
                selected_row = index
        if selected_row >= 0:
            self.regions_list.setCurrentRow(selected_row)
        self._apply_region_summary(self.view_model.selected_region_summary())
        self._refresh_dark_dust_settings()
        self._refresh_preview()

    def _refresh_dark_dust_settings(self) -> None:
        settings = self.view_model.dark_dust_settings()
        with QSignalBlocker(self.dark_dust_enabled_checkbox):
            self.dark_dust_enabled_checkbox.setChecked(settings.enabled)
        for widget, value in [
            (self.dark_dust_sensitivity_input, settings.sensitivity),
            (self.dark_dust_structure_size_input, settings.structure_size),
            (self.dark_dust_background_protection_input, settings.background_protection),
            (self.dark_dust_softness_input, settings.softness),
        ]:
            with QSignalBlocker(widget):
                widget.setValue(value)

    def _refresh_changes(self) -> None:
        changes = self.view_model.unsaved_changes()
        blocker = QSignalBlocker(self.changes_list)
        _ = blocker
        self.changes_list.clear()
        for change in changes:
            item = QListWidgetItem(change.summary)
            item.setData(Qt.ItemDataRole.UserRole, change.key)
            self.changes_list.addItem(item)
        if changes:
            self.changes_list.setCurrentRow(0)

    def _apply_adjustment_summary(self, summary: AdjustmentSummary | None) -> None:
        if summary is None:
            self.adjustment_name_label.setText("No adjustment selected.")
            self.adjustment_type_label.setText("")
            self.adjustment_helper_label.setText("")
            self.colour_title_label.setText("Colour Point")
            self.colour_point_label.setText("Not selected")
            self.colour_swatch.clear()
            self.pick_button.setText("Pick Colour Point")
            self.colour_title_label.setVisible(False)
            self.colour_swatch.setVisible(False)
            self.colour_point_label.setVisible(False)
            self.pick_button.setEnabled(False)
            self.primary_label.setVisible(False)
            self.primary_controls.setVisible(False)
            self.level_inputs_container.setVisible(False)
            return

        self.adjustment_name_label.setText(summary.name)
        self.adjustment_type_label.setText(summary.type_label)
        self.adjustment_helper_label.setText(summary.helper_text)
        with QSignalBlocker(self.adjustment_enabled_checkbox):
            self.adjustment_enabled_checkbox.setChecked(summary.enabled)
        self.adjustment_enabled_checkbox.setEnabled(True)
        self.target_label.setVisible(True)
        self.target_selector.setVisible(True)
        with QSignalBlocker(self.target_selector):
            self.target_selector.clear()
            for target_id, label in [
                ("combined", "Combined Image"),
                ("nebula", "Nebula"),
                ("stars", "Stars"),
                ("dark_dust", "Dark Dust"),
            ]:
                self.target_selector.addItem(label, target_id)
            current_index = self.target_selector.findData(summary.target_id)
            self.target_selector.setCurrentIndex(max(0, current_index))

        has_colour_controls = summary.supports_colour_point and summary.point_label is not None
        self.colour_title_label.setVisible(has_colour_controls)
        self.colour_swatch.setVisible(has_colour_controls)
        self.colour_point_label.setVisible(has_colour_controls)
        if has_colour_controls:
            self.colour_title_label.setText(summary.point_label or "Colour Point")

        if has_colour_controls and summary.swatch_rgb is not None:
            self.colour_swatch.setPixmap(_swatch_pixmap(summary.swatch_rgb))
            self.colour_point_label.setText(summary.colour_point_name or "Selected colour point")
        else:
            self.colour_swatch.clear()
            self.colour_point_label.setText("Not selected")
        point_label = summary.point_label or "Colour Point"
        self.pick_button.setText(f"Pick {point_label}")
        self.pick_button.setEnabled(has_colour_controls and summary.editable)

        has_levels_controls = bool(summary.level_values)
        self.level_inputs_container.setVisible(has_levels_controls)
        self.primary_label.setVisible(not has_levels_controls and summary.primary_label is not None)
        self.primary_controls.setVisible(
            not has_levels_controls and summary.primary_value is not None
        )
        if (
            not has_levels_controls
            and summary.primary_label is not None
            and summary.primary_value is not None
        ):
            self.primary_label.setText(summary.primary_label)
            if summary.transform_type == "colour_amount":
                spin_value = max(
                    _MULTIPLIER_UI_MIN,
                    min(_MULTIPLIER_UI_MAX, (summary.primary_value - 1.0) * 100.0),
                )
                spin_range = (_MULTIPLIER_UI_MIN, _MULTIPLIER_UI_MAX)
                spin_step = 1.0
                spin_decimals = 0
                spin_suffix = "%"
            elif summary.transform_type == "shift_colour_point":
                spin_value = max(
                    _SHIFT_UI_MIN,
                    min(_SHIFT_UI_MAX, summary.primary_value * 100.0),
                )
                spin_range = (_SHIFT_UI_MIN, _SHIFT_UI_MAX)
                spin_step = 1.0
                spin_decimals = 0
                spin_suffix = "%"
            elif summary.type_label == "Smoothing":
                spin_value = max(
                    _SMOOTHING_UI_MIN,
                    min(_SMOOTHING_UI_MAX, summary.primary_value * 100.0),
                )
                spin_range = (_SMOOTHING_UI_MIN, _SMOOTHING_UI_MAX)
                spin_step = 1.0
                spin_decimals = 0
                spin_suffix = "%"
            elif summary.transform_type == "brightness":
                spin_value = _brightness_amount_to_ui(summary.primary_value)
                spin_range = (_MULTIPLIER_UI_MIN, _MULTIPLIER_UI_MAX)
                spin_step = 1.0
                spin_decimals = 0
                spin_suffix = "%"
            else:
                spin_value = max(
                    _MULTIPLIER_UI_MIN,
                    min(_MULTIPLIER_UI_MAX, (summary.primary_value - 1.0) * 100.0),
                )
                spin_range = (_MULTIPLIER_UI_MIN, _MULTIPLIER_UI_MAX)
                spin_step = 1.0
                spin_decimals = 0
                spin_suffix = "%"
            slider_min, slider_max = _primary_slider_bounds(
                summary.transform_type,
                summary.type_label,
            )
            with QSignalBlocker(self.primary_slider):
                self.primary_slider.setRange(slider_min, slider_max)
                self.primary_slider.setValue(int(round(spin_value)))
            with QSignalBlocker(self.primary_input):
                self.primary_input.setDecimals(spin_decimals)
                self.primary_input.setRange(*spin_range)
                self.primary_input.setSingleStep(spin_step)
                self.primary_input.setSuffix(spin_suffix)
                self.primary_input.setValue(spin_value)
        if has_levels_controls:
            for label_widget, slider_widget, input_widget, level_label, level_value in zip(
                self.level_labels,
                self.level_sliders,
                self.level_inputs,
                summary.level_labels,
                summary.level_values,
                strict=False,
            ):
                label_widget.setText(level_label)
                ui_value = _brightness_amount_to_ui(level_value)
                with QSignalBlocker(slider_widget):
                    slider_widget.setRange(int(_MULTIPLIER_UI_MIN), int(_MULTIPLIER_UI_MAX))
                    slider_widget.setValue(int(round(ui_value)))
                with QSignalBlocker(input_widget):
                    input_widget.setDecimals(0)
                    input_widget.setRange(_MULTIPLIER_UI_MIN, _MULTIPLIER_UI_MAX)
                    input_widget.setSingleStep(1.0)
                    input_widget.setSuffix("%")
                    input_widget.setValue(ui_value)

        self.secondary_label.setVisible(summary.secondary_label is not None)
        self.secondary_slider.setVisible(summary.secondary_value is not None)
        self.secondary_value_label.setVisible(summary.secondary_value is not None)
        if summary.secondary_label is not None and summary.secondary_value is not None:
            self.secondary_label.setText(summary.secondary_label)
            self.secondary_slider.setRange(0, 100)
            with QSignalBlocker(self.secondary_slider):
                self.secondary_slider.setValue(int(round(summary.secondary_value * 100)))
            self.secondary_value_label.setText(f"{summary.secondary_value:.2f}")

        with QSignalBlocker(self.apply_everywhere_checkbox):
            self.apply_everywhere_checkbox.setChecked(not summary.region_ids)
        self.apply_everywhere_checkbox.setEnabled(summary.editable)
        self._refresh_region_scope_list(summary)

        self.duplicate_adjustment_button.setEnabled(summary.editable)
        self.remove_adjustment_button.setEnabled(summary.editable)
        self.reset_adjustment_button.setEnabled(True)
        self.move_earlier_button.setEnabled(True)
        self.move_later_button.setEnabled(True)

    def _refresh_region_scope_list(self, summary: AdjustmentSummary) -> None:
        blocker = QSignalBlocker(self.region_scope_list)
        _ = blocker
        self.region_scope_list.clear()
        for region in self.view_model.region_summaries():
            item = QListWidgetItem(region.name)
            item.setData(Qt.ItemDataRole.UserRole, region.region_id)
            state = (
                Qt.CheckState.Checked
                if region.region_id in summary.region_ids
                else Qt.CheckState.Unchecked
            )
            item.setCheckState(state)
            self.region_scope_list.addItem(item)
        self.region_scope_list.setEnabled(
            summary.editable and not self.apply_everywhere_checkbox.isChecked()
        )

    def _apply_region_summary(self, summary: RegionSummary | None) -> None:
        if summary is None:
            self.region_name_edit.setText("")
            self.region_reference_label.setText("No region selected.")
            return
        with QSignalBlocker(self.region_name_edit):
            self.region_name_edit.setText(summary.name)
        with QSignalBlocker(self.region_enabled_checkbox):
            self.region_enabled_checkbox.setChecked(summary.enabled)
        with QSignalBlocker(self.region_softness_slider):
            self.region_softness_slider.setRange(0, 100)
            self.region_softness_slider.setValue(int(round(summary.softness * 100)))
        self.region_softness_value_label.setText(f"{round(summary.softness * 100)}%")
        if summary.adjustment_count == 0:
            self.region_reference_label.setText("This region is not used by any adjustment yet.")
        elif summary.adjustment_count == 1:
            self.region_reference_label.setText("This region is used by 1 adjustment.")
        else:
            self.region_reference_label.setText(
                f"This region is used by {summary.adjustment_count} adjustments."
            )

    def _show_preview(self) -> None:
        self.show_preview_button.setChecked(True)
        self.show_source_button.setChecked(False)
        self.view_model.set_show_source(False)

    def _show_source(self) -> None:
        self.show_preview_button.setChecked(False)
        self.show_source_button.setChecked(True)
        self.before_after_checkbox.setChecked(False)
        self.view_model.set_show_source(True)

    def _on_semantic_overlay_changed(self, index: int) -> None:
        if index < 0:
            return
        mode = self.semantic_overlay_selector.itemData(index)
        if isinstance(mode, str):
            if mode == "off":
                # Clear any visible diagnostic immediately before the next preview refresh.
                self.preview_widget.set_semantic_overlay(None)
            self.view_model.set_semantic_overlay_mode(cast(SemanticOverlaySelection, mode))

    def _toggle_pick_mode(self, enabled: bool) -> None:
        if enabled:
            self.view_model.begin_sampling()
        else:
            self.view_model.cancel_sampling()

    def _toggle_create_from_selection_mode(self, enabled: bool) -> None:
        if enabled:
            self.view_model.begin_adjustment_creation_sampling()
        else:
            self.view_model.cancel_sampling()

    def _apply_sample(self, sample: ImageSample) -> None:
        if self.view_model.sampling_purpose == "create_adjustment":
            self.view_model.finish_sampling()
            self.preview_widget.set_sample_marker(SampleMarker(sample.x, sample.y, sample.rgb))
            try:
                kind = self._choose_adjustment_kind_from_sample(sample)
                if kind is None:
                    self.status_label.setText("Adjustment creation cancelled.")
                    return
                self.view_model.create_adjustment_from_selection(kind, sample)
            finally:
                self.preview_widget.set_sample_marker(None)
            return
        self.view_model.apply_image_sample(sample)

    def _choose_adjustment_kind_from_sample(
        self,
        sample: ImageSample,
    ) -> AdjustmentKind | None:
        menu = QMenu(self)
        title_action = menu.addAction(
            "Create adjustment from sampled colour"
        )
        title_action.setEnabled(False)
        menu.addSeparator()
        actions: dict[object, AdjustmentKind] = {}
        options: tuple[tuple[str, AdjustmentKind], ...] = (
            ("Blue", "blue"),
            ("Red", "red"),
            ("Green", "green"),
            ("Cyan", "cyan"),
            ("Yellow", "yellow"),
            ("Brightness", "brightness"),
            ("Saturation", "saturation"),
            ("Smoothing", "smoothness"),
        )
        for label, kind in options:
            action = menu.addAction(label)
            action.setIcon(QIcon(_swatch_pixmap(sample.rgb)))
            actions[action] = kind
        selected = menu.exec(self.cursor().pos())
        if selected is None:
            return None
        return actions.get(selected)

    def _on_adjustment_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        _ = previous
        if current is None:
            return
        rule_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(rule_id, str):
            self.view_model.select_adjustment(rule_id)

    def _on_region_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        _ = previous
        if current is None:
            return
        region_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(region_id, str):
            self.view_model.select_region(region_id)

    def _on_change_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        _ = previous
        if current is None:
            return
        change_key = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(change_key, str):
            self.view_model.select_change_target(change_key)

    def _on_primary_value_changed(self, value: float) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None or summary.primary_value is None:
            return
        with QSignalBlocker(self.primary_slider):
            self.primary_slider.setValue(int(round(value)))
        self._apply_primary_value(value, render=False)
        self._schedule_adjustment_render()

    def _on_primary_slider_value_changed(self, value: int) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None or summary.primary_value is None:
            return
        with QSignalBlocker(self.primary_input):
            self.primary_input.setValue(float(value))
        self._apply_primary_value(
            float(value),
            render=not self.view_model.is_adjustment_interacting,
        )

    def _on_level_value_changed(self, index: int, value: float) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None or not summary.level_values:
            return
        with QSignalBlocker(self.level_sliders[index]):
            self.level_sliders[index].setValue(int(round(value)))
        self.view_model.set_selected_adjustment_level_value(
            index,
            _brightness_ui_to_amount(value),
            render=False,
        )
        self._schedule_adjustment_render()

    def _on_level_slider_value_changed(self, index: int, value: int) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None or not summary.level_values:
            return
        with QSignalBlocker(self.level_inputs[index]):
            self.level_inputs[index].setValue(float(value))
        self.view_model.set_selected_adjustment_level_value(
            index,
            _brightness_ui_to_amount(float(value)),
            render=not self.view_model.is_adjustment_interacting,
        )

    def _on_target_changed(self, index: int) -> None:
        if index < 0:
            return
        target_id = self.target_selector.itemData(index)
        if isinstance(target_id, str):
            self.view_model.set_selected_adjustment_target(target_id)

    def _on_secondary_value_changed(self, value: int) -> None:
        render = not self.view_model.is_adjustment_interacting
        self.view_model.set_selected_adjustment_secondary_value(value / 100.0, render=render)
        if render:
            self._schedule_adjustment_render()

    def _on_adjustment_slider_pressed(self) -> None:
        self._adjustment_render_timer.stop()
        self.view_model.set_adjustment_interaction_active(True)

    def _on_adjustment_slider_released(self) -> None:
        self.view_model.set_adjustment_interaction_active(False)
        self.view_model.request_preview_render(immediate=False)

    def _apply_primary_value(self, value: float, *, render: bool) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None or summary.primary_value is None:
            return
        if summary.transform_type == "colour_amount":
            normalized = 1.0 + (value / 100.0)
        elif summary.transform_type == "shift_colour_point":
            normalized = value / 100.0
        elif summary.type_label == "Smoothing":
            normalized = value / 100.0
        elif summary.transform_type == "brightness":
            normalized = _brightness_ui_to_amount(value)
        else:
            normalized = 1.0 + (value / 100.0)
        self.view_model.set_selected_adjustment_primary_value(normalized, render=render)

    def _schedule_adjustment_render(self) -> None:
        if self.view_model.is_adjustment_interacting:
            return
        self._adjustment_render_timer.start()

    def _request_deferred_adjustment_render(self) -> None:
        if self.view_model.is_adjustment_interacting:
            return
        self.view_model.request_preview_render(immediate=False)

    def _on_region_scope_item_changed(self, item: QListWidgetItem) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None:
            return
        region_ids: list[str] = []
        for index in range(self.region_scope_list.count()):
            current_item = self.region_scope_list.item(index)
            if current_item.checkState() == Qt.CheckState.Checked:
                region_id = current_item.data(Qt.ItemDataRole.UserRole)
                if isinstance(region_id, str):
                    region_ids.append(region_id)
        if self.apply_everywhere_checkbox.isChecked():
            return
        if not region_ids and item.checkState() == Qt.CheckState.Unchecked:
            item.setCheckState(Qt.CheckState.Checked)
            return
        self.view_model.set_selected_adjustment_regions(region_ids)

    def _on_region_name_changed(self) -> None:
        self.view_model.set_selected_region_name(self.region_name_edit.text())

    def _remove_selected_adjustment(self) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove adjustment",
            f"Remove {summary.name} from the saved adjustments?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.view_model.remove_selected_adjustment()

    def _remove_selected_region(self) -> None:
        summary = self.view_model.selected_region_summary()
        if summary is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete region",
            f"Delete {summary.name}? Any linked adjustments will stop using this region.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.view_model.remove_selected_region()

    def _revert_selected_change(self) -> None:
        current = self.changes_list.currentItem()
        if current is None:
            return
        change_key = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(change_key, str):
            self.view_model.revert_change(change_key)

    def _show_semantic_changes(self) -> None:
        lines = self.view_model.semantic_change_lines()
        if not lines:
            QMessageBox.information(self, "What changed?", "No unsaved semantic changes.")
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("What changed?")
        dialog.setText("Unsaved changes:")
        dialog.setDetailedText("\n".join(lines))
        dialog.setInformativeText("\n".join(f"• {line}" for line in lines[:6]))
        dialog.exec()

    def _show_error(self, summary: str, details: str) -> None:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Nebula Master")
        dialog.setText(summary)
        if details:
            dialog.setDetailedText(details)
        dialog.exec()

    def _on_dirty_changed(self, dirty: bool) -> None:
        self.dirty_label.setText("Unsaved changes" if dirty else "Clean")
        self.setWindowTitle(f"Nebula Master Desktop{' *' if dirty else ''}")

    def _on_sampling_mode_changed(self, enabled: bool) -> None:
        with QSignalBlocker(self.pick_button):
            self.pick_button.setChecked(
                enabled and self.view_model.sampling_purpose == "colour_point"
            )
        with QSignalBlocker(self.create_from_selection_button):
            self.create_from_selection_button.setChecked(
                enabled and self.view_model.sampling_purpose == "create_adjustment"
            )
        self.cancel_selection_button.setVisible(enabled)
        self.cancel_selection_button.setEnabled(enabled)
        if not enabled:
            self.preview_widget.set_sample_marker(None)
        self.preview_widget.set_interaction_mode("sampling" if enabled else "navigate")

    def _on_busy_changed(self, busy: bool) -> None:
        self.rendering_label.setText("Rendering preview..." if busy else "")

    def _on_selection_changed(self, selection_kind: str) -> None:
        if selection_kind == "region":
            self.editor_stack.setCurrentIndex(1)
            self.panel_heading.setText("Regions")
            mode: InteractionMode = (
                "draw_region" if self.view_model.is_drawing_region else "edit_region"
            )
            self.preview_widget.set_interaction_mode(mode)
        else:
            self.editor_stack.setCurrentIndex(0)
            self.panel_heading.setText("Adjustments")
            if not self.view_model.is_sampling:
                self.preview_widget.set_interaction_mode("navigate")

    def _on_drawing_mode_changed(self, drawing: bool) -> None:
        self.cancel_region_button.setEnabled(drawing)
        self.preview_widget.set_interaction_mode("draw_region" if drawing else "edit_region")

    def _on_region_visibility_changed(self, visible: bool) -> None:
        with QSignalBlocker(self.show_regions_checkbox):
            self.show_regions_checkbox.setChecked(visible)

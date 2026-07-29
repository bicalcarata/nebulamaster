from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from project_model import PrintRenderProfile, ScreenRenderProfile
from PySide6.QtCore import QSettings, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
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
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nebula_desktop import __version__
from nebula_desktop.application.assets import asset_path
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
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


def _allow_panel_horizontal_shrink(widget: QWidget) -> None:
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)


def _allow_toolbar_control(widget: QWidget) -> None:
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)


def _build_muted_wrapped_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    label.setStyleSheet("color: #7b8794;")
    return label


_MULTIPLIER_UI_MIN = -100.0
_MULTIPLIER_UI_MAX = 100.0
_SHIFT_UI_MIN = -100.0
_SHIFT_UI_MAX = 100.0
_SMOOTHING_UI_MIN = 0.0
_SMOOTHING_UI_MAX = 100.0
_PALETTE_UI_MIN = 0.0
_PALETTE_UI_MAX = 100.0
_HELP_SHOW_ON_STARTUP_KEY = "ui/show_help_on_startup"
_LEFT_PANEL_MIN_WIDTH = 220
_CENTER_PANEL_MIN_WIDTH = 560
_RIGHT_PANEL_MIN_WIDTH = 320


def _tinted_standard_icon(
    style: QStyle,
    standard_pixmap: QStyle.StandardPixmap,
    *,
    color: QColor,
    size: int = 16,
) -> QIcon:
    base = style.standardIcon(standard_pixmap).pixmap(size, size)
    tinted = QPixmap(base.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return QIcon(tinted)


def _brightness_amount_to_ui(amount: float) -> float:
    return max(_MULTIPLIER_UI_MIN, min(_MULTIPLIER_UI_MAX, (amount - 1.0) * 100.0))


def _brightness_ui_to_amount(value: float) -> float:
    return max(0.0, 1.0 + (value / 100.0))


def _primary_slider_bounds(transform_type: str, type_label: str) -> tuple[int, int]:
    if transform_type == "shift_colour_point":
        return int(_SHIFT_UI_MIN), int(_SHIFT_UI_MAX)
    if transform_type == "faux_palette":
        return int(_PALETTE_UI_MIN), int(_PALETTE_UI_MAX)
    if type_label == "Smoothing":
        return int(_SMOOTHING_UI_MIN), int(_SMOOTHING_UI_MAX)
    return int(_MULTIPLIER_UI_MIN), int(_MULTIPLIER_UI_MAX)


def _load_help_document_html() -> str:
    document_path = asset_path("desktop-help.html")
    if document_path.is_file():
        return document_path.read_text(encoding="utf-8")
    return (
        "<h1>Nebula Master Help</h1>"
        "<p>The help document could not be loaded from the application bundle.</p>"
    )


def _build_about_html() -> str:
    return (
        "<h1>Nebula Master</h1>"
        f"<p><strong>Version:</strong> {__version__}</p>"
        "<p>Beginner-friendly image mastering for nebula and dark-nebula images "
        "produced by smart telescopes.</p>"
        "<p><strong>Repository:</strong> "
        '<a href="https://github.com/bicalcarata/nebulamaster">'
        "github.com/bicalcarata/nebulamaster</a></p>"
        "<p><strong>Latest release:</strong> "
        '<a href="https://github.com/bicalcarata/nebulamaster/releases/latest">'
        "github.com/bicalcarata/nebulamaster/releases/latest</a></p>"
        "<p>Written by reddit user <strong>u/bicalcarata</strong>.<br>"
        "Windows testing by <strong>u/mrrobinson7988</strong>.</p>"
        "<p><strong>Bug reports:</strong> "
        '<a href="https://github.com/bicalcarata/nebulamaster/discussions/categories/bugs">'
        "github.com/bicalcarata/nebulamaster/discussions/categories/bugs</a></p>"
        "<p><strong>Feature requests:</strong> "
        '<a href="https://github.com/bicalcarata/nebulamaster/discussions/categories/features">'
        "github.com/bicalcarata/nebulamaster/discussions/categories/features</a></p>"
    )


class HelpDialog(QDialog):
    startupPreferenceChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None, *, allow_suppress: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nebula Master Help")
        self.resize(860, 680)
        self._startup_preference_emitted = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(_load_help_document_html())

        self.suppress_checkbox = QCheckBox("Do not display this window again", self)
        self.suppress_checkbox.setVisible(allow_suppress)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout.addWidget(browser, 1)
        layout.addWidget(self.suppress_checkbox)
        layout.addWidget(buttons)

    def suppress_startup_help(self) -> bool:
        return self.suppress_checkbox.isVisible() and self.suppress_checkbox.isChecked()

    def _emit_startup_preference_if_needed(self) -> None:
        if self._startup_preference_emitted or not self.suppress_checkbox.isVisible():
            return
        self._startup_preference_emitted = True
        self.startupPreferenceChanged.emit(not self.suppress_startup_help())

    def done(self, result: int) -> None:
        self._emit_startup_preference_if_needed()
        super().done(result)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Nebula Master")
        self.resize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setHtml(_build_about_html())
        self.browser = browser

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout.addWidget(browser, 1)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    _startup_help_shown_this_session = False

    def __init__(self, project_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Nebula Master Desktop")
        self._initial_size_applied = False
        self._startup_help_prompted = False
        self._help_dialog: HelpDialog | None = None
        self._about_dialog: AboutDialog | None = None
        self._adjustment_render_timer = QTimer(self)
        self._adjustment_render_timer.setSingleShot(True)
        self._adjustment_render_timer.setInterval(300)
        self._adjustment_render_timer.timeout.connect(self._request_deferred_adjustment_render)
        self._palette_balance_expanded_by_rule_id: dict[str, bool] = {}
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
        QTimer.singleShot(0, self._maybe_show_startup_help)

    def _apply_initial_window_size(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(1500, max(1100, int(available.width() * 0.82)))
            target_height = min(960, max(760, int(available.height() * 0.82)))
            width = min(target_width, available.width())
            height = min(target_height, available.height())
            x = available.x() + max(0, (available.width() - width) // 2)
            y = available.y() + max(0, (available.height() - height) // 2)
            self.setGeometry(x, y, width, height)
            self._apply_initial_splitter_sizes(width)
        else:
            self.resize(1280, 820)
            self._apply_initial_splitter_sizes(1280)
        self.showFullScreen()

    def _apply_initial_splitter_sizes(self, width: int) -> None:
        left = max(_LEFT_PANEL_MIN_WIDTH, min(340, int(width * 0.22)))
        right = max(_RIGHT_PANEL_MIN_WIDTH, min(420, int(width * 0.24)))
        center = max(_CENTER_PANEL_MIN_WIDTH, width - left - right)
        self.main_splitter.setSizes([left, center, right])

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
        help_action = QAction("Getting Started...", self)
        help_action.triggered.connect(self._show_help_dialog)
        about_action = QAction("About Nebula Master", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(about_action)
        help_menu.addAction(help_action)

        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, root)
        self.left_panel = self._build_left_panel()
        self.center_panel = self._build_center_panel()
        self.right_panel = self._build_right_panel()
        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.center_panel)
        self.main_splitter.addWidget(self.right_panel)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setOpaqueResize(True)
        self.main_splitter.setHandleWidth(10)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setStretchFactor(2, 1)
        self._apply_initial_splitter_sizes(1500)

        bottom_panel = self._build_bottom_panel()
        root_layout.addWidget(self.main_splitter, 1)
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
        _allow_panel_horizontal_shrink(panel)
        panel.setMinimumWidth(_LEFT_PANEL_MIN_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Project")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.help_button = QPushButton("Help")
        _allow_horizontal_shrink(self.help_button)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.help_button)
        self.project_name_label = QLabel("No project open")
        self.project_path_label = QLabel("")
        self.project_path_label.setWordWrap(True)
        self.project_path_label.setStyleSheet("color: #7b8794;")

        source_title = QLabel("Sources")
        source_title.setStyleSheet("font-weight: 600;")
        self.sources_list = QListWidget()
        self.sources_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        _allow_panel_horizontal_shrink(self.sources_list)

        adjustment_header = QHBoxLayout()
        adjustment_title = QLabel("Adjustments")
        adjustment_title.setStyleSheet("font-weight: 600;")
        self.add_adjustment_button = QPushButton("Add")
        self.add_adjustment_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.add_adjustment_button.setMinimumWidth(52)
        self.move_earlier_button = QPushButton("Move Earlier")
        self.move_later_button = QPushButton("Move Later")
        adjustment_header.addWidget(adjustment_title)
        adjustment_header.addWidget(self.add_adjustment_button)
        adjustment_header.addStretch(1)

        self.adjustments_list = QListWidget()
        _allow_panel_horizontal_shrink(self.adjustments_list)
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
        region_header.setContentsMargins(0, 0, 0, 0)
        region_header.setSpacing(8)
        region_header_left = QHBoxLayout()
        region_header_left.setContentsMargins(0, 0, 0, 0)
        region_header_left.setSpacing(8)
        region_header_right = QHBoxLayout()
        region_header_right.setContentsMargins(0, 0, 0, 0)
        region_header_right.setSpacing(8)
        region_title = QLabel("Regions")
        region_title.setStyleSheet("font-weight: 600;")
        self.add_region_button = QPushButton("Add")
        self.add_region_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.add_region_button.setMinimumWidth(52)
        self.cancel_region_button = QPushButton("Cancel")
        self.show_regions_checkbox = QCheckBox("Show")
        self.show_regions_checkbox.setChecked(True)
        region_header_left.addWidget(region_title)
        region_header_left.addWidget(self.add_region_button)
        region_header_left.addStretch(1)
        region_header_right.addWidget(self.show_regions_checkbox)
        region_header_right.addWidget(self.cancel_region_button)
        region_header.addLayout(region_header_left, 1)
        region_header.addStretch(1)
        region_header.addLayout(region_header_right, 0)

        self.regions_list = QListWidget()
        _allow_panel_horizontal_shrink(self.regions_list)
        self.remove_region_button = QPushButton("Delete Region")

        self._configure_left_panel_action_icons()

        for widget in [
            self.project_name_label,
            self.project_path_label,
            self.move_earlier_button,
            self.move_later_button,
            self.duplicate_adjustment_button,
            self.remove_adjustment_button,
            self.reset_adjustment_button,
            self.cancel_region_button,
            self.remove_region_button,
        ]:
            _allow_horizontal_shrink(widget)

        layout.addLayout(header)
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
        _allow_panel_horizontal_shrink(panel)
        panel.setMinimumWidth(_CENTER_PANEL_MIN_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        toolbar_panel = QWidget(panel)
        toolbar_panel.setMinimumWidth(0)
        toolbar_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar = QVBoxLayout(toolbar_panel)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        toolbar_row_view = QHBoxLayout()
        toolbar_row_view.setContentsMargins(0, 0, 0, 0)
        toolbar_row_view.setSpacing(6)
        toolbar_row_compare = QHBoxLayout()
        toolbar_row_compare.setContentsMargins(0, 0, 0, 0)
        toolbar_row_compare.setSpacing(6)
        toolbar_row_secondary = QHBoxLayout()
        toolbar_row_secondary.setContentsMargins(0, 0, 0, 0)
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
        self.edit_dark_dust_button = QToolButton()
        self.edit_dark_dust_button.setText("Edit Dark Dust")
        self.edit_dark_dust_button.setVisible(False)
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
            self.edit_dark_dust_button,
        ]:
            _allow_toolbar_control(widget)
            toolbar_row_view.addWidget(widget)
        toolbar_row_view.addStretch(1)

        for widget in [
            self.before_after_checkbox,
            self.hold_previous_button,
            self.fit_button,
            self.actual_button,
            self.zoom_out_button,
            self.zoom_in_button,
        ]:
            _allow_toolbar_control(widget)
            toolbar_row_compare.addWidget(widget)
        toolbar_row_compare.addStretch(1)

        for widget in [
            self.pick_button,
            self.create_from_selection_button,
            self.cancel_selection_button,
        ]:
            _allow_toolbar_control(widget)
            toolbar_row_secondary.addWidget(widget)
        toolbar_row_secondary.addStretch(1)

        self.semantic_overlay_selector.setMinimumWidth(180)
        self.hold_previous_button.setMinimumWidth(130)
        self.pick_button.setMinimumWidth(150)
        self.create_from_selection_button.setMinimumWidth(250)

        self.preview_widget = ImagePreviewWidget(self)
        self.preview_widget.setMinimumSize(0, 480)
        self.rendering_label = QLabel("")
        self.rendering_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rendering_label.setStyleSheet("color: #9fb3c8;")

        toolbar.addLayout(toolbar_row_view)
        toolbar.addLayout(toolbar_row_compare)
        toolbar.addLayout(toolbar_row_secondary)
        layout.addWidget(toolbar_panel)
        layout.addWidget(self.preview_widget, 1)
        layout.addWidget(self.rendering_label)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget(self)
        _allow_panel_horizontal_shrink(panel)
        panel.setMinimumWidth(_RIGHT_PANEL_MIN_WIDTH)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        self.right_scroll_area = QScrollArea(self)
        self.right_scroll_area.setWidgetResizable(True)
        self.right_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.right_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _allow_panel_horizontal_shrink(self.right_scroll_area)

        content = QWidget(self.right_scroll_area)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        self.adjustment_section = self._build_adjustment_section()
        self.dark_dust_group = self._build_dark_dust_settings_panel()
        note = _build_muted_wrapped_label(
            "YAML comments are not preserved yet when saving edited metadata."
        )

        content_layout.addWidget(self.adjustment_section)
        content_layout.addWidget(self.dark_dust_group)
        content_layout.addWidget(note)
        content_layout.addStretch(1)

        self.right_scroll_area.setWidget(content)
        layout.addWidget(self.right_scroll_area, 1)
        return panel

    def _build_adjustment_section(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("inspectorSection")
        panel.setStyleSheet(
            "QWidget#inspectorSection {"
            "background-color: rgba(255, 255, 255, 0.03);"
            "border: 1px solid rgba(148, 163, 184, 0.18);"
            "border-radius: 12px;"
            "}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.panel_heading = QLabel("Select an adjustment to edit its settings.")
        self.panel_heading.setWordWrap(True)
        self.panel_heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        divider = QFrame(panel)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: rgba(148, 163, 184, 0.18);")

        self.editor_stack = QStackedWidget(self)
        self.editor_stack.addWidget(self._build_adjustment_editor())
        self.editor_stack.addWidget(self._build_region_editor())

        layout.addWidget(self.panel_heading)
        layout.addWidget(divider)
        layout.addWidget(self.editor_stack)
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
        self.adjustment_helper_label = _build_muted_wrapped_label("")

        self.target_label = QLabel("Affects")
        self.target_label.setStyleSheet("font-weight: 600;")
        self.target_selector = QComboBox()
        _allow_horizontal_shrink(self.target_selector)

        self.colour_title_label = QLabel("Colour Point")
        self.colour_title_label.setStyleSheet("font-weight: 600;")
        point_layout = QHBoxLayout()
        self.colour_swatch = QLabel()
        self.colour_swatch.setFixedSize(24, 24)
        self.colour_point_label = QLabel("Not selected")
        _allow_horizontal_shrink(self.colour_point_label)
        point_layout.addWidget(self.colour_swatch)
        point_layout.addWidget(self.colour_point_label, 1)

        self.primary_label = QLabel("Amount")
        self.primary_label.setStyleSheet("font-weight: 600;")
        self.primary_slider = QSlider(Qt.Orientation.Horizontal)
        self.primary_input = QDoubleSpinBox()
        self.primary_input.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
        self.primary_input.setKeyboardTracking(False)
        _allow_horizontal_shrink(self.primary_input)
        primary_controls = QWidget(self)
        _allow_panel_horizontal_shrink(primary_controls)
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
            _allow_horizontal_shrink(input_widget)
            row = QWidget(self.level_inputs_container)
            _allow_panel_horizontal_shrink(row)
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
        self.option_checkbox = QCheckBox("Preserve Brightness")
        self.palette_balance_title_label = QLabel("Colour Balance")
        self.palette_balance_title_label.setStyleSheet("font-weight: 600;")
        self.palette_balance_toggle_button = QPushButton("▸")
        self.palette_balance_toggle_button.setCheckable(True)
        self.palette_balance_toggle_button.setChecked(False)
        self.palette_balance_toggle_button.setFixedWidth(32)
        self.palette_balance_toggle_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.palette_balance_helper_label = _build_muted_wrapped_label(
            "Adjusts the strength of the main colours inside the full palette effect. "
            "Amount still controls how much of the complete palette is mixed into the image."
        )
        palette_balance_header = QHBoxLayout()
        palette_balance_header.setContentsMargins(0, 0, 0, 0)
        palette_balance_header.setSpacing(8)
        palette_balance_header.addWidget(self.palette_balance_title_label)
        palette_balance_header.addStretch(1)
        palette_balance_header.addWidget(self.palette_balance_toggle_button)
        self.palette_balance_controls_widget = QWidget(self)
        self.palette_balance_controls_layout = QVBoxLayout(self.palette_balance_controls_widget)
        self.palette_balance_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.palette_balance_controls_layout.setSpacing(8)
        self.reset_palette_balance_button = QPushButton("Reset Colour Balance")
        self.palette_balance_section = QWidget(self)
        palette_balance_section_layout = QVBoxLayout(self.palette_balance_section)
        palette_balance_section_layout.setContentsMargins(0, 0, 0, 0)
        palette_balance_section_layout.setSpacing(8)
        palette_balance_section_layout.addLayout(palette_balance_header)
        palette_balance_section_layout.addWidget(self.palette_balance_helper_label)
        palette_balance_section_layout.addWidget(self.palette_balance_controls_widget)
        palette_balance_section_layout.addWidget(self.reset_palette_balance_button)

        self.extra_adjustment_controls_title = QLabel("Dark Nebula Controls")
        self.extra_adjustment_controls_title.setStyleSheet("font-weight: 600;")
        self.extra_adjustment_controls_helper = _build_muted_wrapped_label(
            "Fine-tunes how the dark-nebula treatment lifts the veil, preserves the core, "
            "and strengthens existing dust colour."
        )
        self.extra_adjustment_controls_widget = QWidget(self)
        self.extra_adjustment_controls_layout = QVBoxLayout(self.extra_adjustment_controls_widget)
        self.extra_adjustment_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_adjustment_controls_layout.setSpacing(8)
        self.extra_adjustment_controls_section = QWidget(self)
        extra_controls_section_layout = QVBoxLayout(self.extra_adjustment_controls_section)
        extra_controls_section_layout.setContentsMargins(0, 0, 0, 0)
        extra_controls_section_layout.setSpacing(8)
        extra_controls_section_layout.addWidget(self.extra_adjustment_controls_title)
        extra_controls_section_layout.addWidget(self.extra_adjustment_controls_helper)
        extra_controls_section_layout.addWidget(self.extra_adjustment_controls_widget)

        self.scope_title_label = QLabel("Apply in")
        self.scope_title_label.setStyleSheet("font-weight: 600;")
        self.apply_everywhere_checkbox = QCheckBox("Apply everywhere")
        self.region_scope_list = QListWidget()
        self.region_scope_list.setMinimumHeight(110)
        _allow_panel_horizontal_shrink(self.region_scope_list)

        self.adjustment_name_label.setVisible(False)
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
        layout.addWidget(self.option_checkbox)
        layout.addWidget(self.palette_balance_section)
        layout.addWidget(self.extra_adjustment_controls_section)
        layout.addWidget(self.scope_title_label)
        layout.addWidget(self.apply_everywhere_checkbox)
        layout.addWidget(self.region_scope_list, 1)
        return panel

    def _build_dark_dust_settings_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("inspectorSection")
        _allow_panel_horizontal_shrink(panel)
        panel.setStyleSheet(
            "QWidget#inspectorSection {"
            "background-color: rgba(255, 255, 255, 0.03);"
            "border: 1px solid rgba(148, 163, 184, 0.18);"
            "border-radius: 12px;"
            "}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.dark_dust_title_label = QLabel("Dark Dust Mask")
        self.dark_dust_title_label.setStyleSheet("font-weight: 600;")
        self.dark_dust_toggle_button = QPushButton("▾")
        self.dark_dust_toggle_button.setCheckable(True)
        self.dark_dust_toggle_button.setChecked(True)
        self.dark_dust_toggle_button.setFixedWidth(32)
        self.dark_dust_toggle_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.dark_dust_toggle_button.setToolTip("Collapse Dark Dust Mask")
        header.addWidget(self.dark_dust_title_label)
        header.addStretch(1)
        header.addWidget(self.dark_dust_toggle_button)

        self.dark_dust_body = QWidget(panel)
        _allow_panel_horizontal_shrink(self.dark_dust_body)
        body_layout = QVBoxLayout(self.dark_dust_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        helper = _build_muted_wrapped_label(
            "Controls the global Dark Dust mask used by the overlay and by adjustments "
            "that target Dark Dust."
        )

        self.dark_dust_enabled_checkbox = QCheckBox("Enabled")
        self.dark_dust_view_selector = QComboBox()
        self.dark_dust_display_selector = QComboBox()
        self.dark_dust_solo_button = QPushButton("Solo Dark Dust Mask")
        self.dark_dust_coverage_label = _build_muted_wrapped_label("")
        self.dark_dust_sensitivity_input = QDoubleSpinBox()
        self.dark_dust_structure_size_input = QDoubleSpinBox()
        self.dark_dust_background_protection_input = QDoubleSpinBox()
        self.dark_dust_softness_input = QDoubleSpinBox()
        self.dark_dust_veil_strength_input = QDoubleSpinBox()
        self.dark_dust_core_strength_input = QDoubleSpinBox()
        self.dark_dust_veil_core_balance_input = QDoubleSpinBox()
        self.reset_dark_dust_button = QPushButton("Reset Dark Dust Mask")
        for widget in [
            self.dark_dust_view_selector,
            self.dark_dust_display_selector,
            self.dark_dust_solo_button,
            self.dark_dust_sensitivity_input,
            self.dark_dust_structure_size_input,
            self.dark_dust_background_protection_input,
            self.dark_dust_softness_input,
            self.dark_dust_veil_strength_input,
            self.dark_dust_core_strength_input,
            self.dark_dust_veil_core_balance_input,
            self.reset_dark_dust_button,
        ]:
            _allow_horizontal_shrink(widget)

        controls: list[tuple[str, QDoubleSpinBox]] = [
            ("Sensitivity", self.dark_dust_sensitivity_input),
            ("Structure Size", self.dark_dust_structure_size_input),
            ("Background Protection", self.dark_dust_background_protection_input),
            ("Softness", self.dark_dust_softness_input),
            ("Veil Detection", self.dark_dust_veil_strength_input),
            ("Core Detection", self.dark_dust_core_strength_input),
            ("Veil / Core Balance", self.dark_dust_veil_core_balance_input),
        ]
        body_layout.addWidget(helper)
        body_layout.addWidget(self.dark_dust_enabled_checkbox)
        body_layout.addWidget(QLabel("Overlay View"))
        body_layout.addWidget(self.dark_dust_view_selector)
        body_layout.addWidget(QLabel("Display Mode"))
        body_layout.addWidget(self.dark_dust_display_selector)
        body_layout.addWidget(self.dark_dust_solo_button)
        body_layout.addWidget(self.dark_dust_coverage_label)
        for label, widget in controls:
            caption = QLabel(label)
            caption.setStyleSheet("font-weight: 600;")
            widget.setDecimals(2)
            widget.setRange(0.0, 1.0)
            widget.setSingleStep(0.01)
            body_layout.addWidget(caption)
            body_layout.addWidget(widget)
        body_layout.addWidget(self.reset_dark_dust_button)
        layout.addLayout(header)
        layout.addWidget(self.dark_dust_body)
        self._set_dark_dust_collapsed(False)
        return panel

    def _build_region_editor(self) -> QWidget:
        panel = QWidget(self)
        _allow_panel_horizontal_shrink(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.region_name_edit = QLineEdit()
        _allow_horizontal_shrink(self.region_name_edit)
        self.region_enabled_checkbox = QCheckBox("Enabled")
        self.region_helper_label = _build_muted_wrapped_label(
            "Softens the boundary so the adjustment blends naturally into the surrounding image."
        )
        self.region_softness_slider = QSlider(Qt.Orientation.Horizontal)
        self.region_softness_value_label = QLabel("")
        self.region_reference_label = _build_muted_wrapped_label("")

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
        _allow_panel_horizontal_shrink(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Unsaved Changes")
        title.setStyleSheet("font-weight: 600;")
        self.save_button = QPushButton("Keep Change")
        self.save_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.save_button.setMinimumWidth(108)
        header.addWidget(title)
        header.addWidget(self.save_button)
        header.addStretch(1)

        self.changes_list = QListWidget()
        self.changes_list.setMaximumHeight(120)
        _allow_panel_horizontal_shrink(self.changes_list)
        self.revert_change_button = QPushButton("Remove Selected Change")
        self.what_changed_button = QPushButton("What Changed?")
        self.revert_all_button = QPushButton("Revert All")
        for widget in [
            self.revert_change_button,
            self.what_changed_button,
            self.revert_all_button,
        ]:
            _allow_horizontal_shrink(widget)
        actions = QHBoxLayout()
        actions.addWidget(self.revert_change_button)
        actions.addWidget(self.what_changed_button)
        actions.addWidget(self.revert_all_button)
        actions.addStretch(1)

        layout.addLayout(header)
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
        self.help_button.clicked.connect(self._show_help_dialog)

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
        self.option_checkbox.toggled.connect(self.view_model.set_selected_adjustment_option_enabled)
        self.palette_balance_toggle_button.toggled.connect(self._on_palette_balance_toggled)
        self.reset_palette_balance_button.clicked.connect(
            self.view_model.reset_selected_adjustment_palette_balance
        )
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
        self.dark_dust_veil_strength_input.valueChanged.connect(self.view_model.set_dark_dust_veil_strength)
        self.dark_dust_core_strength_input.valueChanged.connect(self.view_model.set_dark_dust_core_strength)
        self.dark_dust_veil_core_balance_input.valueChanged.connect(
            self.view_model.set_dark_dust_veil_core_balance
        )
        self.dark_dust_view_selector.currentIndexChanged.connect(self._on_dark_dust_view_changed)
        self.dark_dust_display_selector.currentIndexChanged.connect(
            self._on_dark_dust_display_changed
        )
        self.dark_dust_solo_button.clicked.connect(
            lambda: self.view_model.set_solo_dark_dust_mask(True)
        )
        self.reset_dark_dust_button.clicked.connect(self.view_model.reset_dark_dust_settings)
        self.dark_dust_toggle_button.toggled.connect(self._on_dark_dust_toggled)

        self.revert_change_button.clicked.connect(self._revert_selected_change)
        self.what_changed_button.clicked.connect(self._show_semantic_changes)
        self.revert_all_button.clicked.connect(self.view_model.revert_unsaved_changes)
        self.save_button.clicked.connect(self.view_model.save_changes)
        self.edit_dark_dust_button.clicked.connect(self._focus_dark_dust_panel)

    def _app_settings(self) -> QSettings:
        return QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "NebulaMaster",
            "Desktop",
        )

    def _show_startup_help_enabled(self) -> bool:
        raw_value = self._app_settings().value(_HELP_SHOW_ON_STARTUP_KEY, True)
        if isinstance(raw_value, bool):
            return raw_value
        if raw_value is None:
            return True
        return str(raw_value).strip().lower() not in {"0", "false", "no"}

    def _set_show_startup_help_enabled(self, enabled: bool) -> None:
        self._app_settings().setValue(_HELP_SHOW_ON_STARTUP_KEY, enabled)

    def _maybe_show_startup_help(self) -> None:
        if (
            self._startup_help_prompted
            or MainWindow._startup_help_shown_this_session
            or not self._show_startup_help_enabled()
        ):
            return
        self._startup_help_prompted = True
        MainWindow._startup_help_shown_this_session = True
        self._show_help_dialog(startup=True)

    def _show_help_dialog(self, _checked: bool = False, *, startup: bool = False) -> None:
        allow_suppress = startup
        dialog = HelpDialog(self, allow_suppress=allow_suppress)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if startup:
            dialog.startupPreferenceChanged.connect(self._set_show_startup_help_enabled)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._help_dialog = dialog

    def _show_about_dialog(self, _checked: bool = False) -> None:
        dialog = AboutDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._about_dialog = dialog

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
        menu.addAction(
            "Add Faux Hubble adjustment",
            lambda: self.view_model.create_adjustment("faux_hubble"),
        )
        menu.addAction(
            "Add Faux HOO adjustment",
            lambda: self.view_model.create_adjustment("faux_hoo"),
        )
        menu.addAction(
            "Add Foraxx-Inspired adjustment",
            lambda: self.view_model.create_adjustment("foraxx"),
        )
        menu.addAction(
            "Add Gold & Cyan adjustment",
            lambda: self.view_model.create_adjustment("gold_cyan"),
        )
        menu.addAction(
            "Add Natural Bi-colour adjustment",
            lambda: self.view_model.create_adjustment("natural_bicolour"),
        )
        menu.addAction(
            "Add Dark Nebula Processing adjustment",
            lambda: self.view_model.create_adjustment("dark_nebula_processing"),
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
        self._update_dark_dust_action_visibility()

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
        with QSignalBlocker(self.dark_dust_view_selector):
            self.dark_dust_view_selector.clear()
            for label, value in [
                ("Final Mask", "final_mask"),
                ("Veil Mask", "veil_mask"),
                ("Core Mask", "core_mask"),
                ("Relative Darkness", "relative_darkness"),
                ("Local Illumination", "local_illumination"),
                ("Background Support", "background_support"),
            ]:
                self.dark_dust_view_selector.addItem(label, value)
            view_index = self.dark_dust_view_selector.findData(
                self.view_model.dark_dust_overlay_view()
            )
            self.dark_dust_view_selector.setCurrentIndex(max(0, view_index))
        with QSignalBlocker(self.dark_dust_display_selector):
            self.dark_dust_display_selector.clear()
            for label, value in [("Overlay on Image", "overlay"), ("Mask Only", "mask")]:
                self.dark_dust_display_selector.addItem(label, value)
            self.dark_dust_display_selector.setCurrentIndex(
                max(
                    0,
                    self.dark_dust_display_selector.findData(
                        self.view_model.dark_dust_overlay_display()
                    ),
                )
            )
        self.dark_dust_coverage_label.setText(
            f"Dark Dust Coverage: {self.view_model.dark_dust_coverage_percent():.1f}%"
        )
        numeric_settings: list[tuple[QDoubleSpinBox, float]] = [
            (self.dark_dust_sensitivity_input, settings.sensitivity),
            (self.dark_dust_structure_size_input, settings.structure_size),
            (self.dark_dust_background_protection_input, settings.background_protection),
            (self.dark_dust_softness_input, settings.softness),
            (self.dark_dust_veil_strength_input, settings.veil_strength),
            (self.dark_dust_core_strength_input, settings.core_strength),
            (self.dark_dust_veil_core_balance_input, settings.veil_core_balance),
        ]
        for widget, numeric_value in numeric_settings:
            with QSignalBlocker(widget):
                widget.setValue(numeric_value)

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
            self.adjustment_name_label.setVisible(True)
            self.adjustment_name_label.setText("Select an adjustment to edit its settings.")
            self.adjustment_type_label.setText("")
            self.adjustment_helper_label.setText("")
            self.adjustment_enabled_checkbox.setVisible(False)
            self.target_label.setVisible(False)
            self.target_selector.setVisible(False)
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
            self.secondary_label.setVisible(False)
            self.secondary_slider.setVisible(False)
            self.secondary_value_label.setVisible(False)
            self.option_checkbox.setVisible(False)
            self.palette_balance_section.setVisible(False)
            self.extra_adjustment_controls_section.setVisible(False)
            self.scope_title_label.setVisible(False)
            self.apply_everywhere_checkbox.setVisible(False)
            self.region_scope_list.setVisible(False)
            return

        self.adjustment_name_label.setVisible(False)
        self.adjustment_name_label.setText(summary.name)
        self.adjustment_type_label.setText(summary.type_label)
        self.adjustment_helper_label.setText(summary.helper_text)
        self.adjustment_enabled_checkbox.setVisible(True)
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
            elif summary.transform_type == "faux_palette":
                spin_value = max(
                    _PALETTE_UI_MIN,
                    min(_PALETTE_UI_MAX, summary.primary_value * 100.0),
                )
                spin_range = (_PALETTE_UI_MIN, _PALETTE_UI_MAX)
                spin_step = 1.0
                spin_decimals = 0
                spin_suffix = "%"
            elif summary.transform_type == "dark_nebula_processing":
                spin_value = max(
                    _PALETTE_UI_MIN,
                    min(_PALETTE_UI_MAX, summary.primary_value * 100.0),
                )
                spin_range = (_PALETTE_UI_MIN, _PALETTE_UI_MAX)
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
        self.option_checkbox.setVisible(summary.option_label is not None)
        if summary.option_label is not None and summary.option_enabled is not None:
            self.option_checkbox.setText(summary.option_label)
            with QSignalBlocker(self.option_checkbox):
                self.option_checkbox.setChecked(summary.option_enabled)
        self._refresh_palette_balance_section(summary)
        self._refresh_extra_adjustment_controls(summary)

        self.scope_title_label.setVisible(True)
        self.apply_everywhere_checkbox.setVisible(True)
        self.region_scope_list.setVisible(True)
        with QSignalBlocker(self.apply_everywhere_checkbox):
            self.apply_everywhere_checkbox.setChecked(not summary.region_ids)
        self.apply_everywhere_checkbox.setEnabled(summary.editable)
        self._refresh_region_scope_list(summary)

        self.duplicate_adjustment_button.setEnabled(summary.editable)
        self.remove_adjustment_button.setEnabled(summary.editable)
        self.reset_adjustment_button.setEnabled(True)
        self.move_earlier_button.setEnabled(True)
        self.move_later_button.setEnabled(True)

    def _refresh_extra_adjustment_controls(self, summary: AdjustmentSummary) -> None:
        self.extra_adjustment_controls_section.setVisible(bool(summary.extra_numeric_controls))
        if not summary.extra_numeric_controls:
            self._clear_layout(self.extra_adjustment_controls_layout)
            return

        self._clear_layout(self.extra_adjustment_controls_layout)
        for control in summary.extra_numeric_controls:
            label = QLabel(control.label)
            label.setStyleSheet("font-weight: 600;")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(round(control.value * 100.0)))
            slider.setToolTip(control.helper_text)
            slider.sliderPressed.connect(self._on_adjustment_slider_pressed)
            slider.sliderReleased.connect(self._on_adjustment_slider_released)

            input_widget = QDoubleSpinBox()
            input_widget.setDecimals(0)
            input_widget.setRange(0.0, 100.0)
            input_widget.setSingleStep(1.0)
            input_widget.setSuffix("%")
            input_widget.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
            input_widget.setKeyboardTracking(False)
            input_widget.setValue(control.value * 100.0)
            input_widget.setToolTip(control.helper_text)
            _allow_horizontal_shrink(input_widget)

            row = QWidget(self.extra_adjustment_controls_widget)
            _allow_panel_horizontal_shrink(row)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(input_widget)

            slider.valueChanged.connect(
                lambda value, key=control.key, widget=input_widget:
                self._on_extra_control_slider_changed(
                    key,
                    value,
                    widget,
                )
            )
            input_widget.valueChanged.connect(
                lambda value, key=control.key, widget=slider: self._on_extra_control_input_changed(
                    key,
                    value,
                    widget,
                )
            )
            input_widget.editingFinished.connect(self._schedule_adjustment_render)

            self.extra_adjustment_controls_layout.addWidget(label)
            self.extra_adjustment_controls_layout.addWidget(row)

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

    def _clear_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(cast(QVBoxLayout | QHBoxLayout, child_layout))

    def _refresh_palette_balance_section(self, summary: AdjustmentSummary) -> None:
        is_palette = summary.transform_type == "faux_palette"
        has_controls = bool(summary.palette_balance_controls)
        self.palette_balance_section.setVisible(is_palette and has_controls)
        if not (is_palette and has_controls):
            return

        expanded = self._palette_balance_expanded_by_rule_id.get(summary.rule_id, False)
        with QSignalBlocker(self.palette_balance_toggle_button):
            self.palette_balance_toggle_button.setChecked(expanded)
        self._set_palette_balance_collapsed(not expanded)
        self._clear_layout(self.palette_balance_controls_layout)

        for control in summary.palette_balance_controls:
            label = QLabel(control.label)
            label.setStyleSheet("font-weight: 600;")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 200)
            slider.setValue(int(round(control.value)))
            slider.setToolTip(control.helper_text)
            slider.sliderPressed.connect(self._on_adjustment_slider_pressed)
            slider.sliderReleased.connect(self._on_adjustment_slider_released)

            input_widget = QDoubleSpinBox()
            input_widget.setDecimals(0)
            input_widget.setRange(0.0, 200.0)
            input_widget.setSingleStep(1.0)
            input_widget.setSuffix("%")
            input_widget.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
            input_widget.setKeyboardTracking(False)
            input_widget.setValue(control.value)
            input_widget.setToolTip(control.helper_text)
            _allow_horizontal_shrink(input_widget)

            row = QWidget(self.palette_balance_controls_widget)
            _allow_panel_horizontal_shrink(row)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(input_widget)

            slider.valueChanged.connect(
                self._make_palette_balance_slider_handler(control.key, input_widget)
            )
            input_widget.valueChanged.connect(
                self._make_palette_balance_input_handler(control.key, slider)
            )
            input_widget.editingFinished.connect(self._schedule_adjustment_render)

            self.palette_balance_controls_layout.addWidget(label)
            self.palette_balance_controls_layout.addWidget(row)

    def _make_palette_balance_slider_handler(
        self,
        key: str,
        input_widget: QDoubleSpinBox,
    ) -> Callable[[int], None]:
        def handler(value: int) -> None:
            self._on_palette_balance_slider_changed(key, value, input_widget)

        return handler

    def _make_palette_balance_input_handler(
        self,
        key: str,
        slider: QSlider,
    ) -> Callable[[float], None]:
        def handler(value: float) -> None:
            self._on_palette_balance_input_changed(key, value, slider)

        return handler

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
            self._update_dark_dust_action_visibility(mode)
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

    def _on_dark_dust_view_changed(self, index: int) -> None:
        if index < 0:
            return
        value = self.dark_dust_view_selector.itemData(index)
        if isinstance(value, str):
            self.view_model.set_dark_dust_overlay_view(cast(Any, value))

    def _on_dark_dust_display_changed(self, index: int) -> None:
        if index < 0:
            return
        value = self.dark_dust_display_selector.itemData(index)
        if isinstance(value, str):
            self.view_model.set_dark_dust_overlay_display(cast(Any, value))

    def _on_secondary_value_changed(self, value: int) -> None:
        render = not self.view_model.is_adjustment_interacting
        self.view_model.set_selected_adjustment_secondary_value(value / 100.0, render=render)
        if render:
            self._schedule_adjustment_render()

    def _on_palette_balance_slider_changed(
        self,
        key: str,
        value: int,
        input_widget: QDoubleSpinBox,
    ) -> None:
        with QSignalBlocker(input_widget):
            input_widget.setValue(float(value))
        self.view_model.set_selected_adjustment_palette_balance(
            key,
            float(value),
            render=not self.view_model.is_adjustment_interacting,
        )

    def _on_palette_balance_input_changed(
        self,
        key: str,
        value: float,
        slider: QSlider,
    ) -> None:
        with QSignalBlocker(slider):
            slider.setValue(int(round(value)))
        self.view_model.set_selected_adjustment_palette_balance(key, value, render=False)
        self._schedule_adjustment_render()

    def _on_extra_control_slider_changed(
        self,
        key: str,
        value: int,
        input_widget: QDoubleSpinBox,
    ) -> None:
        with QSignalBlocker(input_widget):
            input_widget.setValue(float(value))
        self.view_model.set_selected_adjustment_extra_numeric_control(
            key,
            value / 100.0,
            render=not self.view_model.is_adjustment_interacting,
        )

    def _on_extra_control_input_changed(
        self,
        key: str,
        value: float,
        slider: QSlider,
    ) -> None:
        with QSignalBlocker(slider):
            slider.setValue(int(round(value)))
        self.view_model.set_selected_adjustment_extra_numeric_control(
            key,
            value / 100.0,
            render=False,
        )
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
        elif summary.transform_type == "faux_palette":
            normalized = value / 100.0
        elif summary.transform_type == "dark_nebula_processing":
            normalized = value / 100.0
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
            region = self.view_model.selected_region_summary()
            self.panel_heading.setText(
                f"Region: {region.name}" if region is not None else "Region"
            )
            mode: InteractionMode = (
                "draw_region" if self.view_model.is_drawing_region else "edit_region"
            )
            self.preview_widget.set_interaction_mode(mode)
        else:
            self.editor_stack.setCurrentIndex(0)
            summary = self.view_model.selected_adjustment_summary()
            if summary is None:
                self.panel_heading.setText("Select an adjustment to edit its settings.")
            else:
                self.panel_heading.setText(f"Adjustment: {summary.name}")
            if not self.view_model.is_sampling:
                self.preview_widget.set_interaction_mode("navigate")

    def _on_drawing_mode_changed(self, drawing: bool) -> None:
        self.cancel_region_button.setEnabled(drawing)
        self.preview_widget.set_interaction_mode("draw_region" if drawing else "edit_region")

    def _on_region_visibility_changed(self, visible: bool) -> None:
        with QSignalBlocker(self.show_regions_checkbox):
            self.show_regions_checkbox.setChecked(visible)

    def _focus_dark_dust_panel(self) -> None:
        if not self.dark_dust_toggle_button.isChecked():
            self.dark_dust_toggle_button.setChecked(True)
        self.right_scroll_area.ensureWidgetVisible(self.dark_dust_group, 0, 24)

    def _update_dark_dust_action_visibility(self, mode: str | None = None) -> None:
        current_mode = mode or cast(str, self.semantic_overlay_selector.currentData() or "off")
        self.edit_dark_dust_button.setVisible(current_mode == "dark_dust")

    def _on_dark_dust_toggled(self, expanded: bool) -> None:
        self._set_dark_dust_collapsed(not expanded)

    def _on_palette_balance_toggled(self, expanded: bool) -> None:
        summary = self.view_model.selected_adjustment_summary()
        if summary is not None:
            self._palette_balance_expanded_by_rule_id[summary.rule_id] = expanded
        self._set_palette_balance_collapsed(not expanded)

    def _set_dark_dust_collapsed(self, collapsed: bool) -> None:
        self.dark_dust_body.setVisible(not collapsed)
        self.dark_dust_toggle_button.setText("▸" if collapsed else "▾")
        self.dark_dust_toggle_button.setToolTip(
            "Expand Dark Dust Mask" if collapsed else "Collapse Dark Dust Mask"
        )

    def _set_palette_balance_collapsed(self, collapsed: bool) -> None:
        self.palette_balance_helper_label.setVisible(not collapsed)
        self.palette_balance_controls_widget.setVisible(not collapsed)
        self.reset_palette_balance_button.setVisible(not collapsed)
        self.palette_balance_toggle_button.setText("▸" if collapsed else "▾")
        self.palette_balance_toggle_button.setToolTip(
            "Expand Colour Balance" if collapsed else "Collapse Colour Balance"
        )

    def _configure_left_panel_action_icons(self) -> None:
        style = self.style()
        accent = QColor("#f4c542")
        self._left_panel_action_buttons: list[tuple[QPushButton, str]] = [
            (
                self.move_earlier_button,
                "Move Earlier",
            ),
            (
                self.move_later_button,
                "Move Later",
            ),
            (
                self.duplicate_adjustment_button,
                "Duplicate",
            ),
            (
                self.remove_adjustment_button,
                "Remove",
            ),
            (
                self.reset_adjustment_button,
                "Reset",
            ),
        ]
        self.move_earlier_button.setIcon(
            _tinted_standard_icon(
                style,
                QStyle.StandardPixmap.SP_ArrowUp,
                color=accent,
            )
        )
        self.move_later_button.setIcon(
            _tinted_standard_icon(
                style,
                QStyle.StandardPixmap.SP_ArrowDown,
                color=accent,
            )
        )
        self.duplicate_adjustment_button.setIcon(
            _tinted_standard_icon(
                style,
                QStyle.StandardPixmap.SP_FileDialogNewFolder,
                color=accent,
            )
        )
        self.remove_adjustment_button.setIcon(
            _tinted_standard_icon(
                style,
                QStyle.StandardPixmap.SP_TrashIcon,
                color=accent,
            )
        )
        self.reset_adjustment_button.setIcon(
            _tinted_standard_icon(
                style,
                QStyle.StandardPixmap.SP_BrowserReload,
                color=accent,
            )
        )
        self.move_earlier_button.setToolTip("Move selected adjustment earlier")
        self.move_later_button.setToolTip("Move selected adjustment later")
        self.duplicate_adjustment_button.setToolTip("Duplicate selected adjustment")
        self.remove_adjustment_button.setToolTip("Remove selected adjustment")
        self.reset_adjustment_button.setToolTip("Reset selected adjustment")
        for button, label in getattr(self, "_left_panel_action_buttons", []):
            _ = label
            button.setText("")
            button.setIconSize(QSize(18, 18))
            button.setMinimumHeight(40)
            button.setStyleSheet("padding: 0px; text-align: center;")

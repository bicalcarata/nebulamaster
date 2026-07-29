from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml
from engine import semantic_target_influence
from engine.render import render_bundle_output
from engine.semantic import analyze_dark_dust
from image_io import CanonicalImage, inspect_image, load_canonical_image
from nebula_desktop import __version__ as desktop_version
from nebula_desktop.application.project_scaffold import scaffold_project_from_image
from nebula_desktop.application.window import (
    AboutDialog,
    MainWindow,
    _brightness_amount_to_ui,
)
from nebula_desktop.viewmodels.project_editor import AdjustmentKind, ProjectEditorViewModel
from nebula_desktop.views.image_preview import (
    ImagePreviewWidget,
    ImageSample,
    semantic_overlay_rgba,
)
from PIL import Image
from project_io import read_yaml_mapping
from project_model import (
    BrightnessTransform,
    ColourAmountTransform,
    FauxPaletteTransform,
    LevelsTransform,
    SaturationTransform,
    ShiftColourPointTransform,
)
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog


def _copy_example_project(tmp_path: Path) -> Path:
    source = Path("examples/valid/minimal-project")
    destination = tmp_path / "project"
    shutil.copytree(source, destination)
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _append_rule(project_dir: Path, rule: dict[str, Any]) -> None:
    project_path = project_dir / "project.yaml"
    payload = read_yaml_mapping(project_path)
    payload["rules"].append(rule)
    project_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _create_source_image(path: Path) -> None:
    image = Image.new("RGB", (16, 12), color=(32, 64, 128))
    image.save(path)


def _write_star_nebula_tiff(path: Path) -> None:
    width, height = 96, 64
    data = np.zeros((height, width, 3), dtype=np.uint8)
    data[:, :, :] = [12, 10, 20]
    data[20:48, 18:44, :] = [70, 30, 24]
    data[46:58, 34:76, :] = [80, 34, 28]
    for x, y in [(12, 10), (58, 24), (76, 18), (70, 50)]:
        data[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2, :] = [255, 255, 255]
    Image.fromarray(data, mode="RGB").save(path, format="TIFF")


def _preview_sample(view_model: ProjectEditorViewModel) -> ImageSample:
    preview = view_model._current_preview
    assert preview is not None
    rgb = cast(
        tuple[float, float, float],
        tuple(float(channel) for channel in preview.image.data[0, 0]),
    )
    return ImageSample(x=0, y=0, rgb=rgb)


def test_desktop_opens_valid_project_headless(qtbot: Any, tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.project_name_label.text() == "Horsehead Demo"
    assert window.view_model.current_display_image() is not None


def test_main_window_uses_resizable_three_panel_splitter_and_fullscreen_launch(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)
    qtbot.waitUntil(lambda: window._initial_size_applied is True, timeout=5000)

    assert window.main_splitter.count() == 3
    assert window.main_splitter.childrenCollapsible() is False
    assert window.main_splitter.handleWidth() == 10
    ignored = window.left_panel.sizePolicy().Policy.Ignored
    assert window.left_panel.sizePolicy().horizontalPolicy() == ignored
    assert window.center_panel.sizePolicy().horizontalPolicy() == ignored
    assert window.right_panel.sizePolicy().horizontalPolicy() == ignored
    assert window.left_panel.minimumWidth() == 220
    assert window.center_panel.minimumWidth() == 560
    assert window.right_panel.minimumWidth() == 320
    screen = window.screen() or QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    normal_geometry = window.normalGeometry()
    assert normal_geometry.width() >= min(1100, available.width())
    assert normal_geometry.height() >= min(760, available.height())
    sizes = window.main_splitter.sizes()
    assert len(sizes) == 3
    assert sizes[0] > 0
    assert sizes[1] >= sizes[0]
    assert sizes[2] > 0
    assert window.show_preview_button.width() > 0
    assert window.semantic_overlay_selector.width() >= 180
    assert window.pick_button.width() >= 150
    assert window.move_earlier_button.text() == ""
    assert window.move_later_button.text() == ""
    assert window.duplicate_adjustment_button.text() == ""
    assert window.remove_adjustment_button.text() == ""
    assert window.reset_adjustment_button.text() == ""


def test_add_adjustment_button_stays_next_to_adjustments_label(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    button_geometry = window.add_adjustment_button.geometry()
    assert window.add_adjustment_button.isVisible() is True
    assert button_geometry.top() < window.adjustments_list.geometry().top()
    assert button_geometry.left() < window.adjustments_list.geometry().left() + 220


def test_keep_change_button_stays_next_to_unsaved_changes_label(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    button_geometry = window.save_button.geometry()
    assert window.save_button.isVisible() is True
    assert button_geometry.top() < window.changes_list.geometry().top()
    assert button_geometry.left() < window.changes_list.geometry().left() + 180


def test_add_region_button_stays_next_to_regions_label(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    button_geometry = window.add_region_button.geometry()
    assert window.add_region_button.isVisible() is True
    assert window.add_region_button.text() == "Add"
    assert window.add_region_button.width() >= 40
    assert button_geometry.top() < window.regions_list.geometry().top()
    assert button_geometry.left() < window.regions_list.geometry().left() + 180
    assert button_geometry.left() < window.show_regions_checkbox.geometry().left()


def test_open_project_dialog_accepts_project_yaml(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    project_file = project_dir / "project.yaml"
    window = MainWindow()
    qtbot.addWidget(window)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(project_file), "Nebula Project (project.yaml)"),
    )

    window._open_project_dialog()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.project_name_label.text() == "Horsehead Demo"


def test_help_button_opens_help_dialog(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    MainWindow._startup_help_shown_this_session = False
    monkeypatch.setattr(MainWindow, "_show_startup_help_enabled", lambda self: False)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.help_button.click()
    qtbot.waitUntil(lambda: window._help_dialog is not None, timeout=5000)
    assert window._help_dialog is not None
    assert window._help_dialog.windowTitle() == "Nebula Master Help"
    assert window._help_dialog.isVisible() is True
    assert window._help_dialog.suppress_checkbox.isVisible() is False


def test_about_menu_opens_about_dialog_with_version_and_links(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    MainWindow._startup_help_shown_this_session = False
    monkeypatch.setattr(MainWindow, "_show_startup_help_enabled", lambda self: False)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window._show_about_dialog()
    qtbot.waitUntil(lambda: window._about_dialog is not None, timeout=5000)

    assert window._about_dialog is not None
    assert isinstance(window._about_dialog, AboutDialog)
    assert window._about_dialog.windowTitle() == "About Nebula Master"
    html = window._about_dialog.browser.toHtml()
    assert desktop_version in html
    assert "github.com/bicalcarata/nebulamaster/releases/latest" in html
    assert "discussions/categories/bugs" in html
    assert "discussions/categories/features" in html


def test_startup_help_can_be_suppressed_for_future_launches(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    MainWindow._startup_help_shown_this_session = False
    persisted: list[bool] = []
    monkeypatch.setattr(MainWindow, "_show_startup_help_enabled", lambda self: True)
    monkeypatch.setattr(
        MainWindow,
        "_set_show_startup_help_enabled",
        lambda self, enabled: persisted.append(enabled),
    )

    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window._help_dialog is not None, timeout=5000)
    assert window._help_dialog is not None
    assert window._help_dialog.suppress_checkbox.isVisible() is True

    window._help_dialog.suppress_checkbox.setChecked(True)
    window._help_dialog.close()
    qtbot.waitUntil(lambda: persisted == [False], timeout=5000)

    second = MainWindow(project_dir)
    qtbot.addWidget(second)
    second.show()
    qtbot.waitUntil(lambda: second.view_model._current_preview is not None, timeout=5000)
    qtbot.wait(150)
    assert second._help_dialog is None


def test_scaffold_project_from_tiff_creates_valid_project(tmp_path: Path) -> None:
    source_path = tmp_path / "horsehead-source.tiff"
    _create_source_image(source_path)
    parent_dir = tmp_path / "projects"
    parent_dir.mkdir()

    project_file = scaffold_project_from_image(
        source_path=source_path,
        destination_parent=parent_dir,
        project_name="Horsehead First Pass",
    )

    project_dir = project_file.parent
    copied_source = project_dir / "sources/source-01.tiff"
    assert project_file == project_dir / "project.yaml"
    assert copied_source.is_file()
    assert copied_source.read_bytes() == source_path.read_bytes()
    assert inspect_image(copied_source).format == "TIFF"

    payload = read_yaml_mapping(project_file)
    assert payload["project"]["name"] == "Horsehead First Pass"
    assert payload["sources"][0]["path"] == "sources/source-01.tiff"
    assert payload["rules"] == []
    assert [channel["id"] for channel in payload["semantic_channels"]] == [
        "combined",
        "nebula",
        "stars",
        "dark_dust",
        "background",
    ]
    assert (project_dir / "palettes/default-nebula.yaml").is_file()
    assert (project_dir / "render_profiles/screen-preview.yaml").is_file()
    assert (project_dir / "plugins/lock.yaml").is_file()
    palette_payload = read_yaml_mapping(project_dir / "palettes/default-nebula.yaml")
    colour_point_ids = [point["id"] for point in palette_payload["colour_points"]]
    assert colour_point_ids == [
        "nebula-blue",
        "star-blue",
        "nebula-red",
        "nebula-cyan",
        "nebula-green",
        "nebula-yellow",
    ]


def test_new_project_dialog_scaffolds_and_opens_project(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.tiff"
    _create_source_image(source_path)
    parent_dir = tmp_path / "library"
    parent_dir.mkdir()

    window = MainWindow()
    qtbot.addWidget(window)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source_path), "Images (*.tif *.tiff *.png *.jpg *.jpeg)"),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(parent_dir),
    )
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Lion Blue Pass", True),
    )

    window._new_project_from_image_dialog()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    created_project = parent_dir / "Lion Blue Pass"
    assert (created_project / "project.yaml").is_file()
    assert window.project_name_label.text() == "Lion Blue Pass"


def test_first_adjustment_switches_editor_from_region_to_adjustment(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.tiff"
    _create_source_image(source_path)
    parent_dir = tmp_path / "library"
    parent_dir.mkdir()
    project_file = scaffold_project_from_image(
        source_path=source_path,
        destination_parent=parent_dir,
        project_name="First Adjustment Test",
    )

    window = MainWindow(project_file.parent)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.editor_stack.currentIndex() == 1

    window.view_model.create_adjustment("red")

    assert window.view_model.selected_adjustment_id is not None
    assert window.editor_stack.currentIndex() == 0
    summary = window.view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.type_label == "Red"
    assert window.panel_heading.text() == "Adjustment: Red"


def test_right_inspector_uses_scrollable_adjustment_and_dark_dust_sections(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.right_scroll_area.widget() is not None
    assert window.adjustment_section.objectName() == "inspectorSection"
    assert window.dark_dust_group.objectName() == "inspectorSection"
    assert window.panel_heading.text().startswith("Adjustment: ")


def test_adjustment_helper_labels_use_shared_wrapped_layout(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.adjustment_helper_label.wordWrap() is True
    assert window.region_helper_label.wordWrap() is True
    assert window.region_reference_label.wordWrap() is True
    assert window.adjustment_helper_label.minimumWidth() == 0
    assert window.region_helper_label.minimumWidth() == 0


def test_dark_dust_panel_has_dedicated_reset_action(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.dark_dust_sensitivity_input.setValue(0.71)
    window.dark_dust_structure_size_input.setValue(0.13)
    window.dark_dust_background_protection_input.setValue(0.24)
    window.dark_dust_softness_input.setValue(0.29)

    window.reset_dark_dust_button.click()

    settings = window.view_model.dark_dust_settings()
    assert settings.sensitivity == 0.58
    assert settings.structure_size == 0.09
    assert settings.background_protection == 0.30
    assert settings.softness == 0.22
    assert settings.veil_strength == 0.62
    assert settings.core_strength == 0.70
    assert settings.veil_core_balance == 0.46


def test_dark_dust_panel_can_be_collapsed_and_expanded(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.dark_dust_title_label.text() == "Dark Dust Mask"
    assert window.dark_dust_toggle_button.isVisible() is True
    assert window.dark_dust_body.isVisible() is True
    assert window.dark_dust_toggle_button.text() == "▾"

    window.dark_dust_toggle_button.click()

    assert window.dark_dust_body.isVisible() is False
    assert window.dark_dust_toggle_button.text() == "▸"
    assert window.dark_dust_title_label.text() == "Dark Dust Mask"

    window.dark_dust_toggle_button.click()

    assert window.dark_dust_body.isVisible() is True
    assert window.dark_dust_toggle_button.text() == "▾"


def test_invalid_project_raises_readable_error(qtbot: Any, tmp_path: Path) -> None:
    _ = qtbot
    _ = tmp_path
    invalid_project = Path("tests/fixtures/invalid/missing-source")
    messages: list[tuple[str, str]] = []
    view_model = ProjectEditorViewModel()
    view_model.errorRaised.connect(lambda summary, details: messages.append((summary, details)))

    assert view_model.open_project(invalid_project) is False
    assert messages
    assert messages[0][0].startswith("This project could not be opened because")


def test_working_state_is_separate_from_saved_state(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    selected = view_model.selected_rule()
    assert selected is not None

    original_amount = selected.amount
    view_model.set_rule_amount(original_amount + 0.2)

    assert view_model.dirty is True
    updated_selected = view_model.selected_rule()
    assert updated_selected is not None
    assert updated_selected.amount == original_amount + 0.2
    saved_documents = view_model._saved_documents
    assert saved_documents is not None
    saved_rule = view_model._find_rule(saved_documents.bundle, selected.rule_id)
    assert saved_rule is not None
    assert isinstance(saved_rule.transform, ColourAmountTransform)
    assert saved_rule.transform.amount == original_amount


def test_open_project_renders_preview_once_on_load(monkeypatch: Any, tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    from engine.preview import render_preview_image as original_render

    calls = 0

    def tracking_render(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original_render(*args, **kwargs)

    monkeypatch.setattr(
        "nebula_desktop.viewmodels.project_editor.render_preview_image",
        tracking_render,
    )

    assert view_model.open_project(project_dir) is True
    assert calls == 1


def test_adjustment_summary_exposes_rule_specific_point_label(
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.select_adjustment("red")
    summary = view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.point_label == "Red Point"


def test_non_colour_adjustments_hide_point_controls(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.select_adjustment("brightness")
    summary = view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.point_label is None
    assert summary.supports_colour_point is False
    assert summary.colour_point_id is None


def test_adjustment_editor_updates_pick_button_label_for_selected_rule(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.select_adjustment("red")
    qtbot.waitUntil(lambda: window.pick_button.text() == "Pick Red Point", timeout=5000)

    assert window.colour_title_label.text() == "Red Point"
    assert window.pick_button.text() == "Pick Red Point"
    assert window.primary_input.suffix() == "%"
    assert window.primary_input.minimum() == -100.0
    assert window.primary_input.maximum() == 100.0
    assert window.primary_slider.minimum() == -100
    assert window.primary_slider.maximum() == 100


def test_overlay_dark_dust_reveals_edit_dark_dust_action(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.edit_dark_dust_button.isVisible() is False

    dark_dust_index = window.semantic_overlay_selector.findData("dark_dust")
    assert dark_dust_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(dark_dust_index)

    assert window.edit_dark_dust_button.isVisible() is True

    off_index = window.semantic_overlay_selector.findData("off")
    assert off_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(off_index)

    assert window.edit_dark_dust_button.isVisible() is False


def test_faux_hubble_adjustment_uses_nebula_target_and_palette_controls(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("faux_hubble")
    summary = view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.type_label == "Faux Hubble"
    assert summary.transform_type == "faux_palette"
    assert summary.target_id == "nebula"
    assert summary.primary_label == "Amount"
    assert summary.primary_value == 0.0
    assert summary.option_label == "Preserve Brightness"
    assert summary.option_enabled is True
    assert summary.supports_colour_point is False
    assert [(control.label, control.value) for control in summary.palette_balance_controls] == [
        ("Gold", 100.0),
        ("Green", 100.0),
        ("Cyan", 100.0),
    ]

    rule = view_model._selected_rule_model()
    assert rule is not None
    assert isinstance(rule.transform, FauxPaletteTransform)
    view_model.set_selected_adjustment_palette_balance("gold", 80.0)
    updated = view_model.selected_adjustment_summary()
    assert updated is not None
    assert updated.palette_balance_controls[0].value == 80.0
    view_model.reset_selected_adjustment_palette_balance(render=False)
    reset = view_model.selected_adjustment_summary()
    assert reset is not None
    assert all(control.value == 100.0 for control in reset.palette_balance_controls)
    view_model.duplicate_selected_adjustment()
    assert view_model._selected_rule_model() is not None
    view_model.set_selected_adjustment_enabled(False)
    disabled_rule = view_model._selected_rule_model()
    assert disabled_rule is not None
    assert disabled_rule.enabled is False
    view_model.reset_selected_adjustment()
    reset_rule = view_model._selected_rule_model()
    assert reset_rule is not None
    assert reset_rule.enabled is True


def test_additional_faux_palette_adjustments_use_shared_controls(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    expected: tuple[tuple[AdjustmentKind, str, tuple[str, ...]], ...] = (
        ("faux_hoo", "Faux HOO", ("Red", "Cyan")),
        ("foraxx", "Foraxx-Inspired", ("Amber", "Cyan")),
        ("gold_cyan", "Gold & Cyan", ("Gold", "Cyan")),
        ("natural_bicolour", "Natural Bi-colour", ("Warm", "Cool")),
    )
    for kind, label, controls in expected:
        view_model.create_adjustment(kind)
        summary = view_model.selected_adjustment_summary()
        assert summary is not None
        assert summary.type_label == label
        assert summary.transform_type == "faux_palette"
        assert summary.target_id == "nebula"
        assert tuple(control.label for control in summary.palette_balance_controls) == controls
        rule = view_model._selected_rule_model()
        assert rule is not None
        assert isinstance(rule.transform, FauxPaletteTransform)


def test_palette_balance_changes_defer_panel_refresh_until_slider_release(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    refreshes: list[int] = []
    window.view_model.adjustmentsChanged.connect(lambda: refreshes.append(1))

    scenarios: tuple[tuple[AdjustmentKind, str, str], ...] = (
        ("faux_hubble", "Faux Hubble", "gold"),
        ("faux_hoo", "Faux HOO", "red"),
        ("foraxx", "Foraxx-Inspired", "amber"),
        ("gold_cyan", "Gold & Cyan", "gold"),
        ("natural_bicolour", "Natural Bi-colour", "warm"),
    )

    for kind, label, control_key in scenarios:
        window.view_model.create_adjustment(kind)
        refreshes.clear()

        window.view_model.set_adjustment_interaction_active(True)
        window.view_model.set_selected_adjustment_palette_balance(control_key, 80.0, render=False)
        window.view_model.set_selected_adjustment_palette_balance(control_key, 60.0, render=False)

        assert refreshes == []

        window.view_model.set_adjustment_interaction_active(False)

        assert len(refreshes) == 1
        summary = window.view_model.selected_adjustment_summary()
        assert summary is not None
        assert summary.type_label == label
        assert summary.palette_balance_controls[0].value == 60.0


def test_desktop_export_matches_direct_renderer_for_faux_hubble(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    project_path = project_dir / "project.yaml"
    payload = read_yaml_mapping(project_path)
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
        {
            "id": "faux-hubble",
            "name": "Faux Hubble",
            "enabled": True,
            "selection_source": "current",
            "target": "nebula",
            "match": {"softness": 0.5},
            "transform": {
                "type": "faux_palette",
                "palette": "hubble",
                "amount": 0.6,
                "preserve_brightness": True,
            },
        }
    )
    project_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    native = view_model.native_render_dimensions()
    assert native is not None
    profile = view_model.build_screen_export_profile(
        output_format="png",
        width_px=native[0],
        interpolation="nearest",
    )
    desktop_path = tmp_path / "desktop-export.png"
    direct_path = tmp_path / "direct-export.png"
    view_model.export_render(
        output_path=desktop_path,
        profile_id="screen-export",
        profile=profile,
        force=True,
    )
    assert view_model._working_documents is not None
    render_bundle_output(
        view_model._working_documents.bundle.model_copy(deep=True),
        profile_id="screen-export",
        profile=profile,
        output_path=direct_path,
        force=True,
    )

    desktop_image = load_canonical_image(desktop_path).data
    direct_image = load_canonical_image(direct_path).data
    assert np.allclose(desktop_image, direct_image)


def test_adjustment_list_labels_use_target_and_omit_duplicate_type_text(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    first_label = window.adjustments_list.item(0).text()
    assert "Entire image" not in first_label
    assert "Reveal faint blue glow • Nebula" in first_label

    window.view_model.create_adjustment("cyan")
    qtbot.waitUntil(lambda: window.adjustments_list.count() > 0, timeout=5000)
    labels = [
        window.adjustments_list.item(index).text()
        for index in range(window.adjustments_list.count())
    ]
    assert any("Cyan • Combined Image" in label for label in labels)
    assert all("Cyan • Cyan" not in label for label in labels)


def test_brightness_control_uses_linear_multiplier_mapping(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    project_payload = read_yaml_mapping(project_dir / "project.yaml")
    for rule in project_payload["rules"]:
        if rule["id"] == "brightness":
            rule["transform"]["amount"] = 1.12
            break
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(project_payload, sort_keys=False),
        encoding="utf-8",
    )
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.select_adjustment("brightness")
    summary = window.view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.transform_type == "brightness"
    assert abs(_brightness_amount_to_ui(summary.primary_value or 0.0) - 12.0) <= 1.0

    window._on_primary_value_changed(100.0)

    updated = window.view_model.selected_adjustment_summary()
    assert updated is not None
    assert updated.primary_value is not None
    assert updated.primary_value >= 1.99


def test_adjustment_editor_shows_semantic_target_selector(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert window.target_selector.count() == 4
    assert window.target_selector.itemText(0) == "Combined Image"
    assert window.target_selector.itemText(1) == "Nebula"
    assert window.target_selector.itemText(2) == "Stars"
    assert window.target_selector.itemText(3) == "Dark Dust"


def test_semantic_overlay_mode_exposes_star_mask_from_current_image(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    assert view_model.current_semantic_overlay() is None

    view_model.set_semantic_overlay_mode("stars")
    overlay = view_model.current_semantic_overlay()
    display_image = view_model.current_display_image()

    assert overlay is not None
    assert display_image is not None
    assert overlay.mode == "stars"
    assert overlay.mask.shape == (
        display_image.height,
        display_image.width,
    )
    assert np.isfinite(overlay.mask).all()

    view_model.set_semantic_overlay_mode("nebula")
    nebula_overlay = view_model.current_semantic_overlay()
    assert nebula_overlay is not None
    assert nebula_overlay.mode == "nebula"
    assert nebula_overlay.mask.shape == overlay.mask.shape

    view_model.set_semantic_overlay_mode("dark_dust")
    dark_dust_overlay = view_model.current_semantic_overlay()
    overlay_image = view_model._semantic_overlay_source_image()
    assert dark_dust_overlay is not None
    assert overlay_image is not None
    assert dark_dust_overlay.mode == "dark_dust"
    expected_mask = semantic_target_influence(
        overlay_image.data,
        "dark_dust",
        view_model.dark_dust_settings(),
    )
    assert np.allclose(dark_dust_overlay.mask, expected_mask)


def test_semantic_overlay_selector_updates_preview_overlay(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    stars_index = window.semantic_overlay_selector.findData("stars")
    assert stars_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(stars_index)

    qtbot.waitUntil(
        lambda: window.preview_widget.semantic_overlay() is not None,
        timeout=5000,
    )
    overlay = window.preview_widget.semantic_overlay()
    assert overlay is not None
    assert overlay.mode == "stars"
    assert window.view_model.semantic_overlay_mode == "stars"

    off_index = window.semantic_overlay_selector.findData("off")
    assert off_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(off_index)
    qtbot.waitUntil(lambda: window.preview_widget.semantic_overlay() is None, timeout=5000)

    dark_dust_index = window.semantic_overlay_selector.findData("dark_dust")
    assert dark_dust_index >= 0


def test_semantic_overlay_is_a_transparent_tint_not_a_replacement_image() -> None:
    mask = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
    rgba = semantic_overlay_rgba(mask, "nebula")

    assert rgba.shape == (2, 2, 4)
    assert int(rgba[0, 0, 3]) >= 150
    assert tuple(int(channel) for channel in rgba[0, 0, :3]) == (0, 0, 0)
    assert 0 < int(rgba[0, 1, 3]) < 255
    assert 0 < int(rgba[1, 0, 3]) < 255


def test_dark_dust_settings_are_saved_and_loaded(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.dark_dust_enabled_checkbox.setChecked(True)
    window.dark_dust_sensitivity_input.setValue(0.71)
    window.dark_dust_structure_size_input.setValue(0.13)
    window.dark_dust_background_protection_input.setValue(0.24)
    window.dark_dust_softness_input.setValue(0.29)
    window.dark_dust_veil_strength_input.setValue(0.67)
    window.dark_dust_core_strength_input.setValue(0.74)
    window.dark_dust_veil_core_balance_input.setValue(0.51)
    window.view_model.save_changes()

    payload = read_yaml_mapping(project_dir / "project.yaml")
    assert payload["dark_dust"] == {
        "enabled": True,
        "sensitivity": 0.71,
        "structure_size": 0.13,
        "background_protection": 0.24,
        "softness": 0.29,
        "veil_strength": 0.67,
        "core_strength": 0.74,
        "veil_core_balance": 0.51,
    }

    reopened = ProjectEditorViewModel()
    assert reopened.open_project(project_dir) is True
    settings = reopened.dark_dust_settings()
    assert settings.sensitivity == 0.71
    assert settings.structure_size == 0.13
    assert settings.background_protection == 0.24
    assert settings.softness == 0.29
    assert settings.veil_strength == 0.67
    assert settings.core_strength == 0.74
    assert settings.veil_core_balance == 0.51


def test_dark_dust_overlay_views_match_internal_analysis_and_show_coverage(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    dark_dust_index = window.semantic_overlay_selector.findData("dark_dust")
    assert dark_dust_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(dark_dust_index)
    qtbot.waitUntil(lambda: window.preview_widget.semantic_overlay() is not None, timeout=5000)

    overlay_image = window.view_model._semantic_overlay_source_image()
    assert overlay_image is not None
    analysis = analyze_dark_dust(overlay_image.data, window.view_model.dark_dust_settings())

    final_overlay = window.preview_widget.semantic_overlay()
    assert final_overlay is not None
    np.testing.assert_allclose(final_overlay.mask, analysis.final_mask)
    assert window.dark_dust_coverage_label.text().startswith("Dark Dust Coverage: ")

    for view_name, expected in (
        ("Veil Mask", analysis.veil_mask),
        ("Core Mask", analysis.core_mask),
        ("Relative Darkness", analysis.relative_darkness),
        ("Local Illumination", analysis.local_illumination),
        ("Background Support", analysis.background_support),
    ):
        index = window.dark_dust_view_selector.findText(view_name)
        assert index >= 0
        window.dark_dust_view_selector.setCurrentIndex(index)
        overlay = window.preview_widget.semantic_overlay()
        assert overlay is not None
        np.testing.assert_allclose(overlay.mask, expected)


def test_dark_dust_overlay_mask_only_and_solo_mode_update_display_mode(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    dark_dust_index = window.semantic_overlay_selector.findData("dark_dust")
    assert dark_dust_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(dark_dust_index)
    qtbot.waitUntil(lambda: window.preview_widget.semantic_overlay() is not None, timeout=5000)

    mask_only_index = window.dark_dust_display_selector.findText("Mask Only")
    assert mask_only_index >= 0
    window.dark_dust_display_selector.setCurrentIndex(mask_only_index)
    overlay = window.preview_widget.semantic_overlay()
    assert overlay is not None
    assert overlay.display_mode == "mask"

    overlay_index = window.dark_dust_display_selector.findText("Overlay on Image")
    assert overlay_index >= 0
    window.dark_dust_display_selector.setCurrentIndex(overlay_index)
    window.dark_dust_solo_button.click()
    solo_overlay = window.preview_widget.semantic_overlay()
    assert solo_overlay is not None
    assert solo_overlay.display_mode == "mask"


def test_dark_nebula_processing_adjustment_defaults_and_controls(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.create_adjustment("dark_nebula_processing")
    summary = window.view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.type_label == "Dark Nebula Processing"
    assert summary.target_id == "dark_dust"
    assert summary.primary_label == "Amount"
    assert summary.option_label == "Preserve Bright Areas"
    assert [control.label for control in summary.extra_numeric_controls] == [
        "Reveal Dust",
        "Dust Contrast",
        "Core Depth",
        "Dust Colour",
        "Softness",
    ]
    assert window.extra_adjustment_controls_section.isVisible() is True
    assert window.extra_adjustment_controls_layout.count() == 10


def test_desktop_export_matches_direct_renderer_for_dark_nebula_processing(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    project_path = project_dir / "project.yaml"
    payload = read_yaml_mapping(project_path)
    rules = payload["rules"]
    assert isinstance(rules, list)
    rules.append(
        {
            "id": "dark-nebula",
            "name": "Dark Nebula Processing",
            "enabled": True,
            "selection_source": "current",
            "target": "dark_dust",
            "match": {"softness": 0.5},
            "transform": {
                "type": "dark_nebula_processing",
                "amount": 0.65,
                "reveal_dust": 0.60,
                "dust_contrast": 0.45,
                "core_depth": 0.70,
                "dust_colour": 0.20,
                "softness": 0.25,
                "preserve_bright_areas": True,
            },
        }
    )
    project_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    native = view_model.native_render_dimensions()
    assert native is not None
    profile = view_model.build_screen_export_profile(
        output_format="png",
        width_px=native[0],
        interpolation="nearest",
    )
    desktop_path = tmp_path / "desktop-dark-nebula.png"
    direct_path = tmp_path / "direct-dark-nebula.png"
    view_model.export_render(
        output_path=desktop_path,
        profile_id="screen-export",
        profile=profile,
        force=True,
    )
    assert view_model._working_documents is not None
    render_bundle_output(
        view_model._working_documents.bundle.model_copy(deep=True),
        profile_id="screen-export",
        profile=profile,
        output_path=direct_path,
        force=True,
    )

    desktop_image = load_canonical_image(desktop_path).data
    direct_image = load_canonical_image(direct_path).data
    assert np.allclose(desktop_image, direct_image)


def test_nebula_overlay_fill_alpha_stays_subtle_inside_large_selected_area() -> None:
    mask = np.ones((6, 6), dtype=np.float32)
    rgba = semantic_overlay_rgba(mask, "nebula")

    # Interior pixels should remain lightly tinted rather than washing the preview.
    assert int(rgba[3, 3, 3]) <= 20


def test_nebula_overlay_suppresses_star_like_non_target_pixels() -> None:
    mask = np.ones((7, 7), dtype=np.float32)
    mask[3, 3] = 0.0
    rgba = semantic_overlay_rgba(mask, "nebula")

    assert tuple(int(channel) for channel in rgba[3, 3, :3]) == (0, 0, 0)
    assert int(rgba[3, 3, 3]) >= 150
    assert int(rgba[2, 2, 3]) < int(rgba[3, 3, 3])


def test_brightness_adjustment_does_not_break_semantic_overlay(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    _write_star_nebula_tiff(project_dir / "sources/source-01.tif")
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    from engine.preview import render_preview_image

    def immediate_render(*, immediate: bool = False) -> None:
        _ = immediate
        working_documents = view_model._working_documents
        assert working_documents is not None
        view_model._active_job_id += 1
        view_model.apply_preview_result(
            view_model._active_job_id,
            render_preview_image(
                working_documents.bundle.model_copy(deep=True),
                include_provenance=False,
                use_cached_sources=True,
            ),
        )

    monkeypatch.setattr(view_model, "request_preview_render", immediate_render)

    view_model.set_semantic_overlay_mode("stars")
    before = view_model.current_semantic_overlay()
    assert before is not None

    view_model.select_adjustment("brightness")
    view_model.set_selected_adjustment_primary_value(1.4)

    after = view_model.current_semantic_overlay()
    assert after is not None
    np.testing.assert_allclose(after.mask, before.mask, atol=1e-6)


def test_overlay_off_clears_immediately_and_stays_cleared_after_brightness_rerender(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    _write_star_nebula_tiff(project_dir / "sources/source-01.tif")
    project_payload = read_yaml_mapping(project_dir / "project.yaml")
    for rule in project_payload["rules"]:
        if rule["id"] == "brightness":
            rule["transform"]["amount"] = 1.12
            break
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump(project_payload, sort_keys=False),
        encoding="utf-8",
    )
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    from engine.preview import render_preview_image

    def immediate_render(*, immediate: bool = False) -> None:
        _ = immediate
        working_documents = window.view_model._working_documents
        assert working_documents is not None
        window.view_model._active_job_id += 1
        window.view_model.apply_preview_result(
            window.view_model._active_job_id,
            render_preview_image(
                working_documents.bundle.model_copy(deep=True),
                include_provenance=False,
                use_cached_sources=True,
            ),
        )

    monkeypatch.setattr(window.view_model, "request_preview_render", immediate_render)

    stars_index = window.semantic_overlay_selector.findData("stars")
    assert stars_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(stars_index)
    qtbot.waitUntil(lambda: window.preview_widget.semantic_overlay() is not None, timeout=5000)

    off_index = window.semantic_overlay_selector.findData("off")
    assert off_index >= 0
    window.semantic_overlay_selector.setCurrentIndex(off_index)
    assert window.preview_widget.semantic_overlay() is None

    window.view_model.select_adjustment("brightness")
    before = window.view_model.current_display_image()
    assert before is not None
    before_data = before.data.copy()

    window._on_primary_value_changed(100.0)

    qtbot.waitUntil(
        lambda: (
            (after := window.view_model.current_display_image()) is not None
            and not np.allclose(before_data, after.data, atol=1e-6)
        ),
        timeout=1000,
    )
    after = window.view_model.current_display_image()
    assert after is not None
    assert window.preview_widget.semantic_overlay() is None
    assert not np.allclose(before_data, after.data, atol=1e-6)


def test_adjustment_target_selector_updates_selected_rule(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    index = window.target_selector.findData("stars")
    assert index >= 0
    window.target_selector.setCurrentIndex(index)

    def _selected_target_is_stars() -> bool:
        summary = window.view_model.selected_adjustment_summary()
        return summary is not None and summary.target_id == "stars"

    qtbot.waitUntil(
        _selected_target_is_stars,
        timeout=5000,
    )
    summary = window.view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.target_label == "Stars"


def test_adjustment_editor_hides_colour_controls_for_non_colour_adjustments(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.select_adjustment("brightness")
    qtbot.waitUntil(lambda: not window.colour_title_label.isVisible(), timeout=5000)

    assert window.colour_title_label.isHidden()
    assert window.colour_point_label.isHidden()
    assert window.colour_swatch.isHidden()
    assert window.pick_button.isEnabled() is False


def test_disabled_rule_remains_declared_and_revert_restores_saved_state(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    selected = view_model.selected_rule()
    assert selected is not None

    view_model.set_rule_enabled(False)
    working_documents = view_model._working_documents
    assert working_documents is not None
    disabled_rule = view_model._find_rule(working_documents.bundle, selected.rule_id)
    assert disabled_rule is not None
    assert disabled_rule.enabled is False

    view_model.revert_unsaved_changes()
    reverted_documents = view_model._working_documents
    assert reverted_documents is not None
    reverted_rule = view_model._find_rule(reverted_documents.bundle, selected.rule_id)
    assert reverted_rule is not None
    assert reverted_rule.enabled is True


def test_sampling_maps_widget_coordinates_to_underlying_image() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    widget = ImagePreviewWidget()
    widget.resize(400, 300)
    project_dir = Path("examples/valid/minimal-project")
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    image = view_model._source_image
    assert image is not None
    widget.set_image(image)
    coordinates = widget.map_widget_to_image(QPointF(widget.width() / 2.0, widget.height() / 2.0))
    assert coordinates is not None
    x, y = coordinates
    assert 0 <= x < image.width
    assert 0 <= y < image.height


def test_sampling_ignores_clicks_outside_letterboxed_image() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    widget = ImagePreviewWidget()
    widget.resize(500, 300)
    project_dir = Path("examples/valid/minimal-project")
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    image = view_model._source_image
    assert image is not None
    widget.set_image(image)
    assert widget.sample_at_widget_position(QPointF(10.0, 10.0)) is None


def test_sampling_maps_correctly_when_zoomed_and_panned() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    widget = ImagePreviewWidget()
    widget.resize(400, 300)
    project_dir = Path("examples/valid/minimal-project")
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    image = view_model._source_image
    assert image is not None
    widget.set_image(image)
    widget.actual_size()
    widget.zoom_in()
    widget.zoom_in()
    widget._pan = QPointF(30.0, -20.0)
    point = widget.map_normalized_to_widget((0.5, 0.5))
    assert point is not None
    sample = widget.sample_at_widget_position(point)
    assert sample is not None
    assert abs(sample.x - image.width // 2) <= 1
    assert abs(sample.y - image.height // 2) <= 1


def test_sampling_uses_fractional_widget_positions() -> None:
    app = QApplication.instance() or QApplication([])
    _ = app
    widget = ImagePreviewWidget()
    widget.resize(401, 301)
    project_dir = Path("examples/valid/minimal-project")
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    image = view_model._source_image
    assert image is not None
    widget.set_image(image)
    sample = widget.sample_at_widget_position(QPointF(200.5, 150.5))
    assert sample is not None
    assert 0 <= sample.x < image.width
    assert 0 <= sample.y < image.height


def test_stale_preview_results_do_not_overwrite_newer_results(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    first = view_model._saved_preview
    assert first is not None
    second = view_model._current_preview
    assert second is not None

    view_model._active_job_id = 4
    assert view_model.apply_preview_result(3, first) is False
    assert view_model.apply_preview_result(4, second) is True


def test_preview_requests_coalesce_while_render_is_in_flight(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    started_job_ids: list[int] = []

    def start_worker(worker: Any) -> None:
        started_job_ids.append(worker.job_id)

    monkeypatch.setattr(view_model._thread_pool, "start", start_worker)

    view_model.request_preview_render(immediate=True)
    assert started_job_ids == [1]
    assert view_model._preview_render_in_flight is True

    view_model.request_preview_render(immediate=True)
    assert started_job_ids == [1]
    assert view_model._pending_preview_render is True

    preview = view_model._current_preview
    assert preview is not None
    assert view_model.apply_preview_result(1, preview) is True

    assert started_job_ids == [1, 2]
    assert view_model._preview_render_in_flight is True
    assert view_model._pending_preview_render is False


def test_save_changes_does_not_force_foreground_preview_render(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    selected = view_model.selected_rule()
    assert selected is not None
    view_model.set_rule_amount(selected.amount + 0.1)

    def fail_render(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("save_changes should not force a preview render")

    monkeypatch.setattr(
        "nebula_desktop.viewmodels.project_editor.render_preview_image",
        fail_render,
    )

    assert view_model.save_changes() is True


def test_primary_adjustment_input_updates_without_immediate_render(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    recorded: list[tuple[float, bool]] = []

    def record_primary(value: float, *, render: bool = True) -> None:
        recorded.append((value, render))

    monkeypatch.setattr(window.view_model, "set_selected_adjustment_primary_value", record_primary)

    window._on_primary_value_changed(20.0)

    assert recorded
    assert recorded[-1][1] is False


def test_secondary_slider_defers_render_until_release(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.create_adjustment("smoothness")
    created_id = window.view_model.selected_adjustment_id
    assert created_id is not None
    window.view_model.select_adjustment(created_id)

    recorded_secondary: list[tuple[float, bool]] = []
    render_requests: list[bool] = []

    def record_secondary(value: float, *, render: bool = True) -> None:
        recorded_secondary.append((value, render))

    def record_render(*, immediate: bool = False) -> None:
        render_requests.append(immediate)

    monkeypatch.setattr(
        window.view_model,
        "set_selected_adjustment_secondary_value",
        record_secondary,
    )
    monkeypatch.setattr(window.view_model, "request_preview_render", record_render)

    window._on_adjustment_slider_pressed()
    assert window.view_model.is_adjustment_interacting is True

    window._on_secondary_value_changed(55)
    assert recorded_secondary[-1] == (0.55, False)
    assert render_requests == []

    window._on_adjustment_slider_released()
    assert window.view_model.is_adjustment_interacting is False
    assert render_requests == [False]


def test_primary_slider_defers_render_until_release(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    recorded_primary: list[tuple[float, bool]] = []
    render_requests: list[bool] = []

    def record_primary(value: float, *, render: bool = True) -> None:
        recorded_primary.append((value, render))

    def record_render(*, immediate: bool = False) -> None:
        render_requests.append(immediate)

    monkeypatch.setattr(
        window.view_model,
        "set_selected_adjustment_primary_value",
        record_primary,
    )
    monkeypatch.setattr(window.view_model, "request_preview_render", record_render)

    window._on_adjustment_slider_pressed()
    assert window.view_model.is_adjustment_interacting is True

    window._on_primary_slider_value_changed(60)
    assert recorded_primary[-1] == (1.6, False)
    assert render_requests == []

    window._on_adjustment_slider_released()
    assert window.view_model.is_adjustment_interacting is False
    assert render_requests == [False]


def test_numeric_adjustment_render_is_debounced(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    render_requests: list[bool] = []

    def record_render(*, immediate: bool = False) -> None:
        render_requests.append(immediate)

    monkeypatch.setattr(window.view_model, "request_preview_render", record_render)

    window._schedule_adjustment_render()
    window._schedule_adjustment_render()
    window._schedule_adjustment_render()

    qtbot.waitUntil(lambda: len(render_requests) == 1, timeout=1000)
    assert render_requests == [False]


def test_create_adjustment_selection_mode_can_be_cancelled(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.create_from_selection_button.click()
    assert window.view_model.sampling_purpose == "create_adjustment"
    assert window.cancel_selection_button.isVisible() is True

    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    window.preview_widget.keyPressEvent(event)

    assert window.view_model.is_sampling is False
    assert window.view_model.dirty is False


def test_create_adjustment_from_selection_uses_preview_and_source_display_state(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    center = QPointF(window.preview_widget.width() / 2.0, window.preview_widget.height() / 2.0)
    window._show_preview()
    preview_sample = window.preview_widget.sample_at_widget_position(center)
    assert preview_sample is not None
    window._show_source()
    source_sample = window.preview_widget.sample_at_widget_position(center)
    assert source_sample is not None
    assert preview_sample.rgb != source_sample.rgb

    monkeypatch.setattr(window, "_choose_adjustment_kind_from_sample", lambda sample: "blue")
    window.create_from_selection_button.click()
    window._apply_sample(preview_sample)

    summary = window.view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.name == "Selected Blue"
    assert summary.rule_id == window.view_model.selected_adjustment_id


def test_create_adjustment_from_selection_can_create_each_supported_type(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    sample = _preview_sample(view_model)

    kinds: tuple[AdjustmentKind, ...] = (
        "blue",
        "red",
        "green",
        "cyan",
        "yellow",
        "brightness",
        "saturation",
        "smoothness",
    )
    created_ids = [
        view_model.create_adjustment_from_selection(kind, sample)
        for kind in kinds
    ]
    assert all(rule_id is not None for rule_id in created_ids)

    working_documents = view_model._working_documents
    assert working_documents is not None
    rules = working_documents.bundle.project.rules
    assert [rule.id for rule in rules][-8:] == [
        rule_id for rule_id in created_ids if rule_id is not None
    ]
    cyan_rule = view_model._find_rule(working_documents.bundle, created_ids[3] or "")
    assert cyan_rule is not None
    assert isinstance(cyan_rule.transform, ShiftColourPointTransform)
    saturation_rule = view_model._find_rule(working_documents.bundle, created_ids[6] or "")
    assert saturation_rule is not None
    assert isinstance(saturation_rule.transform, SaturationTransform)


def test_selected_colour_adjustments_copy_sampled_colour_into_new_point(
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    sample = ImageSample(x=0, y=0, rgb=(0.12, 0.23, 0.34))

    for kind in cast(tuple[AdjustmentKind, ...], ("blue", "red", "green", "cyan", "yellow")):
        rule_id = view_model.create_adjustment_from_selection(kind, sample)
        assert rule_id is not None
        working_documents = view_model._working_documents
        assert working_documents is not None
        rule = view_model._find_rule(working_documents.bundle, rule_id)
        assert rule is not None
        assert rule.match.colour_point is not None
        colour_point = view_model._find_colour_point(
            working_documents.bundle,
            rule.match.colour_point,
        )
        assert colour_point is not None
        if kind == "red":
            assert colour_point.value.channels[0] >= colour_point.value.channels[1]
            assert colour_point.value.channels[0] >= colour_point.value.channels[2]
        elif kind == "green":
            assert colour_point.value.channels[1] >= colour_point.value.channels[0]
            assert colour_point.value.channels[1] >= colour_point.value.channels[2]
        elif kind in {"blue", "cyan"}:
            assert colour_point.value.channels[2] >= colour_point.value.channels[0]
            assert colour_point.value.channels[2] >= colour_point.value.channels[1]
        elif kind == "yellow":
            assert colour_point.value.channels[0] >= colour_point.value.channels[2]
            assert colour_point.value.channels[1] >= colour_point.value.channels[2]
        if kind in {"cyan", "yellow"}:
            assert isinstance(rule.transform, ShiftColourPointTransform)
            assert rule.transform.target_colour_point == {
                "cyan": "nebula-cyan",
                "yellow": "nebula-yellow",
            }[kind]


def test_selected_adjustment_names_are_unique_and_appended_at_end(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    sample = _preview_sample(view_model)

    first = view_model.create_adjustment_from_selection("blue", sample)
    second = view_model.create_adjustment_from_selection("blue", sample)
    assert first is not None and second is not None

    working_documents = view_model._working_documents
    assert working_documents is not None
    assert working_documents.bundle.project.rules[-2].name == "Selected Blue"
    assert working_documents.bundle.project.rules[-1].name == "Selected Blue 2"


def test_created_adjustment_appears_in_semantic_changes_and_can_be_reverted(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    sample = _preview_sample(view_model)

    created_id = view_model.create_adjustment_from_selection("red", sample)
    assert created_id is not None
    changes = view_model.unsaved_changes()
    assert any("Selected Red" in change.summary for change in changes)
    rule_change = next(
        change
        for change in changes
        if change.entity_type == "rule" and change.entity_id == created_id
    )

    view_model.revert_change(rule_change.key)

    working_documents = view_model._working_documents
    assert working_documents is not None
    assert view_model._find_rule(working_documents.bundle, created_id) is None
    assert view_model.unsaved_changes() == []


def test_marker_is_cleared_after_creation_or_cancellation(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)
    sample = ImageSample(x=1, y=1, rgb=(0.1, 0.2, 0.3))

    monkeypatch.setattr(window, "_choose_adjustment_kind_from_sample", lambda sample: None)
    window.create_from_selection_button.click()
    window._apply_sample(sample)
    assert window.preview_widget.sample_marker() is None

    monkeypatch.setattr(window, "_choose_adjustment_kind_from_sample", lambda sample: "blue")
    window.create_from_selection_button.click()
    window._apply_sample(sample)
    assert window.preview_widget.sample_marker() is None


def test_existing_pick_point_behaviour_still_updates_selected_colour_point(
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    view_model.select_adjustment("red")
    summary = view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.colour_point_id is not None

    view_model.begin_sampling()
    view_model.apply_image_sample(ImageSample(x=0, y=0, rgb=(0.2, 0.3, 0.4)))
    working_documents = view_model._working_documents
    assert working_documents is not None
    colour_point = view_model._find_colour_point(working_documents.bundle, summary.colour_point_id)
    assert colour_point is not None
    red, green, blue = colour_point.value.channels
    assert red >= green
    assert red >= blue


def test_colour_point_sampling_requests_deferred_preview_render(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    view_model.select_adjustment("red")
    view_model.begin_sampling()

    render_requests: list[bool] = []

    def record_render(*, immediate: bool = False) -> None:
        render_requests.append(immediate)

    monkeypatch.setattr(view_model, "request_preview_render", record_render)

    view_model.apply_image_sample(ImageSample(x=0, y=0, rgb=(0.7, 0.1, 0.1)))

    assert view_model.is_sampling is False
    assert render_requests == [False]


def test_colour_point_sampling_retargets_brightness_window(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    view_model.select_adjustment("red")

    view_model.begin_sampling()
    view_model.apply_image_sample(ImageSample(x=0, y=0, rgb=(0.7, 0.1, 0.1)))

    working_documents = view_model._working_documents
    assert working_documents is not None
    red_rule = view_model._find_rule(working_documents.bundle, "red")
    assert red_rule is not None
    assert red_rule.match.brightness is not None
    assert 0.0 <= red_rule.match.brightness.min < red_rule.match.brightness.max <= 1.0
    assert red_rule.match.brightness.max - red_rule.match.brightness.min <= 0.24 + 1e-6
    assert red_rule.match.saturation is not None
    assert red_rule.match.saturation.min >= 0.18


def test_window_open_project_uses_async_preview_render(
    monkeypatch: Any,
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    calls: list[bool] = []
    original_open = ProjectEditorViewModel.open_project

    def tracking_open(
        self: ProjectEditorViewModel,
        project_path: Path,
        *,
        async_preview: bool = False,
    ) -> bool:
        calls.append(async_preview)
        return original_open(self, project_path, async_preview=async_preview)

    monkeypatch.setattr(ProjectEditorViewModel, "open_project", tracking_open)

    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    assert calls == [True]


def test_colour_adjustment_amount_can_reduce_below_neutral(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    view_model.select_adjustment("red")

    view_model.set_selected_adjustment_primary_value(0.4)

    working_documents = view_model._working_documents
    assert working_documents is not None
    red_rule = view_model._find_rule(working_documents.bundle, "red")
    assert red_rule is not None
    assert isinstance(red_rule.transform, ColourAmountTransform)
    assert red_rule.transform.amount == 0.4


def test_unsupported_rules_survive_save_and_source_bytes_remain_unchanged(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    project_path = project_dir / "project.yaml"
    payload = read_yaml_mapping(project_path)
    rules = payload["rules"]
    rules.append(
        {
            "id": "soften-blue-colour",
            "name": "Smooth blue glow",
            "enabled": True,
            "selection_source": "current",
            "target": "nebula",
                "match": {"colour_point": "nebula-blue", "colour_range": 0.15, "softness": 0.5},
            "transform": {"type": "colour_smoothing", "radius": 0.006, "strength": 0.2},
        }
    )
    project_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    source_hash_before = _sha256(project_dir / "sources/source-01.tif")

    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    selected = view_model.selected_rule()
    assert selected is not None
    view_model.set_rule_amount(selected.amount + 0.1)
    assert view_model.save_changes() is True

    refreshed = read_yaml_mapping(project_path)
    refreshed_rules = refreshed["rules"]
    assert any(rule["id"] == "soften-blue-colour" for rule in refreshed_rules)
    assert _sha256(project_dir / "sources/source-01.tif") == source_hash_before


def test_save_persists_metadata_and_no_generated_state_is_written(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    selected = view_model.selected_rule()
    assert selected is not None
    view_model.set_rule_amount(1.42)
    view_model.set_rule_enabled(False)
    assert view_model.snapshot_contains_generated_state() is False
    assert view_model.save_changes() is True

    project_payload = read_yaml_mapping(project_dir / "project.yaml")
    saved_rule = next(rule for rule in project_payload["rules"] if rule["id"] == selected.rule_id)
    assert saved_rule["enabled"] is False
    assert abs(float(saved_rule["transform"]["amount"]) - 1.42) < 1e-6

    palette_path = project_dir / "palettes/default-nebula.yaml"
    palette_payload = read_yaml_mapping(palette_path)
    assert "generated" not in str(project_payload)
    assert "previews" not in str(palette_payload)


def test_adjustments_follow_declaration_order_and_reorder_persists(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    _append_rule(
        project_dir,
        {
            "id": "lift-brightness",
            "name": "Lift brightness",
            "enabled": True,
            "selection_source": "current",
            "target": "nebula",
            "match": {"colour_point": "nebula-blue", "colour_range": 0.2, "softness": 0.5},
            "transform": {"type": "brightness", "amount": 1.1},
        },
    )
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    initial_ids = [summary.rule_id for summary in view_model.adjustment_summaries()]
    assert initial_ids[-1] == "lift-brightness"
    assert "reveal-faint-blue" in initial_ids

    view_model.select_adjustment("lift-brightness")
    for _ in range(len(initial_ids) - 1):
        view_model.move_selected_adjustment("earlier")

    reordered_ids = [summary.rule_id for summary in view_model.adjustment_summaries()]
    assert reordered_ids[0] == "lift-brightness"
    assert any("now runs before" in change.summary for change in view_model.unsaved_changes())

    assert view_model.save_changes() is True
    saved_ids = [rule["id"] for rule in read_yaml_mapping(project_dir / "project.yaml")["rules"]]
    assert saved_ids[0] == "lift-brightness"


def test_add_remove_and_duplicate_adjustments_leave_others_active(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    original_ids = [summary.rule_id for summary in view_model.adjustment_summaries()]
    view_model.create_adjustment("brightness")
    added_ids = [summary.rule_id for summary in view_model.adjustment_summaries()]
    assert len(added_ids) == len(original_ids) + 1
    new_rule_id = next(rule_id for rule_id in added_ids if rule_id not in original_ids)

    view_model.duplicate_selected_adjustment()
    duplicated_ids = [summary.rule_id for summary in view_model.adjustment_summaries()]
    assert len(duplicated_ids) == len(original_ids) + 2

    view_model.select_adjustment("soften-blue-glow")
    view_model.remove_selected_adjustment()
    remaining_ids = [summary.rule_id for summary in view_model.adjustment_summaries()]
    assert "soften-blue-glow" not in remaining_ids
    assert "reveal-faint-blue" in remaining_ids
    assert any(rule_id.startswith(new_rule_id) for rule_id in remaining_ids)


def test_new_blue_and_red_adjustments_create_image_derived_colour_points(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("blue")
    blue_rule = view_model._selected_rule_model()
    assert blue_rule is not None
    assert blue_rule.match.colour_point is not None
    assert blue_rule.match.colour_point != "nebula-blue"
    assert blue_rule.target == "combined"
    assert isinstance(blue_rule.transform, ColourAmountTransform)
    assert blue_rule.transform.amount == 1.0

    view_model.create_adjustment("red")
    red_rule = view_model._selected_rule_model()
    assert red_rule is not None
    assert red_rule.match.colour_point is not None
    assert red_rule.match.colour_point != "nebula-red"
    assert red_rule.target == "combined"
    assert isinstance(red_rule.transform, ColourAmountTransform)
    assert red_rule.transform.amount == 1.0


def test_new_green_cyan_and_yellow_adjustments_create_image_derived_points(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("green")
    green_rule = view_model._selected_rule_model()
    assert green_rule is not None
    assert green_rule.match.colour_point is not None
    assert green_rule.match.colour_point != "nebula-green"
    assert isinstance(green_rule.transform, ColourAmountTransform)
    assert green_rule.transform.channel == "green"
    assert green_rule.transform.amount == 1.0

    view_model.create_adjustment("cyan")
    cyan_rule = view_model._selected_rule_model()
    assert cyan_rule is not None
    assert cyan_rule.match.colour_point is not None
    assert cyan_rule.match.colour_point != "nebula-cyan"
    assert isinstance(cyan_rule.transform, ShiftColourPointTransform)
    assert cyan_rule.transform.target_colour_point == "nebula-cyan"
    assert cyan_rule.transform.amount == 0.0

    view_model.create_adjustment("yellow")
    yellow_rule = view_model._selected_rule_model()
    assert yellow_rule is not None
    assert yellow_rule.match.colour_point is not None
    assert yellow_rule.match.colour_point != "nebula-yellow"
    assert isinstance(yellow_rule.transform, ShiftColourPointTransform)
    assert yellow_rule.transform.target_colour_point == "nebula-yellow"
    assert yellow_rule.transform.amount == 0.0


def test_new_colour_adjustment_uses_current_image_average_for_family(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    view_model._source_image = CanonicalImage(
        data=np.asarray(
            [
                [[0.78, 0.18, 0.16], [0.72, 0.15, 0.14]],
                [[0.05, 0.05, 0.40], [0.0, 0.0, 0.0]],
            ],
            dtype=np.float32,
        ),
        width=2,
        height=2,
    )
    view_model._show_source = True

    view_model.create_adjustment("red")
    rule = view_model._selected_rule_model()
    working_documents = view_model._working_documents

    assert rule is not None
    assert working_documents is not None
    assert rule.match.colour_point is not None
    assert isinstance(rule.transform, ColourAmountTransform)
    assert rule.transform.amount == 1.0

    colour_point = view_model._find_colour_point(working_documents.bundle, rule.match.colour_point)
    assert colour_point is not None
    assert abs(colour_point.value.channels[0] - 0.75) <= 0.08
    assert abs(colour_point.value.channels[1] - 0.16) <= 0.06
    assert abs(colour_point.value.channels[2] - 0.15) <= 0.06


def test_new_black_point_adjustment_uses_dark_range_defaults(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("black")
    black_rule = view_model._selected_rule_model()
    assert black_rule is not None
    assert black_rule.name == "Black Point"
    assert isinstance(black_rule.transform, BrightnessTransform)
    assert black_rule.transform.amount < 1.0
    assert black_rule.match.colour_point is None
    assert black_rule.match.brightness is not None
    assert black_rule.match.brightness.min == 0.0
    assert black_rule.match.brightness.max == 0.18


def test_new_shadows_adjustment_uses_shadow_band_defaults(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("shadows")
    shadows_rule = view_model._selected_rule_model()
    assert shadows_rule is not None
    assert shadows_rule.name == "Shadows"
    assert isinstance(shadows_rule.transform, BrightnessTransform)
    assert shadows_rule.transform.amount > 1.0
    assert shadows_rule.match.colour_point is None
    assert shadows_rule.match.brightness is not None
    assert shadows_rule.match.brightness.min == 0.10
    assert shadows_rule.match.brightness.max == 0.42


def test_new_non_colour_adjustments_do_not_default_to_colour_points(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("black")
    black_rule = view_model._selected_rule_model()
    assert black_rule is not None
    assert black_rule.match.colour_point is None

    view_model.create_adjustment("shadows")
    shadows_rule = view_model._selected_rule_model()
    assert shadows_rule is not None
    assert shadows_rule.match.colour_point is None

    view_model.create_adjustment("saturation")
    saturation_rule = view_model._selected_rule_model()
    assert saturation_rule is not None
    assert saturation_rule.match.colour_point is None

    view_model.create_adjustment("brightness")
    brightness_rule = view_model._selected_rule_model()
    assert brightness_rule is not None
    assert brightness_rule.match.colour_point is None

    view_model.create_adjustment("levels")
    levels_rule = view_model._selected_rule_model()
    assert levels_rule is not None
    assert levels_rule.match.colour_point is None


def test_new_levels_adjustment_uses_five_band_defaults(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.create_adjustment("levels")
    levels_rule = view_model._selected_rule_model()
    assert levels_rule is not None
    assert levels_rule.name == "Levels"
    assert isinstance(levels_rule.transform, LevelsTransform)
    assert levels_rule.transform.darkest == 1.0
    assert levels_rule.transform.dark == 1.0
    assert levels_rule.transform.mid == 1.0
    assert levels_rule.transform.light == 1.0
    assert levels_rule.transform.brightest == 1.0


def test_levels_adjustment_editor_shows_five_band_controls(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.create_adjustment("levels")
    summary = window.view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.type_label == "Levels"
    assert summary.level_labels == ("Darkest", "Dark", "Mid", "Light", "Brightest")
    assert summary.level_values == (1.0, 1.0, 1.0, 1.0, 1.0)
    assert window.level_inputs_container.isHidden() is False


def test_black_point_and_shadows_use_distinct_editor_language(
    qtbot: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    window = MainWindow(project_dir)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.view_model._current_preview is not None, timeout=5000)

    window.view_model.create_adjustment("black")
    black_summary = window.view_model.selected_adjustment_summary()
    assert black_summary is not None
    assert black_summary.type_label == "Black Point"
    assert black_summary.primary_label == "Depth"
    assert "stronger black point" in black_summary.helper_text

    window.view_model.create_adjustment("shadows")
    shadows_summary = window.view_model.selected_adjustment_summary()
    assert shadows_summary is not None
    assert shadows_summary.type_label == "Shadows"
    assert shadows_summary.primary_label == "Lift / Deepen"
    assert "darker detail above black" in shadows_summary.helper_text


def test_export_defaults_and_profiles_reflect_native_source_dimensions(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    native_dimensions = view_model.native_render_dimensions()
    assert native_dimensions is not None
    assert native_dimensions[0] > 0
    assert native_dimensions[1] > 0

    default_print = view_model.default_print_dimensions(units="cm", ppi=300)
    assert default_print is not None
    assert default_print[0] > 0.0
    assert default_print[1] > 0.0

    screen_profile = view_model.build_screen_export_profile(
        output_format="jpeg",
        width_px=native_dimensions[0] * 2,
        interpolation="nearest",
    )
    assert screen_profile.format == "jpeg"
    assert screen_profile.width_px == native_dimensions[0] * 2
    assert screen_profile.interpolation == "nearest"
    assert screen_profile.bit_depth == 8

    print_profile = view_model.build_print_export_profile(
        output_format="tiff",
        width=default_print[0],
        height=default_print[1],
        units="cm",
        ppi=300,
        interpolation="nearest",
    )
    assert print_profile.format == "tiff"
    assert print_profile.ppi == 300
    assert print_profile.interpolation == "nearest"
    assert print_profile.bit_depth == 16


def test_changing_colour_adjustment_amount_updates_preview_image(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True
    sample = _preview_sample(view_model)
    created_id = view_model.create_adjustment_from_selection("blue", sample)
    assert created_id is not None
    before = view_model._current_preview
    assert before is not None

    from engine.preview import render_preview_image

    def immediate_render(*, immediate: bool = False) -> None:
        _ = immediate
        working_documents = view_model._working_documents
        assert working_documents is not None
        view_model._active_job_id += 1
        view_model.apply_preview_result(
            view_model._active_job_id,
            render_preview_image(
                working_documents.bundle.model_copy(deep=True),
                include_provenance=False,
                use_cached_sources=True,
            ),
        )

    monkeypatch.setattr(view_model, "request_preview_render", immediate_render)

    view_model.select_adjustment(created_id)
    view_model.set_selected_adjustment_primary_value(1.8)

    after = view_model._current_preview
    assert after is not None
    assert not np.allclose(before.image.data, after.image.data, atol=1e-6)


def test_brightness_adjustment_has_visible_low_vs_high_difference(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    _write_star_nebula_tiff(project_dir / "sources/source-01.tif")
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    from engine.preview import render_preview_image

    def immediate_render(*, immediate: bool = False) -> None:
        _ = immediate
        working_documents = view_model._working_documents
        assert working_documents is not None
        view_model._active_job_id += 1
        view_model.apply_preview_result(
            view_model._active_job_id,
            render_preview_image(
                working_documents.bundle.model_copy(deep=True),
                include_provenance=False,
                use_cached_sources=True,
            ),
        )

    monkeypatch.setattr(view_model, "request_preview_render", immediate_render)

    view_model.select_adjustment("brightness")
    view_model.set_selected_adjustment_primary_value(1.15)
    low = view_model._current_preview
    assert low is not None
    low_data = low.image.data.copy()

    view_model.set_selected_adjustment_primary_value(4.0)
    high = view_model._current_preview
    assert high is not None

    diff = np.abs(high.image.data - low_data)
    assert float(diff.mean()) > 0.01


def test_region_drawing_editing_and_scope_assignment_use_normalized_geometry(
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    view_model.begin_region_drawing()
    view_model.add_region_point(0.1, 0.2)
    view_model.add_region_point(0.4, 0.2)
    view_model.add_region_point(0.4, 0.6)
    view_model.finish_region_drawing()

    region = view_model.selected_region_summary()
    assert region is not None
    assert region.polygon == [(0.1, 0.2), (0.4, 0.2), (0.4, 0.6)]

    view_model.move_region_vertex(region.region_id, 1, 0.45, 0.25)
    moved = view_model.selected_region_summary()
    assert moved is not None
    assert moved.polygon[1] == (0.45, 0.25)

    view_model.insert_region_vertex(region.region_id, 2, 0.5, 0.45)
    inserted = view_model.selected_region_summary()
    assert inserted is not None
    assert len(inserted.polygon) == 4

    view_model.select_adjustment("reveal-faint-blue")
    view_model.set_selected_adjustment_apply_everywhere(False)
    view_model.set_selected_adjustment_regions([region.region_id])
    summary = view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.region_ids == [region.region_id]


def test_region_union_references_and_deletion_keep_references_safe(tmp_path: Path) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    for points in [
        [(0.1, 0.1), (0.3, 0.1), (0.3, 0.3)],
        [(0.6, 0.6), (0.8, 0.6), (0.8, 0.8)],
    ]:
        view_model.begin_region_drawing()
        for x, y in points:
            view_model.add_region_point(x, y)
        view_model.finish_region_drawing()

    region_ids = [
        summary.region_id
        for summary in view_model.region_summaries()
        if summary.region_id != "lower-right"
    ]
    assert len(region_ids) == 2

    view_model.select_adjustment("reveal-faint-blue")
    view_model.set_selected_adjustment_regions(region_ids)
    summary = view_model.selected_adjustment_summary()
    assert summary is not None
    assert summary.region_ids == region_ids

    view_model.select_region(region_ids[0])
    view_model.remove_selected_region()
    remaining_summary = view_model.selected_adjustment_summary()
    assert remaining_summary is not None
    assert region_ids[0] not in remaining_summary.region_ids
    assert region_ids[1] in remaining_summary.region_ids


def test_semantic_change_list_and_individual_revert_preserve_unrelated_changes(
    tmp_path: Path,
) -> None:
    project_dir = _copy_example_project(tmp_path)
    view_model = ProjectEditorViewModel()
    assert view_model.open_project(project_dir) is True

    selected = view_model.selected_rule()
    assert selected is not None
    view_model.set_rule_amount(selected.amount + 0.15)

    view_model.begin_region_drawing()
    view_model.add_region_point(0.2, 0.2)
    view_model.add_region_point(0.5, 0.2)
    view_model.add_region_point(0.5, 0.5)
    view_model.finish_region_drawing()
    new_region = view_model.selected_region_summary()
    assert new_region is not None

    changes = view_model.unsaved_changes()
    region_change = next(change for change in changes if change.entity_type == "region")
    view_model.revert_change(region_change.key)

    still_changed = view_model.selected_rule()
    assert still_changed is not None
    assert still_changed.amount == selected.amount + 0.15
    assert all(
        summary.region_id != new_region.region_id
        for summary in view_model.region_summaries()
    )

    assert view_model.save_changes() is True
    assert view_model.dirty is False
    assert view_model.unsaved_changes() == []

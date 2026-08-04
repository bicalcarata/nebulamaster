# NebulaMaster User Manual

## 1. Introduction

NebulaMaster is a free desktop image-mastering application for already-prepared deep-sky images. It is designed for people who want to improve a finished telescope image without learning a full astrophotography processing stack or using a general-purpose photo editor.

NebulaMaster does not replace capture, stacking, calibration, alignment, or stretching. Those steps happen before NebulaMaster. You start with an image that already exists as a TIFF, PNG, or JPEG, then use NebulaMaster to refine colour, tone, stars, nebula structure, dark dust, local regions, and final output framing.

The app is project-based and non-destructive:

- Your original source image is never edited in place.
- Saving writes project metadata, not pixels back into the source file.
- Preview images are temporary renders.
- Exported files are regenerated from the source image plus the saved project state.

Think of NebulaMaster as a mastering desk for one image project at a time.

## 2. Core Concepts

Before using the app, it helps to understand four ideas that shape the workflow.

### 2.1 Projects

A NebulaMaster project is a folder containing:

- `project.yaml`
- source image references
- palette data
- render profiles
- plugin lock metadata
- optional region metadata

When you create a new project from an image, the app creates this folder structure for you and copies the chosen source image into the project under `sources/`.

### 2.2 Ordered Adjustments

Every edit lives in an ordered adjustment stack. Order matters. Each adjustment runs in sequence through the shared renderer, so moving one earlier or later can change the result.

You can:

- add adjustments
- edit them
- disable them
- duplicate them
- reset them
- reorder them
- remove them

### 2.3 Semantic Targets

An adjustment can be aimed at different kinds of image structure through the `Affects` control:

- `Combined Image`
- `Nebula`
- `Stars`
- `Dark Dust`

This lets you work more selectively than a normal global image editor.

### 2.4 Regions

Regions are polygon selections drawn over the image preview. They do not replace colour or semantic targeting. Instead, they act as a spatial limit on top of the adjustment’s normal targeting.

You can use regions to keep an edit inside one part of the image while still targeting only nebula, stars, dark dust, or a selected colour family.

## 3. Main Window Overview

The main window is organized into four working areas.

### 3.1 Left Panel

The left panel contains project structure:

- project name and path
- source list
- adjustment stack
- adjustment action buttons
- region list
- region controls

This is where you select what you want to work on.

### 3.2 Center Panel

The center panel contains the live preview and view controls:

- `Show Preview`
- `Show Source`
- `Overlay`
- `Before / After`
- `Hold Previous`
- zoom controls
- colour picking
- `Create Adjustment from Selection`

This is the main visual workspace.

### 3.3 Right Panel

The right panel contains the editor for the selected item:

- adjustment settings
- semantic target selection
- colour point selection
- amount sliders and numeric inputs
- region scope assignment
- palette-specific balance controls
- dark dust mask controls

If an adjustment is selected, the inspector shows that adjustment. If a region is selected, the inspector shows the region editor.

### 3.4 Bottom Panel

The bottom panel tracks unsaved semantic changes:

- list of pending changes
- `Keep Change`
- `Remove Selected Change`
- `What Changed?`
- `Revert All`

This is how you review and save project edits.

## 4. Starting a New Project

Use this workflow when you have an image but no NebulaMaster project yet.

### 4.1 Supported Source Formats

NebulaMaster can create a project from:

- TIFF
- PNG
- JPEG

### 4.2 Create a Project from an Image

1. Open the `File` menu.
2. Choose `New Project from Image...`.
3. Select the source image.
4. Choose the parent folder where the new project should be created.
5. Enter a project folder name when prompted.
6. Confirm the dialog.

NebulaMaster will:

- create a new project folder
- create the required metadata files
- copy the source image into the project’s `sources/` folder
- open the new project in the app

### 4.3 What the App Creates

A newly scaffolded project includes:

- one source image entry
- a default palette
- a default screen preview render profile
- standard semantic channels including `Dark Dust`
- plugin lock metadata

You can begin editing immediately after the project opens.

## 5. Opening an Existing Project

Use this workflow when a project already exists.

1. Open the `File` menu.
2. Choose `Open Project...`.
3. Select the project’s `project.yaml` file.

The app loads:

- project metadata
- sources
- adjustments
- regions
- preview state
- dark dust settings

### 5.1 Recent Projects

NebulaMaster keeps a recent-project list in the `File` menu. Up to five recent projects can appear there for faster reopening between sessions.

### 5.2 Unsaved Work Protection

If you try to open another project, create a new one, or close the app while the current project has unsaved changes, NebulaMaster asks whether to save, discard, or cancel first.

## 6. Everyday Editing Workflow

A typical session looks like this:

1. Open or create a project.
2. Study the preview and overlays.
3. Add an adjustment.
4. Aim it with `Affects`.
5. Optionally sample a colour point.
6. Optionally limit it to one or more regions.
7. Reorder the adjustment if needed.
8. Review the unsaved changes list.
9. Click `Keep Change` to save project metadata.
10. Export a final render when ready.

## 7. Working with Adjustments

Adjustments are the heart of NebulaMaster.

### 7.1 Add an Adjustment

1. In the `Adjustments` section, click `Add`.
2. Choose the adjustment type from the menu.

The new adjustment appears in the stack and can then be edited in the right-hand inspector.

### 7.2 Select and Edit an Adjustment

1. Click an adjustment in the left panel.
2. Use the right panel to change its settings.

Depending on the adjustment type, the inspector may show:

- an `Enabled` checkbox
- `Affects`
- a colour point preview and picker
- one or more amount controls
- palette balance controls
- extra numeric options
- region scope assignment

### 7.3 Reorder Adjustments

With an adjustment selected, use:

- `Move Earlier`
- `Move Later`

Reordering changes declaration order in the project and can materially change the render.

### 7.4 Duplicate an Adjustment

Use `Duplicate` when you want a variation of an existing adjustment without rebuilding it from scratch.

This is useful when:

- trying a stronger or weaker version
- splitting one idea into separate regional versions
- testing the same treatment on different semantic targets

### 7.5 Disable an Adjustment

Use the `Enabled` checkbox to temporarily turn an adjustment off without removing it.

Disabled adjustments remain in the stack and can be re-enabled later.

### 7.6 Reset an Adjustment

Use `Reset` to return the selected adjustment to its baseline settings while keeping it in the project.

### 7.7 Remove an Adjustment

Use `Remove` to delete the selected adjustment from the stack.

This affects only that adjustment. Later adjustments remain active.

## 8. Adjustment Types

NebulaMaster supports a mix of tonal, colour, palette, and structure-focused tools.

### 8.1 Tonal Adjustments

- `Black Point`
- `Shadows`
- `Brightness`
- `Levels`
- `Tone Shaping`
- `Local Contrast`

Use these to control overall structure, depth, and separation without needing a traditional curves tool.

### 8.2 Colour Adjustments

- `Blue`
- `Red`
- `Green`
- `Cyan`
- `Yellow`
- `Saturation`
- `Vibrance`
- `Colour Temperature`
- `Colour Smoothness`

These adjustments help refine the balance and presentation of existing colour in the image.

### 8.3 Faux Palette Adjustments

- `Faux Hubble`
- `Faux HOO`
- `Foraxx-Inspired`
- `Gold & Cyan`
- `Natural Bi-colour`

These are creative palette treatments for RGB images. They do not reconstruct true narrowband data. They behave like normal ordered adjustments and can be targeted, scoped, moved, duplicated, enabled, or disabled like other adjustments.

### 8.4 Dark Structure Adjustment

- `Dark Nebula Processing`

This is a dedicated ordered adjustment for revealing faint translucent dark-nebula structure while preserving denser obscuring regions.

## 9. Targeting What an Adjustment Affects

Every adjustment can be directed through `Affects`.

### 9.1 Combined Image

`Combined Image` applies the adjustment across the full image result.

### 9.2 Nebula

`Nebula` biases the adjustment toward nebular structure.

### 9.3 Stars

`Stars` biases the adjustment toward compact stellar sources.

### 9.4 Dark Dust

`Dark Dust` biases the adjustment toward detected dark dust structure.

This target depends on the dark dust mask settings described later in this guide.

## 10. Colour Points and Sampling

Several adjustment types work best when they are anchored to a sampled colour point.

### 10.1 Pick a Colour Point

1. Select a colour-capable adjustment.
2. Click the `Pick ... Point` button in the center toolbar.
3. Click the relevant feature in the preview.

The sampled point becomes part of the adjustment’s selection logic. The inspector shows the point label and a swatch.

### 10.2 Source vs Preview Sampling

Sampling follows the current displayed image state:

- `Show Source` samples from the source image
- `Show Preview` samples from the rendered preview

This matters when you want to sample either the untouched source colour or the current mastered result.

## 11. Create Adjustment from Selection

This tool creates a new adjustment directly from a clicked image feature.

### 11.1 When to Use It

Use it when you want to begin from an actual visible feature rather than manually adding an adjustment and then hunting for a matching colour point.

### 11.2 Workflow

1. Click `Create Adjustment from Selection`.
2. Click a visible feature in the preview.
3. Choose the prompted adjustment type.

NebulaMaster creates a normal declarative adjustment at the end of the stack. It is not a temporary or special object. You can edit, reorder, duplicate, disable, scope, or remove it like any other adjustment.

### 11.3 Important Limitation

This tool does not automatically create a polygon region. If you want to restrict the new adjustment spatially, create or assign a region afterwards.

## 12. Using Regions

Regions let you confine adjustments to specific parts of the image.

### 12.1 Create a Region

1. In the `Regions` section, click `Add`.
2. Click points in the preview to draw the polygon.
3. Finish the shape.
4. Select the region from the list.
5. Edit its properties in the inspector.

### 12.2 Region Properties

For a selected region, you can edit:

- name
- enabled state
- edge softness

### 12.3 Assign a Region to an Adjustment

1. Select an adjustment.
2. In the inspector, find the scope section.
3. Leave `Apply everywhere` checked for global use, or uncheck it.
4. Select one or more regions to limit the adjustment.

You can combine regions with semantic targets and colour-point logic for more selective control.

### 12.4 Show or Hide Region Overlays

The preview can show project regions as an overlay while editing. This helps you understand where local treatments will apply.

## 13. Preview and Comparison Tools

The center panel is more than a static preview. It is a working inspection surface.

### 13.1 Show Preview

`Show Preview` displays the current mastered result through the shared renderer.

### 13.2 Show Source

`Show Source` displays the underlying source image.

Use this for comparison and for source-based colour sampling.

### 13.3 Before / After

`Before / After` compares the current working state to the saved state.

This is useful when you have a set of unsaved edits and want to judge them as a group.

### 13.4 Hold Previous

`Hold Previous` temporarily shows the previous rendered state for comparison.

This is useful when you are making iterative refinements and want a quick short-term comparison rather than a saved-vs-unsaved comparison.

### 13.5 Zoom Controls

Use:

- `Fit`
- `100%`
- `−`
- `+`

These affect only the view, not the project data.

### 13.6 Render Status

The interface reports preview render states such as:

- queued
- rendering
- ready
- cancelled
- failed

If a preview looks stale, check the render status first.

## 14. Semantic Overlays

Overlays are diagnostic views to help you understand how the renderer is interpreting image structure.

### 14.1 Available Overlay Options

The overlay selector supports:

- `Overlay: Off`
- `Overlay: Stars`
- `Overlay: Nebula`
- `Overlay: Dark Dust`

### 14.2 What Overlays Are For

Use overlays to answer questions like:

- Is the star mask catching only stars?
- Is the nebula mask actually following the emission structure?
- Is the dark dust mask identifying the right lanes and clouds?

### 14.3 What Overlays Are Not

Overlays do not become saved image content and do not directly alter exports. They are inspection tools.

## 15. Dark Dust Mask Tools

NebulaMaster includes a dedicated dark dust analysis system that can drive both overlays and Dark Dust-targeted adjustments.

### 15.1 Where to Find It

The `Dark Dust Mask` section appears in the right panel.

### 15.2 What It Controls

Dark dust settings affect:

- the dark dust overlay
- Dark Dust-targeted adjustments
- diagnostic mask views

### 15.3 Main Controls

The panel includes:

- `Enabled`
- `Overlay View`
- `Display Mode`
- `Solo Dark Dust Mask`
- `Reset Dark Dust Mask`
- coverage readout
- numeric mask tuning controls

### 15.4 Overlay Views

Available views include:

- `Final Mask`
- `Veil Mask`
- `Core Mask`
- `Relative Darkness`
- `Local Illumination`
- `Background Support`

These are useful for diagnosing why a Dark Dust-targeted adjustment behaves the way it does.

### 15.5 Display Modes

You can switch between:

- `Overlay on Image`
- `Mask Only`

`Mask Only` is often the clearest choice when fine-tuning the detection.

### 15.6 Numeric Parameters

The panel exposes these global controls:

- `Sensitivity`
- `Structure Size`
- `Background Protection`
- `Softness`
- `Veil Detection`
- `Core Detection`
- `Veil / Core Balance`

These settings shape how the app detects and prioritizes dark structures. If a Dark Dust-targeted adjustment seems too broad, too weak, or aimed at the wrong structures, inspect these settings before assuming the adjustment itself is the problem.

### 15.7 Coverage Readout

The panel reports `Dark Dust Coverage` as a percentage. This gives a quick sense of how much of the image is currently being included by the dark dust model.

## 16. Faux Palette Workflows

Faux palette adjustments are creative finishing tools.

### 16.1 How They Behave

Each faux palette is:

- an ordered adjustment
- non-destructive
- targetable
- region-aware
- blendable by amount
- editable in the same inspector model as other adjustments

### 16.2 Amount Control

The main amount acts like a wet/dry mix between the incoming image and the fully mapped palette result.

### 16.3 Palette Balance Controls

Some palettes expose additional balance controls. Use these when the base palette is close but one colour family needs finer control.

## 17. Reviewing and Saving Changes

NebulaMaster separates working edits from saved project metadata.

### 17.1 Unsaved Changes List

The bottom panel lists semantic changes such as:

- added or removed adjustments
- reordered adjustments
- target changes
- region edits
- dark dust setting changes
- palette balance edits

### 17.2 Keep Change

Click `Keep Change` to save the current project state to disk.

This writes project metadata only. It does not export a final image file.

### 17.3 Remove Selected Change

Use `Remove Selected Change` to revert a selected pending change without undoing unrelated work.

This is object-based change removal, not a traditional linear undo stack.

### 17.4 Revert All

Use `Revert All` to discard the full set of unsaved changes and return to the last saved project state.

## 18. Exporting for Screen

Use screen export when the output is intended for monitors, web sharing, or digital viewing.

### 18.1 Start Screen Export

1. Open the `File` menu.
2. Choose `Export for Screen...`.

### 18.2 Screen Export Options

The screen export dialog supports:

- `PNG`, `JPEG`, or `TIFF`
- output width and height in pixels
- interpolation choice
- output crop selection

### 18.3 Output Framing and Crop

Crop is treated as output framing, not a destructive edit inside the mastering stack. The image is mastered first, then cropped, then resized to the output dimensions.

This means one project can produce:

- a full-frame export
- a square social crop
- a portrait crop
- multiple alternate framed outputs

without altering the source image or the ordered adjustments.

### 18.4 Save Destination

After confirming export options, choose a destination path. If you omit the file extension, NebulaMaster adds the correct one automatically.

If the file already exists, the app asks before overwriting it.

## 19. Exporting for Print

Use print export when you want a physical-size oriented render.

### 19.1 Start Print Export

1. Open the `File` menu.
2. Choose `Export for Print...`.

### 19.2 Print Export Options

The print export dialog supports:

- `PNG` or `TIFF`
- physical width and height
- units
- target PPI
- interpolation choice
- output crop selection

### 19.3 Print Dimensions

The dialog can derive sensible default print dimensions from the source resolution and chosen crop.

### 19.4 Export Guidance

After a successful export, NebulaMaster reports:

- output path
- final output size
- renderer guidance text

## 20. Cropping and Output Framing

Crop in NebulaMaster is intentionally separate from the adjustment stack.

### 20.1 Crop Presets

The export crop workflow supports:

- `Off / Full Frame`
- `Original`
- `Custom`
- `1:1`
- `4:5`
- `5:4`
- `3:2`
- `2:3`
- `16:9`
- `9:16`

### 20.2 Crop Editing Behavior

The crop editor supports:

- a transparent crop window
- dimmed outside area
- drag-resize from edges and corners
- moving the crop rectangle
- locked aspect ratios for preset modes
- previewing the cropped output

### 20.3 Why This Matters

Because crop happens after the full image is mastered, you avoid wasting processing decisions on a permanently reduced frame and can export several compositions from the same project.

## 21. What Saving Does and Does Not Do

Saving and exporting are different.

### 21.1 Saving

Saving with `Keep Change`:

- writes project metadata to disk
- preserves your editable adjustment stack
- preserves region data
- preserves dark dust settings

### 21.2 Exporting

Exporting:

- renders a final image file
- does not replace your source image
- does not eliminate the need to save project metadata separately

If you export without saving first, the export still uses the current working project state for that render, but the project file on disk will not reflect those edits until you save.

## 22. Limitations and Important Behaviors

The current desktop app has a few important limits.

### 22.1 YAML Comments Are Not Preserved

When edited metadata is saved, YAML comments are not preserved.

### 22.2 Formatting May Change on Save

The app rewrites semantic YAML content rather than preserving the original formatting layout exactly.

### 22.3 Unsupported Saved Adjustments

If a project contains adjustments not currently editable in the UI, they are preserved and continue to render. The app does not discard them simply because it cannot fully edit them.

### 22.4 Preview Is Engine-Driven

The desktop app does not maintain a separate image-processing pipeline. Preview and export both come from the shared renderer.

## 23. Practical Tips

### 23.1 Work in Small Passes

Add one or two adjustments, compare them, then save. This makes the unsaved changes list easier to interpret.

### 23.2 Use Overlays Before Aggressive Targeting

If a Nebula, Stars, or Dark Dust adjustment behaves unexpectedly, inspect the matching overlay first.

### 23.3 Use Regions Sparingly at First

Start with global semantic targeting before adding regions. It is easier to judge whether the semantic target is correct when you are not also limiting the effect spatially.

### 23.4 Prefer Vibrance Before Heavy Saturation

If colour looks thin, `Vibrance` is often a safer first move than pushing `Saturation` hard.

### 23.5 Treat Faux Palettes as Finishing Moves

A faux palette usually behaves best after the image already has a reasonable tonal and structural balance.

## 24. Troubleshooting

### 24.1 “No project open” When Exporting

Open or create a project first. Export requires an active project.

### 24.2 Preview Looks Wrong

Check:

- whether `Show Source` is active instead of `Show Preview`
- whether an overlay is turned on
- whether `Before / After` or `Hold Previous` is affecting the view
- whether the render state says `queued` or `rendering`

### 24.3 Dark Dust Result Looks Inaccurate

Inspect:

- the `Overlay: Dark Dust` view
- the dark dust mask display mode
- the global dark dust parameters
- whether the adjustment itself is aimed at `Dark Dust`

### 24.4 Save Did Not Produce an Image File

That is expected. `Keep Change` saves project metadata only. Use `Export for Screen...` or `Export for Print...` for a final rendered image.

### 24.5 My Original Image Did Not Change

That is also expected. NebulaMaster is non-destructive and does not overwrite the source image.

## 25. Recommended First Session

If you are new to the app, use this short path:

1. Create a new project from a TIFF, PNG, or JPEG.
2. Add a `Brightness` or `Black Point` adjustment.
3. Add a `Vibrance` or `Saturation` adjustment.
4. Use `Overlay: Stars` or `Overlay: Nebula` to inspect targeting.
5. Add one colour-family adjustment such as `Blue` or `Red`.
6. Save with `Keep Change`.
7. Export one full-frame screen render.
8. Export a second version with a square crop.

That sequence introduces the project model, ordered adjustments, overlays, saving, and output framing without making the workflow overly complex.

## 26. Summary

NebulaMaster is best understood as a non-destructive project editor for refining finished deep-sky images. Its strengths are:

- ordered declarative adjustments
- semantic targeting
- region-based local edits
- dark dust analysis and masking
- renderer-backed preview
- non-destructive output framing
- separate save and export workflows

If you keep those ideas in mind, the app becomes much easier to reason about and much more predictable to use.

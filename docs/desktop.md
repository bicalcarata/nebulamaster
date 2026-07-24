# Desktop Authoring Client

Nebula Master desktop is a visual authoring client for declarative projects.

The renderer remains authoritative. The desktop does not contain its own image-processing pipeline and it does not call the CLI through subprocesses. Every preview comes from the shared engine.

## Guarantees

- Source images remain immutable.
- Preview renders are ephemeral.
- Saving writes project metadata only.
- Unsupported saved adjustments are preserved and continue to render.
- Only metadata files whose semantic content changed are rewritten in this slice.

## Project Creation

The desktop can create a new project from a single TIFF, PNG, or JPEG source image.

Workflow:

- Choose a source image.
- Choose a parent directory for the new project.
- The desktop creates a new project root folder, project metadata, and source reference.
- The original source image remains the immutable input.

Project creation does not generate hidden edits or derived project state beyond normal declarative metadata.

## Mastering Desk

The current desktop supports a beginner-facing mastering desk with:

- Sources
- Adjustments in declaration order
- Regions
- A shared-engine preview
- Semantic target selection for Combined Image, Nebula, and Stars
- Diagnostic semantic overlays
- An unsaved semantic change list

Supported editable adjustments:

- Blue, Red, Green, Cyan, and Yellow colour amount
- Brightness
- Saturation
- Black Point
- Shadows
- Colour smoothness

Unsupported saved adjustments remain visible, render normally, and are preserved on save.

Adjustment list labels use ordinary language. Each row shows the adjustment name and what it affects, for example `Reveal faint blue glow • Nebula` or `Cyan • Stars`.

## Adjustment Order

Adjustment order maps directly to declaration order in `project.yaml`.

- Move earlier and move later change that declaration order.
- Disabling keeps an adjustment declared but stops it from running.
- Removing an adjustment leaves later adjustments active.
- Re-rendering always starts from immutable sources through the full ordered stack.

## Create From Selection

The desktop can create a new declarative adjustment directly from a visible image feature.

Workflow:

- Activate `Create Adjustment from Selection`.
- Click a visible feature in the currently displayed image.
- Choose Blue, Red, Brightness, Saturation, or Smoothing.
- Refine the new adjustment with the existing controls.

Sampling behaviour:

- `Show Source` samples from the displayed source image.
- `Show Preview` samples from the current rendered preview.
- Before/after comparison and hold-previous sampling use the currently displayed comparison state.

Resulting behaviour:

- The sampled colour becomes a normal declarative colour point in project metadata.
- The new adjustment initially applies across the full image and targets similar colours.
- It does not create a polygon region automatically.
- If you want to restrict it spatially, assign one or more existing polygon regions afterwards.

This keeps colour selection and region scope separate. The desktop stores no hidden masks, no persisted click coordinates, and no desktop-only adjustment model.

The same sampling path is reused by explicit colour-point picking actions such as `Pick Blue Point`, `Pick Red Point`, `Pick Green Point`, `Pick Cyan Point`, and `Pick Yellow Point`.

## Semantic Targets And Overlays

Each adjustment can target one of three semantic layers:

- Combined Image
- Nebula
- Stars

This target affects both selection and transformation execution in the shared renderer.

The preview can also show semantic diagnostic overlays:

- `Overlay: Off`
- `Overlay: Stars`
- `Overlay: Nebula`

These overlays are preview diagnostics only. They do not become project metadata, and they do not change the rendered output or exported files.

## Region Drawing

The desktop supports polygon regions with normalized coordinates.

- Region points are stored as 0.0–1.0 source-relative coordinates.
- Zoom and pan affect only the overlay display, not stored geometry.
- Regions can be drawn, renamed, softened, moved, and assigned to adjustments.
- Multiple region references use the existing union semantics from the engine.

## Working Changes

The desktop maintains:

- last saved project state
- current working project state
- semantic unsaved changes derived from the diff engine

Each unsaved change is described in ordinary language, such as:

- Blue increased
- Lower Right region added
- Smooth blue glow now runs before Blue

Individual change removal is object-based rather than a linear undo stack. Reverting one adjustment or region restores that object to the last saved baseline while leaving unrelated working edits in place.

## Export

The desktop can export through the shared renderer for both screen and print.

Screen export supports:

- PNG
- JPEG
- TIFF
- Optional upscale output sizing
- Interpolation choices including nearest-neighbour style pixel-preserving upscale

Print export supports:

- PNG
- JPEG
- TIFF
- Physical width and height
- Output units
- Target DPI / PPI

Export remains declarative in the same sense as preview rendering: the output file is generated from immutable sources and project metadata and is not fed back into project state.

## Current Limitations

- YAML comments are not preserved yet because the current loader uses `PyYAML`.
- The desktop rewrites semantic YAML content rather than preserving original formatting.
- Before/after comparison is toggle and hold-based rather than split-view.
- Region overlay editing is intentionally lightweight and does not attempt desktop-side rasterisation logic.

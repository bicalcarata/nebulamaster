# Project Format

## Goals

The project format is the product. It must be:

- Declarative
- Diffable
- Human-inspectable
- Versionable in Git
- Stable across desktop, CLI, and container execution

## Directory Layout

```text
project/
  project.yaml
  sources/
  regions/
  palettes/
  render_profiles/
  plugins/
```

## Persistent vs Ephemeral

Persistent project state includes:

- Source images
- Project metadata
- Rule definitions
- Regions
- Palettes
- Render profiles
- Plugin locks

Ephemeral artifacts include:

- Preview caches
- Rendered TIFF/PNG/JPEG outputs
- Temporary execution traces unless explicitly exported

## Root Project File

Example `project.yaml`:

```yaml
schema_version: 1
project:
  id: horsehead-demo
  name: Horsehead Demo
  created_at: 2026-07-20T00:00:00Z

sources:
  - id: source-01
    path: sources/horsehead-linear.tif
    name: Base Source
    role: base
    reference: true
    enabled: true
    weight: 1.0

semantic_channels:
  - id: combined
    name: Combined Image
  - id: nebula
    name: Nebula
  - id: stars
    name: Stars
  - id: dark_dust
    name: Dark Dust
  - id: background
    name: Background

palettes:
  - id: default-nebula
    path: palettes/default-nebula.yaml

regions:
  - id: lower-right
    path: regions/lower-right.yaml

render_profiles:
  - id: screen
    path: render_profiles/screen.yaml

plugins:
  path: plugins/lock.yaml

source_mix:
  mode: weighted_average

rules:
  - id: increase-nebula-blue
    name: Increase Nebula Blue
    enabled: true
    selection_source: current
    target: nebula
    match:
      colour_point: nebula-blue
      colour_range: 0.18
      brightness:
        min: 0.2
        max: 0.5
      softness: 0.5
    regions: [lower-right]
    transform:
      type: colour_amount
      channel: blue
      amount: 1.35
      preserve_luminance: true
```

## Rules

Rules encode ordered intent in a stable structure. Their array order is their execution order.
Targets are `combined`, `nebula`, `stars`, or `dark_dust`. Transformations are discriminated by
their `type` field and unknown fields fail validation.

Example faux palette rule:

```yaml
rules:
  - id: gold-and-cyan
    name: Gold & Cyan
    enabled: true
    selection_source: current
    target: nebula
    match:
      softness: 0.5
    regions: []
    transform:
      type: faux_palette
      palette: gold_cyan
      amount: 0.65
      preserve_brightness: true
      cool_mode: add
      colour_balance:
        gold: 100.0
        cyan: 140.0
```

`cool_mode: enhance` strengthens existing cool colour. `cool_mode: add` introduces the palette's
cool role into coherent selected source structure. Older declarations may omit it and inherit
`enhance`.

## Regions

Regions are durable polygon definitions with optional feathering. Coordinates and feather radius
are normalized to the source image, so geometry is independent of preview and output resolution.

Example:

```yaml
id: lower-right
name: Lower Right
enabled: true
feather:
  radius: 0.08
polygon:
  - [0.56, 0.44]
  - [0.90, 0.44]
  - [0.93, 0.82]
  - [0.60, 0.84]
```

## Palettes and Colour Points

Palettes should name user-facing colour anchors rather than expose raw technical colour tooling in the UI.

Example:

```yaml
id: default-nebula
colour_points:
  - id: nebula-blue
    name: Nebula Blue Point
    value:
      model: working-rgb
      channels: [0.18, 0.31, 0.77]
  - id: star-blue
    name: Star Blue Point
    value:
      model: working-rgb
      channels: [0.62, 0.71, 0.95]
```

## Render Profiles

Render profiles describe output intent and reproducibility settings.

Example:

```yaml
id: screen
name: Screen Preview
profile:
  type: screen
  format: png
  color_space: srgb
  bit_depth: 8
  width_px: 1920
  interpolation: lanczos
  crop:
    enabled: false
    x: 0.0
    y: 0.0
    width: 1.0
    height: 1.0
    lock_aspect_ratio: true
preview:
  cacheable: true
```

## Plugin Locking

Plugins should be pinned explicitly.

Example `plugins/lock.yaml`:

```yaml
plugins:
  - id: core.semantic-masks
    version: 1.2.0
  - id: core.transforms
    version: 1.0.4
```

## Validation Rules

The renderer rejects projects when:

- Source references are missing
- IDs that must be unique are duplicated
- Rule references point to unknown regions or colour points
- Rule targets do not match declared semantic channels
- Ranges, normalized geometry, crop bounds, or transformation parameters are invalid
- Plugin lock entries are syntactically invalid
- Schema versions are unsupported

## CLI Contract

Expected command behavior:

- `nebula validate`
  - Validate project structure, references, schema, and plugin availability
- `nebula preview`
  - Produce a disposable preview render for a selected profile
- `nebula render`
  - Produce a final export for a selected profile
- `nebula diff`
  - Summarize semantic project differences between two versions
- `nebula explain`
  - Explain why a pixel or region appears as it does

## Compatibility Strategy

Schema evolution should occur through explicit migrations contributed by the core system or plugins. The project format should avoid silent behavior changes across versions.

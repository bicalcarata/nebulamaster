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
    checksum: sha256:example

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
  lockfile: plugins/lock.yaml

rules:
  - id: increase-nebula-blue
    enabled: true
    target: nebula
    match:
      colour_point: nebula-blue
      brightness: faint
      regions: [lower-right]
    transform:
      blue: +0.35
      preserve_brightness: true
```

## Rules

Rules should encode intent in a stable structure.

Suggested shape:

```yaml
rules:
  - id: rule-id
    enabled: true
    target: nebula | stars | background | dust | custom-layer
    match:
      colour_point: optional-reference
      brightness:
        min: 0.2
        max: 0.5
      saturation:
        min: 0.1
        max: 0.8
      regions: [region-a, region-b]
      semantic_mask: optional-plugin-mask
    transform:
      blue: +0.20
      red: -0.05
      saturation: +0.10
      star_presence: -0.15
      preserve_brightness: true
    metadata:
      label: More blue in lower-right nebula
      intent: creative-adjustment
```

## Regions

Regions are durable GIS-style polygon definitions with optional feathering.

Example:

```yaml
id: lower-right
name: Lower Right
enabled: true
feather:
  radius: 24
polygon:
  - [1520, 880]
  - [2240, 910]
  - [2310, 1420]
  - [1600, 1490]
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
output:
  format: png
  color_space: srgb
  bit_depth: 16
  dimensions:
    mode: source
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

The renderer should reject projects when:

- Source references are missing
- Checksums do not match
- Rule references point to unknown regions or palettes
- Plugin capabilities are unavailable
- Schema versions are unsupported
- Transforms conflict with renderer constraints

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

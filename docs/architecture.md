# Architecture

## Objective

Define an implementation shape that preserves the product vision:

- Declarative authoring
- Immutable image sources
- Reproducible rendering
- Shared renderer across all surfaces
- Semantic explainability

## Top-Level System

```text
+------------------+       +---------------------+
| Desktop UI       |       | CLI / Container     |
| Authoring Client |       | Automation Clients  |
+---------+--------+       +----------+----------+
          |                           |
          +-----------+   +-----------+
                      |   |
                +-----v---v------+
                | Shared Renderer |
                | Core Engine     |
                +-----+-----------+
                      |
        +-------------+-------------------+
        |             |                   |
  +-----v-----+ +-----v------+     +------v------+
  | Project   | | Plugin     |     | Output      |
  | Loader    | | Runtime    |     | Writers     |
  +-----+-----+ +-----+------+     +------+------+
        |             |                   |
  +-----v-----+ +-----v------+     +------v------+
  | Sources    | | Rules /    |     | Preview /   |
  | Metadata   | | Masks /    |     | Rendered    |
  | Regions    | | Profiles   |     | Artifacts   |
  +-----------+ +------------+     +-------------+
```

## Architectural Rules

### 1. Renderer is the source of processing truth

Anything that changes pixels or computes semantic explanations belongs in the shared renderer, not in the desktop application.

### 2. Desktop authors intent only

The desktop converts UI interactions into declarative project mutations. It should never invent a separate rendering path or private adjustment model.

### 3. Project state is durable, renders are not

Only durable project inputs and metadata are part of the persistent model. Preview caches and exported images are outputs and may be deleted safely.

### 4. Explainability is first-class

The renderer should retain enough execution metadata to explain why a pixel or region appears as it does.

## Suggested Package Boundaries

Initial logical modules:

- `project-model`
  - Schema definitions for projects, regions, palettes, profiles, and rules
- `project-io`
  - Parsing, validation, normalization, migrations, and compatibility checks
- `pixel-model`
  - Internal pixel representation and derived attributes
- `semantic-engine`
  - Layer classification, region membership, and plugin-provided masks
- `query-engine`
  - Rule matching over semantic layers, colour points, brightness ranges, and regions
- `transform-engine`
  - Declarative transformation execution and composition
- `render-engine`
  - Preview and export generation
- `explain-engine`
  - Pixel-level and version-to-version semantic explanations
- `plugin-runtime`
  - Plugin discovery, version locking, capability registration, and migrations
- `cli`
  - Stable command surface
- `desktop-client`
  - UI editor using the renderer API

## Rendering Pipeline

Recommended pipeline:

1. Load project and lock plugin versions.
2. Validate schema and normalize config.
3. Load immutable source image data.
4. Build semantic views and region memberships.
5. Resolve palette and colour point references.
6. Compile declarative rules into executable selectors and transforms.
7. Execute rules deterministically.
8. Produce preview or final output.
9. Persist explanation metadata for inspection.

## Determinism Requirements

To make renders reproducible:

- Rule ordering must be defined.
- Plugin versions must be pinned.
- Project schema versions must be explicit.
- Derived defaults must be normalized before execution.
- Output profiles must be named and versioned.

The same source images, project metadata, renderer version, and plugin set should yield identical outputs.

## Explainability Model

The renderer should emit trace data at two levels:

### Pixel Explanation

Given a coordinate, report:

- Source pixel baseline
- Semantic layers matched
- Regions matched
- Rules applied in order
- Net transform effect
- Render profile contribution

### Version Explanation

Given two project versions, report semantic deltas such as:

- Nebula blue increased
- Star suppression increased
- Dust visibility increased
- Background darkened

This should be derived from rule and profile changes, not just raster diffs.

## Desktop Implications

The desktop should be framed as a project editor with:

- Local preview rendering via the shared engine
- Region drawing and editing tools
- Palette and colour point editors
- Rule editors backed by human-readable controls
- History views expressed in creative language

Suggested language mappings:

- Alternative Version instead of Branch
- Snapshot instead of Commit
- Rewind instead of Reset or Checkout

## Non-Goals

The system should avoid expanding into:

- Camera-specific ingestion workflows
- Telescope-specific assumptions
- FITS-only design constraints
- Traditional destructive layer editing
- Graph-heavy colour grading tooling

## First Implementation Milestones

1. Define project schema and normalization rules.
2. Implement deterministic rule evaluation against a basic pixel model.
3. Add `validate`, `preview`, and `explain` CLI commands.
4. Build a minimal desktop editor that edits project metadata and calls the renderer.

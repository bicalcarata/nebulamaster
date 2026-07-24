# Nebula Master

Nebula Master is a declarative nebula image mastering engine.

It is not an astrophotography workflow tool and it is not a destructive pixel editor. The product treats imported source images plus project metadata as the only source of truth. Every rendered preview or export is an ephemeral build artifact that can be reproduced at any time from the project.

Think "Terraform for nebula image mastering" rather than "Photoshop for astrophotography".

## Product Position

Nebula Master transforms image mastering into a version-controlled declarative workflow:

- Source images are immutable.
- Adjustments are stored as intent, not destructive edits.
- Rendered outputs are disposable and reproducible.
- Projects are designed to live naturally in Git.
- Desktop, CLI, and container workflows all use the same renderer.

## Core Principles

### Immutable Sources

Imported images are never modified in place. After import, all user actions are represented as project metadata, regions, palettes, and render profiles.

### Ephemeral Renders

TIFF, PNG, and JPEG outputs are generated artifacts. Deleting them must lose nothing. Re-rendering the same project with the same inputs and plugin versions must reproduce the same output.

### Declarative Intent

The user describes what they want to see, and the system stores that as rules.

Example:

```yaml
target: nebula
match:
  colour: blue_point
  brightness: faint
  region: lower_right
transform:
  blue: +35%
```

### Version Controlled

Projects should commit:

- Source images
- Project metadata
- Regions
- Palettes
- Render profiles
- Plugin versions

Generated renders should not be committed by default.

### Non-Destructive

Every change remains editable. Removing or changing a rule causes the renderer to recompute the final image from immutable inputs.

## Data Model

The atomic unit is the pixel.

Each pixel is modeled as structured data with:

- Spatial position
- Colour channels
- Derived colour attributes
- Semantic layer membership
- Region membership
- Pipeline metadata

Semantic layers are views over pixel data, not separate edited assets. Typical layers include:

- Nebula
- Stars
- Background
- Dust

## User Experience

The UI is a visual authoring environment for declarative intent.

Users work through:

- Image preview
- Sliders
- Colour points
- Polygon regions
- Before/after comparison
- Helper text

The UI should not expose graphs such as histograms, curves, waveforms, or channel plots. Controls should describe perceptual outcomes in human language, such as:

- Nebula Blue Point
- Star Blue Point
- Behind Dust Brightness
- Background Darkness
- Star Presence

The UI generates the underlying query rules automatically.

## Explainability

Nebula Master should answer:

- Why does this look like this?
- What changed between version A and version B?

These explanations should be semantic rather than pixel-diff oriented. For any sampled point, the system should be able to report:

- Which rules matched
- Which regions applied
- Which semantic layers contributed
- Which palette or colour point was used
- Which render profile affected the result

## Architecture

The system is split into two products:

### Desktop

Responsibilities:

- Import images
- Create new projects from immutable source images
- Create colour points
- Draw regions
- Edit sliders and rules
- Preview and compare
- Preview semantic star and nebula overlays
- Export screen and print renders through the shared renderer
- Present history and alternative versions
- Manage project files

The desktop application must not contain renderer-only logic.

### Renderer

Responsibilities:

- Read project state
- Validate declarative configuration
- Execute selection and transformation rules
- Produce previews and final renders
- Explain pixel outcomes
- Diff project versions semantically
- Guarantee reproducible outputs

All rendering paths must use the same engine:

- Desktop
- CLI
- Container

## Command Surface

The renderer should be exposed through a stable CLI:

```text
nebula validate
nebula preview
nebula render
nebula diff
nebula explain
```

## Plugin Model

Plugins may contribute:

- Semantic masks
- Colour palettes
- Transformations
- Render profiles
- Project migrations

Plugins contribute declarative behavior. They must never mutate source images.

## Repository Intent

This repository should grow around three stable contracts:

1. Project format
2. Renderer API and CLI
3. Desktop editor behavior as a client of the renderer

See [docs/architecture.md](/Users/damon/gitlab/nebulamaster/docs/architecture.md) and [docs/project-format.md](/Users/damon/gitlab/nebulamaster/docs/project-format.md) for the initial specification.

## Current Implementation

The current repository includes:

- A typed YAML project model built with Pydantic v2
- Shared image loading, validation, preview rendering, and export paths
- A renderer CLI with `nebula validate`, `nebula preview`, `nebula diff`, `nebula git`, and `nebula render`
- A PySide6 desktop authoring client that edits declarative project metadata

Current desktop mastering controls include:

- Colour adjustments for Blue, Red, Green, Cyan, and Yellow
- Tonal adjustments for Brightness, Saturation, Black Point, and Shadows
- Colour smoothing
- Semantic targets for Combined Image, Nebula, and Stars
- Polygon region scoping
- Image-driven colour-point sampling and adjustment creation
- Screen and print export using the shared renderer

The desktop preview can also show star and nebula diagnostic overlays so the user can see the current semantic split before applying adjustments.

## Local Packaging

The desktop application can be packaged locally as a standalone macOS app bundle plus release artifacts.

Prerequisites:

- macOS
- Python 3.13
- Synced workspace dependencies with `uv`

Build steps:

```bash
uv sync --dev
make package-desktop
```

Artifacts are written to `dist/`:

- `dist/Nebula Master.app`
- `dist/NebulaMaster.app.zip`
- `dist/NebulaMaster.dmg`

The packaging entrypoint is [scripts/package_desktop.sh](/Users/damon/gitlab/nebulamaster/scripts/package_desktop.sh), which builds the app via PyInstaller using [apps/desktop/packaging/nebula_master.spec](/Users/damon/gitlab/nebulamaster/apps/desktop/packaging/nebula_master.spec).

## CI And Releases

The repository includes two GitHub Actions workflows:

- [.github/workflows/ci.yml](/Users/damon/gitlab/nebulamaster/.github/workflows/ci.yml) runs `ruff`, `mypy`, and `pytest` on pushes to `main` and on pull requests.
- [.github/workflows/package-desktop.yml](/Users/damon/gitlab/nebulamaster/.github/workflows/package-desktop.yml) builds the standalone macOS desktop package on demand and on version tags.

Release flow:

1. Push a version tag such as `v0.1.0`.
2. GitHub Actions builds the macOS desktop artifacts.
3. The workflow uploads the `.zip` and `.dmg` files to the matching GitHub Release.

For non-release test builds, run the `Package Desktop` workflow manually with `workflow_dispatch` and download the artifacts from the workflow run.

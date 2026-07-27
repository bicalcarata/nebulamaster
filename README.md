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
- Numeric adjustment controls
- Colour points
- Polygon regions
- Before/after comparison
- Semantic targets
- Helper text

The UI does not expose histograms, curves, waveforms, or channel plots. Controls describe visible outcomes in human language, such as:

- Nebula Blue Point
- Star Blue Point
- Background Darkness
- Star Presence
- Black Point
- Levels

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
- Tonal adjustments for Brightness, Saturation, Black Point, Shadows, and five-band Levels
- Colour smoothing
- Semantic targets for Combined Image, Nebula, and Stars
- Polygon region scoping
- Image-driven colour-point sampling and adjustment creation
- Screen and print export using the shared renderer
- Packaged desktop application paths for macOS and Windows with a Nebula Master app icon

The desktop preview can also show star and nebula diagnostic overlays so the user can see the current semantic split before applying adjustments.

## Desktop Overview

The current desktop app is a working authoring environment for real projects. Adjustments are ordered, target-aware, and non-destructive.

![Nebula Master desktop preview](docs/images/readme/desktop-main.png)

The adjustment stack is declaration-ordered and shows what each adjustment affects:

- `Black Point` for deeper dark tones
- `Levels` for five tonal bands from darkest to brightest
- Colour adjustments targeted at `Nebula`, `Stars`, or `Combined Image`
- Multiple brightness and colour adjustments in a deterministic stack

![Adjustment stack](docs/images/readme/adjustment-stack.png)

Current desktop workflows include:

- Create a new project from a TIFF, PNG, or JPEG source image
- Open and edit declarative projects
- Target adjustments at `Nebula`, `Stars`, `Dark Dust`, or `Combined Image`
- Pick colour points directly from the image
- Create adjustments from image selections
- Draw polygon regions and scope adjustments to them
- Preview semantic star, nebula, and dark dust overlays
- Keep semantic unsaved-change history

## Current Adjustment Types

The desktop currently supports these editable adjustment types:

- Black Point
- Levels
- Shadows
- Brightness
- Saturation
- Blue
- Red
- Green
- Cyan
- Yellow
- Colour Smoothness
- Faux Hubble
- Faux HOO
- Foraxx-Inspired
- Gold & Cyan
- Natural Bi-colour

Levels is implemented as a five-band tonal adjustment with explicit controls for:

- Darkest
- Dark
- Mid
- Light
- Brightest

The faux palette adjustments operate on prepared RGB images rather than reconstructed
narrowband channels. `Amount` is a wet/dry blend from the incoming image state to the
full palette result, `Nebula` is the recommended default target, and the same adjustments
can also be constrained with regions or directed at `Dark Dust` while leaving `Stars`
more natural.

## Export

Final exports render through the shared engine rather than through a desktop-only path.

Screen export currently supports:

- PNG
- JPEG
- TIFF
- Native-size or upscaled output
- `Preserve pixels` upscale mode for mapping the mastered image onto a larger pixel grid without inventing new detail

Print export currently supports:

- PNG
- JPEG
- TIFF
- Physical dimensions
- DPI / PPI targeting
- Shared-renderer output planning

![Screen export dialog](docs/images/readme/export-screen-dialog.png)

## Local Packaging

The desktop application now has explicit packaging paths for both macOS and Windows.

Prerequisites:

- Python 3.13
- Synced workspace dependencies with `uv`
- macOS for `.app` and `.dmg` production
- Windows for native Windows desktop builds

Build steps:

```bash
uv sync --dev
make package-desktop
```

Or call the packaging entrypoint directly:

```bash
uv run python scripts/package_desktop.py
```

On Windows PowerShell:

```powershell
uv sync --dev
uv run python scripts/package_desktop.py
```

Artifacts are written to `dist/`.

On macOS:

- `dist/Nebula Master.app`
- `dist/NebulaMaster.app.zip`
- `dist/NebulaMaster.dmg`

On Windows:

- `dist/Nebula Master/`
- `dist/NebulaMaster-windows.zip`
- `dist/NebulaMaster-Setup.exe` when Inno Setup is available

The packaging entrypoint is [scripts/package_desktop.py](/Users/damon/gitlab/nebulamaster/scripts/package_desktop.py), which:

- builds the app via PyInstaller using [apps/desktop/packaging/nebula_master.spec](/Users/damon/gitlab/nebulamaster/apps/desktop/packaging/nebula_master.spec)
- generates the bundled Nebula Master application icon from [scripts/build_app_icon.py](/Users/damon/gitlab/nebulamaster/scripts/build_app_icon.py)
- emits `.icns` for macOS and `.ico` for Windows
- packages native desktop artifacts for the current platform
- emits a portable Windows `.zip` plus an installer `.exe` when Inno Setup is installed

## CI And Releases

The repository includes three GitHub Actions workflows:

- [.github/workflows/ci.yml](/Users/damon/gitlab/nebulamaster/.github/workflows/ci.yml) runs the main lint, typecheck, and test suite on Ubuntu and a Windows desktop import smoke test on `windows-latest`.
- [.github/workflows/create-release.yml](/Users/damon/gitlab/nebulamaster/.github/workflows/create-release.yml) is a manual release-tag workflow. It validates the requested version, confirms it matches [pyproject.toml](/Users/damon/gitlab/nebulamaster/pyproject.toml), and pushes the version tag to GitHub.
- [.github/workflows/package-desktop.yml](/Users/damon/gitlab/nebulamaster/.github/workflows/package-desktop.yml) builds standalone desktop artifacts on macOS and Windows on demand and on immutable semver release tags.

Release flow:

1. Bump the repo version with `make bump-version VERSION=0.2.0` and push the commit to GitHub.
2. In GitHub, open `Actions` -> `Create Release` -> `Run workflow`.
3. Enter a version tag such as `v0.2.0` and choose the target ref, usually `main`.
4. The workflow confirms the tag matches the repo version, then creates and pushes the annotated tag.
5. The same workflow then starts `Package Desktop` explicitly for that tag, which avoids GitHub's suppressed follow-on workflow behavior for `GITHUB_TOKEN` tag pushes.
6. `Package Desktop` creates a draft release, uploads the macOS and Windows assets to that draft, and only then publishes the immutable release.
7. After publish, `Package Desktop` updates the movable major tag, for example `v0`, to the released commit.

This gives Nebula Master both immutable versioned releases such as `v0.2.1` and a movable convenience tag such as `v0`.

For non-release test builds, run the `Package Desktop` workflow manually with `workflow_dispatch` and download the artifacts from the workflow run.

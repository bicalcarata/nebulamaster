from __future__ import annotations

import re
import shutil
from pathlib import Path

from image_io import inspect_image, sha256_file
from project_io import save_model_file, save_project_file
from project_model import (
    SCHEMA_VERSION,
    ColourPoint,
    FileReference,
    NoAlignment,
    PaletteFile,
    PluginLockEntry,
    PluginLockFile,
    ProjectFile,
    ProjectMetadata,
    ScreenRenderProfile,
    SemanticChannel,
    SourceImage,
    WeightedAverageSourceMix,
)
from project_model.models import (
    ColourValue,
    PluginLockReference,
    PreviewSettings,
    RenderProfileFile,
)


class ProjectScaffoldError(Exception):
    pass


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "nebula-project"


def scaffold_project_from_image(
    *,
    source_path: Path,
    destination_parent: Path,
    project_name: str,
) -> Path:
    if not source_path.is_file():
        raise ProjectScaffoldError(f"Source image does not exist: {source_path}")
    if not destination_parent.exists():
        raise ProjectScaffoldError(f"Destination folder does not exist: {destination_parent}")
    if not destination_parent.is_dir():
        raise ProjectScaffoldError(
            f"Destination is not a folder: {destination_parent}"
        )

    try:
        inspect_image(source_path)
    except Exception as exc:  # pragma: no cover - Pillow-specific failure paths
        raise ProjectScaffoldError(f"Source image could not be read: {source_path}") from exc

    clean_name = project_name.strip()
    if not clean_name:
        raise ProjectScaffoldError("Project name cannot be empty")

    project_dir = destination_parent / clean_name
    if project_dir.exists():
        raise ProjectScaffoldError(f"Project folder already exists: {project_dir}")

    source_id = "source-01"
    source_filename = f"{source_id}{source_path.suffix.lower()}"
    source_relative_path = Path("sources") / source_filename
    palette_relative_path = Path("palettes/default-nebula.yaml")
    profile_relative_path = Path("render_profiles/screen-preview.yaml")
    plugins_relative_path = Path("plugins/lock.yaml")

    try:
        (project_dir / "sources").mkdir(parents=True, exist_ok=False)
        (project_dir / "palettes").mkdir(parents=True, exist_ok=False)
        (project_dir / "render_profiles").mkdir(parents=True, exist_ok=False)
        (project_dir / "plugins").mkdir(parents=True, exist_ok=False)

        copied_source_path = project_dir / source_relative_path
        shutil.copy2(source_path, copied_source_path)
        checksum = f"sha256:{sha256_file(copied_source_path)}"

        project = ProjectFile(
            schema_version=SCHEMA_VERSION,
            project=ProjectMetadata(
                id=_slugify(clean_name),
                name=clean_name,
            ),
            sources=[
                SourceImage(
                    id=source_id,
                    path=source_relative_path,
                    name=source_path.stem,
                    role="base",
                    reference=True,
                    enabled=True,
                    weight=1.0,
                    checksum=checksum,
                    alignment=NoAlignment(),
                )
            ],
            semantic_channels=[
                SemanticChannel(
                    id="combined",
                    name="Combined Image",
                    description="Full image before semantic targeting",
                ),
                SemanticChannel(
                    id="nebula",
                    name="Nebula",
                    description="Main nebula emission",
                ),
                SemanticChannel(
                    id="stars",
                    name="Stars",
                    description="Compact stellar sources",
                ),
            ],
            palettes=[FileReference(id="default-nebula", path=palette_relative_path)],
            regions=[],
            render_profiles=[
                FileReference(id="screen-preview", path=profile_relative_path)
            ],
            plugins=PluginLockReference(path=plugins_relative_path),
            source_mix=WeightedAverageSourceMix(),
            rules=[],
        )
        palette = PaletteFile(
            schema_version=SCHEMA_VERSION,
            id="default-nebula",
            colour_points=[
                ColourPoint(
                    id="nebula-blue",
                    name="Nebula Blue Point",
                    value=ColourValue(
                        model="working-rgb",
                        channels=(0.31, 0.10, 0.43),
                    ),
                ),
                ColourPoint(
                    id="star-blue",
                    name="Star Blue Point",
                    value=ColourValue(
                        model="working-rgb",
                        channels=(0.62, 0.71, 0.95),
                    ),
                ),
                ColourPoint(
                    id="nebula-red",
                    name="Nebula Red Point",
                    value=ColourValue(
                        model="working-rgb",
                        channels=(0.58, 0.20, 0.18),
                    ),
                ),
                ColourPoint(
                    id="nebula-cyan",
                    name="Nebula Cyan Point",
                    value=ColourValue(
                        model="working-rgb",
                        channels=(0.24, 0.58, 0.62),
                    ),
                ),
                ColourPoint(
                    id="nebula-green",
                    name="Nebula Green Point",
                    value=ColourValue(
                        model="working-rgb",
                        channels=(0.26, 0.44, 0.22),
                    ),
                ),
                ColourPoint(
                    id="nebula-yellow",
                    name="Nebula Yellow Point",
                    value=ColourValue(
                        model="working-rgb",
                        channels=(0.64, 0.56, 0.20),
                    ),
                ),
            ],
        )
        profile = RenderProfileFile(
            schema_version=SCHEMA_VERSION,
            id="screen-preview",
            name="Screen Preview",
            profile=ScreenRenderProfile(
                type="screen",
                format="png",
                color_space="srgb",
                bit_depth=8,
                width_px=1280,
                interpolation="lanczos",
            ),
            preview=PreviewSettings(cacheable=True),
        )
        plugins = PluginLockFile(
            schema_version=SCHEMA_VERSION,
            plugins=[
                PluginLockEntry(id="core.semantic-masks", version="1.2.0"),
                PluginLockEntry(id="core.transforms", version="1.0.4"),
            ],
        )

        save_project_file(project_dir / "project.yaml", project)
        save_model_file(project_dir / palette_relative_path, palette)
        save_model_file(project_dir / profile_relative_path, profile)
        save_model_file(project_dir / plugins_relative_path, plugins)
    except Exception:
        if project_dir.exists():
            shutil.rmtree(project_dir)
        raise

    return project_dir / "project.yaml"

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml
from project_model import ProjectFile
from pydantic import BaseModel

PROJECT_FILE_NAME = "project.yaml"


class ProjectPathError(Exception):
    pass


class YamlFormatError(Exception):
    pass


def locate_project_file(project_path: Path) -> Path:
    if project_path.is_dir():
        candidate = project_path / PROJECT_FILE_NAME
        if candidate.is_file():
            return candidate
        raise ProjectPathError(f"project declaration not found: {candidate}")

    if project_path.is_file():
        return project_path

    raise ProjectPathError(f"project path does not exist: {project_path}")


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            content = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise YamlFormatError(f"invalid YAML in {path}") from exc

    if not isinstance(content, dict):
        raise YamlFormatError(f"expected YAML mapping in {path}")
    return content


def load_model_file[ModelT: BaseModel](model_type: type[ModelT], path: Path) -> ModelT:
    data = read_yaml_mapping(path)
    return model_type.model_validate(data)


def load_project_file(path: Path) -> ProjectFile:
    return load_model_file(ProjectFile, path)


def resolve_reference_path(project_dir: Path, relative_path: Path) -> Path:
    return (project_dir / relative_path).resolve()


def write_yaml_mapping(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as handle:
        yaml.safe_dump(data, handle, sort_keys=False)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def save_model_file[ModelT: BaseModel](path: Path, model: ModelT) -> None:
    payload = model.model_dump(mode="json", exclude_none=True)
    if not isinstance(payload, dict):
        raise TypeError("expected model dump to produce a mapping")
    write_yaml_mapping(path, payload)


def save_project_file(path: Path, project: ProjectFile) -> None:
    save_model_file(path, project)

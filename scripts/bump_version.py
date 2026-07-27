from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.-]+)?$")

PYPROJECT_FILES = [
    ROOT / "pyproject.toml",
    ROOT / "apps" / "desktop" / "pyproject.toml",
    ROOT / "apps" / "renderer-cli" / "pyproject.toml",
    ROOT / "packages" / "engine" / "pyproject.toml",
    ROOT / "packages" / "image-io" / "pyproject.toml",
    ROOT / "packages" / "project-io" / "pyproject.toml",
    ROOT / "packages" / "project-model" / "pyproject.toml",
    ROOT / "packages" / "versioning" / "pyproject.toml",
]

PYPROJECT_VERSION_PATTERN = re.compile(r'(?m)^version = "(?P<version>[^"]+)"$')
INIT_FILE = ROOT / "apps" / "desktop" / "src" / "nebula_desktop" / "__init__.py"
INIT_VERSION_PATTERN = re.compile(r'(?m)^__version__ = "(?P<version>[^"]+)"$')
RENDERER_FALLBACK_FILES = [
    ROOT / "packages" / "engine" / "src" / "engine" / "preview.py",
    ROOT / "packages" / "engine" / "src" / "engine" / "render.py",
]
RENDERER_FALLBACK_PATTERN = re.compile(r'(?m)^        return "(?P<version>[^"]+)"$')
SPEC_FILE = ROOT / "apps" / "desktop" / "packaging" / "nebula_master.spec"
SPEC_VERSION_PATTERNS = [
    re.compile(r'(?m)^            "CFBundleShortVersionString": "(?P<version>[^"]+)",$'),
    re.compile(r'(?m)^            "CFBundleVersion": "(?P<version>[^"]+)",$'),
]


def _read_root_version() -> str:
    match = PYPROJECT_VERSION_PATTERN.search(PYPROJECT_FILES[0].read_text())
    if match is None:
        raise SystemExit(f"Could not determine version from {PYPROJECT_FILES[0]}.")
    return match.group("version")


def _replace_single(pattern: re.Pattern[str], content: str, new_version: str, path: Path) -> str:
    match = pattern.search(content)
    if match is None:
        raise SystemExit(f"Could not find version declaration in {path}.")
    return pattern.sub(
        lambda _: _.group(0).replace(match.group("version"), new_version),
        content,
        count=1,
    )


def _update_file(path: Path, pattern: re.Pattern[str], new_version: str) -> None:
    original = path.read_text()
    updated = _replace_single(pattern, original, new_version, path)
    if updated != original:
        path.write_text(updated)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/bump_version.py <version>", file=sys.stderr)
        return 1

    new_version = argv[1]
    if SEMVER_PATTERN.fullmatch(new_version) is None:
        print(f"Invalid version: {new_version}", file=sys.stderr)
        return 1

    old_version = _read_root_version()
    if old_version == new_version:
        print(f"Version is already {new_version}.")
        return 0

    for path in PYPROJECT_FILES:
        _update_file(path, PYPROJECT_VERSION_PATTERN, new_version)
        print(f"Updated {path.relative_to(ROOT)}")

    _update_file(INIT_FILE, INIT_VERSION_PATTERN, new_version)
    print(f"Updated {INIT_FILE.relative_to(ROOT)}")

    for path in RENDERER_FALLBACK_FILES:
        _update_file(path, RENDERER_FALLBACK_PATTERN, new_version)
        print(f"Updated {path.relative_to(ROOT)}")

    spec_content = SPEC_FILE.read_text()
    updated_spec = spec_content
    for pattern in SPEC_VERSION_PATTERNS:
        updated_spec = _replace_single(pattern, updated_spec, new_version, SPEC_FILE)
    if updated_spec != spec_content:
        SPEC_FILE.write_text(updated_spec)
    print(f"Updated {SPEC_FILE.relative_to(ROOT)}")

    print(f"Bumped version from {old_version} to {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

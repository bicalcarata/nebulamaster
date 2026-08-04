from __future__ import annotations

import pytest

from scripts.package_desktop import (
    PackagingError,
    _macos_architecture_label,
    _macos_artifact_names,
)


@pytest.mark.parametrize("machine", ["arm64", "aarch64"])
def test_macos_apple_silicon_artifact_names(machine: str) -> None:
    assert _macos_architecture_label(machine) == "Apple-Silicon"
    assert _macos_artifact_names(machine) == (
        "NebulaMaster-MacOS-Apple-Silicon.app.zip",
        "NebulaMaster-MacOS-Apple-Silicon.dmg",
    )


@pytest.mark.parametrize("machine", ["x86_64", "amd64"])
def test_macos_intel_artifact_names(machine: str) -> None:
    assert _macos_architecture_label(machine) == "Intel"
    assert _macos_artifact_names(machine) == (
        "NebulaMaster-MacOS-Intel.app.zip",
        "NebulaMaster-MacOS-Intel.dmg",
    )


def test_unknown_macos_architecture_fails() -> None:
    with pytest.raises(PackagingError, match="Unsupported macOS packaging architecture"):
        _macos_artifact_names("powerpc")

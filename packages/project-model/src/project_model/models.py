from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SEMVER_PATTERN = r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SelectionSource = Literal["original", "current"]
ColourChannel = Literal["red", "green", "blue"]
SemanticTarget = Literal["combined", "nebula", "stars", "dark_dust"]
FauxPaletteId = Literal["hubble"]
InterpolationMethod = Literal["lanczos", "bicubic", "nearest"]
RenderProfileType = Literal["screen", "print", "archive"]
OutputFormat = Literal["png", "jpeg", "tiff"]
ColourSpace = Literal["srgb"]
PrintUnits = Literal["cm", "inches"]
CropMode = Literal["fit", "fill", "exact"]
SourceRole = Literal["base", "red", "blue", "cyan", "luminance", "neutral", "custom"]
AlignmentMode = Literal["none", "inspect", "translation", "manual"]
SourceMixMode = Literal["weighted_average", "lighten", "screen", "channel_contribution"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RelativePathModel(StrictModel):
    @staticmethod
    def validate_relative_path(value: Path) -> Path:
        if value.is_absolute():
            raise ValueError("path must be relative to the project directory")
        if ".." in value.parts:
            raise ValueError("path must not traverse outside the project directory")
        return value


class ProjectMetadata(StrictModel):
    id: Identifier
    name: DisplayName
    created_at: datetime | None = None


class SourceImage(StrictModel):
    id: Identifier
    path: Path
    name: DisplayName | None = None
    role: SourceRole = "base"
    reference: bool = False
    enabled: bool = True
    weight: float = Field(default=1.0, ge=0.0)
    checksum: str | None = None
    alignment: SourceAlignmentDeclaration | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Path) -> Path:
        RelativePathModel.validate_relative_path(value)
        if value.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError("source image must use png, jpeg, jpg, tif or tiff")
        return value

    @model_validator(mode="after")
    def normalize_source(self) -> SourceImage:
        if self.name is None:
            self.name = self.id
        if self.alignment is None:
            self.alignment = NoAlignment()
        return self


class NoAlignment(StrictModel):
    mode: Literal["none"] = "none"


class InspectAlignment(StrictModel):
    mode: Literal["inspect"] = "inspect"
    max_shift_px: float = Field(default=32.0, gt=0.0)


class TranslationAlignment(StrictModel):
    mode: Literal["translation"] = "translation"
    max_shift_px: float = Field(default=32.0, gt=0.0)


class ManualAlignment(StrictModel):
    mode: Literal["manual"] = "manual"
    x_px: float = 0.0
    y_px: float = 0.0


SourceAlignmentDeclaration = Annotated[
    NoAlignment | InspectAlignment | TranslationAlignment | ManualAlignment,
    Field(discriminator="mode"),
]


class ChannelContributionEntry(StrictModel):
    source: Identifier
    red: float = 0.0
    green: float = 0.0
    blue: float = 0.0


class WeightedAverageSourceMix(StrictModel):
    mode: Literal["weighted_average"] = "weighted_average"


class LightenSourceMix(StrictModel):
    mode: Literal["lighten"] = "lighten"


class ScreenSourceMix(StrictModel):
    mode: Literal["screen"] = "screen"


class ChannelContributionSourceMix(StrictModel):
    mode: Literal["channel_contribution"] = "channel_contribution"
    contributions: list[ChannelContributionEntry] = Field(min_length=1)


SourceMixDeclaration = Annotated[
    WeightedAverageSourceMix
    | LightenSourceMix
    | ScreenSourceMix
    | ChannelContributionSourceMix,
    Field(discriminator="mode"),
]


class SemanticChannel(StrictModel):
    id: Identifier
    name: DisplayName
    description: str | None = None


class DarkDustSettings(StrictModel):
    enabled: bool = True
    sensitivity: float = Field(default=0.58, ge=0.0, le=1.0)
    structure_size: float = Field(default=0.09, gt=0.0, le=1.0)
    background_protection: float = Field(default=0.30, ge=0.0, le=1.0)
    softness: float = Field(default=0.22, ge=0.0, le=1.0)


class FileReference(StrictModel):
    id: Identifier
    path: Path

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Path) -> Path:
        return RelativePathModel.validate_relative_path(value)


class PluginLockReference(StrictModel):
    path: Path

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Path) -> Path:
        return RelativePathModel.validate_relative_path(value)


class RangeSelection(StrictModel):
    min: float = Field(ge=0.0, le=1.0)
    max: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> RangeSelection:
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        return self


class RuleMatch(StrictModel):
    colour_point: Identifier | None = None
    colour_range: float = Field(default=0.2, ge=0.0, le=1.0)
    brightness: RangeSelection | None = None
    saturation: RangeSelection | None = None
    softness: float = Field(default=0.5, ge=0.0, le=1.0)
    regions: list[Identifier] = Field(default_factory=list)
    semantic_mask: Identifier | None = None


class ColourAmountTransform(StrictModel):
    type: Literal["colour_amount"]
    channel: ColourChannel
    amount: float = Field(ge=0.0, le=4.0)
    preserve_luminance: bool = True


class ShiftColourPointTransform(StrictModel):
    type: Literal["shift_colour_point"]
    target_colour_point: Identifier
    amount: float = Field(ge=-1.0, le=1.0)
    preserve_luminance: bool = True


class BrightnessTransform(StrictModel):
    type: Literal["brightness"]
    amount: float = Field(ge=0.0, le=4.0)


class SaturationTransform(StrictModel):
    type: Literal["saturation"]
    amount: float = Field(ge=0.0, le=4.0)


class LevelsTransform(StrictModel):
    type: Literal["levels"]
    darkest: float = Field(default=1.0, ge=0.0, le=4.0)
    dark: float = Field(default=1.0, ge=0.0, le=4.0)
    mid: float = Field(default=1.0, ge=0.0, le=4.0)
    light: float = Field(default=1.0, ge=0.0, le=4.0)
    brightest: float = Field(default=1.0, ge=0.0, le=4.0)


class ColourSmoothingTransform(StrictModel):
    type: Literal["colour_smoothing"]
    radius: float = Field(ge=0.0, le=1.0)
    strength: float = Field(ge=0.0, le=1.0)


class FauxPaletteTransform(StrictModel):
    type: Literal["faux_palette"]
    palette: FauxPaletteId
    amount: float = Field(default=0.0, ge=0.0, le=1.0)
    preserve_brightness: bool = True


TransformationDeclaration = Annotated[
    ColourAmountTransform
    | ShiftColourPointTransform
    | BrightnessTransform
    | SaturationTransform
    | LevelsTransform
    | ColourSmoothingTransform
    | FauxPaletteTransform,
    Field(discriminator="type"),
]
RuleTransform = TransformationDeclaration


class RuleMetadata(StrictModel):
    label: DisplayName | None = None
    intent: Identifier | None = None


class DeclarativeRule(StrictModel):
    id: Identifier
    name: DisplayName | None = None
    enabled: bool = True
    selection_source: SelectionSource = "current"
    target: SemanticTarget
    match: RuleMatch = Field(default_factory=RuleMatch)
    regions: list[Identifier] = Field(default_factory=list)
    transform: TransformationDeclaration
    metadata: RuleMetadata | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_rule(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        match = data.get("match")
        if isinstance(match, dict) and "regions" in match and "regions" not in data:
            data["regions"] = match["regions"]

        if "selection_source" not in data:
            data["selection_source"] = "current"

        if "name" not in data:
            metadata = data.get("metadata")
            if isinstance(metadata, dict) and metadata.get("label"):
                data["name"] = metadata["label"]
            elif data.get("id"):
                data["name"] = data["id"]

        transform = data.get("transform")
        if isinstance(transform, dict) and "type" not in transform:
            preserve_brightness = bool(transform.get("preserve_brightness", False))
            rgb_keys = ["red", "green", "blue"]
            present_rgb = [
                (channel, transform.get(channel))
                for channel in rgb_keys
                if transform.get(channel) is not None
            ]

            if len(present_rgb) == 1:
                channel, legacy_value = present_rgb[0]
                legacy_amount = float(legacy_value) if legacy_value is not None else 0.0
                data["transform"] = {
                    "type": "colour_amount",
                    "channel": channel,
                    "amount": 1.0 + legacy_amount,
                    "preserve_luminance": preserve_brightness,
                }
            elif transform.get("saturation") is not None:
                data["transform"] = {
                    "type": "saturation",
                    "amount": 1.0 + float(transform["saturation"]),
                }

        return data

    @model_validator(mode="after")
    def normalize_rule(self) -> DeclarativeRule:
        if self.match.regions:
            if self.regions and self.regions != self.match.regions:
                raise ValueError("rule regions must not conflict with match.regions")
            if not self.regions:
                self.regions = list(self.match.regions)

        if self.name is None:
            self.name = self.id

        return self


class ColourValue(StrictModel):
    model: Literal["working-rgb"]
    channels: tuple[float, float, float]

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        for channel in value:
            if not 0.0 <= channel <= 1.0:
                raise ValueError("colour channels must be between 0.0 and 1.0")
        return value


class ColourPoint(StrictModel):
    id: Identifier
    name: DisplayName
    value: ColourValue


class PaletteFile(StrictModel):
    schema_version: int | None = None
    id: Identifier
    colour_points: list[ColourPoint] = Field(min_length=1)


class Feather(StrictModel):
    radius: float = Field(ge=0.0, le=1.0)


class RegionFile(StrictModel):
    schema_version: int | None = None
    id: Identifier
    name: DisplayName
    enabled: bool = True
    feather: Feather | None = None
    polygon: list[tuple[float, float]] = Field(min_length=3)

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for x, y in value:
            if not 0.0 <= x <= 1.0:
                raise ValueError("polygon x coordinates must be between 0.0 and 1.0")
            if not 0.0 <= y <= 1.0:
                raise ValueError("polygon y coordinates must be between 0.0 and 1.0")

        unique_points = {point for point in value}
        if len(unique_points) < 3:
            raise ValueError("polygon must contain at least three distinct points")

        area = 0.0
        for index, point in enumerate(value):
            next_point = value[(index + 1) % len(value)]
            area += point[0] * next_point[1] - next_point[0] * point[1]
        if area == 0:
            raise ValueError("polygon must enclose a non-zero area")
        return value


class CropDeclaration(StrictModel):
    x: float = Field(default=0.0, ge=0.0, le=1.0)
    y: float = Field(default=0.0, ge=0.0, le=1.0)
    width: float = Field(default=1.0, gt=0.0, le=1.0)
    height: float = Field(default=1.0, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> CropDeclaration:
        if self.x + self.width > 1.0:
            raise ValueError("crop width must remain inside source bounds")
        if self.y + self.height > 1.0:
            raise ValueError("crop height must remain inside source bounds")
        return self


class LegacyOutputDimensions(StrictModel):
    mode: Literal["source"]


class LegacyOutputSettings(StrictModel):
    format: OutputFormat
    color_space: ColourSpace
    bit_depth: Literal[8, 16, 32]
    dimensions: LegacyOutputDimensions


class PreviewSettings(StrictModel):
    cacheable: bool = True


class RenderProfileBase(StrictModel):
    type: RenderProfileType
    color_space: ColourSpace = "srgb"
    format: OutputFormat
    bit_depth: Literal[8, 16]
    interpolation: InterpolationMethod = "lanczos"
    jpeg_quality: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def validate_common_constraints(self) -> RenderProfileBase:
        if self.format == "jpeg" and self.bit_depth != 8:
            raise ValueError("jpeg output supports 8-bit only")
        if self.color_space != "srgb":
            raise ValueError("only srgb is supported in this schema version")
        return self


class ScreenRenderProfile(RenderProfileBase):
    type: Literal["screen"]
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)


class PrintRenderProfile(RenderProfileBase):
    type: Literal["print"]
    width: float = Field(gt=0.0)
    height: float = Field(gt=0.0)
    units: PrintUnits
    ppi: int = Field(default=300, gt=0)
    crop_mode: CropMode = "fit"

    @model_validator(mode="after")
    def validate_print_format(self) -> PrintRenderProfile:
        if self.format == "jpeg":
            raise ValueError("print profiles do not support jpeg output")
        return self


class ArchiveRenderProfile(RenderProfileBase):
    type: Literal["archive"]
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_archive_format(self) -> ArchiveRenderProfile:
        if self.format == "jpeg":
            raise ValueError("archive profiles do not support lossy jpeg output")
        return self


RenderProfileDeclaration = Annotated[
    ScreenRenderProfile | PrintRenderProfile | ArchiveRenderProfile,
    Field(discriminator="type"),
]


class RenderProfileFile(StrictModel):
    schema_version: int | None = None
    id: Identifier
    name: DisplayName
    profile: RenderProfileDeclaration
    preview: PreviewSettings = Field(default_factory=PreviewSettings)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_profile(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "profile" in data:
            return data
        if "output" not in data:
            return data
        legacy = LegacyOutputSettings.model_validate(data["output"])
        data["profile"] = {
            "type": "screen",
            "format": legacy.format,
            "color_space": legacy.color_space,
            "bit_depth": 16 if legacy.bit_depth == 32 else legacy.bit_depth,
        }
        return data


class PluginLockEntry(StrictModel):
    id: Identifier
    version: Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)]


class PluginLockFile(StrictModel):
    schema_version: int | None = None
    plugins: list[PluginLockEntry] = Field(default_factory=list)


class ProjectFile(StrictModel):
    schema_version: int
    project: ProjectMetadata
    sources: list[SourceImage] = Field(min_length=1)
    semantic_channels: list[SemanticChannel] = Field(min_length=1)
    palettes: list[FileReference] = Field(default_factory=list)
    regions: list[FileReference] = Field(default_factory=list)
    render_profiles: list[FileReference] = Field(default_factory=list)
    plugins: PluginLockReference
    dark_dust: DarkDustSettings = Field(default_factory=DarkDustSettings)
    crop: CropDeclaration = Field(default_factory=CropDeclaration)
    source_mix: SourceMixDeclaration = Field(default_factory=WeightedAverageSourceMix)
    rules: list[DeclarativeRule] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {value}")
        return value


class ProjectBundle(StrictModel):
    project_dir: Path
    project_file: Path
    project: ProjectFile
    palettes: dict[str, PaletteFile] = Field(default_factory=dict)
    regions: dict[str, RegionFile] = Field(default_factory=dict)
    render_profiles: dict[str, RenderProfileFile] = Field(default_factory=dict)
    plugin_lock: PluginLockFile | None = None


DiffSignificance = Literal["informational", "visual", "structural", "compatibility"]


class DiffProjectIdentity(StrictModel):
    project_file: Path
    project_id: Identifier
    project_name: DisplayName
    schema_version: int
    project_file_sha256: str


class DiffExplanationEntry(StrictModel):
    code: Identifier
    entity_type: Identifier
    entity_id: Identifier | None = None
    summary: DisplayName


class ProjectDiffChange(StrictModel):
    code: Identifier
    entity_type: Identifier
    entity_id: Identifier | None = None
    entity_name: DisplayName | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    significance: list[DiffSignificance] = Field(min_length=1)
    human_summary: DisplayName
    technical_path: str | None = None


class RuleReorderChange(StrictModel):
    code: Literal["rule.reordered"] = "rule.reordered"
    entity_type: Literal["rule"] = "rule"
    entity_id: Identifier
    entity_name: DisplayName | None = None
    old_position: int = Field(ge=1)
    new_position: int = Field(ge=1)
    significance: list[DiffSignificance] = Field(
        default_factory=lambda: cast(
            list[DiffSignificance],
            ["structural", "visual"],
        )
    )
    human_summary: DisplayName
    technical_path: str | None = None


class ProjectDiffSummary(StrictModel):
    added: int = Field(ge=0, default=0)
    removed: int = Field(ge=0, default=0)
    modified: int = Field(ge=0, default=0)
    reordered_rules: int = Field(ge=0, default=0)
    informational: int = Field(ge=0, default=0)
    visual: int = Field(ge=0, default=0)
    structural: int = Field(ge=0, default=0)
    compatibility: int = Field(ge=0, default=0)


class ProjectDiffDocument(StrictModel):
    schema_version: int = 1
    project_a: DiffProjectIdentity
    project_b: DiffProjectIdentity
    summary: ProjectDiffSummary
    added_items: list[ProjectDiffChange] = Field(default_factory=list)
    removed_items: list[ProjectDiffChange] = Field(default_factory=list)
    modified_items: list[ProjectDiffChange] = Field(default_factory=list)
    reordered_rules: list[RuleReorderChange] = Field(default_factory=list)
    rendering_significant_changes: list[ProjectDiffChange | RuleReorderChange] = Field(
        default_factory=list
    )
    explanations: list[DiffExplanationEntry] = Field(default_factory=list)

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms
from pydantic import BaseModel, ConfigDict


class ImageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int
    height: int
    mode: str
    format: str | None


class CanonicalImage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    data: np.ndarray
    width: int
    height: int


class SaveImageOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str
    bit_depth: int
    jpeg_quality: int | None = None


def inspect_image(path: Path) -> ImageMetadata:
    with Image.open(path) as image:
        width, height = image.size
        return ImageMetadata(width=width, height=height, mode=image.mode, format=image.format)


def load_image_array(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image)


def load_canonical_image(path: Path) -> CanonicalImage:
    with Image.open(path) as image:
        rgba_image = image.convert("RGBA")
        rgba = np.asarray(rgba_image, dtype=np.float32) / 255.0

    alpha = rgba[..., 3:4]
    rgb = rgba[..., :3] * alpha
    height, width, _ = rgb.shape
    return CanonicalImage(data=rgb.astype(np.float32, copy=False), width=width, height=height)


def resize_to_max_edge(image: CanonicalImage, max_edge: int) -> CanonicalImage:
    if max(image.width, image.height) <= max_edge:
        return image

    scale = max_edge / max(image.width, image.height)
    width = max(1, int(round(image.width * scale)))
    height = max(1, int(round(image.height * scale)))

    source = np.clip(image.data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    resized = Image.fromarray(source, mode="RGB").resize((width, height), Image.Resampling.LANCZOS)
    data = np.asarray(resized, dtype=np.float32) / 255.0
    return CanonicalImage(data=data.astype(np.float32, copy=False), width=width, height=height)


def _resampling(method: str) -> Image.Resampling:
    if method == "lanczos":
        return Image.Resampling.LANCZOS
    if method == "bicubic":
        return Image.Resampling.BICUBIC
    raise ValueError(f"unsupported interpolation method: {method}")


def resize_exact(image: CanonicalImage, width: int, height: int, *, method: str) -> CanonicalImage:
    if image.width == width and image.height == height:
        return image

    source = np.clip(image.data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    resized = Image.fromarray(source, mode="RGB").resize((width, height), _resampling(method))
    data = np.asarray(resized, dtype=np.float32) / 255.0
    return CanonicalImage(data=data.astype(np.float32, copy=False), width=width, height=height)


def crop_image(
    image: CanonicalImage,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> CanonicalImage:
    cropped = image.data[top:bottom, left:right]
    height, width, _channels = cropped.shape
    return CanonicalImage(data=cropped.astype(np.float32, copy=False), width=width, height=height)


def translate_image(image: CanonicalImage, *, x_px: float, y_px: float) -> CanonicalImage:
    if abs(x_px) < 1e-9 and abs(y_px) < 1e-9:
        return image

    height, width = image.height, image.width
    y_freq = np.fft.fftfreq(height).reshape(-1, 1)
    x_freq = np.fft.fftfreq(width).reshape(1, -1)
    phase = np.exp(-2j * np.pi * (y_freq * y_px + x_freq * x_px))

    translated_channels: list[np.ndarray] = []
    for channel_index in range(image.data.shape[2]):
        spectrum = np.fft.fft2(image.data[:, :, channel_index])
        shifted = np.fft.ifft2(spectrum * phase).real.astype(np.float32, copy=False)
        translated_channels.append(shifted)

    data = np.stack(translated_channels, axis=-1).astype(np.float32, copy=False)
    return CanonicalImage(data=data, width=width, height=height)


def save_png(path: Path, data: np.ndarray) -> None:
    clipped = np.clip(data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    Image.fromarray(clipped, mode="RGB").save(path, format="PNG")


def save_mask_png(path: Path, data: np.ndarray) -> None:
    clipped = np.clip(data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    Image.fromarray(clipped, mode="L").save(path, format="PNG")


def save_image(path: Path, image: CanonicalImage, options: SaveImageOptions) -> None:
    srgb_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    icc_bytes = srgb_profile.tobytes()

    if options.bit_depth == 8:
        clipped = np.clip(image.data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
        pil_image = Image.fromarray(clipped, mode="RGB")
    elif options.bit_depth == 16:
        clipped = np.clip(image.data * 65535.0 + 0.5, 0.0, 65535.0).astype(">u2", copy=False)
        if options.format == "png":
            raise ValueError("16-bit PNG output is not supported by this renderer build")
        pil_image = Image.frombytes(
            "RGB",
            (image.width, image.height),
            clipped.tobytes(),
            "raw",
            "RGB;16B",
        )
    else:
        raise ValueError(f"unsupported bit depth: {options.bit_depth}")

    save_kwargs: dict[str, object] = {"icc_profile": icc_bytes}
    if options.format == "jpeg":
        save_kwargs["quality"] = options.jpeg_quality or 95
    if options.format == "tiff":
        save_kwargs["compression"] = "tiff_lzw"
    pil_image.save(path, format=options.format.upper(), **save_kwargs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()

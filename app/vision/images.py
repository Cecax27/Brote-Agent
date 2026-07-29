from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.config.settings import Settings  # noqa: TC001

_MIME_TO_FORMAT: dict[str, str] = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}

_INVALID_IMAGE_SIZE = "La imagen es demasiado grande."
_INVALID_IMAGE_PROCESS = "La imagen no se pudo procesar."
_INVALID_IMAGE_FORMAT = "El formato de imagen no está permitido."


class InvalidImageError(Exception):
    pass


def sniff_allowed_mime(raw: bytes, settings: Settings) -> str | None:
    try:
        img = Image.open(BytesIO(raw))
        pil_format = img.format
    except UnidentifiedImageError:
        return None

    for mime, fmt in _MIME_TO_FORMAT.items():
        if fmt == pil_format and mime in settings.vision_allowed_mime:
            return mime
    return None


def _decode_for_format_check(raw: bytes) -> str | None:
    try:
        img = Image.open(BytesIO(raw))
    except (UnidentifiedImageError, OSError):
        return None
    else:
        return img.format


def validate_image_bytes(raw: bytes, settings: Settings) -> None:
    if len(raw) > settings.vision_max_image_bytes:
        raise InvalidImageError(_INVALID_IMAGE_SIZE)
    try:
        img = Image.open(BytesIO(raw))
        img.verify()
    except (UnidentifiedImageError, OSError):
        raise InvalidImageError(_INVALID_IMAGE_PROCESS) from None

    pil_format = _decode_for_format_check(raw)
    if pil_format is None:
        raise InvalidImageError(_INVALID_IMAGE_PROCESS) from None

    allowed = any(_MIME_TO_FORMAT.get(mime) == pil_format for mime in settings.vision_allowed_mime)
    if not allowed:
        raise InvalidImageError(_INVALID_IMAGE_FORMAT)


def resize_image(raw: bytes, settings: Settings) -> bytes:
    img = Image.open(BytesIO(raw))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img).convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    max_dim = settings.vision_max_dimension
    w_orig, h_orig = img.size
    longest = max(w_orig, h_orig)

    if longest > max_dim:
        ratio = max_dim / longest
        new_w = int(w_orig * ratio)
        new_h = int(h_orig * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=settings.vision_jpeg_quality)
    return buf.getvalue()

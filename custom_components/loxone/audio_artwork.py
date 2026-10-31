"""Safe native-player image responses; no changes to global HA rendering."""
from __future__ import annotations

from functools import cache
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


@cache
def music_placeholder() -> tuple[bytes, str]:
    """Load original neutral artwork from an executor, once per process."""
    return Path(__file__).with_name("music-placeholder.png").read_bytes(), "image/png"


def decoded_cover(content: bytes | None) -> tuple[bytes, str] | None:
    """Keep valid original pixels; reject empty, corrupt or excessive images."""
    if not content or len(content) > 8 * 1024 * 1024:
        return None
    try:
        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > 16 * 1024 * 1024:
                return None
            content_type = Image.MIME.get(image.format)
            image.load()
            return (content, content_type) if content_type else None
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None

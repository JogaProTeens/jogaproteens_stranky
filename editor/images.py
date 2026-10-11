"""Photo pipeline: phone photo in, small web-ready files out.

Every photo is turned upright using the phone's rotation flag and saved
again from pixels only, so EXIF data such as GPS location never reaches
the website.
"""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()            # lets Pillow open iPhone HEIC photos

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
RATIOS = {"portrait": (2, 3), "landscape": (3, 2)}

COVER_LONG_EDGE = 1600            # post page
CARD_HEIGHT = 760                 # carousel card, 2x its height on screen
SHARE_SIZE = (1200, 630)          # link previews on Facebook, WhatsApp...
BODY_LONG_EDGE = 1600             # photos inside the text
WEBP_QUALITY = 82


class ImageError(ValueError):
    """A photo that cannot be used. The message is shown to Petra."""


def open_photo(data: bytes) -> Image.Image:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("Fotka je větší než 20 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("Soubor se nepodařilo otevřít jako fotku.") from None
    img = ImageOps.exif_transpose(img)        # stand the photo upright
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (251, 248, 244))   # site cream
        background.paste(img, mask=img.getchannel("A"))
        return background
    return img.convert("RGB")


def crop_to_ratio(img: Image.Image, ratio: tuple[int, int]) -> Image.Image:
    """Cut the centre of the photo to the given width:height ratio."""
    w, h = img.size
    rw, rh = ratio
    if w * rh > h * rw:                       # too wide: trim the sides
        new_w = h * rw // rh
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = w * rh // rw                      # too tall: trim top and bottom
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def shrink(img: Image.Image, long_edge: int) -> Image.Image:
    """Scale down so the longer side is at most long_edge. Never scales up."""
    img = img.copy()
    img.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    return img


def to_webp(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=WEBP_QUALITY, method=4)
    return buf.getvalue()


def to_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue()


def cover_files(data: bytes, orientation: str) -> dict[str, bytes]:
    """The three files every post cover needs, keyed by file name."""
    if orientation not in RATIOS:
        raise ImageError("Neznámý tvar fotky.")
    photo = open_photo(data)
    cropped = crop_to_ratio(photo, RATIOS[orientation])
    card_w = CARD_HEIGHT * RATIOS[orientation][0] // RATIOS[orientation][1]
    share = crop_to_ratio(photo, SHARE_SIZE)
    return {
        "cover.webp": to_webp(shrink(cropped, COVER_LONG_EDGE)),
        "cover-card.webp": to_webp(shrink(cropped, max(card_w, CARD_HEIGHT))),
        "og.jpg": to_jpeg(share.resize(SHARE_SIZE, Image.Resampling.LANCZOS)
                          if share.width >= SHARE_SIZE[0] else share),
    }


def body_photo(data: bytes) -> tuple[str, bytes]:
    """A photo placed inside the text. The name comes from its content, so
    the same photo saved twice is stored once."""
    webp = to_webp(shrink(open_photo(data), BODY_LONG_EDGE))
    return f"img-{hashlib.sha1(webp).hexdigest()[:10]}.webp", webp

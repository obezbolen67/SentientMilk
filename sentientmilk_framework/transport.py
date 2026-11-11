"""What is sent to the provider: the stored conversation, sized to fit the request budget.

Only the newest few images are sent (at least KEPT_IMAGES, fewer than KEPT_IMAGES +
IMAGE_BATCH): the newest step's as the model sees them best (config ``image_pixels``), the others as
thumbnails; older ones become a note.
The provider reads every image of every request again: 42 old thumbnails took it 35-45 s
a call (2026-11-07), the same request without them 14 s. Its prompt cache reuses a request
only as far as the next one repeats it, and a new image comes in a user message, after
which the provider re-reads from the previous user message anyway: so the image before the
new one may change at no cost, and older ones turn into notes IMAGE_BATCH at a time, not
one at every step. The byte budget drops the older half of what is left, then sends the newest
step's pictures at a lower quality, and only then smaller (an app's points in them would then be
off: with the default budget it does not happen). The stored conversation itself is never changed.

Picture size, measured 2026-11-11 against the default model (synthetic 2560 x 1600 screens of small
text, scripts in that session's scratchpad): it counts 600-650 prompt tokens per megapixel up to about
1.6 MP (1,069 tokens), and no more past it. At 768 px wide it read 0 of 63 and 3 of 45 codes in 12-18
px text, at 1280 px 38 and 25, at 1600 x 1000 53 and 33; sent at 2048 or 2560 px it cost the same
tokens and read fewer (53 and 26, 43 and 25): the provider's own shrinking is worse than LANCZOS. JPEG
quality 90 with every colour sample (4:4:4) read as well as PNG, smaller.
"""

import base64
import copy
import io
import json
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

IMAGE_PIXELS = 1_600_000  # what the default model sees of a picture (config image_pixels; 0: as sent)
SHARP = 90  # JPEG quality of a picture to read; from it on every colour sample is kept, so small text stays sharp
LOW = 50  # the newest pictures' quality when the request is still too big without the others
THUMBNAIL = (40_960, 42)  # (pixels, JPEG quality): 256 x 160 of a 16:10 screen
KEPT_IMAGES, IMAGE_BATCH = 3, 4  # images sent: the newest, at least 3 and fewer than 3 + 4
OMITTED_IMAGE = "[Earlier screenshot omitted.]"
DISABLED_IMAGE = "[Image omitted: the model is set up without image support.]"
# The default provider took a 13.7 MiB request (2026-11-11); 800 KiB had been a guess at a proxy's limit.
DEFAULT_BUDGET = 8 * 1024 * 1024


class RequestPayloadTooLarge(ValueError):
    """The prepared request still exceeds the configured body budget."""


def validate_image(data_url) -> str:
    """A base64 data URL that holds a readable picture, or ValueError."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or ";base64," not in data_url:
        raise ValueError("image must be a base64 data URL")
    from PIL import Image

    try:
        with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1], validate=True))) as picture:
            picture.verify()
    except Exception as exc:
        raise ValueError(f"image is not a readable picture: {exc}") from exc
    return data_url


def fitted(width: int, height: int, pixels: int) -> Tuple[int, int]:
    """A picture's size shrunk to at most ``pixels`` pixels (0: as it is), never grown."""
    if not pixels or width * height <= pixels:
        return width, height
    scale = (pixels / (width * height)) ** 0.5
    return max(1, int(width * scale)), max(1, int(height * scale))


def encode_image(data_url: str, pixels: int, quality: int = SHARP, again: bool = False) -> str:
    """A JPEG data URL of at most ``pixels`` pixels (0: any size); a JPEG that already fits is kept as it is,
    unless ``again`` (encoded at ``quality`` to make it smaller)."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return data_url
    try:
        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as image:
            size = fitted(*image.size, pixels)
            if image.format == "JPEG" and size == image.size and not again:
                return data_url
            image = image.convert("RGB")
            if size != image.size:
                image = image.resize(size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True, subsampling=0 if quality >= SHARP else -1)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except Exception as exc:  # a corrupt stored image must not block the conversation
        logger.warning("Could not compact an image: %s", exc)
        return data_url


def _pixels(data_url: str) -> int:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as image:
            return image.width * image.height
    except Exception:  # not a picture: encode_image keeps it as it is
        return 0


def _replace_with_text(block: dict, text: str) -> None:
    block.clear()
    block.update(type="text", text=text)


def prepare_messages(messages: List[dict], max_bytes: int = DEFAULT_BUDGET, *, support_images: bool = True,
                     image_pixels: int = IMAGE_PIXELS) -> List[dict]:
    """A copy of ``messages`` that fits ``max_bytes``; ``messages`` is not changed. The newest step's pictures go
    at most ``image_pixels`` big (0: as they are)."""
    projected = copy.deepcopy(messages)
    placed = [
        (index, block)
        for index, message in enumerate(projected) if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    images = [block for _, block in placed]
    kept = images if support_images else []
    for block in images[:len(images) - len(kept)]:
        _replace_with_text(block, DISABLED_IMAGE)
    # the newest step's images are all readable: frames of a motion, or a before and after, are compared, and
    # as thumbnails beside one readable image they could not be (2026-11-09: animations judged from stills)
    newest = len([1 for index, _ in placed if index == placed[-1][0]]) if kept else 0
    old = max(0, len(kept) - KEPT_IMAGES) // IMAGE_BATCH * IMAGE_BATCH  # moves only every IMAGE_BATCH images
    old = min(old, len(kept) - newest)
    for block in kept[:old]:
        _replace_with_text(block, OMITTED_IMAGE)
    kept = kept[old:]
    for block in kept[:len(kept) - newest]:
        block["image_url"]["url"] = encode_image(block["image_url"]["url"], *THUMBNAIL)
    for block in kept[len(kept) - newest:]:
        block["image_url"]["url"] = encode_image(block["image_url"]["url"], image_pixels)

    def body_size() -> int:
        return len(json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    while len(kept) > newest and body_size() > max_bytes:  # the older half at once, so the past changes rarely
        dropped = max(1, (len(kept) - newest) // 2)
        for block in kept[:dropped]:
            _replace_with_text(block, OMITTED_IMAGE)
        kept = kept[dropped:]
    # past the budget the newest go plainer at their size, then at half their sides, then as thumbnails,
    # oldest first, never away
    for step in ("plainer", "smaller", "thumbnail"):
        for block in kept:
            if body_size() > max_bytes:
                url = block["image_url"]["url"]
                pixels, quality = {"plainer": (0, LOW), "smaller": (_pixels(url) // 4, LOW), "thumbnail": THUMBNAIL}[step]
                block["image_url"]["url"] = encode_image(url, pixels, quality, again=True)
    for message in projected:
        content = message.get("content")
        if isinstance(content, list) and all(
            isinstance(block, dict) and block.get("type") == "text" for block in content
        ):
            message["content"] = "\n".join(block.get("text", "") for block in content)
    size = body_size()
    if size > max_bytes:
        raise RequestPayloadTooLarge(
            f"Prepared request is {size:,} bytes; configured transport budget is {max_bytes:,} bytes"
        )
    return projected

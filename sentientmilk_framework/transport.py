"""What is sent to the provider: the stored conversation, sized to fit the request budget.

The newest image is sent readable and older ones as thumbnails, until the byte budget
drops the older half for notes. The provider's prompt cache reuses a request only as far
as the next one repeats it, and a new image comes in a user message, after which the
provider re-reads from the previous user message anyway: so only the image before the
new one changes, never older ones. The stored conversation itself is never changed.
"""

import base64
import copy
import io
import json
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

IMAGE = (768, 70)  # (longest side, JPEG quality)
IMAGE_REDUCED = (512, 55)  # the newest image, when the request is still too big without the others
THUMBNAIL = (256, 42)
OMITTED_IMAGE = "[Earlier screenshot omitted.]"
DISABLED_IMAGE = "[Image omitted: the model is set up without image support.]"
# Keep below nginx's common 1 MiB request-body default.
DEFAULT_BUDGET = 800 * 1024


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


def encode_image(data_url: str, size: Tuple[int, int]) -> str:
    """A JPEG data URL no larger than ``size``; a JPEG that already fits is kept as is."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return data_url
    max_side, quality = size
    try:
        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as image:
            if image.format == "JPEG" and max(image.size) <= max_side:
                return data_url
            image = image.convert("RGB")
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except Exception as exc:  # a corrupt stored image must not block the conversation
        logger.warning("Could not compact an image: %s", exc)
        return data_url


def _replace_with_text(block: dict, text: str) -> None:
    block.clear()
    block.update(type="text", text=text)


def prepare_messages(messages: List[dict], max_bytes: int = DEFAULT_BUDGET, *,
                     support_images: bool = True) -> List[dict]:
    """A copy of ``messages`` that fits ``max_bytes``; ``messages`` is not changed."""
    projected = copy.deepcopy(messages)
    images = [
        block
        for message in projected if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    kept = images if support_images else []
    for block in images[:len(images) - len(kept)]:
        _replace_with_text(block, DISABLED_IMAGE)
    for block in kept[:-1]:
        block["image_url"]["url"] = encode_image(block["image_url"]["url"], THUMBNAIL)
    for block in kept[-1:]:
        block["image_url"]["url"] = encode_image(block["image_url"]["url"], IMAGE)

    def body_size() -> int:
        return len(json.dumps(projected, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    while len(kept) > 1 and body_size() > max_bytes:  # the older half at once, so the past changes rarely
        dropped = max(1, (len(kept) - 1) // 2)
        for block in kept[:dropped]:
            _replace_with_text(block, OMITTED_IMAGE)
        kept = kept[dropped:]
    for block in kept:
        if body_size() > max_bytes:
            block["image_url"]["url"] = encode_image(block["image_url"]["url"], IMAGE_REDUCED)
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

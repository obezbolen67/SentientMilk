"""Reasoning-budget controls for OpenAI-compatible chat completion providers."""

from urllib.parse import urlparse

THINKING_MODES = (
    ("Provider default", "default"),
    ("Off", "none"),
    ("Minimal", "minimal"),
    ("Low", "low"),
    ("Medium", "medium"),
    ("High", "high"),
    ("Extra high", "xhigh"),
    ("Custom token budget", "tokens"),
)


def thinking_request_options(base_url: str, mode: str, tokens: int = 4096) -> dict:
    """Leave defaults untouched; send only the selected reasoning control."""
    if mode not in {value for _, value in THINKING_MODES}:
        raise ValueError(f"Unknown thinking budget mode: {mode}")
    if mode == "default":
        return {}
    if mode == "tokens":
        if isinstance(tokens, bool) or not isinstance(tokens, int) or not 1 <= tokens <= 131072:
            raise ValueError("Thinking token budget must be between 1 and 131072")
        return {"reasoning": {"max_tokens": tokens}}
    if urlparse(base_url).hostname == "openrouter.ai":
        return {"reasoning": {"enabled": False} if mode == "none" else {"effort": mode}}
    return {"reasoning_effort": mode}

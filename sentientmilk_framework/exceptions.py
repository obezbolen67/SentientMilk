from typing import Optional


class LLMError(Exception):
    def __init__(self, message: str = ""):
        super().__init__(message)


class BrainError(Exception):
    """A failure reported to apps as ``{type, message, details, http_status}``."""

    def __init__(self, type: str, message: str, details: Optional[str] = None,
                 http_status: Optional[int] = None):
        super().__init__(message)
        self.type = type
        self.message = message
        self.details = details
        self.http_status = http_status

    def as_dict(self) -> dict:
        return {"type": self.type, "message": self.message, "details": self.details,
                "http_status": self.http_status}


def http_error(status: int, url: str = "") -> BrainError:
    if status == 429:
        return BrainError("rate_limit", "API rate limit exceeded",
                          "The AI service is busy. Please wait a moment and try again.", 429)
    if status == 401:
        return BrainError("auth_error", "Authentication failed", "Please check the provider API key.", 401)
    if status == 402:
        return BrainError("payment_required", "API quota exceeded",
                          "The API account needs credits. Please add funds or wait for quota reset.", 402)
    if status in (408, 504):
        return BrainError("timeout", "Request timed out", "The AI took too long to respond. Try again.", status)
    if status == 413:
        return BrainError(
            "payload_too_large", "Conversation is too large for the API gateway",
            "The history is kept intact and older images are compacted automatically. If this continues, "
            "lower the request budget, raise the gateway's body limit or clear the conversation.", 413,
        )
    if status >= 500:
        return BrainError("server_error", "AI service error",
                          f"The AI service returned error {status}. Try again later.", status)
    return BrainError("http_error", f"Request failed ({status})", f"URL: {url}", status)


def classify(exc: BaseException) -> BrainError:
    """Turn any failure during a turn into a report an app can show."""
    import requests

    from .transport import RequestPayloadTooLarge

    if isinstance(exc, BrainError):
        return exc
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        error = http_error(response.status_code, str(getattr(response, "url", "")))
        body = getattr(response, "text", "") or ""
        if body:
            error.details = f"{error.details or ''}\n{body[:1000]}".strip()
        return error
    if isinstance(exc, RequestPayloadTooLarge):
        return BrainError("payload_too_large", "Conversation is too large for the request budget", str(exc))
    if isinstance(exc, requests.Timeout):
        return BrainError("timeout", "Request timed out", "The AI took too long to respond.")
    if isinstance(exc, requests.ConnectionError):
        return BrainError("network", "Connection failed", "Could not reach the AI service. Check your network.")
    return BrainError("unknown", "An error occurred", str(exc))

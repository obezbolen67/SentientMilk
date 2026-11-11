"""The brain's settings: provider, models, the super model, limits, tool keys and permission rules.

Stored as JSON in the brain's home. Secrets are never returned through the
API; apps only learn whether they are set.
"""

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from .thinking import thinking_request_options
from .transport import DEFAULT_BUDGET, IMAGE_PIXELS

# The provider and model used when the user does not choose their own.
DEFAULT_BASE_URL = "https://api.refuseless.com/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash-fast"

DEFAULTS = {
    "api_key": "",
    "base_url": "",  # empty: DEFAULT_BASE_URL
    "model": "",  # empty: DEFAULT_MODEL
    "light_model": "",  # summaries, journal notes, subagents; empty: same as model
    "context_window": 128000,  # tokens; clearing and compaction thresholds are fractions of it
    "thinking_mode": "default",
    "thinking_tokens": 4096,
    "vision": True,  # the model accepts images
    "image_pixels": IMAGE_PIXELS,  # the most of a picture the model sees: pictures go fitted to it (0: as sent)
    "request_budget": DEFAULT_BUDGET,
    "stream": True,
    "web_search_key": "",
    "shell": "",  # empty: powershell on Windows, bash elsewhere
    "task_workers": 2,
    "rules": {"allow": [], "ask": [], "deny": []},
    "disabled_toolkits": [],
    # Super agents (superagent.py): Claude, through the user's own Claude Code, for code and hard thinking.
    "super_model": "claude-opus-5-5",  # empty: no super agents
    "super_effort": "high",
    "super_command": "",  # empty: claude, found on PATH or where its installer puts it
}
logger = logging.getLogger(__name__)

SECRETS = ("api_key", "web_search_key")
MIN_BUDGET, MAX_BUDGET = 128 * 1024, 16 * 1024 * 1024
MIN_PIXELS = 65_536  # 256 x 256
OLD_BUDGET = 800 * 1024  # the default before 0.9: saved with the rest, it is not a choice of the user's
SHELLS = ("", "powershell", "pwsh", "bash", "sh", "cmd")
RULE_KINDS = ("allow", "ask", "deny")
EFFORTS = ("low", "medium", "high", "xhigh", "max")  # Claude Code's --effort


def normalize_base_url(base_url: str) -> str:
    """The OpenAI-compatible API root, not a concrete endpoint."""
    value = (base_url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
    return value


def validate_rules(value) -> dict:
    if not isinstance(value, dict) or set(value) - set(RULE_KINDS):
        raise ValueError(f"rules must be an object with {', '.join(RULE_KINDS)}")
    for kind in RULE_KINDS:
        items = value.get(kind, [])
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise ValueError(f"rules.{kind} must be a list of patterns such as 'shell_run(git status*)'")
    return {kind: [item.strip() for item in value.get(kind, [])] for kind in RULE_KINDS}


def validate_setting(key, value):
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting: {key}")
    expected = type(DEFAULTS[key])
    if type(value) is not expected:
        raise ValueError(f"{key} must be a {expected.__name__}")
    if key == "base_url":
        value = normalize_base_url(value)
        if value and (urlparse(value).scheme not in ("http", "https") or not urlparse(value).netloc):
            raise ValueError("base_url must be an http(s) URL")
    elif key == "request_budget" and not MIN_BUDGET <= value <= MAX_BUDGET:
        raise ValueError(f"request_budget must be between {MIN_BUDGET} and {MAX_BUDGET} bytes")
    elif key == "image_pixels" and 0 < value < MIN_PIXELS:
        raise ValueError(f"image_pixels must be 0 (pictures go as they are) or at least {MIN_PIXELS}")
    elif key == "context_window" and not 4096 <= value <= 10_000_000:
        raise ValueError("context_window must be between 4096 and 10000000 tokens")
    elif key == "task_workers" and not 1 <= value <= 16:
        raise ValueError("task_workers must be between 1 and 16")
    elif key == "shell" and value.strip() not in SHELLS:
        raise ValueError(f"shell must be one of: {', '.join(s or '(empty)' for s in SHELLS)}")
    elif key == "rules":
        value = validate_rules(value)
    elif key == "super_effort" and value not in EFFORTS:
        raise ValueError(f"super_effort must be one of: {', '.join(EFFORTS)}")
    elif key == "disabled_toolkits" and not all(isinstance(item, str) for item in value):
        raise ValueError("disabled_toolkits must be a list of toolkit names")
    elif isinstance(value, str):
        value = value.strip()
    return value


class BrainConfig:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._values = copy.deepcopy(DEFAULTS)
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(stored, dict):
                raise ValueError("top level is not an object")
            if stored.get("request_budget") == OLD_BUDGET:
                del stored["request_budget"]
            self._values.update({key: validate_setting(key, stored[key]) for key in DEFAULTS if key in stored})
        except (OSError, ValueError) as exc:
            # Keep the unreadable file so a later save cannot destroy its contents.
            kept = self.path.with_name(self.path.name + ".invalid")
            logger.error("Brain settings %s are unreadable (%s); kept as %s", self.path, exc, kept)
            os.replace(self.path, kept)
            self._values = copy.deepcopy(DEFAULTS)

    def values(self) -> dict:
        """Every setting with the defaults filled in, secrets included: for the brain only."""
        with self._lock:
            values = copy.deepcopy(self._values)
        values["base_url"] = values["base_url"] or DEFAULT_BASE_URL
        values["model"] = values["model"] or DEFAULT_MODEL
        values["light_model"] = values["light_model"] or values["model"]
        return values

    def public(self) -> dict:
        """What apps may see: secrets become ``<name>_set`` flags."""
        with self._lock:
            view = {key: copy.deepcopy(value) for key, value in self._values.items() if key not in SECRETS}
            view.update({f"{key}_set": bool(self._values[key]) for key in SECRETS})
        view["defaults"] = {"base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL}
        return view

    def update(self, changes: dict) -> dict:
        """Apply a partial update after validating all of it; nothing changes on error."""
        if not isinstance(changes, dict):
            raise ValueError("settings must be an object")
        with self._lock:
            updated = {**self._values, **{key: validate_setting(key, value) for key, value in changes.items()}}
            thinking_request_options(updated["base_url"] or DEFAULT_BASE_URL,
                                     updated["thinking_mode"], updated["thinking_tokens"])
            self._save(updated)
            self._values = updated
        return self.public()

    def _save(self, values: dict) -> None:
        """Atomic and private to the user: the file holds the API key."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(values, output, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except BaseException:
            os.unlink(temporary)
            raise

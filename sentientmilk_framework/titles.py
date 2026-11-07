"""Session titles: after a session's first reply the model names it in a few words, off the request path,
and apps hear it as the ``session.titled`` notification. A title the user gave is never replaced."""

import logging
import threading

logger = logging.getLogger(__name__)

PROMPT = """Name the conversation below in 3 to 5 words, the way a chat list shows it: what it is about. No
quotes, no punctuation at the end, no "Chat about". Plain text, in the language of the conversation."""
TITLE_CHARS = 60
QUOTED_CHARS = 1_000  # of the first message and of the reply, for the model

_naming = set()
_lock = threading.Lock()


def request(brain, app: str, session: str) -> None:
    """Name the session in the background unless it has a title or is being named."""
    with _lock:
        if (app, session) in _naming:
            return
        _naming.add((app, session))
    threading.Thread(target=_name, args=(brain, app, session), name="title", daemon=True).start()


def clean(text: str) -> str:
    line = next((part.strip() for part in (text or "").splitlines() if part.strip()), "")
    line = " ".join(line.strip("\"'`*# ").split()).rstrip(".!?:;,")
    if len(line) > TITLE_CHARS:
        line = line[:TITLE_CHARS].rsplit(" ", 1)[0]
    return line


def _name(brain, app: str, session: str) -> None:
    try:
        if brain.store.session(app, session)["settings"].get("title") or not brain.config.values()["api_key"]:
            return
        events = brain.store.events(app, session, types=("input", "end"))
        said = next((e["display"] for e in events if e["type"] == "input" and e.get("display")), "")
        reply = next((e["reply"] for e in events if e["type"] == "end" and e.get("reply")), "")
        if not said or not reply:
            return
        profile = brain.profile(app, session)
        message, _ = brain.provider(profile["light_model"]).complete(
            [{"role": "system", "content": PROMPT},
             {"role": "user", "content": f"User: {said[:QUOTED_CHARS]}\n\nYou: {reply[:QUOTED_CHARS]}"}])
        title = clean(message.get("content") or "")
        if not title:
            return
        named = []

        def change(settings):
            if not settings.get("title"):  # the user may have named it meanwhile
                settings["title"] = title
                named.append(title)
            return settings
        brain.store.update_session(app, session, "settings", change)
        if named:
            brain.notify(app, session, "session.titled", {"session": session, "title": title})
    except Exception:
        logger.exception("Could not name session %s/%s", app, session)
    finally:
        with _lock:
            _naming.discard((app, session))

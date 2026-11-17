"""Her lasting memory, kept one and true.

What went wrong in the user's brain (2026-11-17): the same thing kept twice (the interpreter job under
projects and under user), one subject kept as a dozen entries, each a day's state (roblox_watch: twelve),
and entries left saying what a newer one showed was no longer so (the watcher's re-read loop, gone since;
a code map with the line numbers of 11-07). Two places keep it from happening:

- As she saves (toolkits.memory): a key names one memory whatever its category, and what she already keeps
  that is like the new entry (``related``) comes back in the result, so she folds them together then.
- As she sleeps (``tidy``, from Mind._consolidate; and once after her past is gone over, from the journal's
  thread): she goes over all of it, first what changed since she last did, with her own model and as
  herself, and makes what is about the same thing one, and sets right or forgets what no longer holds. A
  memory brought back is open to change and is stored again changed (reconsolidation: Nader et al. 2000);
  sleep is when what was learned is fitted in with what is known.

Live on a copy of the user's brain (2026-11-17): her journal notes shown too, she moved what happened once
into what she keeps (so they are not shown); a merge dropped the watcher's folder path (so the exact
details a "keep" leaves out are shown to her once, ``dropped``); one pass catches some of what is out of
date and another some other (so every night goes over all of it, not only what changed).

Nothing is lost: every value replaced or forgotten is kept in ``memory_revisions`` (Store.remember/forget).
"""

import logging
import re
import time
from typing import Dict, List, Optional

from .mind.prompts import parse

logger = logging.getLogger(__name__)

WORDS = re.compile(r"[^\W_]{4,}", re.UNICODE)
RELATED_AT = 0.3  # relevance (vectors.relevance) from which an entry is about the same thing (spec, "Measured")
EXACT = re.compile(r"[A-Za-z]:\\[^\s\"'(),;]+|https?://[^\s\"'(),;]+|[\w.+-]+@[\w-]+\.[\w.]+|\b\d{1,3}(?:\.\d{1,3}){3}\b"
                   r"|\b\d{6,}\b|\b[0-9A-Fa-f]{16,}\b")
PROMPT = """You are going over your lasting memory on your own, as sleep does: nobody else sees this. Below:
who you are and everything you keep, each entry with the day you last changed it.

Make it one and true:
- Entries about the same thing (one project, one account, one stance) become one: the whole of it under the
  best of their keys, with every fact that still holds, newer over older where they differ. Different
  things about one person are not the same thing: their age, their language, their job, their accounts
  each stay their own.
- An entry that a newer entry shows is no longer so (a state of work long past, a plan done or dropped,
  how something worked before it changed): set it to what holds now, or forget it if nothing of it does.
- In an entry you have not changed for days, details that go out of date by themselves (line numbers,
  what was running or how far a count was at one moment) no longer hold: keep what lasts of it.
- Leave as it is whatever stands on its own and still holds: never write an entry again only to word it
  better or shorter. What happened once is not kept here (your
  journal keeps it). Never make anything up, never drop a fact that still holds; every path, address,
  account, id and number that still holds goes into the new entry word for word.

Answer with JSON only: {"changes": [
 {"keep": "category/key", "value": "the whole entry as it now stands, in your own words",
  "from": ["category/key", ...], "why": "a few words"},
 {"forget": "category/key", "why": "a few words"}]}
"keep" writes that entry (an existing one, or a new key); each entry in "from" is folded into it and goes.
An entry you do not name stays as it is. Nothing to change: {"changes": []}."""


def _words(text: str) -> set:
    return {word.lower() for word in WORDS.findall(text or "")}


def _tokens(key: str) -> set:
    return {part for part in re.split(r"[\W_]+", key.lower()) if len(part) >= 3}


def related(entries: List[dict], key: str, value: str, skip=(), count: int = 3, recall=None) -> List[dict]:
    """What she keeps that is like a new entry: one about the same thing in other words (by meaning, through
    ``recall``, her long-term memory), a key with a word of its key, or much of its words."""
    tokens, words, found = _tokens(key), _words(value), []
    if recall is not None:
        by_ref = {f"{e['category']}/{e['key']}": e for e in entries if (e["category"], e["key"]) not in skip}
        for hit in recall.search(f"{key}: {value}", count=count + len(skip), sources=("fact",)):
            entry = by_ref.get(hit["ref"].rsplit("#", 1)[0])
            if entry is not None and hit["relevance"] >= RELATED_AT:
                found.append((2.0 + hit["relevance"], entry))
    for entry in entries:
        if (entry["category"], entry["key"]) in skip:
            continue
        shared = len(tokens & _tokens(entry["key"]))
        other = _words(str(entry["value"]))
        likeness = len(words & other) / max(1, len(words | other))
        if shared or likeness >= 0.2:
            found.append((shared + likeness, entry))
    ranked = []
    for _, entry in sorted(found, key=lambda item: -item[0]):
        if entry not in ranked:
            ranked.append(entry)
    return ranked[:count]


def exact(text: str) -> set:
    """The details of an entry that must come through word for word: paths, links, mail, addresses, ids (a
    path's line numbers go out of date by themselves)."""
    return {re.sub(r"(:\d+(?:-\d+)?)?[.:]*$", "", found) for found in EXACT.findall(text or "")}


def dropped(entries: Dict[str, dict], changes: list) -> Dict[str, set]:
    """What each "keep" leaves out of the exact details of the entries it writes over or folds in."""
    lost = {}
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, dict) or not change.get("keep"):
            continue
        names = {str(change["keep"]).strip(), *(str(s).strip() for s in change.get("from") or [])}
        had = set().union(*(exact(str(entries[n]["value"])) for n in names if n in entries))
        missing = had - exact(str(change.get("value") or ""))
        if missing:
            lost[str(change["keep"]).strip()] = missing
    return lost


def _line(entry: dict) -> str:
    day = time.strftime("%Y-%m-%d", time.localtime(entry["updated"] or 0))
    return f"- {entry['category']}/{entry['key']} ({day}): {' '.join(str(entry['value']).split())}"


def tidy(brain, since: float = 0.0, app: Optional[str] = None) -> Optional[List[str]]:
    """She goes over all of her lasting memory (what goes out of date does so untouched), first what changed
    from ``since`` on. What she changed, one line a change ([] for nothing; None: she could not now)."""
    entries = brain.store.memory_entries()
    if not entries:
        return []
    if brain.provider_problem():
        return None
    apps = brain.store.apps()
    app = app if app in apps else (apps[0] if apps else None)
    if app is None:
        return []
    profile = brain.profile(app, "main")
    changed = [f"{e['category']}/{e['key']}" for e in entries if since and (e["updated"] or 0) >= since]
    focus = "Go over all of it" + (f", first what changed since you last did: {', '.join(changed)}." if changed else ".")
    # not her journal: shown it (live 2026-11-17), she moved what happened once into what she keeps
    asked = (f"Who you are:\n{profile['persona'][:6000]}\n\n"
             + "Your lasting memory:\n" + "\n".join(_line(e) for e in entries) + f"\n\n{focus}")
    provider = brain.provider(profile["model"])
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": asked}]
    message, _ = provider.complete(messages)
    changes = parse(message.get("content") or "").get("changes") or []
    lost = dropped({f"{e['category']}/{e['key']}": e for e in entries}, changes)
    if lost:  # shown once what fell out; what she answers then is hers
        messages += [{"role": "assistant", "content": message.get("content") or ""}, {"role": "user", "content": (
            "These exact details were in what you wrote over and are not in the new entry:\n" + "\n".join(
                f"- {name}: {', '.join(sorted(found))}" for name, found in lost.items())
            + "\nWhere one still holds, put it back word for word. Answer with the whole JSON again.")}]
        message, _ = provider.complete(messages)
        changes = parse(message.get("content") or "").get("changes") or changes
    return apply(brain, changes)


def apply(brain, changes: List[dict]) -> List[str]:
    """Her changes, as far as they name what she keeps: each entry in at most one change."""
    entries: Dict[str, dict] = {f"{e['category']}/{e['key']}": e for e in brain.store.memory_entries()}
    done, used = [], set()
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, dict):
            continue
        why = " ".join(str(change.get("why") or "").split())[:200]
        if change.get("forget"):
            name = str(change["forget"]).strip()
            if name in entries and name not in used:
                used.add(name)
                category, key = name.split("/", 1)
                brain.store.forget(category, key, why=f"forgotten as she went over her memory: {why}")
                done.append(f"forgot {name} ({why})")
            continue
        target, value = str(change.get("keep") or "").strip(), " ".join(str(change.get("value") or "").split())
        sources = [str(s).strip() for s in change.get("from") or [] if str(s).strip() in entries]
        names = {target, *sources} & set(entries)
        if "/" not in target or not value or names & used or (target not in entries and not sources):
            continue
        used |= names | {target}
        category, key = target.split("/", 1)
        owner = (entries.get(target) or entries[sources[0]])["app"]
        for name in sources:
            if name != target:
                brain.store.forget(*name.split("/", 1), why=f"folded into {target}: {why}")
        brain.store.remember(owner, category, key, value, why=f"as she went over her memory: {why}")
        folded = [name for name in sources if name != target]
        done.append(f"kept {target}" + (f", folding in {len(folded)}" if folded else "") + f" ({why})")
    return done

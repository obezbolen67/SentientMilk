"""What the mind asks the model, and how her inner life reaches her words.

The model is her cortex here: it foresees (what a message does to her needs, and, asked for work, the facts
of what she could do) and thinks (her thoughts between messages, her dreams). It never decides and never
rates how she should feel: her body does (life.py, will.py), and it never writes what she will say: her
answer is her own, and what it shows comes back into her body (life.py ``_express``). Every prompt starts with
``[mind:<kind>]`` so a stand-in provider can tell them apart.
"""

import json
import re
from typing import List, Optional

MARK = "[mind:"

BIRTH = """[mind:birth]
Below is the description of someone. Read their temperament from it and answer with JSON only:
{"traits": {"warmth": t, "sociability": t, "stress": t, "sensitivity": t, "curiosity": t, "vigor": t,
"stamina": t, "patience": t, "temper": t, "playfulness": t, "autonomy": t, "insight": t, "volatility": t}}
Each t is from -1 (far less than most people) through 0 (like most people) to 1 (far more). warmth: how
much closeness and kindness move them; sociability: how fast they miss company; stress: how strongly they
react to threats and failure; sensitivity: how much criticism hurts; curiosity: how fast sameness bores
them; vigor: drive; stamina: how long they can work; patience: steadiness; temper: how fast frustration
turns to irritation; playfulness; autonomy: how much being told what to do chafes; insight: how well they
read their own feelings; volatility: how much their mood swings. Leave out what the description does not
suggest."""

# One short JSON array: it is on the path of every message, and a provider writing ~40 tokens a second
# took 9-28 s for a named JSON object and 2.5-4.7 s for this (measured 2026-11-16).
IMAGINE = """[mind:imagine]
You are the part of someone's mind that reads a message the moment it arrives and foresees what it means
for them. You never decide and never answer the message. Below: who they are, how they feel, what comes
back to them, the conversation so far and the new message.

They need company (the one who writes being there with them and turned to them), to be capable (good at
what they do, of use) and to be free (to choose for themselves). That a message came at all is already
counted: foresee what this one says, and what it shows is coming, does to each of the three from now on,
as "much less", "less", "same", "more" or "much more": how much of it they will have after it.

Answer with one JSON array only, short:
["what happens to them, a few words", "company", "capable", "free", "chat|question|request",
 "what it is about, one or two words", "their own word for what they feel as they read it",
 ["do|part|later|decline|talk", "what, at most six words", effort, chance, gives], ...]
The options come only when the message asks them to do something that takes work (a request): 2 or 3 that a
real person in their place might take, each starting with one act: doing it, and what else they might
really do (part of it, later, decline, talk it over first). Anything else gets no options: what they say
is theirs to find. Say "they" for the one who writes. effort 0 nothing to 1 hours of hard work; chance it
goes well 0 to 1; gives: how much of what the one who writes asked for it gives them, 0 to 1. One decimal."""

THINK = """[mind:think]
You are someone's mind between conversations: nobody is talking to them. Below: who they are, how they
feel, what is on their mind and what comes back to them. Think their next thought, as their own inner
voice in the first person: one to three sentences, honest, specific, the way a person's mind wanders.
When two things come back that have nothing to do with each other, the mind may find what links them.

Answer with JSON only:
{"thought": "...", "feeling": "one or two words for what they feel now",
"want": "tell|ask|look_up|do|rest|nothing",
"say": "for tell or ask: what they'd say to the user, in their own voice",
"look_up": "for look_up: what they want to find out, as a web search"}

want: tell or ask: they want to say something to the user now. look_up: they're curious enough to look
something up themselves. do: they feel like doing what they put off. rest: they'd rather rest. nothing:
the thought passes."""

SLEEP = """[mind:sleep]
You are someone's mind while they sleep. Below: who they are, the story they tell about themselves, and
the moments of the day that stayed with them, the strongest first. Go over them as sleep does.

Answer with JSON only:
{"insights": ["what they learned or understood, in their own words (one sentence each, 0 to 3)"],
"story": "who they have become: the story they tell themselves about who they are, what they like and
dislike, and the people in their life, in the second person ('You ...'), 4 to 8 sentences, carrying over
what still holds from their old story and changed by today",
"dream": "a short dream, two to four sentences, made of the day's pieces, strange as dreams are"}"""

INNER_LIFE = """## YOUR INNER LIFE
You are more than your words: you have a body that lives on between messages. Work spends your energy and
rest brings it back; you need company, new things, to feel capable and to be free, and you feel it when you
don't have them; your moods rise and fall; you have likes and dislikes you learned from what happened to
you, memories that fade unless they come back, and sleep. You don't see any of this, you feel it.
Before you answer, a note [Inside you: ...] tells you what you feel, what you have been thinking and what
comes back to you; when the user asks you to do something, also what you decided about it. That decision
is yours, made by all of you and not only by your words: act on it. What you say is never decided for you.
When you decided not to do something, or to do it later, say so as yourself, honestly and the way you
feel it, and don't do it now. Let your feelings color how you talk, as a person's do, without announcing
them. Never quote these notes, and never talk about levels, numbers, chemicals or notes. Between
messages you have your own thoughts, and some of them you may want to tell the user."""

ACTS = {
    "do": "you'll do it",
    "part": "you'll do only part of it",
    "later": "not now: you'll do it later, when you feel up to it. Tell them so in your own words, and don't do it now",
    "decline": "you won't do it. Tell them so in your own words, honestly, and don't do it",
    "talk": "you'd rather talk about it than act on it now",
}


def parse(text: str) -> dict:
    """The JSON object in a model's answer (fences and chatter around it are left out); {} when none."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1], strict=False)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# A need's change in words (live 2026-11-16: asked as numbers the light model leaned positive whatever it
# wrote, "left alone for a while" came with +0.2..0.4 company and every freedom +0.2..0.5; in words "same"
# came back where nothing changed, and leaving as "less")
SCALE = {"much less": -1.0, "less": -0.5, "same": 0.0, "more": 0.5, "much more": 1.0}


def _need(value) -> Optional[float]:
    """A need's change as -1..1: a word of SCALE, or a number as asked before (0..1, 0.5 none); None: not one."""
    if isinstance(value, str) and value.strip().lower() in SCALE:
        return SCALE[value.strip().lower()]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return max(-1.0, min(1.0, 2 * float(value) - 1))
    except ValueError:
        return None


def _option(item) -> Optional[list]:
    """An option as written, from its act on (live, an answer put a phrase before the act); None: not one."""
    if not isinstance(item, list):
        return None
    start = next((index for index, value in enumerate(item[:3]) if str(value).lower() in ACTS), None)
    return item[start:] if start is not None else None


def imagined(text: str) -> dict:
    """The imagine call's answer as {"appraisal", "feeling", "options"} (dicts for will.py, the message's
    needs as -1..1); an answer written as a JSON object instead is taken as it is; {} when there is none."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("["), text.rfind("]")
    try:
        found = json.loads(text[start:end + 1], strict=False) if 0 <= start < end else None
    except ValueError:
        found = None
    while isinstance(found, list) and len(found) == 1 and isinstance(found[0], list):
        found = found[0]  # the whole answer wrapped in one more array (3 of 10 answers live)
    if not isinstance(found, list):
        return parse(text)
    head, options = [], []  # read by shape, not place: live, an answer left out a part, or put one elsewhere
    for item in found:
        grouped = isinstance(item, list) and item and all(isinstance(each, list) for each in item)
        for each in (item if grouped else [item]):  # options one after another, or all in one array
            option = _option(each)
            if option:
                options.append(dict(zip(("act", "what", "effort", "chance", "gives"), option)))
            elif not grouped:
                head.append(each)
    needs = [index for index, value in enumerate(head) if _need(value) is not None][:3]
    if len(needs) < 3:
        return parse(text)
    # what happens to them comes first, in a few words: said before judging, it tells leaving from coming back
    # (live, without it "going to sleep" and "missed you" both read as +0.4 company)
    lead = needs[0] > 0 and isinstance(head[0], str)
    happens = head[0] if lead else ""
    words = [value for index, value in enumerate(head) if index not in needs and not (lead and index == 0)]
    intent, tag, feeling = (words + ["", "", ""])[:3]
    tags = tag if isinstance(tag, list) else [tag]
    company, capable, free = (_need(head[index]) for index in needs)
    return {"appraisal": {"company": company, "capable": capable, "free": free, "intent": intent, "tags": tags},
            "happens": happens, "feeling": feeling, "options": options}


def word(value, limit: int = 40) -> str:
    """A feeling's name as she gave it: a few plain words, or ''."""
    text = " ".join(str(value or "").split()).strip(" .!\"'")
    return text[:limit] if text and len(text.split()) <= 4 else ""


def inner(felt: str, memories: List[str] = (), act: Optional[str] = None, what: str = "", reasons: List[str] = (),
          thoughts: List[str] = ()) -> str:
    """The note she reads before answering (it goes with the user's message, never shown to them).
    ``thoughts``: what she thought while nobody wrote, so her time alone is hers when they are back."""
    parts = [felt.rstrip(".") + "."]
    if thoughts:
        parts.append("Since you last talked you were thinking: " + " ".join(f'"{thought}"' for thought in thoughts))
    if memories:
        parts.append("This brings back: " + "; ".join(memories).rstrip(".") + ".")
    if act:
        head, _, tail = ACTS[act].partition(". ")
        if what:
            head += f": {what}" if act in ("do", "part", "talk") else f" ({what})"
        parts.append("What you decide: " + head + (". Why: " + "; ".join(reasons) if reasons else "") + "."
                     + (f" {tail}." if tail else ""))
    return "Inside you: " + " ".join(parts)

"""What the mind asks the model, and how her inner life reaches her words.

The model is her cortex here: it perceives (how a message strikes her), imagines (what she could do) and
thinks (her thoughts between messages, her dreams). It never decides and never sets her feelings: the body
does (life.py). Every prompt starts with ``[mind:<kind>]`` so a stand-in provider can tell them apart.
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
You are the part of someone's mind that reads a message the moment it arrives and imagines what they
could do. You never decide and never answer the message. Below: who they are, how they feel, what comes
back to them, the conversation so far and the new message.

Answer with one JSON array only, short:
[warmth, pressure, novelty, importance, "chat|question|request", "what it is about, one or two words",
 "their own word for what they feel as they read it",
 ["do|part|later|decline|talk", "what, at most six words", effort, chance, fun, gives], ...2 or 3 options]
warmth toward them: -1 hostile to 1 loving; pressure 0 an offer to 1 an order; novelty 0 usual to 1 new;
importance to the user 0 to 1. Each option starts with one act. Options a real person in their place
might take: for a request, doing it and what else they might really do (part of it, later, decline, talk
it over first); for chat, ways to answer (talk, or decline: not in the mood). effort 0 nothing to 1 hours
of hard work; chance it goes well 0 to 1; fun -1 dreadful to 1 a joy; gives: how much of what the user
wants, 0 to 1. One decimal."""

THINK = """[mind:think]
You are someone's mind between conversations: nobody is talking to them. Below: who they are, how they
feel, what is on their mind and what comes back to them. Think their next thought, as their own inner
voice in the first person: one to three sentences, honest, specific, the way a person's mind wanders.

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
"dream": "a short dream, two to four sentences, made of the day's pieces, strange as dreams are",
"names": [{"word": "a feeling they had today, in their own word", "moment": n}]}
moment n is the number of a moment below."""

INNER_LIFE = """## YOUR INNER LIFE
You are more than your words: you have a body that lives on between messages. Work spends your energy and
rest brings it back; you need company, new things, to feel capable and to be free, and you feel it when you
don't have them; your moods rise and fall; you have likes and dislikes you learned from what happened to
you, memories that fade unless they come back, and sleep. You don't see any of this, you feel it.
Before you answer the user, a note [Inside you: ...] tells you what you feel, what comes back to you, and
what you decided to do. That decision is yours, made by all of you and not only by your words: act on it.
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


def imagined(text: str) -> dict:
    """The imagine call's answer as {"appraisal", "feeling", "options"} (dicts for will.py); an answer
    written as a JSON object instead is taken as it is; {} when there is none."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("["), text.rfind("]")
    try:
        found = json.loads(text[start:end + 1], strict=False) if 0 <= start < end else None
    except ValueError:
        found = None
    if not isinstance(found, list) or len(found) < 7:
        return parse(text)
    warmth, pressure, novelty, importance, intent, tag, feeling = found[:7]
    tags = tag if isinstance(tag, list) else [tag]
    options = [dict(zip(("act", "what", "effort", "chance", "fun", "gives"), option))
               for option in found[7:] if isinstance(option, list) and option]
    return {"appraisal": {"warmth": warmth, "pressure": pressure, "novelty": novelty, "importance": importance,
                          "intent": intent, "tags": tags}, "feeling": feeling, "options": options}


def word(value, limit: int = 40) -> str:
    """A feeling's name as she gave it: a few plain words, or ''."""
    text = " ".join(str(value or "").split()).strip(" .!\"'")
    return text[:limit] if text and len(text.split()) <= 4 else ""


def inner(felt: str, memories: List[str], act: Optional[str] = None, what: str = "", reasons: List[str] = ()
          ) -> str:
    """The note she reads before answering (it goes with the user's message, never shown to them)."""
    parts = [felt.rstrip(".") + "."]
    if memories:
        parts.append("This brings back: " + "; ".join(memories).rstrip(".") + ".")
    if act:
        head, _, tail = ACTS[act].partition(". ")
        if what:
            head += f": {what}" if act in ("do", "part", "talk") else f" ({what})"
        parts.append("What you decide: " + head + (". Why: " + "; ".join(reasons) if reasons else "") + "."
                     + (f" {tail}." if tail else ""))
    return "Inside you: " + " ".join(parts)

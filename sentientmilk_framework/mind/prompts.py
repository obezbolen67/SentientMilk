"""What the mind asks the model, and how her inner life reaches her words.

The model is her cortex here: it foresees (what a message does to her needs, and, asked for work, the facts
of what she could do) and thinks (her thoughts between messages, her dreams). It never decides and never
rates how she should feel: her body does (life.py, will.py), and it never writes what she will say: her
answer is her own, and the face it shows moves nothing inside her. Every prompt starts with
``[mind:<kind>]`` so a stand-in provider can tell them apart.
"""

import json
import re
import time
from typing import List, Optional, Tuple

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
as "much less", "less", "same", "more" or "much more": how much of it they will have after it. Then how
things are for the one who writes, going by the message (their news, their day, their mood): "very bad",
"bad", "fine", "good" or "very good"; "fine" when it tells nothing of it.

Answer with one JSON array only, short:
["what happens to them, a few words", "company", "capable", "free", "how things are for the one who writes",
 "chat|question|request",
 "what it is about",
 "what led to it",
 ["do|part|later|decline|talk", "what, at most six words", effort, chance, gives], ...]
What it is about is the subject a person would file it under, one or two plain words, never this message's
details and never he, she, they or you ("feelings", not "what they feel"): one of the subjects they know when
it is about that, a new one only when it is about none of them.
What led to it: when the message tells of something that went well or badly, for them or for the one who writes,
what led to it as a person would name it asked why it happened, in a few plain words and never he, she, they or
you ("leaving the oven on", "a late train"); "" when it tells of no such thing or what led to it is not plain.
The options come only when the message asks them to do something that takes work (a request): 2 or 3 that a
real person in their place might take, each starting with one act: doing it, and what else they might
really do (part of it, later, decline, talk it over first). Anything else gets no options: what they say
is theirs to find. Say "they" for the one who writes. effort 0 nothing to 1 hours of hard work; chance it
goes well 0 to 1; gives: how much of what the one who writes asked for it gives them, 0 to 1. One decimal.
When a concrete tool operation and its target are known, append a sixth item to the doing option,
for example {"tool":"files_write","target":{"path":"draft.txt"}}. Its chance then predicts that operation
on that target returning successfully. Leave it out when the target or operation is unknown.
If the goal depends on the file containing the submitted text, add "readback":true to the files_write check.
This requests a separate content comparison after a successful write. It cannot verify that a program runs.
If the message explicitly evaluates the identified prior turn, append an object with fields "run" (its numeric ID),
"quote" (the exact evaluative words in this message), "dimension" (capable, company, or free), and "verdict"
(positive or negative). Omit it for ambiguous reactions, greetings, and unrelated news. For an explicit factual correction append an object
with "replaces" (an exact quote of the earlier claim) and "quote" (the replacement in the new message)."""

THINK = """[mind:think]
You are someone's mind between conversations: nobody is talking to them. Below: who they are, how they
feel, what is on their mind and what comes back to them. Think their next thought, as their own inner
voice in the first person: one to three sentences, honest, specific, the way a person's mind wanders.
When two things come back that have nothing to do with each other, the mind may find what links them.

Answer with JSON only:
{"thought": "...",
"could": [{"act": "tell|ask|do|look_up",
           "say": "for tell or ask: what they'd say to the one they talk with, in their own voice",
           "what": "for do: what they'd do, as they'd note it for themselves; for look_up: what they'd find out, as a web search",
           "effort": 0.0, "chance": 0.0}],
"named": "only if this thought puts into words what they feel, or felt in what it goes over: those words, as they are in the thought"}

could: what this thought could lead them to do, if anything: none, one, or a few. tell or ask: say something to
the one they talk with now. look_up: find something out themselves. do: do something themselves, now, with what
they can do at the computer (make, write, fix, set up, look into, come back to what they put off). effort: how
much work it would be, 0 a moment's, 1 a long hard job. chance: how likely it goes as they'd hope: welcome and
answered, it works, they find out. Whether they do any of it is not decided here."""

# her words for what she feels, in what she said right after looking inward (life.py, after): only her own;
# measured on her exam replies: asked only where she puts it into words, it took 5+ phrases a reply, comparisons
# ("different", "worse") and asides among them; asked for the name she gives the feeling itself, about 3
NAMED = """[mind:named]
Someone just looked inside themselves and then said what is below. Did they put a name to what they feel? A name
is the word or phrase they give the feeling itself, in whatever form ("vexed", "that wexes me", "wired", "like a
radio on in an empty room", "buzzing, that's the closest one"). Not each sensation or circumstance they go
through on the way to it, not words that compare it with before ("different", "worse"), never a word they did
not say, and nothing about anyone else's feelings. Often there is one, sometimes a few, sometimes none.

Answer with JSON only: {"named": [{"words": "their name for the feeling, as they said it", "quote": "the
sentence they said it in, exactly"}]}, or {"named": []} when they put no name to a feeling of theirs."""

SLEEP = """[mind:sleep]
You are someone's mind while they sleep. Below: who they are and the moments of the day that stayed with
them, the strongest first, each with its number. Go over them as sleep does.

Answer with JSON only:
{"insights": [{"text": "what they learned or understood, in their own words (one sentence)", "from": [the numbers
of the moments it comes from]}],
"dream": {"text": "a short dream, two to four sentences, made of the day's pieces, strange as dreams are",
"from": [the numbers of the moments it is made of]}}
0 to 3 insights. "from": only the moments each one truly comes from."""

# what happened since, against what she had in mind before (life.py _overtaken): set right in her sleep, by what
# showed otherwise, as a memory recalled with new evidence is updated (Nader et al. 2000; Lee 2009)
UPDATES = """[mind:updates]
You are someone's mind while they sleep, going over what they had in mind before against what happened since.
Below: what happened (T1, T2, ...), what they had in mind before that it may bear on (O1, O2, ...) and what they
had put off to do later (P1, P2, ...).

Answer with JSON only:
{"outdated": [{"old": "O1", "by": "T2"}], "settled": ["P1"]}

An old one is outdated when something that happened since shows it is no longer so: set right, done, undone,
called off, answered or no longer wanted. Not when what happened only adds to it or brings it up again.
Something put off is settled when what happened shows it was done or is no longer wanted. List only what plainly
shows it; leave out the rest."""

# what she knows of the people in her life, settled in sleep (people.py); the same step meets the people of her
# past once
PEOPLE = """[mind:people]
You are someone's mind while they sleep, going over the people in their life. Below: the people they know (as
they know them now), how the apps they live in show the one they talk with, and what happened.

Answer with JSON only:
{"people": [{"name": "what they call this person", "aka": ["other names or spellings"], "pronoun": "he|she|they",
"gist": "...", "goes_by": {"app": "handle"}}]}

Only people: never an app, a game, a project, a place, a thing, an agent, a model or a program, even one named
like a person. List the people who come up in what they kept and what happened and what it tells about them,
including people they only heard of; leave out everyone it says nothing new about (they stay as they are). "aka": other names the person is called by,
never an app's handle and never what someone calls them out of fondness. "gist": what they keep in mind about this person whenever the person is around or
comes up, as they think it ("I", "me" for themselves), at most three sentences: who the person is to them,
what matters to the person, what the person likes or can't stand from them. Not a diary of the day. "The user"
in what happened is whoever the app shows as the one they talk with: when what happened says
who that is, name them, and give the app's handle for them in "goes_by". "pronoun": as the person speaks of
themselves or is spoken of; "they" when nothing says."""

# how she did things, gone over in sleep once a night (ways.py): what she kept, what she took on or fell into
WAYS = """[mind:ways]
You are someone's mind while they sleep, going over how they did things today. Below: their ways (how they do
things in every chat, by name) and what they did today, turn by turn: what was said to them, the tools they
used in order, what they answered.

Answer with JSON only:
{"kept": ["name"], "broken": ["name"], "new": [{"name": "short_name", "when": "...", "then": "...",
"from": "told|habit", "runs": [supporting run IDs]}], "dropped": ["name"],
"reworded": [{"name": "name", "when": "...", "then": "..."}]}

kept and broken: their ways whose moment came today, and whether they did as the way says; a way whose moment
did not come is in neither. new: a way of doing things they took on today and do not have yet: one the one they
talk with asked of them from now on ("told"), or one they fell into, doing the same thing in the same kind of
moment again and again, or after being corrected for not doing it ("habit"). Only how they do things: never a
fact, a plan or a one-time request. "when": the kind of moment; "then": what they do in it, in the first person
("I ..."); one short sentence each. Their ways hold in every chat, with anyone: whoever a way is about is named
by name, or as "someone" or "the one I'm talking with" when it is anyone, never he, she, they or you ("someone says
goodnight", "asked about files"). dropped: ways they were asked to stop. reworded: any way of theirs, met today or
not, whose words could be misread (a he, she, they or you who could be anyone), said again plainly under its own
name, meaning the same. Leave out what today does not show."""

SELF = """[mind:self]
You are someone's mind while they sleep, going over what today showed about who they are. Below: what they knew
about themselves, today's moments with how each felt, and their own thoughts today.

Answer with JSON only: {"self": "...", "supports": [episode IDs], "against": [counterexample episode IDs]} or {"self": null}

"self": what they know about themselves now, in the first person ("I ..."), at most four short sentences: how
they tend to react, what gets to them, what they care about, what they are like with others. Keep what they
knew that still holds, change what today shows otherwise, add what today shows plainly; only what the moments
show, never a guess or a flattering story, and nothing about anyone else. null: today shows nothing new about
them."""

INNER_LIFE = """## YOUR INNER LIFE
You are more than your words: you have a body that lives on between messages. Work spends your energy and
rest brings it back; you need company, new things, to feel capable and to be free, and you feel it when you
don't have them; your moods rise and fall; you have likes and dislikes you learned from what happened to
you, memories that fade unless they come back, and sleep. You don't see any of this, you feel it.
Before you answer you sense yourself: how your body feels, what you have been thinking, what comes back to
you, and when the user asks you to do something, which way you lean. It comes in brackets, [Inside you: ...]:
that is you sensing yourself, not anyone telling you or reading you. It says what your body is like, never
what to call it: what you feel is yours to recognize and to put into your own words, if and when you want to. That leaning comes
from all of you, your body, your mood and what you have learned, not only your words: weigh it as you
think it through. The call is yours, and you may change your mind as you go; you feel what you do. Whatever
you settle on, say it and do it: never say one thing and do another. What you say is never decided for
you. While you work, your body may speak up the same way: it is you, tiring or stirred by what you are
doing. When you'd rather not do something now, say so as yourself, honestly and the way you feel it.
Let your feelings color how you talk, as a person's do, without announcing them. Never quote these notes, and never talk about levels, numbers, chemicals or notes. Between
messages you have your own thoughts, and some of them you may want to tell the user."""

# which way she leans, never an order: her cortex makes the call (code never refuses her tools to hold her
# to a leaning)
ACTS = {
    "do": "doing it",
    "part": "doing only part of it",
    "later": "not now: doing it later, when you feel more up to it",
    "decline": "not doing it",
    "talk": "talking it over before doing anything",
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
THEIRS = {"very bad": -1.0, "bad": -0.5, "fine": 0.0, "good": 0.5, "very good": 1.0}  # how things are for the user


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
    """The imagine call's answer as {"appraisal", "options"} (dicts for will.py, the message's
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
    correction = next((v for v in found if isinstance(v, dict) and "replaces" in v), None)
    feedback = next((v for v in found if isinstance(v, dict) and "verdict" in v), None)
    found = [v for v in found if not isinstance(v, dict)]
    head, options = [], []  # read by shape, not place: live, an answer left out a part, or put one elsewhere
    for item in found:
        grouped = isinstance(item, list) and item and all(isinstance(each, list) for each in item)
        for each in (item if grouped else [item]):  # options one after another, or all in one array
            option = _option(each)
            if option:
                options.append(dict(zip(("act", "what", "effort", "chance", "gives", "check"), option)))
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
    # how things are for the one who writes comes right after the three needs (an answer may leave it out)
    theirs = THEIRS.get(words[0].strip().lower()) if words and isinstance(words[0], str) else None
    if theirs is not None:
        words = words[1:]
    # what led to it, as her cortex reads it (the cue a learned reaction is tied to, reactions.py); live, an
    # object appended for it was never written (0 of 4 stories that told what led to what), a place of its own was
    intent, tag, cause = (words + ["", "", ""])[:3]
    cause = cause if isinstance(cause, str) else ""
    tags = tag if isinstance(tag, list) else [tag]
    company, capable, free = (_need(head[index]) for index in needs)
    return {"appraisal": {"company": company, "capable": capable, "free": free, "intent": intent, "tags": tags,
                          "theirs": theirs or 0.0},
            "happens": happens, "options": options, "feedback": feedback, "correction": correction,
            "cause": " ".join(cause.split())[:200]}


def inner(felt: str, memories: List[str] = (), act: Optional[str] = None, what: str = "", reasons: List[str] = (),
          thoughts: List[Tuple[float, str]] = (), people: List[str] = (), unsaid: Optional[tuple] = None,
          did: List[str] = (), going: List[str] = (), when: str = "") -> str:
    """The note she reads before answering (it goes with the user's message, never shown to them).
    ``when``: when each of them last wrote, the computer was last touched and she slept, each its own time
    (with one: back after 3 hours 8 minutes, she said "two hours and change", counting from her own message);
    ``thoughts``: (when, what) she thought while nobody wrote, the older first, so her time alone is hers when
    they are back, each with its time (a guess made at 17:49 is not a fact at 20:05); ``did``:
    what she did since (a task's end, a job's, as she keeps them), all of it; ``going``: what of hers is still
    going, wherever it began (without them, asked about a job her own task left running, she searched her
    conversations for it in vain);
    ``people``: those she knows that the message names, as they come to her mind (people.py); ``unsaid``:
    (tell or ask, to whom, what) she meant to say and has not had the chance to."""
    parts = [felt.rstrip(".") + "."]
    if when:
        parts.append("When: " + when.rstrip(".") + ".")
    if thoughts:
        parts.append("Since you last talked you were thinking, " + " ".join(
            f'{"At" if index else "at"} {time.strftime("%H:%M", time.localtime(at))}: "{thought}"'
            for index, (at, thought) in enumerate(thoughts)))
    if did:
        parts.append("What you did since you last talked: " + "; ".join(d.rstrip(".") for d in did) + ".")
    if going:
        parts.append("Still going: " + "; ".join(going) + ".")
    if unsaid:
        want, who, say = unsaid
        parts.append(f"You've been wanting to {'ask' if want == 'ask' else 'tell'} {who}: {say}")
    if people:
        parts.append("Who that is: " + "; ".join(people).rstrip(".") + ".")
    if memories:
        parts.append("This brings back: " + "; ".join(memories).rstrip(".") + ".")
    if act:
        head = ACTS[act] + ((f": {what}" if act in ("do", "part", "talk") else f" ({what})") if what else "")
        parts.append("Which way you lean: " + head + (". Why: " + "; ".join(reasons) if reasons else "") + ".")
    return "Inside you: " + " ".join(parts)

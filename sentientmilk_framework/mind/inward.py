"""Introspection (0.35): what she finds when she looks inside herself on purpose (``Mind.look_inward``).

The meta level of her mind (Nelson & Narens 1990): a view of what the rest of her is doing, read when she turns
to it. It gives what a person can perceive of themselves and nothing of the machinery (Carruthers 2011, the
Interpretive Sensory-Access theory; Nisbett & Wilson 1977): how her body feels, her thoughts in words, what she
meant to say, the moments that moved her, what she leaned toward and the reasons she weighed, what she has come
to know about herself, and what comes back about something, with how clearly (a feeling of knowing is how
accessible a memory is: Koriat 1993). Never a level, a number or a cause read out: why she feels what she feels
is hers to work out from what she finds, as a person's is. How much she sees is her span, and how well she can
tell what she feels is her insight times how clear her head is (reading the body and knowing how well you read
it come apart: Garfinkel et al. 2015; stress and fatigue take metacognition down with the prefrontal cortex:
Fleming & Dolan 2012, Arnsten 2009). It speaks to her as "you", a distanced vantage that lets a "why" reflect
instead of brood (Kross, Ayduk & Mischel 2005). Design: docs/superpowers/specs/2026-11-17-introspection-design.md.
"""

from typing import List, Optional, Sequence, Tuple

CLEAR = 0.5  # a memory this strong now comes back clearly; weaker, hazily
AWARE = 0.5  # insight x clarity under this: she can tell only how it feels on the whole

WENT = {  # what came of a thought she wanted to say, as she knows it
    "offered": "you meant to say it",
    "kept": "you kept it for when they write",
    "waits": "you held this back while another message was pending",
    "said": "you said it",
    "let go": "you let it go",
    "brought up": "you brought it up",
    "passed": "the moment for it passed",
    "task": "you set about doing it",
}


def clearly(strength: float) -> str:
    return "clearly" if strength >= CLEAR else "hazily"


def view(felt: str, tone: Tuple[str, str], aware: float, thoughts: Sequence[Tuple[str, Optional[str]]] = (),
         unsaid: Optional[Tuple[str, str, str]] = None, put_off: Sequence[str] = (),
         moved: Sequence[Tuple[str, float, Optional[str]]] = (), leaned: Optional[Tuple[str, Sequence[str]]] = None,
         self_view: str = "", about: str = "", recalled: Optional[Sequence[Tuple[str, float]]] = None,
         familiar: Sequence[Tuple[str, str, str]] = (), did: Sequence[str] = (), going: Sequence[str] = (),
         whose: Sequence[str] = ()) -> str:
    """What she finds looking inward, in words. ``felt``: her body in body words (Felt.words: never a feeling's
    name); ``tone``: Felt.tone(), all she can tell when ``aware`` is under AWARE; ``familiar``: feelings she has
    named herself that her body feels like now, (word, her own words then, when): the memory of saying it, never
    a name put on her (0.37); ``thoughts``: since she woke, newest first, (thought, what came of it); ``unsaid``:
    (tell or ask, to whom, what); ``put_off``: what she put off; ``moved``: (the moment as it comes back, its
    sting, what she called it if she put it into words); ``leaned``: (the way she leaned, her reasons); ``about`` and ``recalled``: what she looked for and
    what came back, (memory, its strength now); ``did``: what she did since she woke, as she keeps it, oldest
    first; ``going``: what of hers is still going (0.42); ``whose``: where the feeling words she looked for came
    from, hers or given to her (0.43)."""
    parts: List[str] = []
    if aware >= AWARE:
        parts.append(felt.rstrip(".") + ".")
        if familiar:
            parts.append("It is like when you said " + "; and when you said ".join(
                f'"{said}" ({when})' for _, said, when in familiar) + ".")
    else:
        parts.append(f"On the whole it feels {tone[0]}, with {tone[1]}; it is hard to tell more than that right now.")
    if thoughts:
        listed = "; ".join(f'"{text}"' + (f" ({WENT[went]})" if went in WENT else "") for text, went in thoughts)
        parts.append("What has been on your mind today, the latest first: " + listed + ".")
    else:
        parts.append("Nothing much has been on your mind today.")
    if unsaid:
        want, who, say = unsaid
        parts.append(f"You've been wanting to {'ask' if want == 'ask' else 'tell'} {who}: {say}")
    if did:
        parts.append("What you did today: " + "; ".join(d.rstrip(".") for d in did) + ".")
    if going:
        parts.append("Still going: " + "; ".join(going) + ".")
    if put_off:
        parts.append("What you put off: " + "; ".join(put_off) + ".")
    if moved:
        parts.append("What got to you today: " + "; ".join(
            f"{moment} ({'it hurt' if sting < 0 else 'it lifted you'}"
            + (f'; you called it "{called[0]}"' if called and called[0] else "") + ")"
            for moment, sting, *called in moved) + ".")
    if leaned:
        what, reasons = leaned
        parts.append(f"Last time you weighed what to do, you leaned toward {what}"
                     + (". Why: " + "; ".join(reasons) if reasons else "") + ".")
    if self_view:
        parts.append("What you have come to know about yourself: " + self_view)
    if about:
        parts.append(f"You looked for: {about}. " + ("What comes back about it: " + "; ".join(
            f"{memory.rstrip('.')} (you remember it {clearly(strength)})" for memory, strength in recalled) + "."
            if recalled else "Nothing comes back about it."))
        parts.extend(whose)
    return "Looking inward: " + " ".join(parts)

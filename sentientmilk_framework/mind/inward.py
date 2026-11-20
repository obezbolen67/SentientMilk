"""Introspection: what she finds when she looks inside herself on purpose (``Mind.look_inward``).

The meta level of her mind (Nelson & Narens 1990): a view of what the rest of her is doing, read when she turns
to it. It gives what a person can perceive of themselves and nothing of the machinery (Carruthers 2011, the
Interpretive Sensory-Access theory; Nisbett & Wilson 1977): how her body feels, her thoughts in words, what she
meant to say, the moments that moved her, what she leaned toward and the reasons she weighed, what she has come
to know about herself, and what comes back about something, with how clearly (a feeling of knowing is how
accessible a memory is: Koriat 1993). Never a level, a number or a cause read out: why she feels what she feels
is hers to work out from what she finds, as a person's is. How much she sees is her span, and how well she can
tell what she feels is her insight times how clear her head is (reading the body and knowing how well you read
it come apart: Garfinkel et al. 2015; stress and fatigue take metacognition down with the prefrontal cortex:
Fleming & Dolan 2012, Arnsten 2009). It never speaks to her: spoken to as "you", her reasoning
called it "the inside-you report" and said "something in me reports" (0.51; a person's sense of themselves has no
addressee). Design: docs/superpowers/specs/2026-11-17-introspection-design.md.
"""

from typing import List, Optional, Sequence, Tuple

CLEAR = 0.5  # a memory this strong now comes back clearly; weaker, hazily
AWARE = 0.5  # insight x clarity under this: she can tell only how it feels on the whole

WENT = {  # what came of a thought she wanted to say, as she knows it
    "offered": "meant to be said",
    "kept": "kept for when they write",
    "waits": "held back while another message was pending",
    "said": "said",
    "let go": "let go",
    "brought up": "brought up",
    "passed": "the moment for it passed",
    "task": "set about doing",
    "let be": "let be",
}


def clearly(strength: float) -> str:
    return "clearly" if strength >= CLEAR else "hazily"


def view(felt: str, tone: Tuple[str, str], aware: float, thoughts: Optional[Sequence[Tuple[str, Optional[str]]]] = None,
         unsaid: Optional[Tuple[str, str, str]] = None, put_off: Sequence[str] = (),
         moved: Sequence[Tuple[str, float, Optional[str]]] = (), leaned: Optional[Tuple[str, Sequence[str]]] = None,
         self_view: str = "", about: str = "", recalled: Optional[Sequence[Tuple[str, float]]] = None,
         familiar: Sequence[Tuple[str, str, str]] = (), did: Sequence[str] = (), going: Sequence[str] = (),
         whose: Sequence[str] = (), also: Sequence[str] = ()) -> str:
    """What she finds looking inward, in words. ``felt``: her body in body words (Felt.words: never a feeling's
    name); ``tone``: Felt.tone(), all she can tell when ``aware`` is under AWARE; ``familiar``: feelings she has
    named herself that her body feels like now, (word, her own words then, when): the memory of saying it, never
    a name put on her; ``thoughts``: since she woke, newest first, (thought, what came of it), None when not looked at; ``unsaid``:
    (tell or ask, to whom, what); ``put_off``: what she put off; ``moved``: (the moment as it comes back, its
    sting, what she called it if she put it into words); ``leaned``: (the way she leaned, her reasons); ``about`` and ``recalled``: what she looked for and
    what came back, (memory, its strength now); ``did``: what she did since she woke, as she keeps it, oldest
    first; ``going``: what of hers is still going; ``whose``: the feeling words she looked for that are hers, with
    when she said them; ``also``: what else is before her now (workspace.py), the most active first."""
    parts: List[str] = []
    if aware >= AWARE:
        if felt:
            parts.append(felt.rstrip(".") + ".")
        if familiar:
            parts.append("Like when the words were " + "; and when they were ".join(
                f'"{said}" ({when})' for _, said, when in familiar) + ".")
    else:
        parts.append(f"On the whole it feels {tone[0]}, with {tone[1]}; it is hard to tell more than that right now.")
    if thoughts:
        listed = "; ".join(f'"{text}"' + (f" ({WENT[went]}" + "".join(f": {why}" for why in reasons[:1]) + ")"
                                          if went in WENT else "") for text, went, reasons in thoughts)
        parts.append("On the mind today, the latest first: " + listed + ".")
    elif thoughts is not None:
        parts.append("Nothing much on the mind today.")
    if unsaid:
        want, who, say = unsaid
        parts.append(f"Wanting to {'ask' if want == 'ask' else 'tell'} {who}: {say}")
    if did:
        parts.append("Done today: " + "; ".join(d.rstrip(".") for d in did) + ".")
    if going:
        parts.append("Still going: " + "; ".join(going) + ".")
    if put_off:
        parts.append("Put off: " + "; ".join(put_off) + ".")
    if also:
        parts.append("Also here now: " + "; ".join(also) + ".")
    if moved:
        parts.append("What got through today: " + "; ".join(
            f"{moment} ({'it hurt' if sting < 0 else 'it lifted'}"
            + (f'; called "{called[0]}"' if called and called[0] else "") + ")"
            for moment, sting, *called in moved) + ".")
    if leaned:
        what, reasons = leaned
        parts.append(f"Last weighing what to do: leaning toward {what}"
                     + (". Why: " + "; ".join(reasons) if reasons else "") + ".")
    if self_view:
        parts.append("Known of myself by now: " + self_view)
    if about:
        parts.append(f"Looked for: {about}. " + ("What comes back about it: " + "; ".join(
            f"{memory.rstrip('.')} (remembered {clearly(strength)})" for memory, strength in recalled) + "."
            if recalled else "Nothing comes back about it."))
        parts.extend(whose)
    return "Looking inward: " + " ".join(parts)

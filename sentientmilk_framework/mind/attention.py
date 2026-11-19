"""Attention turned inward: whether a moment draws her attention to herself, and what little it takes in
(``Mind.attend``).

Her sense of her body runs all the time (feel.Interoception), and every note carries what stands out against
what she is used to. Looking deeper takes attention, and attention needs a reason:
- her body is a lot further from where it usually sits than she knows. That covers what has lasted, which getting
  used to hides, and what came suddenly, against her senses' prediction;
- she is torn between two ways of acting;
- she is asked.
Focus on something outward holds the first off (acetylcholine favours what is attended: Hasselmo 2006).

What she took in is known for that stretch. An unchanged state does not call again; a meaningful change does;
sleep forgets it. Noticing is not naming: it eases nothing, names nothing and keeps no memory of its own (the
moment it is part of does)."""

from typing import Dict, List, Optional

from .feel import _amounts

LOT = 1.0  # what wins her attention for her body: a lot (feel.CHANNELS' unit), as far as her attention is free
FLOOR = 0.4  # less than this is too little to tell (Felt.standing_out's floor)
CHANGED = 0.4  # how much further than she knew a channel must go, to be news while she attends to it
TORN = 1.0  # two ways of acting within one temperature of each other (p2/p1 >= 1/e) are a toss-up to her own noise


def unknown(far: Dict[str, float], known: Dict[str, float]) -> Dict[str, float]:
    """What she does not know yet of each channel standing out (``far``: lots from where it usually sits, signed;
    ``known``: as she took it in). All of it when she never took it in or it turned the other way; otherwise how
    far it grew past what she knew."""
    out = {}
    for name, value in far.items():
        if abs(value) < FLOOR:
            continue
        was = known.get(name)
        part = abs(value) if was is None or was * value < 0 else abs(value) - abs(was)
        if part > 0:
            out[name] = part
    return out


def news(far: Dict[str, float], known: Dict[str, float], free: float, attending: bool) -> Dict[str, float]:
    """The channels that win her attention, with how much of each is new to her. While she attends to herself,
    a change of ``CHANGED`` is enough (what reaches her cortex mid-work, life.during). Otherwise only a lot she
    does not know, as far as her attention is free (``free``: 1 - focus held outward, times her insight)."""
    found = unknown(far, known)
    if attending:
        return {name: part for name, part in found.items() if part >= CHANGED}
    return {name: part for name, part in found.items() if part * free >= LOT}


def torn(considered: List[dict], temperature: Optional[float]) -> Optional[dict]:
    """The way of acting that pulls as much as the one she leans to (``considered``: will.Choice.considered), when
    the two are within ``TORN`` temperatures of each other, so her own noise cannot tell them apart (conflict
    draws control: Botvinick et al. 2001); None when one clearly wins."""
    picked = next((one for one in considered if one.get("picked")), None)
    others = sorted((one for one in considered if not one.get("picked")), key=lambda one: -one["worth"])
    if not picked or not others or not temperature:
        return None
    return others[0] if abs(picked["worth"] - others[0]["worth"]) <= TORN * temperature else None


def body_words(far: Dict[str, float], lasting: Dict[str, float], names: List[str]) -> str:
    """Her body as attention takes it in, against where it usually sits (what getting used to it hides from
    her passing sense): what has lasted ("For a while now: much less drive than usual") apart from what came
    lately."""
    old = [(name, far[name]) for name in names if abs(lasting.get(name, 0.0)) >= FLOOR]
    new = [(name, far[name]) for name in names if abs(lasting.get(name, 0.0)) < FLOOR]
    return " ".join(filter(None, (f"For a while now: {_amounts(old)} than usual." if old else "",
                                  f"Lately: {_amounts(new)} than usual." if new else "")))

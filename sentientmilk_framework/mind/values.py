"""What she has come to like and dislike: learned from what things did to her, not written by anyone.

Each situation and option is a few features ("act:do", "tag:coding", "act:decline|tag:coding",
"hour:night"); her values are a weight for each, the feeling she expects from it. After something
happened, the weights move toward what she actually felt (a prediction error, at a rate her acetylcholine
sets). These are her somatic markers: the thought of an option comes with a gut feeling from what such
things did to her before. Weights she has not used fade in sleep, so old likes can be outgrown.
"""

import math
from typing import Dict, Iterable, List, Tuple

LIMIT = 1.0  # a learned feeling is at most this strong
FAINT = 0.02  # weaker than this, sleep lets a weight go; as strong, it is a leaning she keeps


def _clip(value: float) -> float:
    return -LIMIT if value < -LIMIT else LIMIT if value > LIMIT else value


def subjects(tags: Iterable[str]) -> List[str]:
    """What a moment is about, as she learns to like or dislike it: one feature a subject."""
    return [f"tag:{w}" for w in dict.fromkeys(" ".join(str(t).lower().split()) for t in tags) if w][:6]


def features(act: str, tags: Iterable[str] = (), intent: str = "", hour: float = 12.0, app: str = "") -> List[str]:
    """What an option is, as she learns about it: the act, what it is about, with whom and when."""
    when = "night" if hour < 6 or hour >= 23 else "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    words = [f[4:] for f in subjects(tags)]
    found = [f"act:{act}", f"when:{when}", f"act:{act}|when:{when}"]
    if intent:
        found += [f"intent:{intent}", f"act:{act}|intent:{intent}"]
    if app:
        found.append(f"app:{app}")
    for word in words:
        found += [f"tag:{word}", f"act:{act}|tag:{word}"]
    return found


class Values:
    def __init__(self, weights: Dict[str, float] = None, uses: Dict[str, int] = None):
        self.weights: Dict[str, float] = dict(weights or {})
        self.uses: Dict[str, int] = dict(uses or {})

    def predict(self, found: List[str]) -> float:
        """The feeling she expects (-1..1) from what she knows of these features."""
        known = [self.weights[f] for f in found if f in self.weights]
        return _clip(sum(known) / math.sqrt(len(found))) if known else 0.0

    def learn(self, found: List[str], felt: float, rate: float) -> float:
        """What it felt like (-1..1): the weights move toward it; the prediction error."""
        error = _clip(felt) - self.predict(found)
        step = rate * error / math.sqrt(max(1, len(found)))
        for f in found:
            self.weights[f] = _clip(self.weights.get(f, 0.0) + step)
            self.uses[f] = self.uses.get(f, 0) + 1
        return error

    def fade(self, share: float = 0.1, floor: float = FAINT) -> None:
        """In sleep: every weight fades a little toward nothing; the faintest go."""
        for f in list(self.weights):
            self.weights[f] *= 1.0 - share
            if abs(self.weights[f]) < floor:
                del self.weights[f]
                self.uses.pop(f, None)

    def subjects(self, count: int) -> List[str]:
        """What she knows things to be about, the most met first: for filing what comes next under them."""
        met = sorted(((uses, name[4:]) for name, uses in self.uses.items() if name.startswith("tag:")), reverse=True)
        return [subject for _, subject in met[:count]]

    def leanings(self, count: int = 5) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
        """Her strongest likes and dislikes: subjects (``tag:``) by what moments about them did to her, any she
        keeps through sleep (FAINT). One moment that moved her is a liking (before 0.24.1 two were needed).
        Before 0.29.1 a fixed 0.05 left nearly all out, as one moment moves a subject 0.01-0.05 (her rate over
        the root of the subjects it had) and sleep fades it, and the strongest five were taken before a subject
        and its acts were told apart: her brain held a dozen likes and showed one, "what to watch"."""
        about = [(f, w) for f, w in self.weights.items() if f.startswith("tag:")]
        likes = sorted((item for item in about if item[1] >= FAINT), key=lambda item: -item[1])[:count]
        dislikes = sorted((item for item in about if item[1] <= -FAINT), key=lambda item: item[1])[:count]
        return likes, dislikes

    def fond(self, found: List[str], floor: float = FAINT) -> Tuple[List[str], List[str]]:
        """Of these subjects, the ones she likes and the ones she dislikes (by their learned worth)."""
        return ([f[4:] for f in found if self.weights.get(f, 0.0) >= floor],
                [f[4:] for f in found if self.weights.get(f, 0.0) <= -floor])

    def to_dict(self) -> dict:
        return {"weights": self.weights, "uses": self.uses}

    @classmethod
    def from_dict(cls, data: dict) -> "Values":
        return cls((data or {}).get("weights"), (data or {}).get("uses"))

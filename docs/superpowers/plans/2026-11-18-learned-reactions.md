# Learned Reactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** She learns bodily reactions to cues from what followed them (one intense outcome is enough), feels them
ahead when a like cue comes back, avoids what she dreads and is relieved by it, and gets over a fear by meeting the
cue without the outcome, a getting-over that holds less elsewhere, with time and under stress.

**Architecture:** A new associative store `mind/reactions.py` (SQLite table `reactions` + `reactions_vectors` in her
mind's database), matched by meaning (her embedder, likeness anchored between unrelated and paraphrase) and by
surroundings (0.38 cues). Mind wires it into reading (`before`), doing (`during`), outcomes (`after`), thinking
(`_think`) and choosing (`will.worth` part "reacting"). The imagine answer names a message's cause.

**Tech Stack:** Python 3.12, SQLite, numpy, pytest; MilkChan PyQt5.

**Spec:** docs/superpowers/specs/2026-11-18-learned-reactions-design.md

## Global Constraints

- Version 0.39.0 (pyproject.toml, `sentientmilk_framework/__init__.py`, extension/manifest.json).
- Reacting channels: her chemistry and grievance (`REACTS = (*CHEMICALS, "grievance")`), amounts in lots
  (`CHANNELS[name][1]` per lot), pushed with `body.apply`.
- Likeness: `clip((cos - floor) / (same - floor)) ** (2 - anxious)`; same cue at likeness >= 0.9 (`SAME_CUE`).
- Learning rate: associability (new 1.0; then 0.3 x |error| + 0.7 x before) x (0.2 + 0.8 x noradrenaline) x salience.
- Reconsolidation window 10 min to 6 h after a reaction is called up. Spontaneous recovery time 2 days x trials.
- No feeling words, no gates, no keyword lists; service calls (embedding) never under her lock.
- Stage only my hunks (the other agent's uncommitted work in life.py, memory.py, prompts.py, will.py stays).

## Review Focus

- No embedder (service down or no key): reading, doing and learning go on without meaning cues; surroundings still
  work; nothing raises.
- A reaction's own push must not teach itself (outcome minus what reactions did in the moment).
- A turn with no previous turn in the chat, or a previous turn by another actor or over a day old: no "then" cues.
- Old minds (0.38 databases) open and migrate (new table only).
- An imagine answer without a cause, or with a non-string cause: no cause.

---

### Task 1: The store (`mind/reactions.py`, `vectors.py`)

**Files:** Create `sentientmilk_framework/mind/reactions.py`; modify `sentientmilk_framework/vectors.py`
(`SAME` pairs, `Vectors.same(embedder) -> float`); test `tests/test_reactions.py`.

**Interfaces (produces):**
- `REACTS`, `SAME_CUE = 0.9`, `anxious(levels) -> float` (cortisol above usual over 0.5, 0..1).
- `class Reactions(db, lock)`: `.vectors`, `.embedder` (set by recall like Memory's);
  `likeness(texts: List[str], anxious: float) -> List[Dict[int, float]]` (embeds outside any lock; [] maps when no
  embedder); `vectors_of(texts) -> Optional[np.ndarray]` kept from the last likeness call for new cues;
  `expressed(rid, now, around, stress) -> Dict[str, float]`; `predict(present: Dict[int, float], now, around, stress)
  -> Dict[str, float]` (sum of likeness x expressed); `called(ids, now)` (marks reactivation);
  `learn(cues: List[dict], outcome: Dict[str, float], arousal: float, now, around: List[str], salience: Dict[str,
  float], episode: Optional[int], stress: float) -> List[dict]` (each cue: {"text", "source", "kind": "meaning" |
  "around", "found": likeness map or None, "vector": array or None}); `strongest(count, now, around, stress)`.
- [ ] Tests (fail first): one intense outcome learns most of itself, a mild one little; blocking (a cue that adds
  nothing learns nothing); likeness >= 0.9 updates the same reaction, else a new one; extinction holds in the
  surroundings it was learned in and less in others, less with time, less under stress; the outcome again takes
  the hold away fast; a shortfall within the window after `called` changes the reaction itself; safety (negative
  cortisol) is learned; no embedder: meaning cues are skipped, surroundings learn; the gradient widens when anxious;
  a 0.38 database opens.
- [ ] Implement; run `pytest tests/test_reactions.py`; commit.

### Task 2: The cause in her reading (`prompts.py`)

**Files:** modify `sentientmilk_framework/mind/prompts.py` (IMAGINE: append `{"cause": "..."}` when the message
tells what led to something; `imagined()` returns `"cause"`: a stripped string or ""); test `tests/test_reactions.py`.
- [ ] Tests: a cause object anywhere in the array is read; none, or not a string: "".
- [ ] Live check of the prompt line on 6 messages (cause named for the two outcome stories, none for chat), the other
  fields as before; commit.

### Task 3: Wiring into her mind (`life.py`, `will.py`, `recall.py`)

**Files:** modify `sentientmilk_framework/mind/life.py`, `sentientmilk_framework/mind/will.py`,
`sentientmilk_framework/recall.py` (sweep embeds `mind.reactions.vectors`); test `tests/test_mind_reactions.py`.

**Interfaces:** `will.worth(option, seen, body, learned, reacting=0.0)` adds `parts["reacting"] = reacting`;
`will.choose(..., reacting=None)` (`reacting(option) -> float`, as-if valence); REASONS "dread" ("the thought of
doing it sets you on edge: something like it went badly before") and "eager" ("the thought of doing it pulls at
you: something like it went well before"). Mind: `self.reactions`; decision gains "cause", "then", "reacted";
`self._working[run]["actions"]`, `["reacted"]`; waiting entry gains "actions", "option"; state `reactions`,
`reacted`.
- [ ] Tests (fail first, through the real Mind with the stand-in provider and embedder): a reaction alike to a
  message moves her as she reads it ("reacting to: ..."); an action of hers alike to a feared cue moves her as she
  does it and its note reaches her cortex; a message naming a cause after an intense outcome teaches a reaction to
  it, and the outcome excludes what reactions did; the next message teaches her last turn's option and actions; a
  dreaded option is worth less and can still be picked; choosing not to do it relieves her and teaches the act; a
  thought alike to a feared cue moves her; a story about the user teaches her; state shows reactions and what
  called them up; nothing breaks without an embedder.
- [ ] Implement; run the mind test files; commit.

### Task 4: Seen (panel, MilkChan Inside her head)

**Files:** `sentientmilk_framework/panel.py` (card "What she has learned to react to"); MilkChan
`milkchan/desktop/ui/mind_window.py` (neuron `reactions` "Learned reactions", amygdala; card rows); tests
`tests/test_panel.py`, MilkChan `tests/test_mind_window.py`.
- [ ] Tests; implement; commit.

### Task 5: Exam, docs, version, ship

**Files:** `scripts/exam.py` (stations `learned_fear`, `told_fear`; trace check "reacted"), `tests/test_exam.py`,
`docs/consciousness-exam.md`, `docs/architecture.md` (10.14), `docs/cognition-backlog.md`, version 0.39.0.
- [ ] Full suites both repos (clean worktree), live exam 0.38 vs 0.39 on a frozen copy (new stations + full set),
  results in docs; commit only my hunks; push; pin; build.

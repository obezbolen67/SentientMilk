# Memory that feels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her memories keep what she felt and what was around her, come back by rare surroundings, her state and
their feeling as well as by meaning, and move her body when they do (SentientMilk 0.38, MilkChan senses).

**Architecture:** Approach A of the spec: episodes gain `felt` (peak-end way, lots) and cues (`episode_cues`);
`Memory.recall` scores meaning + cue overlap (rarity-weighted) + state likeness + intensity, with habituation;
`Mind._refeel` moves the body by a share of a recalled moment's feeling; recall.py rounds inherit their
exchange's feeling; sleep softens unevenly and tags related weak memories. MilkChan sends the window in front
and what plays, with each message and with its frequent `/mind` look.

**Tech Stack:** Python 3.12, sqlite3, numpy vectors (existing), PyQt5, winrt (Windows.Media.Control: new).

**Spec:** docs/superpowers/specs/2026-11-18-memory-that-feels-design.md

## Global Constraints

- No feeling names on memories; no list or regex of feelings (0.37 rule): a memory brings back a body.
- No caps or step limits; no code gates refusing her tool calls.
- Never hand-edit her saved memories: old episodes keep working without `felt` (re-feel nothing).
- Re-felt share: 0.3 x charge x strength_now x cue quality (meaning relevance or cue overlap, whichever higher).
- Cue strength: `log(N / n) / log(N)` (N episodes, n with the cue); 1 when N < 2.
- Surroundings shown while `strength_now >= 0.5`.
- MilkChan switches default on: `senses.window`, `senses.playing`.
- Another agent's uncommitted hunks are in the SentientMilk and MilkChan trees: commit only this plan's hunks.

## Review Focus

- A cue present in nearly every memory ("user: X", "writes from: their computer") must not bring anything back on
  its own: tested in Task 2.
- The same song playing for a whole evening must not bring the same memory back every message: habituation,
  Task 2.
- A brain without an embedder (service down) still recalls by surroundings: Task 2.
- Episodes from before 0.38 (no `felt`, no cues) still recall and re-feel nothing: Task 4.
- MilkChan without the winrt media package or off Windows sends nothing and never crashes: Task 9.

---

### Task 1: What a moment keeps

**Files:** Modify `sentientmilk_framework/mind/memory.py`. Test: `tests/test_memory_feels.py` (new).

**Interfaces:** Produces `Memory.add(..., felt: Dict[str, float] = None, cues: Iterable[str] = ())`;
`Memory.cues(ids) -> Dict[int, List[str]]`; `Memory.cue_strength(cues) -> Dict[str, float]`;
`cue(key, value) -> str` (module: `"key: value"`, whitespace collapsed, lowercased, 160 chars);
`intensity(felt) -> float` (Euclidean size, lots). Column `episodes.felt TEXT` (JSON or NULL).

- [ ] Test `test_a_moment_keeps_its_feeling_and_what_was_around_it`: add with felt and cues; by_ids row's felt
  parses back; cues(ids) lists them normalized; cue_strength: a cue in 1 of 10 episodes 1.0, in all 10 0.0.
- [ ] Implement; run; commit with Task 2.

### Task 2: What comes back

**Files:** Modify `memory.py` (`recall`). Test: `tests/test_memory_feels.py`.

**Interfaces:** `Memory.recall(cue, valence, now, ..., cues=(), state=None)` adds `cued` (summed strength of
shared cues) and `through` (the strongest shared cue) to each returned episode; admits an episode with no
meaning likeness when `cued >= 0.5`; score adds `1.0 * cued + 0.35 * likeness(state, felt) + 0.3 * charge *
min(intensity, 2) / 2 - 0.6 * exp(-(now - recalled) / 1800)`.

- [ ] Tests: `test_a_rare_shared_surrounding_brings_back_a_memory_unlike_in_meaning` (no embedder: recall by
  cues alone returns the episode with `through` the rare cue); `test_a_common_surrounding_brings_back_nothing`;
  `test_a_memory_that_just_came_back_is_held_off` (recalled 1 min ago loses to an equal one); `test_the_more
  intense_comes_sooner` (two cued equally, the intense one first); `test_her_state_like_the_moment_favors_it`.
- [ ] Implement; run `tests/test_memory_feels.py tests/test_mind_memory*.py`; commit.

### Task 3: The details fade first

**Files:** `memory.py` (`line`). Test: `tests/test_memory_feels.py`.

- [ ] Test: vivid episode with cues "time: late at night", "playing: clair de lune": line has "late at night"
  and "clair de lune playing"; strength_now < 0.5: neither; `through` given: line has "what brings it back".
- [ ] Implement `line(episode, now, *, waking_evidence=False, cues=(), through=None)`; commit.

### Task 4: Her mind keeps them

**Files:** `mind/life.py` (after: exchange; _think: thought; event episodes), `presence.py` (`around`),
`server.py` + `client.py` (`/mind?around=JSON`). Test: `tests/test_mind_feels.py` (new).

**Interfaces:** `Presence.report(..., around: Optional[Dict[str, str]] = None)`, `Presence.around` (dict, with
`Presence.around_at`); `Mind.state(..., around=None)`; `Mind._cues(run_or_none, now) -> List[str]` (context
entries of the run, time of day band, with, app, device, presence: away/busy, and `presence.around`);
`HOURS` bands: 0-5 "late at night", 5-8 "early morning", 8-12 "morning", 12-17 "afternoon", 17-21 "evening",
21-24 "late evening".

- [ ] Tests: a turn with context {"playing": "Clair de Lune"} keeps an exchange with felt = mean of the
  decision's way and the turn's end change, and cues incl. "playing: clair de lune" and "time: ..."; a thought
  keeps felt and cues; an old-style episode (felt NULL) recalls and re-feels nothing.
- [ ] Implement; commit.

### Task 5: Remembering moves her

**Files:** `mind/life.py` (`_refeel`, `_arrives`/`before`, `_think`, `look_inward`). Test: `tests/test_mind_feels.py`.

**Interfaces:** `Mind._refeel(episodes, now, why_prefix="remembering") -> Dict[str, float]` applies
`felt[ch] * CHANNELS[ch][1] * 0.3 * charge * strength_now * quality` per channel; quality =
`max(relevance, cued)`; called after `levels` snapshot in `before` (so it is in "Reading it"), after the thought
in `_think`, in `look_inward` for what comes back. Remove the 0.33 rumination cortisol stir.

- [ ] Tests: a message that brings back a moment that moved cortisol up raises cortisol now by the share and
  shows in the note's "Reading it"; recalled twice, applied each time it comes; no felt: nothing applied;
  rumination re-feels the hurt moment through the same path.
- [ ] Implement; run mind tests; commit.

### Task 6: Her wandering (spec 11-16)

**Files:** `mind/life.py` (`_think` wonder, `_remember_task`), `memory.py` (`near(ids, seconds) -> List[dict]`,
`newness(text, before) -> Optional[float]`), `presence.py` (`words(now) -> str`), `runs.py` (task profile
`"signals": False`). Test: `tests/test_mind_wander.py` (new), `tests/test_runs*.py` for the task profile.

**Interfaces:** `Presence.words(now)`: "" when nobody can tell; else "at the computer" / "away from the
computer for <ago>" / "the screen locked" / "absorbed in something fullscreen"; `Memory.newness(text,
before)`: 1 - max relevance in meaning among episodes before ``before`` (None without the embedder);
wander novelty push `0.3 * newness` (0.15 when None), dopamine `0.06 * newness` (0.03); task end novelty push
`0.3 * newness`; chain chance `exp(-(now - last_thought_at) / 3600)`.

- [ ] Tests: the thought's input has the last thought's age and "What you can tell of"; a repeated thought
  fills novelty less than a new one; the cued memory shares the surroundings and is not the last talk; a
  chain brings a neighbour in time of the last thought's memory; a finished look-up fills novelty; a task's
  profile has no signals and its stored reply no header.
- [ ] Implement; commit.

### Task 7: Rounds take their moment's feeling

**Files:** `recall.py` (`weighed`), `mind/life.py` (`_arrives`), `memory.py` (`by_events(ids)`).

- [ ] Tests: a round whose exchange episode is intense weighs `need x (1 + intensity)` and outlasts a flat one;
  a transcript hit whose event has an episode re-feels that episode.
- [ ] Implement; commit.

### Task 8: Sleep

**Files:** `memory.py` (`soften` uneven; `tag_related(ids, embedder)`), `mind/life.py` (`_consolidate`).

- [ ] Tests: soften(share) takes 1.4 x share from an unpleasant moment and 0.6 x share from a pleasant one;
  the night's most intense moment raises the strength of the weakest memory most like it in meaning.
- [ ] Implement; commit.

### Task 9: MilkChan senses and Memories card

**Files:** MilkChan `milkchan/desktop/services/surroundings.py` (new), `services/brain.py` (turn context,
`mind(around=...)`), `core/config.py` (`senses` defaults), `ui/settings_window.py` (two switches),
`ui/mind_window.py` (Memories card lists `state['remembered']`), `pyproject.toml`
(`winrt-Windows.Media.Control; sys_platform == 'win32'`). SentientMilk `state()["remembered"]`.

**Interfaces:** `surroundings.now(config) -> Dict[str, str]` keys "in front" (app — title, 160 chars) and
"playing" (title — artist), each only when its switch is on and it can be read.

- [ ] Tests: switches off: {}; no media package: no "playing", no error; turn context carries them; settings
  save them; the Memories card lists what came back with what brought it.
- [ ] Implement; MilkChan tests; commit.

### Task 10: Exam, docs, ship

- [ ] Exam stations `song_brings_back` (plant a moment with felt + cue, then the cue with an unrelated message)
  and `moment_hurt` (ask about a planted hurt moment); run 0.37 vs 0.38 two trials, grade, read traces.
- [ ] Architecture 10.13, backlog, spec results; version 0.38.0; full suites; commit both repos; pin; build.

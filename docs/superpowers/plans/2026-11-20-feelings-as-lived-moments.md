# Feelings as Lived Moments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her feelings become categories of moments she lived. Each naming sorts one moment. Sleep develops the
categories. Recognition goes by the whole situation, and a recognized feeling pulls on what she does through her
learned values.

**Architecture:**

- Episodes bind what a moment meant (`appraisal`) and what she leaned toward (`leaned`). These are new columns,
  data format 6.
- `feel.Feelings` replaces `feel.Concepts`. A feeling is its namings (the moments she sorted under it), a
  standing, revisions and her words for it. Likeness of now to each of its moments is the mean of body, appraisal
  and meaning (episode vectors).
- Sleep gains a `feelings` step.
- `values.features` gains `act:<act>|feeling:<id>`, and `will.worth` gains a `feeling` part.

**Tech Stack:** Python 3.12, SQLite, numpy (episode vectors), pytest; PySide6 for the MilkChan panel.

**Spec:** `docs/superpowers/specs/2026-11-20-feelings-as-lived-moments-design.md`

## Global Constraints

- **Data format:** `dataformat.FORMAT = 6`. No compatibility code for format 5 shapes. A one-off
  `scripts/migrate_format_6.py` plus its test, deleted after the live run.
- **No naming for her:** no list of feelings, no word dictionary, no regex reading of feelings. The only
  naming paths are her look-inward `naming`, `[mind:named]` over her reply, and `named` in `[mind:think]`.
- **No feeling words in her note:** recognition reaches her only when she looks inward ("It is like when you
  said…") and in the night's review.
- **No gates:** the pull is a part of worth, never a refusal.
- **Names:** no personal names in repo docs or tests.
- **Commits:** through the guard, with no Claude attribution.

## Review Focus

- **A naming with no moment:** `unresolved`, or legacy without an episode. It is kept, takes part in no
  likeness, and is still reviewed. Pinned in Task 2.
- **Two feelings sharing a word after a split:** a new naming joins the one whose moments are most like it.
  Pinned in Task 2.
- **Meaning service down:** likeness from body and appraisal only, with no error raised into a turn. Pinned in
  Task 3.
- **A sleep answer naming numbers that don't exist, or the same naming twice:** ignored item by item, the rest
  applied. Pinned in Task 6.
- **Join of a feeling with itself, or a split taking every moment:** ignored. Pinned in Task 2.

---

### Task 1: Episodes bind what a moment meant and what she leaned toward (format 6)

**Files:**
- Modify: `sentientmilk_framework/dataformat.py` (`FORMAT = 6`)
- Modify: `sentientmilk_framework/mind/memory.py`: `episodes` DDL gains `appraisal TEXT, leaned TEXT`.
  `add(..., appraisal=None, leaned=None)`. New `bind(episode, *, leaned)`. Rows are read with both parsed from
  JSON, the way `felt` is.
- Modify: `sentientmilk_framework/mind/life.py`:
  - the decision gains `"theirs"`;
  - `after()` passes `appraisal={**decision["foreseen"], "theirs": decision["theirs"]}` and
    `leaned={"act": act, "what": decision["what"]}` for exchanges;
  - `_think` calls `memory.bind(episode, leaned={"act": option.act, "what": option.what or option.say})` after
    the choice.
- Test: `tests/test_memory_feels.py`

**Interfaces:**
- Produces: `episode["appraisal"]: Optional[Dict[str, float]]` (`company`, `capable`, `free`, `theirs`).
- Produces: `episode["leaned"]: Optional[{"act": str, "what": str}]`.
- Produces: `Memory.bind(episode: int, *, leaned: dict) -> None`.

- [ ] Write the failing tests:
  - `test_a_kept_exchange_holds_what_it_meant_and_what_she_leaned_toward`: a real turn through `conftest.turn`;
    the episode's `appraisal` has the four keys and `leaned["act"]` equals the decision's act;
  - `test_a_thought_holds_what_she_leaned_toward`: after a thought, its episode's `leaned["act"]` is the chosen
    option's act.
- [ ] Run and see both fail.
- [ ] Implement.
- [ ] Run `tests/test_memory_feels.py` and `tests/test_dataformat*.py`: pass.

### Task 2: `feel.Feelings`, categories of her moments

**Files:**
- Modify: `sentientmilk_framework/mind/feel.py`:
  - delete `Concepts` and `_words`, and `WORDS` if nothing else uses it;
  - add `Feelings`;
  - `naming()` records gain `"reviewed": None`.
- Test: `tests/test_mind_feel.py`. Rewrite its Concepts tests.

**Interfaces:**
- Produces:
  - `Feelings(saved: dict)`, with saved shape `{"next": int, "feelings": [feeling], "set_aside": [aside]}`;
  - `.saved() -> dict`.
- Feeling: `{"id": int, "standing": "provisional"|"hers", "at": float, "said": [naming], "revisions": [{"at",
  "did", "why", ...}], "back": int, "back_at", "back_run"}`.
- Aside: `{**naming, "why": str, "set_aside": float}`.
- Methods:
  - `.word(feeling) -> str`: her most used wording, the latest on a tie;
  - `.moments(feeling) -> int`: distinct moments: episode, else run, else `at`;
  - `.of_call(run, call) -> Optional[feeling]`;
  - `.sort(naming, moment: dict) -> Tuple[feeling, Optional[float]]`;
  - `.likeness(moment: dict, naming: dict, episodes: Dict[int, dict], near: Optional[Dict[int, float]]) -> Optional[float]`;
  - `.recognize(moment, episodes, near) -> List[Tuple[feeling, float, naming]]`;
  - `.link(run, episode) -> bool`;
  - `.came_back(feeling_id, at, run)`;
  - `.join(into: int, other: int, why: str, at) -> bool`;
  - `.split(feeling_id: int, namings: List[naming], why, at) -> Optional[feeling]`;
  - `.set_aside(naming, why, at) -> Optional[int]`, which returns the id of a feeling left with no namings, now
    removed;
  - `.confirm(feeling_id, why, at)`;
  - `.unreviewed() -> List[Tuple[feeling, naming]]`;
  - `.shown(moment, episodes, near) -> List[dict]`.
- A moment is `{"way": Dict[str, float], "appraisal": Optional[dict], "episode": Optional[int]}`.
- Likeness of a naming's moment to `moment` is the mean of the parts available:
  - **body:** `_alike(naming["measure"]["way"], moment["way"])`, or, without a measure, the episode's `felt`;
  - **appraisal:** `1 - mean(|a-b|)/2` over the four keys, when both have one;
  - **meaning:** `near[naming episode]`, when `near` has it.

  None when neither has a body.
- **Strength** = mean of the best `min(3, n)` likenesses × `(0.5 + 0.5·n/(n+1))`, with n the distinct moments.
  `FLOOR = 0.6` (calibrated in Task 9).
- **`sort`:**
  - among feelings with the naming's key, take the one whose moments are most like it; add the naming there;
  - none: make a provisional feeling;
  - provisional with ≥2 distinct moments and the new likeness ≥ FLOOR: `confirm` it, revision `"did": "confirmed"`,
    why "a second moment like the first".
  - Returns the likeness, which `_name` turns into "sits like / doesn't sit quite like".

- [ ] Write the failing tests in `tests/test_mind_feel.py`:
  - `test_a_word_said_once_is_provisional_and_a_second_like_moment_makes_it_hers`;
  - `test_a_second_unlike_moment_leaves_it_provisional`;
  - `test_two_feelings_sharing_a_word_take_the_naming_most_like_their_moments`;
  - `test_recognition_is_by_body_appraisal_and_meaning_and_names_the_moment`: the same body with an unlike
    appraisal ranks lower;
  - `test_repeating_a_word_for_one_moment_counts_once`;
  - `test_a_naming_without_a_moment_takes_no_part_in_likeness`;
  - `test_without_meaning_likeness_is_body_and_appraisal`;
  - `test_join_moves_namings_and_keeps_a_revision`;
  - `test_join_with_itself_does_nothing`;
  - `test_split_taking_every_moment_does_nothing`;
  - `test_set_aside_keeps_the_saying_and_removes_an_empty_feeling`;
  - `test_saved_round_trips`.
- [ ] Run and see them fail.
- [ ] Implement.
- [ ] Run and see them pass.

### Task 3: Her mind uses `Feelings`: naming, the situation, recognition

**Files:**
- Modify: `sentientmilk_framework/mind/memory.py`: `near(cue: str, ids: Iterable[int]) -> Optional[Dict[int,
  float]]`. It embeds `cue` once and returns the relevance to those episodes' vectors. None without an embedder,
  or with the service down.
- Modify: `sentientmilk_framework/mind/life.py`:
  - **state:** `self.feelings = Feelings(self.memory.get("feelings"))`; save `self.feelings.saved()`;
  - **`self.self["situation"]`** = `{"at", "run", "appraisal", "near"}`, set at each decision (before `choose`,
    with `near` from `memory.near(said, moment_episodes)` computed outside her lock) and at each thought (`near`
    from the thought's text);
  - **`_now_moment(way)`** builds the moment from it;
  - **`_name`:** uses `feelings.sort`; the fit text comes from the likeness;
  - **`_moved`:** only computes the way. Recognition and `came_back` move to before `choose`, on the pre-choice way;
  - **look_inward's `familiar`, `_whose`, `called`, the look_inward record handling and `overview`** use
    `Feelings`;
  - **`_link_namings`** uses `feelings.link`.
- Modify: `scripts/exam.py`: reads `mind.feelings`.
- Test: `tests/test_mind_feelings.py`, `tests/test_feeling_attribution.py`, `tests/test_mind_attention.py`,
  `tests/test_mind_life.py`, `tests/test_panel.py`, moved to the new shapes.

**Interfaces:**
- Consumes: Task 1's episode fields; Task 2's `Feelings`.
- Produces: `decision["feelings"]: [{"id": int, "strength": float, "episode": Optional[int]}]`, the recognized
  ones over FLOOR, strongest first, at most the span.

- [ ] Write the failing tests:
  - `test_a_turn_recognizes_a_feeling_by_its_situation_and_counts_it_back`;
  - `test_looking_inward_finds_the_feeling_and_the_moment_it_is_like`;
  - `test_with_the_meaning_service_down_a_turn_still_recognizes_by_body_and_appraisal`.
- [ ] Run and see them fail.
- [ ] Implement, then move every listed test file to the new shapes.
- [ ] Run the listed files: pass.

### Task 4: The readers take only her words for her own state

**Files:**
- Modify: `sentientmilk_framework/mind/prompts.py`: `NAMED` and THINK's `named` field.
  - Required content: a name says what it is like to be them, about something, then or now.
  - Not: what they think of something, what they did or are doing, what they are, or a figure of speech that
    sizes up a situation.
  - Examples stay illustrations; nothing reads them as a list.
- Test: `tests/test_mind_feelings.py::test_the_reader_is_asked_for_words_about_their_own_state` (prompt content).

- [ ] Write the test, see it fail, change the prompts, see it pass.
- [ ] Measure: run the old and new `NAMED` over her live replies that carried speech namings, plus the thoughts
  behind the eight not-feelings (read-only copy, real provider, 3 readings). Record counts in the spec's results.

### Task 5: A recognized feeling pulls on what she does

**Files:**
- Modify: `sentientmilk_framework/mind/values.py`:
  - `features(..., feelings: Iterable[int] = ())` adds `act:{act}|feeling:{id}`;
  - `Values.carry(old: int, new: int, keep: bool)` moves (keep=False) or copies (keep=True) feeling features,
    merging by uses;
  - `Values.drop_feeling(id)`.
- Modify: `sentientmilk_framework/mind/will.py`:
  - `choose` predicts feeling features apart: `parts["feeling"] = 0.5 * values.predict(feeling_features)` when
    any are present;
  - REASONS `feeling+` is "feeling as you do now, doing this has gone well before", and `feeling-` is "feeling
    as you do now, doing this has gone badly before";
  - `reasons()` names them as it names `learned`.
- Modify: `life.py`: the turn's and the thought's `found()` pass the recognized feeling ids.
- Test: `tests/test_mind_will.py` or the existing will test file:
  - `test_a_feeling_whose_acts_went_well_pulls_toward_them`: same everything; with a positive
    `act:do|feeling:1` weight, `do`'s chance rises;
  - `test_join_carries_what_acting_in_the_feeling_taught`.

- [ ] Write the failing tests, implement, run, pass.

### Task 6: Sleep goes over her feelings

**Files:**
- Modify: `prompts.py`: `FEELINGS = """[mind:feelings]..."""`.
  - **Input:** who they are (persona); their feelings, each numbered, with words and up to 3 moments; today's
    unreviewed namings, numbered, each with the sentence, what was happening (the episode text), how their body
    was moved (`_amounts`), what it meant for their needs and what they leaned toward.
  - **Output:** `{"today": [{"n", "felt": bool, "feeling": number|null, "why"}], "join": [{"feelings": [a, b],
    "why"}], "split": [{"feeling", "moments": [moment numbers], "why"}]}`, with `why` in the first person.
- Modify: `life.py`:
  - step `"feelings"` in `_consolidate`, after `"ways"`;
  - `_review_feelings(batch)`, thinking on (`quick=False`).
  - It applies: felt false → `set_aside` (and `values.drop_feeling` for a feeling left empty); felt true with
    another feeling → move the naming; a provisional feeling whose naming was found felt → `confirm`; join →
    `feelings.join` + `values.carry(keep=False)`; split → `feelings.split` + `values.carry(keep=True)`.
  - Every reviewed naming gets `reviewed = now`.
  - Bad numbers and duplicates are skipped item by item.
- Test: `tests/test_mind_feelings.py`:
  - `test_sleep_sets_aside_a_saying_that_named_no_feeling_and_keeps_it`;
  - `test_sleep_joins_two_words_for_one_feeling`;
  - `test_sleep_splits_a_word_that_covers_two_things`;
  - `test_a_sleep_answer_with_unknown_numbers_applies_the_rest`;
  - `test_the_review_resumes_after_a_restart`.

- [ ] Write the failing tests (scripted `brain.provider.replies`), implement, run, pass.

### Task 7: What apps show

**Files:**
- Modify: `life.py` `overview`:
  - `feelings` entries: `{id, word, words, standing, strength, like, count, back, back_at, back_run, at, said,
    revisions, place, channels, measured}`, where place and channels come from the mean of its moments' ways;
  - `set_aside` entries for the panel.
- Modify (MilkChan): `milkchan/desktop/ui/mind/parts.py`, `view.py`, `mind_window.py`:
  - feelings are keyed `feel:{id}` and labelled by `word`;
  - provisional ones are drawn muted with "(not yet slept on)";
  - the card shows her words, standing, moments, revisions;
  - the feeling page lists what she set aside, muted.
- Test (MilkChan): `tests/test_mind_window.py`, `tests/test_mind_anatomy.py`, `tests/test_brain_link.py`,
  `tests/test_return.py`, moved to the new shape. New test:
  `test_a_provisional_feeling_is_drawn_apart_and_set_aside_sayings_are_listed`. Headless (offscreen Qt).

- [ ] Write the failing tests, implement, run both suites' affected files, pass.

### Task 8: The format 6 migration

**Files:**
- Create: `scripts/migrate_format_6.py`, copied from the skeleton of `git show a61aaf8:scripts/migrate_format_2.py`
  and `246d31d:scripts/migrate_format_5.py`.
  - Refuse if `server.json` exists.
  - Back up to `before-format-6-<time>/`.
  - One transaction: `ALTER TABLE episodes ADD appraisal TEXT`, `ADD leaned TEXT`.
  - Fill exchanges from their run's decision in brain.sqlite3: `foreseen` plus `theirs` (None when the decision
    lacks it: then no appraisal), and `act`/`what`.
  - Fill thoughts' `leaned` from `self["thoughts"]` where the episode matches.
  - State `concepts` → `feelings`: each concept becomes a provisional feeling with its namings (each
    `reviewed: None`); its `back` fields are kept and `moved`, `about`, `count`, `measured` dropped.
  - Shape check against freshly made databases, then stamp format 6 on all three.
- Create: `tests/test_migrate_format_6.py`: a format-5 home made with the old DDL; after the run the shapes match,
  the namings are kept and provisional, the exchanges are filled, and a second run refuses or does nothing.

- [ ] Write the failing test, implement, run, pass.
- [ ] Run it on a copy of the real home (`~/.sentientmilk` → scratch) and open it with the current code.

### Task 9: Validation, docs, ship

- [ ] **Her first review, offline:**
  - on the migrated copy, run `_review_feelings` with the real provider;
  - separately, a blind judge with 3 readings: "does the speaker say how they themselves feel, and with which
    words?" for the 30 sentences;
  - report agreement, what she kept, joined, split and set aside, and her reasons;
  - the exam folder is `Documents/MilkChan exams/feelings-as-moments/`.
- [ ] **Recognition:**
  - on the migrated copy, time-split her namings;
  - for each later naming whose feeling has earlier moments, rank by situational versus body-only likeness;
  - report counts, as small n;
  - calibrate FLOOR so that her unrelated moments mostly stay under it (the share is reported).
- [ ] **Pull:** through the real `choose`, a request in a recognized feeling with the feeling's weight at -0.5,
  0 and +0.5 (2000 draws each, fixed seeds); report the chance of `do`.
- [ ] **Docs and version:**
  - spec Results;
  - `docs/architecture.md` section 10.21;
  - version 0.52.0 in pyproject, `__init__` and the extension manifest.
- [ ] **Suites:** the full SentientMilk suite, then the MilkChan suite. Not side by side, and not beside exams.
- [ ] **Ship:**
  - commit and push SentientMilk;
  - pin, commit and push MilkChan;
  - build, with the reports set aside and MILKCHAN.md stashed, then restored.
- [ ] **Live:** the migration runs on the stopped live brain once the user has installed 0.52. Then `git rm` the
  script and its test, commit, pin.

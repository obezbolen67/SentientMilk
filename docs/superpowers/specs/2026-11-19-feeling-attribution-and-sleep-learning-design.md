# Feeling attribution, and learning across experiences in sleep (0.45, data format 2)

The user's brief (2026-11-19) asks for two connected changes, end to end in SentientMilk and MilkChan:

1. A named feeling is tied to the experience it describes, by intent, never by what retrieval ranked first.
2. Sleep review can change what she expects next time a similar situation comes, kept apart from the episodes
   it came from and from the words she later uses for it, with each source counted once, reliability apart
   from accessibility, ordinary forgetting for weak insights, and a map that answers a causal question.

The user handed over the how ("proceed end to end"); every call below is mine unless marked as theirs.
Theirs: the live brain is migrated at the end (stopped and backed up first); no code reads old shapes (data
format 2 with a one-off migration, deleted after it runs).

## Part 1: what a naming names

### The bug

`Mind.look_inward(about, naming)` passed `came_back[0]` (the first memory retrieval returned for `about`) to
`_name` as the moment named. `_name` then used that moment's run `way`, softened it by 0.15, and
`Concepts.add` linked the words to it. In the user's brain, run 692's naming ("something warm and a bit
unearned, that I keep saying anyway") holds run 691's response (reward +0.231, alertness +0.169, closeness
+0.075) and episode 341, while the exchange she was in became episode 342 (+0.183, +0.159, +0.063).

### The fix

- **Intent is explicit.** `look_inward` gains one optional argument, `moment`: the number of a past moment she
  means, as looking shows it. Recalled lines and "what got to you" lines now show their numbers (`#341`).
  Without `moment` a naming is of now. With a `moment` that is not an existing lived moment (exchange, event
  or thought) the naming stays *unresolved*: kept as her words, no target, no measurement, nothing softened.
  No keyword reading of her words, no question to the user.
- **What came back is a reminder, not a target.** Every memory retrieval returned while she looked is kept
  on the naming as `reminded` (ids). Retrieval keeps its own effects (strengthening, being felt again);
  only a deliberate past naming softens its moment (0.15, once per naming).
- **Each naming is a record** (`Concepts.named[i]["said"]`, all of them, no longer the last three):
  - `words`: her wording exactly as she wrote it (no truncation; the concept's identity key stays the
    casefolded, space-collapsed form, without the old 80-character cut);
  - `text`: the sentence she said it in; `at`;
  - `how`: `tool` (look_inward naming), `speech` (said in her reply right after looking), `thought`;
  - `named`: `now`, `past`, `unresolved`, or `legacy` (stored by older software, below);
  - `run`, `event` (the input event of the run), `call` (the tool call id: a repeated call does nothing twice);
  - `episode`: for `past` the moment she named; for `now` the run's own moment, linked when the turn's
    episode is kept (`Mind.after`) and at start for any naming whose run was kept meanwhile;
  - `measure`: `{"of": "message" | "reading" | "moment", "way": {...}, "run"?, "episode"?}` or null:
    `message` is the response to the incoming message measured as she read it (the run's decision `way`),
    `reading` is a reading taken during introspection or a thought (what stands out in her body then),
    `moment` is a past moment's kept change (`felt`) when it has no run response; null when nothing measured;
  - `reminded`: what came back as she looked.
- **The concept** keeps `count` (deliberate namings), `moved` (running mean of measured namings only: an
  unmeasured or unresolved naming does not move it; `measured` counts those that did), `back` with `back_at`/`back_run` (recognized by likeness
  without being named: never counted as a naming), `at` (last naming).
- **Old records** become `named: "legacy"` in the migration, their stored episode kept as `episode`: what the
  old software stored, its intended target not reconstructed. Older software kept no numbers per naming, only
  the concept's mean of every naming: the records get no `measure`, the mean stays, and `measured` starts at
  the old `count` so the next measured naming weighs as it would have.

### Desktop

The feeling card lists each naming with what it named (the exchange she was in, a past moment, a moment not
found, or "stored by an older version: linked to #341; what she meant can't be told"), what it reminded her
of (links), and its bars labelled by what was measured ("Body response during the named exchange", "Body
reading while she looked inward", "Kept change of the past moment she named"). Recognition is its own line
("matched again by likeness 2 times, not named then"). The old heading "What it does to her body" goes: the
average is "Average of the measured responses she named it for (n of m namings)".

## Part 2: what sleep learns across experiences

### Representation: expectations (`mind/expectations.py`, mind.sqlite3)

An **expectation** is a relationship inferred across episodes: after a cue like this, in this setting, this is
what followed for her needs. It reuses the forecast's own outcome space: the needs a message moves
(`company`, `capable`, `free`, as `Memory.follow` keeps them on exchanges once the next message settles
them) and the forecast's blending (`_arrives` totals, `_forecast` trust). It is not a second engine: it is one
more item in the existing "what followed messages like this" record, kept by sleep, with evidence.

- `expectations`: id, formed, updated, `context` (rare cues it holds in; `[]` anywhere), `parent` (the broader
  one a narrower one splits from), `status` (`tentative`, `held`, `superseded`), `superseded_by`,
  accessibility (`strength`, `recalls`, `recalled`, as episodes), and a vector (`expectations_vectors`, the
  normalized mean of its observations' vectors, refreshed as evidence changes).
- `expectation_evidence` (primary key: expectation, source): `source` is the waking event an observation
  stands for (`event:<app>/<session>/<event_id>`, else `episode:<id>`), so a waking event counts once however
  often it comes back (conversation, summary, thought, replay); `episode`, `kind` (`observation`, `correction`,
  `settled`, `inspired`), `role` (`formed`, `supports`, `challenges`, `explained` (moved to a narrower one),
  `inspired`), `outcome` (what followed), `expected` (what she foresaw then, when kept), `context`, `likeness`,
  `at`, `added`, `superseded` (a correction replaced it; the basis is kept, not counted).
- `expectation_uses`: each time one contributed at waking (run, likeness, contribution per need) or was
  expressed in words (insight id): the trace the desktop shows.
- `expressions` (expectation, episode): the insights that put an expectation into words; one expectation, any
  number of phrasings; an insight with none is a one-off reflection.

Only exchanges and events with a settled outcome are observations. A thought, a dream or an insight that
goes over one is `inspired` (weight 0): it can prompt reflection, never corroborate. A correction
(`Memory.supersede`) marks the corrected observation `superseded` and adds the correcting one.

### Sleep: start with an episode, revisit what overlaps (`Mind._integrate`)

Runs in NREM: in the nap path of `_live_until` (10 minutes of NREM, no language provider needed) and in the
`local` step of `_consolidate`. Persisted once per sleep (`self["integrated"][slept_at]` holds the seeds
done), so a resumed or repeated review adds nothing twice (the evidence key enforces it too).

1. Seeds: the moments replay picks (`_replay_items`: the nap's 2, the review's batch).
2. Candidates for a seed: exchanges and events with a settled outcome, by stored vectors (no embedder call:
   `Vectors.nearest` with the seed's own vector) and by shared rare cues (`cue_strength >= 0.5`), older ones
   outside the review window included; at most `CANDIDATES = 8`.
3. Overlap: a candidate overlaps when its cosine to the seed reaches `Vectors.matter` (the closest 3 in 100 of
   her own pairs: "about the same matter", measured on her vectors, not a constant), or it shares a rare cue
   and its cosine is above her usual nearest (`Vectors.usual`).
4. An overlapping set with two independent observations either joins the expectation it matches (its vector
   at `matter` or nearer, a context that fits) or forms a new one.
5. Opposite outcomes on a need: when every contrary observation shares a rare cue none of the supporting ones
   has (a recorded contextual difference), they go to a narrower expectation with that context (`parent`
   set, their role `explained` in the broader one). Otherwise they stay as `challenges` and the expectation
   weakens; with low agreement it stays `tentative`.

### What it is worth (computed from the evidence, never from words)

For each need: `mean = sum(w * o) / sum(w)` over counted observations (`w` = likeness to the expectation, at
most 1; superseded, explained and inspired rows excluded). `support = sum(w)`. Weight at waking =
`applies * support / (support + PRIOR)` with `PRIOR = 1` observation: one observation moves the forecast at
most half as much as a recalled episode would, two at most two thirds; nothing grows past `applies`.
Agreement = `|sum(w*o)| / sum(w*|o|)` on its strongest need; `held` from two observations and agreement 0.75,
else `tentative`. Recalling or expressing it raises accessibility only.

### Waking: before the reply (`_arrives`)

The message's vector (embedded once, shared with `Memory.known`) is compared with each expectation's vector:
`applies = clip((cos - matter) / (1 - matter))`, and its context must be among the cues around the message
(`_cues` + `_surroundings`); a narrower one that fits replaces its parent. Each that applies adds its mean to
the forecast's totals at its weight, and its contribution is recorded on the decision (`path.expected`: id,
applies, weight, means, sources, the share of each need it moved) and in `expectation_uses`. That forecast
feeds `_forecast` and so the options' worth. No new model call, no prompt text: the insight sentence is not
in the prompt. When the outcome comes (`_settle`), each contributing expectation takes the observation as
`settled` evidence (supporting or challenging, or explained by context), by the same rules.

### Narrative review

The `narrative` step lists, after the moments, the expectations integration formed or changed since the
last review, as "what overlapping moments showed" with their moment numbers; an insight may say which it
expresses (`"expresses": n`), stored in `expressions`, and records `expectation_uses` (`expressed`). A night
may express none. An insight resumed after waking is kept with when it was actually written
(`review.reviewed_at`, `review.awake`).

### Accessibility, reliability, retention

- Insights: `forget_faint` no longer excludes them. Its salience floor (0.3) is for what mattered when it
  happened; an insight's 0.45 is a constant, so for insights "mattered" is: it expresses a `held`
  expectation, or something kept is made from it. A faint, disused insight that does neither goes after 30
  days like any moment; one held by a stronger one alike in meaning goes sooner (`Vectors.held`).
- Expectations: in the `local` step, one with no counted observation left goes; a faint (`strength_now <
  0.08`), unreliable (`support < 2` or `tentative`) one goes; a held one stays however rarely recalled.
- Retraction (`_revise_derived`): evidence of moments taken back goes; an expectation left without counted
  observations goes, and with it its contribution. Correction: `superseded` evidence stops counting.
- Reduced accessibility (strength), superseded (`superseded_by`), deleted (absent) are three states the
  desktop shows apart.

### Legacy (data format 2 migration)

Old insights and dreams keep their place; `episodes.provenance` says what their sources are worth: `cited`
(the sleep named them), `whole night` (all of a night's insights and dream stored the same origins: older
software kept the whole batch), `unknown` (none). No expectation is made from them, no corroboration added,
nothing purged. `state.traced_since` marks when uses began to be recorded: before it, "not recorded" differs
from zero.

## Part 3: the map

`memory.region(episode)` (MilkChan) is the one resolver for hover and pinned detail: the hippocampus for
moments (left: words, right: what happened), the medial prefrontal cortex for insights, described as
approximate functional locations; a square is a software memory, its spiral place and side are layout. The
insight card separates `formed from`, later `supports` / `challenges`, and `similar in meaning`, and shows
whether it came to mind (recalls), came up in a thought, and whether the expectation it expresses changed a
forecast (with the run and the amount), or "not recorded before <traced_since>".

## Tests (the brief's acceptance tests, in other domains than the example)

- Attribution: two turns with different bodies; a present naming that retrieves the earlier one first keeps
  the current run's id and vector, links the earlier as `reminded`, softens nothing extra; an explicit
  `moment` takes the earlier vector and softens once; an unknown moment stays unresolved; a legacy record; a
  repeated call and a restart before the episode is kept; a later recognition leaves `count` alone; through
  the tool and the desktop card.
- Learning: two profiles copied from one snapshot, same seed and stand-in answers, one with integration's
  contribution withheld; a held-out paraphrase moves the forecast in the learned direction, traced to the
  source episodes; an unrelated cue does not. Another setting splits a narrower expectation; contradictions
  in the original setting weaken it (values reported); recall, a paraphrasing thought and a dream add no
  support. Lifecycle: sleep, an offline nap, an interrupted and resumed review, a repeat; a controlled clock
  through the real cleanup with a neglected and a supported insight; retraction and correction; a legacy
  insight; desktop hover, card and link types.

## Limits

Units and sensitivity of `PRIOR`, `CANDIDATES` and the thresholds are reported with the tests. The human
findings motivate the function (inference across overlapping experiences, sleep's hippocampal-prefrontal
coordination, sleep and hidden-rule discovery); they give no learning rates, no neuron-per-memory map and
no evidence that a sleeper writes sentences.

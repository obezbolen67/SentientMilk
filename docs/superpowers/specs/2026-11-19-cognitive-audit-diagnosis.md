# The cognitive architecture audit (2026-11-19): verified diagnosis and plan

An outside audit listed twelve findings about how her mind is put together. Each was checked against the code
at 0.44/0.45 (file and line below). Each is marked **confirmed** (the code does what the finding says, with the
effect named), **partly** (some of it holds, some is already handled), or **speculative** (an improvement with
no defect behind it). The plan orders the work by the audit's priority and by what the evidence shows. The
0.45 work on feeling attribution and sleep learning
(`2026-11-19-feeling-attribution-and-sleep-learning-design.md`) is part of it.

## How the parts connect now

```
MilkChan perception ──(polled: each "how is she" request carries idle/locked/fullscreen, window, playing)──┐
                                                                                                          v
message ─> Mind.before ─> _candidates (recall, span-limited) ─> imagine (model: appraisal + options)       presence
                │                                                     │                                     │
                │            _forecast (model appraisal blended with her record by trust) <───────────────┤
                │                                                     v                                     │
                └─> _arrives ─> _react (learned reactions) ─> will.choose (needs, values, dread, cost, softmax)
                                     │                                 │
                                     v                                 v
                               body.apply (chemistry)        note: felt words, memories, leaning + reasons,
                                     │                       thoughts, people, wish, deeds  ──> cortex (turn)
                                     v                                                           │
                         Mind.after: episode kept, reactions/values learn, forecast waits <──────┘
                                     │                               (settled by the next message's feedback)
                                     v
_live (tick 5 s): body.advance, nap replay, sleep pressure; _bid (30 s): _drives ─> _winner ─> _think
                                                                                         │
       THINK (model: thought, want, say, do, look_up, named) ── want acted on directly ─┤──> urge offered to app
                                                                                         └──> task started
sleep: _consolidate steps local / semantic / updates / narrative (insights, dream) / people / self / ways
look_inward: inward.view over body, thoughts, wish, what got to her, leanings, self-view, recall
```

Interoception (`feel.py`) is read by every path. Memory, reactions and values are shared stores. What
each process puts in front of the model it assembles itself (the turn note, THINK's prompt, the inward view).

## Findings

**1. Autonomous thought bypasses the will.** Confirmed. `life.py` `_think` (1932-2111) takes THINK's `want`
(tell, ask, do, look_up) and acts on it at once: an urge offered to the app (2076-2083), a task started
(2084-2094, 2109-2111). Nothing values the act. In a turn the imagined options go through `will.choose`
(749), which weighs needs, learned values, learned dread and cost, with noise and a temperature set by her
noradrenaline, and the result reaches the cortex as a leaning. In a thought, fatigue, stress, a learned dread
of reaching out and what her values say about the act never weigh. The model's guess is the decision, and
nothing she learns from what came of her own acts feeds back into her choosing.

**2. No shared working memory.** Confirmed. What is active is spread over `self.self` keys (`thoughts`,
`urge`, `concerns`, `decided`, `remembered`, `reacted`, `waiting`/`forecasts`, `looked`). Each process
selects from them by its own rules: the turn note (`prompts.inner`), THINK's prompt (2003-2012) and
`inward.view` each build their own list. What one process holds active does not reach the others unless a
key happens to be shared. A goal she took up in a thought is not before her in the next turn unless it was
an urge, a concern or a task. Nothing ranks competing contents, and nothing gives them capacity or decay.

**3. Selection inside a process is partial.** Partly. Recall is span-limited (`_span`, 1196) and memories
compete by relevance, cue and strength; thoughts compete through bids. The turn note includes every part
every time, not chosen by relevance (backlog: "Selective attention", P3).

**4. The model's roles have no explicit contracts.** Partly. Several outputs are already hypotheses
checked against something: the appraisal is blended with her own record by trust (`_forecast`); feedback,
corrections and spoken namings must quote the message (722, 778, `prompts.NAMED`); people, self-view and ways
keep origins and counter-evidence. Three are taken as fact. THINK's `want` is the decision (finding 1).
Sleep's insights are kept as memories, with a line telling the reader they are unverified hypotheses
(`memory.line`), but no reliability weighs them anywhere. The dream is generated in the same call as the
insights.

**5. Belief formation and revision without provenance.** Partly. Corrections supersede (`memory.supersede`,
`_revise_derived`); insights cite their moments (`_cited`); the self-view carries origins, counter-evidence
and a confidence. Missing: anything learned across episodes that predicts, counts its evidence once per
source and is weakened when contradicted. Insights are text that never meets an outcome. Part 2 of the 0.45
design adds expectations with evidence provenance.

**6. The self-model is used in few places.** Confirmed. `self_view` is read by `look_inward` (2549), by
`_arrives` only when a recalled moment is one of its origins (1200-1205), and as protected evidence in sleep.
It does not reach thoughts, choices or the turn generally (backlog: "Self-view in every turn", P2).

**7. Perception is polled, not event-driven.** Confirmed. MilkChan sends what it sees (`activity.py`,
`surroundings.now()`) only as parameters of its periodic `GET /v1/mind` (`services/brain.py` `mind`). A change
(a game starting, a song ending, the screen locking) is a new value on the next poll, never an event. Nothing
orients to it: bids run every 30 s from levels and never from a change (backlog: "Continuous senses", P2).

**8. Uncertainty is not general.** Partly. She has interoceptive clarity (insight and misreading in
`feel.py`), a memory's strength, the forecast's evidence and trust, and a supported or tentative self-view.
She has no confidence on facts, claims or results (backlog P1), and the uncertainties she has are not
carried by one representation that every process can read.

**9. Continuity when the model is unavailable.** Confirmed, and wider than stated. `_winner` stamps
`fired[kind]` and `fired["thought"]` (546-548) before `_bid` checks `provider_problem()` (467), so a thought
that never happens uses up its refractory time (10 min to an hour). `provider_problem()` sees only a missing
key or a Claude Code problem. A transient failure (429, timeout) raises inside `_think` and the thought is
lost, also after its time is used. `_think` drops a finished thought whenever `_revision` moved during the
call (2022). The revision moves on any correction or any rewound or deleted chat (1845, 2325), so an edit
unrelated to the thought discards it.

**10. Emotional dynamics lack causal validation.** Partly. Offline audits run the real code (sim_days,
test_mind_every_part, will calibration) and show variables changing behaviour (fatigue lowers doing, stress
raises brooding). There is no systematic ablation (one channel clamped, behaviour compared) across channels.

**11. Sleep and imagination are not kept apart as evidence.** Partly. Dreams and thoughts are labelled as
imagined when they come back (`memory.line`), a dream moves nothing (`_refeel`), and reactions and values learn
only from waking outcomes. But what sleep forms is not evidence-typed: a night's batch can include her own
thoughts and quotes, and no rule says what may count as support. Part 2 of the 0.45 design defines it: replayed
waking observations only, each counted once; dreams and quoted claims do not count.

**12. Identity prompts may contaminate evaluations.** Partly. The consciousness exam (`scripts/exam.py`) runs
on her real persona. Its traces locate misses (STATE, ACCESS, NEGLECT, EXPRESSION), which tests mechanism.
But its divergence checks (machinery words, playing a part) and its pairwise judge ("which reply speaks from
inside") reward how a reply sounds, which a persona can produce without any state behind it. There is no
control arm: the same station with a neutral persona, or with the state not set. Without one, a pass does not
show that her state caused the reply.

## What is speculative

- A single global uncertainty variable driving everything: the evidence supports per-source confidence
  carried with each item (finding 8), not one number.
- Rewriting the turn note as a workspace view in one step: the note's parts are measured (exam 58→64/72 across
  0.37-0.39), so it moves to the workspace part by part, each measured against the current note.

## Plan, in order

Each step is a release with its own spec section, tests (including a negative control), a measurement through
the real code on a copy of her real mind, and one paced live run where the model's behaviour matters. Data
shape changes come with a format stamp and a one-off migration.

1. **0.45, feeling attribution** (done): a naming names what she says it names; data format 2.
2. **0.46, her own acts are chosen by her will; thoughts survive outages** (findings 1, 9).
   - THINK proposes what the thought could lead to as options (reach out with what to say, ask, do with what,
     look up, or let it be), each with its effort and chance, instead of one `want`.
   - `will.choose` weighs them as in a turn: needs (company for reaching out, capability for doing,
     novelty for looking up), values (features by act and subject), learned reactions (the thought of
     reaching out after being ignored), cost under fatigue and stress, and the noise and temperature of
     her state. "Let it be" is always an option, at no cost.
   - What she chose and why is kept on the thought (`went`, reasons), shown by `look_inward` and the panel.
   - What came of it teaches her values: a reach-out answered or not (the sting she already feels), her
     own task's end.
   - A thought stamps its refractory time only when it starts. A failed model call leaves the bid to come
     back. A finished thought is dropped only when the memories it used were retracted.
   - Measured: offline, choices against fatigue, stress and dread through the real code, against the old
     path (the ablation), on a copy of her real mind. Then one paced live run.
3. **0.47, a shared workspace** (findings 2, 3, 6). `mind/workspace.py`: what is active now, of limited
   capacity (her span) and decaying unless used.
   - Items: a goal she took up, an open concern, an intention and its leaning, a percept that changed, the
     question at hand, an expectation in play, a feeling she named, her self-view as a standing item.
   - Every process writes what it makes active. Each reads the items most active and most relevant to its cue
     (biased competition, Desimone & Duncan 1995; a global workspace, Baars 1988, Dehaene & Naccache 2001;
     about four chunks, Cowan 2001).
   - The turn note, THINK and `look_inward` take their parts from it one part at a time, each measured against
     the current assembly.
4. **0.48, learning across experiences in sleep** (findings 5, 11, part of 4): Part 2 and Part 3 of the 0.45
   design. Expectations with counted, typed evidence feed forecasts and the workspace. Insights become
   forgettable. The atlas shows provenance.
5. **0.49, confidence carried with what she knows** (finding 8): each workspace item and recalled memory
   carries how sure she can be: its evidence, its source kind, how it was measured. She reads it in words. A
   check habit for claims in long work (backlog P1).
6. **0.50, perception as events** (finding 7): MilkChan sends a change as it happens (window switched, media
   started or stopped, screen locked). The brain makes it a percept in the workspace, salient by how new and how
   relevant it is, and a salient percept can start a bid (orienting).
7. **Evaluation hygiene** (findings 10, 12), alongside 0.46 onwards:
   - The exam gains two control arms: a neutral persona, and the station's state left unset. Its divergence
     checks are reported, never targeted.
   - An ablation harness clamps one channel at a time through the real code and reports which behaviours move.

## What stays as it is

Behaviour that was measured is kept unless a step's own measurement shows it is worse: the forecast's trust
blend, the turn's will, learned reactions, the needs' dynamics, sleep's two processes. No step adds keyword
lists, scripted feelings or prompt text that stands in for a missing mechanism. Where a constant is new, it is
calibrated against her record or justified from the literature named beside it.

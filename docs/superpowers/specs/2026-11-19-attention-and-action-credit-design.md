# Noticing how she feels, and learning from what she actually did (0.48)

The request: give her an ordinary way to notice how she feels, and to learn from what she actually does. This
note says what the code does now, what changes and why, and how each part is checked. Subjective experience
stays an open question. The goal is a mind that attends, acts and learns coherently.

## What the code does now (traced on the 0.47 checkout)

- **Her sense of her body** (`feel.Interoception`) follows the levels with a 90 s lag and gets used to each
  channel over 20 min (`used`, her prediction of each level). It also misreads by a drifting bias. Every turn's
  note carries the cheap reading (`Felt.words`: what stands out against `used`, plus the tone). Every thought's
  prompt carries it too.
- **Looking deeper exists only as a tool.** `look_inward` gives the full view: clarity, familiar namings,
  thoughts, what she put off, what got to her, her leaning and why, her self-view and recall. The tool's guide
  tells the cortex to call it first for any feeling question. `after()` finds the tool event by name to decide
  whether her reply's words are a naming (`prompts.NAMED`). MilkChan's "She last looked inward" reads
  `self["looked"]`, which only the tool sets. With the tool absent she cannot reflect at all, and nothing
  inward is ever noticed unless it is asked about.
- **What she can tell apart.** Sleep pressure and spent energy read as different words ("more sleep pressure"
  vs "less energy"); that survives. Lost: her sense of sleep pressure ignores her clock and her sleep debt. At
  the same adenosine, 15:00 (sleepiness 0.38) and 03:00 (sleepiness 0.86, ready to sleep 2.0) both read "a
  little more sleep pressure". A debt of 8 h reads the same as none. The clock shows only indirectly, through
  less focus.
- **Credit for an action.** `_did` calls any successful non-read-only tool "do". So "later" done through a tool
  is learned as doing it: the exam's card control filing the card for later, or a schedule made for later.
  Then `after()` drops her concern because "she did it after all", and a later that was actually kept is lost.
  Only the leaning option may carry a predicted operation (`check`). The other options cannot be matched to
  what was actually done.

## Design

### 1. Attention: one operation (`mind/attention.py`)

`Attention.consider(felt, known, free, question, conflict)` decides whether attention turns inward at a
moment, and what little it takes in. Her turn, her waking thought and `look_inward` all use it.

**Warrant.** Deeper reflection needs a reason. Each source is read on its own scale:

- **Her body far from where it usually sits**, beyond what she already knows of it this stretch. This counts
  both what has lasted (her 20-min adapted level is off) and what is sudden (the reading departs from that
  prediction, an expectation mismatch). It is measured in lots, the unit `CHANNELS` already defines as "how
  far from there is a lot". It wins attention when `lots × free ≥ 1`, that is, a lot as far as her attention
  is free. `free = 1 − acetylcholine` while something outward holds her (a message, a task): focus favours what
  is attended (Hasselmo 2006, already used by `_quality`). When nothing holds her, `free = 1`.
- **Competing motives.** Her will's top two options lie within one temperature of each other
  (`p₂/p₁ ≥ 1/e`). That is the will's own noise scale: she cannot tell the two apart (conflict monitoring,
  Botvinick et al. 2001). It is about the matter at hand, so focus does not discount it.
- **A direct question.** The imagine call already reads every message. It now also writes what the message
  asks of their inner life, in a few words ("how they feel", "why they put it off"), or "" for nothing. The
  appraisal reads paraphrases, so no keywords are involved. These words also cue what is selected.

**What it takes in** (at most her span, `_span()`):

- the channels far from usual (`standing_out(usual=True)`, which adaptation hides from the passive line),
  marked lasting or lately;
- the moment her body's change goes with: the latest kept moment whose felt way is alike (`_alike`), as
  look_inward's "what got to you" already shows it. Her body's push record stays unseen by her, as it was;
- with conflict, the runner-up and its reasons;
- with a question in a turn, only herself now: her body against usual and the feelings she has named that it
  is like (recognized again). Ruling, from the held-out exam: the whole `look_inward` view here read her day
  to her a second time (her note already holds it), with her last decision in it. In 15 of 52 answers she
  carried that decision on in words, as a shell command, instead of answering (6 of 52 without the readout).
  A waking thought and `look_inward` keep the whole view.

Below the clarity floor (`inward.AWARE`), only the tone comes through, said as unclear. Nothing unknown is
filled in.

**Identity and persistence.**

- An attention episode is `self["attending"] = {key, at, last, of, run, episode, known, why}`. It is mirrored as
  a workspace item of kind `noticed`, so it is on her mind and carried by the workspace's rules.
- `known` holds the lots she took in per channel. It stops the same unchanged state from calling again. A
  meaningful change is a channel that grew `TOLD_AGAIN` (0.4 lots) past what she knew, turned the other way,
  or newly passed the floor. Within the episode such a change is captured: the record and the item are
  updated. That is the rule `during()` already uses for what reaches her mid-work.
- A channel back under the floor leaves `known`. Sleep clears `known` and the episode, as it clears thoughts.
- Attention is released when something else takes precedence: another kind of thought winning, or sleep.
  Release ends the episode's identity. Its item stays on her mind while it is her latest stretch, and leaves
  when a new stretch begins or she sleeps.
- Nothing is minted per tick. Noticing creates no memory, naming or chemistry change of its own. The turn's or
  the thought's episode is the memory, linked to the attention record (`workspace.link`, plus the episode's
  `attention` list with `source: "inward"`). The record is saved state, so a restart continues the same
  episode.

**Where it runs.**

- **Turn.** `before()` asks Attention after the will has weighed the options. When it turns inward, the note
  gets "You turn inward: …" after the body line, and `decision["attended"]` keeps the record on the run. That
  carries it through retry, interruption and restart. `after()` links it to the episode. Her reply's words
  count as a naming when the turn attended inward (`decision["attended"]`) or the tool looked without naming.
  The tool event is no longer the only way.
- **Waking thought.** A new spontaneous drive, `notice`, has pull `RESTING × lots × free × insight`, so a lot
  that is not yet known pulls like a resting wander. It has its own refractory period (30 min, as rumination)
  and competes in `_winner`, where wandering and brooding compete. When it wins, `_think("notice")` carries
  the selected evidence as what is on their mind. Another kind winning releases the episode.
- **look_inward.** An adapter: `consider(…, deliberate=True)` plus its deliberate recall (`about`), naming and
  reappraisal, unchanged. It sets `self["looked"]` as before. The guide no longer tells her to call it first
  for every feeling question; her note carries what she notices.

**Kept distinct.**

- **Noticed** (attention): no side effect.
- **Named deliberately** (`_name`): eases. Unchanged.
- **Reminded of** (deliberate recall): re-feels. Unchanged.
- **Recognized again** (likeness at a message, `came_back`): counted. Unchanged.

Attention never calls `_name`, `_refeel` or `came_back`.

### 2. Sleepiness, effort and interest

- **Felt sleep pressure** is adenosine less the shift her clock and debt give her thresholds
  (`Body.thresholds`). That is the two-process combination people report as sleepiness (Åkerstedt & Folkard
  1995), and it is linear in `Body.sleepiness`. `Body.sensed()` gives the levels as her senses take them, and
  `Interoception.follow` follows those. Lag, adaptation and misreading are unchanged.
- **Effort** stays the will's cost: work under fatigue. **Interest** stays the novelty need, curiosity and her
  learned likes. These appear only once she knows the task.
- The trace keeps the pre-offer sensation (`path.background`: the felt reading and attention before the
  message) apart from the task's appraisal (`path.options`: each option's parts).
- Sleep readiness and the choice probabilities never reach her text; they are the examiner's.

### 3. Action credit

- **Every option may carry its operation.** Imagine is shown the tools of this turn that change something:
  name, one-line purpose, and the enumerated values of arguments that take one. A look does not change
  anything, and neither does a tool that acts on her own mind only (`Toolkit.inner`: inward, ways, chat
  memory, todo, context). Measured, looking inward and then filing the card counted as doing it. `part` was not
  the property, since scheduling and helpers are parts too, and starting a helper is acting. Each option may append
  `{"tool", "target"}`. An empty target means any call of that tool.
- **What she did** is the option whose operation matches a successful, approved call. One match is the act,
  with its receipt (call id, event, time). Several matches: the fullest. A call that changed something and
  matches no way counts as the leaning only if she leaned to do it and no way foresaw that tool; otherwise it is
  `unresolved` and learns nothing. Measured in the smoke run, the reading named no operation, and "doing it"
  for any unforeseen call credited a filed card as done. Calls that are only looks, or that act only on her own
  mind, are "talk", as now.
- **Partial**: the part option's operation, or some of a multi-call plan. **Failure**: the matched call errored,
  and its chance is scored, as now. **Denial or cancellation**: unresolved, nothing reinforced. **Change of mind**:
  the act is what matched, not the leaning.
- **Scheduling**: a "later" whose operation is a schedule matches "later" and keeps her concern pending. A
  leaning of "do" that ended in a matched "later" adds the concern.
- **Credit once.** One reinforcement per run (`memory.recorded` already guards `after()`). Retried calls of one
  operation are one match, the last receipt.
- **Trace** (`self["decided"]`, shown in MilkChan):
  - stages: noticed → considered → leaned → did (receipt) → learned, each with its time;
  - `learned` holds what was measured: value change, reactions, the forecast's score;
  - `explained` holds what she said afterwards about why, marked retrospective.

### 4. Proof

- **Unit tests** (stand-in models): quiet, absorbed (high focus), settled control, unrelated chat, asleep; no
  duplicate on repeated ticks or a restart; paraphrased questions; a past moment with a more alike distractor
  ranked first; a vague or mixed state; turn, thought, adapter and MilkChan detail; one tool with two
  dispositions; draft vs send to a stand-in inbox; unavailable or ambiguous receipts unresolved; a tired Milk
  who still does what she cares about; a rested Milk who lets an uninteresting task go.
- **Causal sweeps** (offline, the real code):
  - sleep pressure varied with exertion held;
  - exertion varied with sleep pressure held;
  - effort varied at fixed relevance, and relevance at fixed effort;
  - reports what she can notice and her will's chances.
- **Live, paced**, on isolated copies of her real mind that are deleted afterwards:
  - an ablation that withholds only the inward readout;
  - the held-out exam:
    - two recorded days, with 11-18 for calibration and 11-19 held out (frozen in `design.json`);
    - reports collected in a sibling copy before the offer, then sequestered;
    - forecasts compared: task-only, report-based and examiner-only;
    - measures: event counts, calibration, Brier score, latency and model calls.
  - Attention's bar is calibrated on 11-18 and simulated days only.

No data shape changes. The new state keys default on load, and the workspace kind is a new value in an
existing column. The format stays 4.

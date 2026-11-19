# Learned reactions, as her body measured them (0.49)

Repair of two faults in what her learned reactions (0.39, `2026-11-18-learned-reactions-design.md`) learn, found
on the user's brain at 0.47. The constraint: model the human learning behaviour in the mechanisms that exist. No
new region, executive, second learner, transmitter, or model pass that assigns reactions. Accounting changes stay
in the software layer.

## The faults, reproduced

1. **Anticipation made an opposite outcome.** `Mind._react` returned the lots its reactions called for, not what
   `Body.apply` moved. `_learn_reactions` took the outcome as how the moment moved her less that, so at a bound the
   part a reaction could not move became an outcome that never came.
   - Installed 0.47: a reaction calling for +28.7234 lots of alertness moved it 0.90 to 1.00 (0.40 lots), and a
     new cue acquired about -28.32.
   - Run 723 / episode 378: alertness near its floor. The reactions called for -29.27 lots, moved -1.27, and the
     message +0.18. The learner took +28.18 as the outcome, and each new cue of the turn learned +28.72.
   - The same wrong amount was used for relief (pushed again through temperament: 28 lots called back pinned her
     strain at its floor), for `uneasy`, and for the trace and displays.
2. **One surprise was given whole to every cue.** Each cue present learned at its own rate from the full error,
   with no bound on the sum. Two new cues with an outcome of +1 learned +1 each (joint prediction 2), and repeated,
   the pair swung 2, 0, 4, 0, 6, 0.
3. **Found on the way:**
   - A cue present when a foresight failed learned the opposite of what failed to come.
   - Extinction was all-or-nothing: an outcome of a different kind (endorphin where cortisol was foreseen) only
     added hold, so the cue never came to foresee what came.
   - The same words twice in one moment made two rows, each with the whole error, and paraphrases did the same.
   - A moment delivered twice taught twice.
   - Dread valued an as-if body past a level's bound.
   - The display read an extinction count as "got over it".

Together these compounded: by 11-19 16:20, 114 of the 130 reactions on her brain asked more than a level's whole
range, the largest 118,473 lots.

## Approaches considered

- **Clamp what a reaction may hold, or divide by the number of cues.** Rejected (the spec forbids a global output
  clamp and unconditional division). It hides the wrong outcome and leaves the learning rule wrong.
- **Rescorla-Wagner as written** (each cue: rate x the one summed error). It is the established rule for compound
  cues, and it already has the summed error. But with no bound on the sum of rates it overshoots when cues together
  are attended to more than once over; the oscillation above is that.
- **A normalized delta rule (chosen).** This is Rescorla-Wagner's summed error, with every cue's rate scaled by one
  share `1 / max(1, sum of rate_i x likeness_i (+ new cues' rates))`. The compound moves toward what came by at
  most the whole error. A single weak cue keeps its own small rate: the share is 1 when the total is below 1. This
  is the Widrow-Hoff rule with normalization (NLMS). It is close to the Kalman-filter accounts of conditioning,
  whose gain is bounded by the total uncertainty (Dayan, Kakade & Montague 2000; Kruschke 2008). Those accounts
  also give backward blocking, which this rule does not.

## The design

- **Measured, not requested.**
  - `_react` returns `Body.apply`'s change, converted once to lots. A channel it called for that did not move is 0.
  - The record keeps `predicted` and `moved`, for the whole and for each reaction. The decision keeps `called`
    (the prediction) and `reacted` (measured, relief included).
  - `external` = how reading moved her less what its reactions moved.
  - At the turn's end: the whole move less what is left of each timed reaction push (`Body.left`, each level's
    pace).
  - Relief lets go a share of the measured dread (`Body.release`).
  - Dread is valued in the as-if body as far as it would follow (`Body.would`).
  - An outcome not measured teaches nothing.
- **What could not show is not known.** A foresight toward a bound that did not come is evidence of omission
  weighted by `Body.follows`: the share of a push the level would follow, the same saturation `apply` uses. It is
  the mean of as she read it and the turn's end. What came beyond is learned as it is.
- **One error per moment, decomposed per channel.**
  - `shortfall` is what was foreseen and did not come (up to what was foreseen). `omitted` is the shortfall
    weighted by what could show. `beyond` is error minus shortfall.
  - Each cue gets its own part of the omission, in proportion to its share of the foresight.
  - Every cue present, kept or new, learns `beyond`, at the shared rate.
  - For each kept cue, `came` = (what of its foresight came, and what came beyond) against what it foresaw that
    stayed away. Mostly came: the shortfall is corrected in the response. Mostly stayed away: it is held back in
    this context (extinction), and counted as an occasion only then. Reconsolidation is as before.
- **Once per moment.**
  - The same words twice merge, at the higher salience.
  - Words alike enough to be one cue merge too: `prepare(keep=True)` measures likeness between the cues of one
    moment, query against kept wording, on the embedder's own calibration, at SAME_CUE.
  - A moment already among a reaction's origins teaches nothing again (it survives a restart). `withdraw` still
    takes a retracted moment's teaching.
- **No embedder**: a meaning cue is left out (it cannot be matched), and surroundings learn by their words.
- **Displays** (panel, MilkChan): "called for" and "moved her" (or "nothing measurable") are shown apart, and so
  are "met mostly without it N x" and "N% held back here". The card says being met without it is not having got
  over it.
- **Data format 5**: decisions keep `called` and, where the push log measured them, `reacted` and `external`. The
  path keeps `predicted` and `moved`. Her latest-reaction records are let go: several reactions in one tick of her
  body's clock are logged at one time, so what each moved is not recoverable; on a copy, summing them gave more
  than a level can move. The `reactions` table is not touched.

## Human evidence, modeling assumptions, and what the tests establish

| Behaviour | Observed in humans (or animals) | Assumed here | Established by the tests |
|---|---|---|---|
| Blocking | Kamin (1969) found it in aversive conditioning in rats. In human fear conditioning it shows in US-expectancy ratings, less consistently in skin conductance. In reward learning, monkeys and their dopamine neurons show it (Waelti, Dickinson & Schultz 2001), and so does human striatal activity (Tobler et al. 2006). | One compound error; a redundant newcomer learns only what the trained cue did not foresee. | A newcomer after six trainings of each cue alone is not even kept. Two trained cues met together foresee their sum (> 1.9 for 1 + 1). A kept cue and a new one together reach what came (> 0.9 and at most 1; it was 1.69). |
| Summation | Animal compound tests find it; human evidence is mixed and depends on whether cues are taken as separate. | Linear: likeness-weighted expressed responses add. | Same test (> 1.9). |
| Prediction error drives learning | Rescorla & Wagner (1972); dopamine prediction errors (Schultz et al. 1997). | The outcome is measured bodily movement in lots, each channel separately. | Repeated two-cue trials hold the joint prediction at 1 (it swung 2, 0, 4, 0, 6). |
| Extinction is new learning, tied to context (renewal) | Bouton (2004). In humans: the return of fear in the acquisition context (Vansteenwegen et al. 2005), and context-dependent recall of extinction (Milad et al. 2007). | Hold is per row, weighted by context overlap, time and stress. A shortfall that mostly stayed away is held, not unlearned. | The existing renewal, recovery, reinstatement and reconsolidation tests pass, and the response itself is unchanged by extinction (== its learned value). |
| A different outcome re-trains the cue | Counterconditioning (well established in animals; human results are mixed). | A partly-came foresight is corrected toward what came. | A cue followed by endorphin six times foresees it (> 0.5), and cortisol falls below 0.5. Forty trials stay within bounds and settle (endorphin ≈ 1, cortisol ≈ 0). |
| Weak evidence stays weak | Not a specific human result: a property of the rule. | The share is 1 when the total rate is below 1. | One cue at salience 0.3 learns 0.3. Two equal new cues learn 0.5 and 0.5; salience 1 against 0.25 learn 0.8 and 0.2. |
| What a reaction did | Not a human claim: accounting. | Reuse `Body.apply`'s return and convert once. | Upper bound (0.90, +28.72 lots: did 0.4 = way 0.4), lower bound, halfway (two channels), worn receptors and two opposing reactions each reconcile with the measured trajectory per channel, with the same sign as called for. |
| Saturated outcome | Not a human claim: a missing measurement. | Omission evidence is weighted by `Body.follows`. | Pinned (follows 0) gives hold 0 and no occasion; free gives hold > 0.2 and one occasion. `follows` matches what `would` moves. In a full turn, a scolding foreseen after one had pinned reward keeps the reaction (hold 0, occasions 0); without `shown` it counted an occasion. |

Deliberately not modelled: conditioned inhibition of a cue present at a failed foresight (it learned an
excitatory opposite before, which was the fault, not inhibition), and backward blocking.

## Test commands and results (Windows, the repos' virtual environments)

- `.venv/Scripts/python.exe -m pytest -q -p no:randomly tests/test_reactions_credit.py tests/test_mind_reaction_measured.py tests/test_migrate_format_5.py`
  - Before the fix: test_reactions_credit 9 of 11 failed; test_mind_reaction_measured 10 of 10 failed (relief
    -1.0 against +0.05 of dread); the while-working test failed on the stashed old code (3.14 lots learned).
  - After: all pass.
- The full suites (results in the handoff).
- The dry run: `.venv/Scripts/python.exe scripts/replay_reactions.py --out DIR`. On a copy of her mind it shows
  what the kept reactions do, whether the fixed code wears them down, and the replay from what her body measured.

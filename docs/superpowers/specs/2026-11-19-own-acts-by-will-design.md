# Her own acts are chosen by her will; thoughts survive outages (0.46)

Findings 1 and 9 of the architecture audit (`2026-11-19-cognitive-audit-diagnosis.md`).

## Intent

Between conversations her thought decides what she does: THINK's `want` is acted on as the model gave it.
Fatigue, stress, a learned dread of reaching out and what her values learned about acting on her own never
weigh, and what came of an act of hers never teaches her choosing. In a turn the same things weigh through
`will.choose`. The model's part in a thought becomes imagination: what the thought could lead to. The choice
becomes her will's, as in a turn. Separately, a thought that never happened (the model unreachable) or that
an unrelated edit discarded no longer uses up her readiness to think.

Non-goals: no new drive or bid, no change to how a turn chooses, no threshold that forbids an act.

## Approaches

- **A. The will chooses among imagined options** (chosen). THINK lists what the thought could lead to, each
  with its effort and chance. `will.choose` weighs them with "let it be" always among them, using the same
  needs, values, reactions, cost, noise and temperature as a turn. Sampling from the softmax means nothing is
  forbidden: what she dreads or is too tired for becomes less likely, never impossible.
- B. The will's leaning goes back to the model, which decides: a second call per thought, and the model stays
  the decider. That is the finding.
- C. A rule on the model's `want` (no task when tired): a code gate, against the design (no code refuses
  what she does) and with no valuation behind it.

## Design

**THINK** answers the thought, `could` (zero to three acts it could lead to) and `named`. Each act is
`{"act": "tell"|"ask"|"do"|"look_up", "say" (tell, ask), "what" (do: what she'd do; look_up: the search),
"effort": 0-1, "chance": 0-1}`. `chance` is how likely it goes as hoped: welcome and answered, it works, she
finds out. `want` is gone.

**What an act of her own does to her needs** (`will.Option.effects`, its scale the turn's):
- `tell`: company `chance - 0.5`. Welcome brings closeness. Unwelcome or unanswered takes from it, as far as
  a turn's letdown does (`gives - 0.5` with nothing given). Losses weigh more through `value`'s curve.
- `ask`: as `tell`, plus new `novelty * ENGAGES["talk"]`.
- `do`: a turn's `do` with nothing asked for. Capable `chance * (0.3 + min(effort, 0.7)) - 0.5 * (1 - chance)`,
  new `novelty * ENGAGES["do"]`, company 0: nobody is let down by what nobody asked for.
- `look_up`: new `chance`: what she looks for is what she does not know.
- `let`: nothing, at no cost.

`novelty` is the thought's newness against her memory (`Memory.newness`, as wandering measures it). Work is
spent whole now (`WORK` 1.0 for her own acts). Values see `features(act, (), "own", hour, app)`, so
`act:do` learned from asked work generalizes and `act:do|intent:own` is her own. Dread is
`reactions.predict` over the act's words, embedded outside her lock, as a turn's options are. A reason that
fits a reach-out is named in her words.

**What she chose** is kept on the thought (`leaned`: act, reasons, chances). `went` is `let be` when she lets
it be, and what it already was otherwise. `look_inward` and the panel show it.

**What came of it teaches her** (`_credit(features, followed)`, the values half of `_settle`; trust and
reliability are the forecast's and stay out of it):
- A reach-out said and answered: company as her reading of the answer gives it (the appraisal's `company`).
  Unanswered past her patience (the sting): company `-0.5`, the scale's letdown.
- Her own task ended. A do: capable as the effects formula gives with the outcome known, `0.3 + min(effort,
  0.7)` when it completed, `-0.5` when it failed. A look up: new 1 when it completed, 0 when it failed.

**Continuity.**
- `_winner` stamps nothing. `_bid`, once the model is known to be there, stamps the attempt
  (`fired["thought"]`: the 10 minutes between any two thoughts). `_think` stamps the kind's own refractory
  time when the thought is made.
- A call that fails (429, timeout) costs the attempt, and the bid comes back after it.
- A finished thought is dropped only when a memory it used (what came back, what it grew from, what it
  dwells on) was retracted or set right meanwhile. Before, any correction or rewound chat anywhere dropped it.

## Tests

- Her state moves her own acts. With the same imagined options over many seeds: rested, she reaches out and
  does more; exhausted and stressed, she lets it be more; never 0 or 1.
- "Let it be" is always open, even when every option is unattractive.
- A learned dread of reaching out (being ignored) lowers reaching out against a control with no dread.
- What came of it teaches: an answered reach-out raises `act:tell|intent:own`, a sting lowers it; her own task
  completing or failing moves `act:do|intent:own`.
- Continuity: a failing model leaves the kind's refractory time unstamped and the bid fires again after the
  attempt's 10 minutes; a correction in another chat keeps a thought in flight; a retracted source drops it.
- Negative control: with every act's worth equal, choices follow the softmax at chance level, so no hidden
  rule picks.

## Measured

Offline through the real code on a copy of her real mind: act rates by state, new against the old path (every
`want` acted on). Then one paced live run on a throwaway copy, for whether the model gives usable options.

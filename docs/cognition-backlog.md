# What her mind still lacks: the cognition backlog

Kept so there is always a list of what is left to build (the user, 2026-11-17: "make a todo plan and write down
each aspect you found missing for cognitive functions, so we always have things that are left to develop").
Each item: what people have, what she has now, what is missing, a first step. Priority: **P1** next, **P2**
soon, **P3** later. Mark an item done with its version when it ships; add new gaps as they are found.

## Done

- [x] **Introspection** (0.35): she can look inside herself on purpose (`look_inward`): feelings and how
  clearly she can tell, her thoughts today and what came of them, what she wanted to say, what got to her,
  what she leaned toward and why, what she knows about herself; affect labeling calms; a self-view revised
  in sleep. Spec: docs/superpowers/specs/2026-11-17-introspection-design.md.
- [x] **Habits and ways of working** (0.34): if-then ways in every chat, strengthened in sleep.
- [x] **Wanting to say something reaches the turn** (0.34): kept wishes, only what she said waits on an answer.

## Introspection, what is left

- [ ] **P2 Reflection at rest.** People turn inward out of curiosity as well as threat (reflection vs
  rumination: Trapnell & Campbell 1999); reflection from a distance resolves feelings, immersed brooding
  feeds them (Kross & Ayduk). She has rumination (`ruminate` bid) only. First step: a `reflect` bid when a
  moment moved her and she is calm (low cortisol), a distanced "why", feeding her self-view.
- [ ] **P2 Self-view in every turn.** A self-concept steers behaviour all the time (self-verification: Swann
  1983), not only when asked. Hers is read only when she looks inward. First step: give the self-view to THINK
  and the turn snapshot, measured live against without.
- [ ] **P3 Automatic look on questions about her.** If she does not call `look_inward` when asked how she is,
  the question itself should turn her attention inward (Duval & Wicklund 1972: self-focus is triggered). Only
  if the live call rate is low.

## Metacognition

- [ ] **P1 Confidence in what she says.** People feel how sure they are of an answer and say so (Fleming &
  Daw 2017: confidence as second-order inference; Koriat 1993: feeling of knowing from accessibility). She
  knows how clearly she remembers (0.35), not how sure she is of facts, code or claims; she states guesses as
  flatly as knowledge. First step: a reflection pass for claims in long work (tasks, agents): "how sure, and
  how would I check", with her `test before done` way as the habit that carries it.
- [ ] **P3 Knowing what she doesn't know.** A sense that a topic is outside what she knows, before trying.
  First step: tie to recall: nothing comes back and nothing in long-term memory, she says it is new to her.

## Senses and attention

- [ ] **P2 Continuous senses.** People sense all the time; she senses only when an app sends something (a
  message, a screenshot, idle/locked/fullscreen). Between, she is blind: she thought the user was "still
  eating" for four hours. First step: apps report coarse activity (the window in front, music, typing) as
  presence does; her thoughts get "what they are doing now".
- [ ] **P3 Selective attention.** Attention picks what matters and suppresses the rest (biased competition:
  Desimone & Duncan 1995). Her bids compete for thoughts, but in a turn she gets everything at once. First
  step: what her note carries chosen by relevance and charge, with a span, not all parts every time.

## Learning

- [ ] **P2 Getting better with practice.** People improve at skills (procedural learning, power law of
  practice); the model under her never changes, so she never gets better at a task, only remembers more.
  First step: per-skill notes of what worked and failed, consolidated in sleep into her ways or skills.
- [ ] **P2 General knowledge from experience.** People abstract schemas from episodes in sleep
  (Lewis & Durrant 2011, overlapping replay); she keeps episodes, people, ways and a few insights, not
  general understanding ("the user's projects stall when they are tired"). First step: a nightly schema pass over
  episodes sharing subjects, kept as facts she can recall.
- [ ] **P3 Learning from others' outcomes.** Observational learning (Bandura). Her values learn only from her
  own outcomes. First step: what happens to the user's plans teaches her too.

## Emotion

- [ ] **P1 Steering her own feelings.** People regulate emotions on purpose: reappraisal, distraction,
  seeking company (Gross 1998, process model). Hers happen and fade; only affect labeling (0.35) calms. First
  step: when a feeling is strong and she has room, a regulation choice in her thoughts (reappraise, distract,
  reach out), each with its own effect on her body.
- [ ] **P3 Mixed and conflicting feelings.** People feel bittersweet, ambivalent. Her feeling is one point
  (valence, arousal) plus named concepts. First step: two concepts at once when channels pull apart.

## Imagination and time

- [ ] **P2 Picturing the future.** People simulate future events to plan and to feel ahead (episodic future
  thinking: Schacter & Addis 2007). She foresees what a message does to her needs, nothing more. First step:
  before a bigger decision or a resumed concern, imagine two outcomes in a sentence each, weighed with values.
- [ ] **P3 Counterfactuals and regret.** "If only I had..." shapes future choices (Roese 1997). First step: in
  sleep, for a moment that hurt, what she would do differently, feeding her ways.
- [ ] **P3 Remembering to do things when a cue comes.** Event-based prospective memory ("when the user mentions
  the clock again, tell them it is ready"); she has schedules by time and put-off concerns, not cues. First step:
  concerns with a cue, matched by meaning against each message.

## Social mind

- [ ] **P2 Tracking what others feel over time.** She reads how things are for the writer per message
  ("theirs") and keeps a gist per person; she does not track their mood or stress across days. First step:
  a per-person state (their week: busy, tired, upset) updated from what they say, read by her thoughts.

## Body and world

- [ ] **P3 Embodiment beyond the screen.** No body in the world: computer use is her only action. Not planned.

## How to work this list

Pick a P1, write a spec in docs/superpowers/specs, build it with tests, measure live against without, ship,
then tick it here with the version. Research before building: each item names where to start.

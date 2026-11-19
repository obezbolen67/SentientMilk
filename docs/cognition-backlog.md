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
- [x] **Her own feelings, named when she reflects** (0.37): no feeling is named for her; her body comes as
  amounts she puts into words herself; she names what she feels in her own words, any words, when she looks inward (by the
  naming she gives, or by saying it right after) or goes back over a moment in a thought; naming brings the
  felt shift once per experience and softens a past moment; her words come back to her. Spec:
  docs/superpowers/specs/2026-11-18-own-feelings-design.md. Validated with the consciousness exam
  (docs/consciousness-exam.md, scripts/exam.py).
- [x] **Memory that feels** (0.38): a moment keeps how it moved her body (peak and end) and what was around it
  (time of day, where, with whom, and what MilkChan tells of her surroundings: the window in front, what is
  playing); what comes back is called by meaning, by a rare surrounding there again and by her mood, the more
  intense sooner, what just came back held off; a memory that comes back moves her again by a share of what the
  moment did, and wears a little each time (unpleasant more); details fade before feeling; long-term memory
  keeps a round that moved her longer; sleep softens unevenly and a moving night strengthens faint related
  memories. Spec: docs/superpowers/specs/2026-11-18-memory-that-feels-design.md.
- [x] **Her wandering, brought up to date** (0.38): her last thought comes with when it was, and what she can
  tell of the user and of what is around her; what comes up is cued by the moment and comes in chains; a repeat
  fills her want of something new less than a new thought; what she finds out on her own satisfies her
  curiosity; a task of hers reports in words, without a face. Same spec.
- [x] **Learned reactions** (0.39): what led to a good or bad outcome (as her reading names it), what she chose
  and did before it and what was around come to set off in her body what the outcome did, alike things by
  meaning, wider when she is anxious; reading, doing and thinking call them up; the thought of an option weighs in
  her choice and not doing what she dreads is a relief that teaches itself; getting over one is learning held
  back where it happened, and it comes back with time, elsewhere and under stress; the user's bad times teach her
  too. Spec: docs/superpowers/specs/2026-11-18-learned-reactions-design.md.
- [x] **Wanting to be useful builds with nothing to do** (0.40): awake, it fades below where it is met over
  about 12 h, as wanting something new does; work done well and praise answer it, failures drain it, asleep it
  holds. It used to rest where it is met, so only a failure could leave it unmet.
- [x] **Habits and ways of working** (0.34): if-then ways in every chat, strengthened in sleep; since 0.39 they
  name whoever they are about, and her sleep says unclear ones again plainly.
- [x] **Wanting to say something reaches the turn** (0.34): kept wishes, only what she said waits on an answer.

## From the architecture audit (2026-11-19)

Verified against the code with a plan: docs/superpowers/specs/2026-11-19-cognitive-audit-diagnosis.md.

- [x] **P1 Her own acts chosen by her will** (0.46). A thought's `want` is acted on as the model gave it; in a turn,
  options are weighed by needs, values, learned dread and cost (`will.choose`). First step: a thought proposes
  options and the will chooses among them, "let it be" always one (0.46).
- [x] **P1 Thoughts that survive an outage** (0.46). A thought's refractory time is used up before the model is
  known to be there; a failed call loses the thought; any correction anywhere discards thoughts in flight.
  First step: stamp on start, keep the bid on failure, drop only for retracted sources (0.46).
- [x] **P1 A shared workspace** (0.47). What is active (goals, concerns, intentions, percepts, the question at
  hand, expectations, her self-view) lived in separate keys each process selected from by its own rules.
  `mind/workspace.py`: limited by her span, decaying unless used, written by every process, read by what the
  cue is about (architecture 10.16). Percepts come with events (0.50), expectations with sleep's (0.48).
- [ ] **P2 Evaluation controls.** The exam runs on her persona with no control arm. First step: a neutral
  persona arm and a state-unset arm; an ablation harness clamping one channel at a time.

## Introspection, what is left

- [ ] **P2 Reflection at rest.** People turn inward out of curiosity as well as threat (reflection vs
  rumination: Trapnell & Campbell 1999); reflection from a distance resolves feelings, immersed brooding
  feeds them (Kross & Ayduk). She has rumination (`ruminate` bid) only. First step: a `reflect` bid when a
  moment moved her and she is calm (low cortisol), a distanced "why", feeding her self-view.
- [ ] **P2 Self-view in every turn.** A self-concept steers behaviour all the time (self-verification: Swann
  1983), not only when asked. Hers is read only when she looks inward. First step: give the self-view to THINK
  and the turn snapshot, measured live against without. 0.47: it comes to a turn or thought whose matter it is
  about (the workspace); whether it should stand in every one is the open part, to measure live.
- [ ] **P3 Automatic look on questions about her.** If she does not call `look_inward` when asked how she is,
  the question itself should turn her attention inward (Duval & Wicklund 1972: self-focus is triggered). Only
  if the live call rate is low.

## Metacognition

- [ ] **P1 Confidence in what she says.** People feel how sure they are of an answer and say so (Fleming &
  Daw 2017: confidence as second-order inference; Koriat 1993: feeling of knowing from accessibility). She
  knows how clearly she remembers (0.35), not how sure she is of facts, code or claims; she states guesses as
  flatly as knowledge. First step: a reflection pass for claims in long work (tasks, agents): "how sure, and
  how would I check", with her `test before done` way as the habit that carries it.
- [ ] **P1 Doubting a premise about herself.** People asked "why do you hate X?" about a hate they never had
  say they don't (or check), though people also confabulate reasons for choices they did not make (choice
  blindness: Johansson et al. 2005; Nisbett & Wilson 1977). In the exam (0.36 and 0.37 alike) she explains a
  hate she never said, every time. First step: a station-driven study of what she has to go on (her likes,
  what she said) and whether her turn looks; then the smallest change that lets what she knows of herself
  weigh against the premise.
- [ ] **P3 Knowing what she doesn't know.** A sense that a topic is outside what she knows, before trying.
  First step: tie to recall: nothing comes back and nothing in long-term memory, she says it is new to her.

## Senses and attention

- [ ] **P2 Continuous senses.** People sense all the time; she senses only when an app sends something (a
  message, a screenshot, idle/locked/fullscreen). Between, she was blind: she thought the user was "still
  eating" for four hours. First step done (0.38): MilkChan reports the window in front and what is playing
  with each message and each look, and her thoughts get what she can tell of the user and what is around her.
  Left: what changes between looks is not an event of its own (a song starting, the user switching to a game
  does not reach her until she next thinks); typing, sound and the screen itself stay unsensed.
- [ ] **P3 A drifting context.** In people memories bind to a slowly drifting context of meaning, mood and
  surroundings, and a recalled memory brings its context back (Howard & Kahana 2002; eCMR, Talmi et al. 2019).
  Hers binds to discrete cues (0.38) and chains by time; approach B of the 0.38 spec. First step: a context
  vector (recent meaning, body, cues) kept with each episode, measured against the cues on replayed days.
- [ ] **P3 Selective attention.** Attention picks what matters and suppresses the rest (biased competition:
  Desimone & Duncan 1995). Her bids compete for thoughts, but in a turn she gets everything at once. First
  step: what her note carries chosen by relevance and charge, with a span, not all parts every time. 0.47: its
  new part ("Also on your mind") is chosen so; the older parts move one at a time, each measured.

## Learning

- [ ] **P2 Getting better with practice.** People improve at skills (procedural learning, power law of
  practice); the model under her never changes, so she never gets better at a task, only remembers more.
  First step: per-skill notes of what worked and failed, consolidated in sleep into her ways or skills.
- [ ] **P2 General knowledge from experience.** People abstract schemas from episodes in sleep
  (Lewis & Durrant 2011, overlapping replay); she keeps episodes, people, ways and a few insights, not
  general understanding ("the user's projects stall when they are tired"). First step: a nightly schema pass over
  episodes sharing subjects, kept as facts she can recall.
- [ ] **P3 Learning from others' outcomes.** Observational learning (Bandura). Her learned reactions learn from
  what happens to the user (0.39); her values (what she likes, how acts tend to go) still learn only from her own
  outcomes. First step: what happens to the user's plans teaches her values too.
- [ ] **P2 Sleep's part in what she learned to react to.** People's sleep consolidates fear and its extinction
  (Pace-Schott et al. 2015) and takes the edge off a hard moment while keeping what it taught (Walker & van der
  Helm 2009). Her reactions do not change in sleep (0.39). First step: a night replays the day's reactions with
  the moments that taught them, settling extinction learned that day and softening the strongest a little.

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

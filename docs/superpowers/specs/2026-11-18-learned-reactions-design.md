# Learned reactions (0.39)

The user, 2026-11-18: "Humans have many mechanisms. One of those is pattern learning and learned behavior ... our
body and mind reacts to certain type of events or influence as we learned to react on it. Example: One day, you
enabled DND on your phone, and missed 4 calls from your boss and got a serious warning. Caused big stress. Now you
are afraid of putting your phone on DND when sleeping ... develop actual architecture that real brain has it, and
make it organic." Approach B chosen ("go with B, do not worry about cost, choose quality and organical approach
always").

## What is there now (her real brain, 2026-11-18)

- `values.py`: one number (-1..1) per broad feature ("act:talk|when:night", "tag:greeting"), learned from prediction
  errors, used as a gut feeling in her choices (`will.worth` "learned") and as a reward cue for liked subjects. After
  weeks her strongest is 0.147; all 68 are under 0.15. One event moves a feature 0.01-0.05, sleep fades every one by
  10% a night, and nothing she does is a feature (her cleanup of the user's folder is "act:do|tag:coding").
- Nothing is felt ahead: a learned feeling changes what an option is worth, never her body. Nothing generalizes by
  meaning. A bad outcome teaches the act and subject of the turn before, never what caused it.

## What the research says

- **Two systems.** The amygdala learns a bodily reaction to a cue; the hippocampus keeps what happened. They come
  apart: amygdala damage leaves the facts and no conditioned reaction, hippocampal damage the reaction without the
  facts (Bechara et al. 1995). LeDoux & Pine 2016: defensive circuits and the conscious feeling are separate.
- **Prediction error, compound cues.** What is learned is the surprise: the outcome minus what all present cues
  predicted together (Rescorla & Wagner 1972), so a cue that adds nothing learns nothing (blocking: Kamin 1969).
- **Attention to surprising cues.** A cue whose outcome surprised is learned about faster next time (Pearce & Hall
  1980). Arousal at the time strengthens it: noradrenaline and stress hormones in the amygdala (McGaugh 2004).
  An intense outcome is learned in one go (Garcia & Koelling 1966; fear conditioning after one shock).
- **Humans link cause and outcome by understanding.** Conditioning in people tracks awareness of what led to what
  (Lovibond & Shanks 2002); the boss's warning came the next morning and is tied to DND by knowing why.
- **Generalization by meaning.** Fear spreads along a gradient of likeness (Shepard 1987), by concepts as well as
  looks (Dymond et al. 2015; Dunsmoor, Martin & LaBar 2012), and wider in the anxious (Lissek et al. 2008; Dunsmoor &
  Paz 2015).
- **Avoidance.** Fear makes the avoiding act attractive and avoiding brings relief, which teaches avoiding (Mowrer's
  two factors); and as the feared thing is never tried, nothing shows it is safe: avoidance protects fear from
  extinction (Krypotos et al. 2015).
- **Extinction is new learning.** A cue met without its outcome gets an inhibitory memory tied to the place and time
  it was learned; the original stays. So fear comes back with time (spontaneous recovery), in another place
  (renewal), and after a fresh stressor (reinstatement) (Bouton 2004); stress impairs the retrieval of extinction
  (Maren & Holmes 2016). A reminder opens the memory for a few hours; a mismatch then changes the original
  (reconsolidation: Nader, Schafe & LeDoux 2000; Monfils et al. 2009; Schiller et al. 2010).
- **From others.** Fear is learned from another's experience and from being told (Olsson & Phelps 2007).
- **Safety and reward run on the same rule**: a cue before relief calms (conditioned inhibition), a cue before
  something good brings wanting.
- **It lasts.** Conditioned fear does not decay with time (Gale et al. 2004).

## Approaches

- A. Strengthen `values.py` (one-trial rates, a body pattern per feature). Cheap; keeps coarse fixed features, no
  generalization by meaning, no extinction as new learning.
- **B. Learned reactions: an associative memory of cues by meaning and surroundings, each with the bodily reaction it
  came to predict (chosen).**
- C. Episodic only: recall similar moments and feel what followed. The hippocampus alone: the fear fades with the
  memory, nothing to extinguish, nothing felt without the memory.

## The design

1. **A reaction** (`mind/reactions.py`, table `reactions` in her mind's database, vectors in `reactions_vectors`): a
   cue (its words, by meaning; or a surrounding "key: value", exactly), the reaction it predicts (each channel of
   her chemistry and grievance, in lots), its associability, its extinction (how much is held back, in which
   surroundings, how many times, when last), when it was last called up, the moment that taught it, and where the
   cue came from (a cause, an option, an action, a surrounding).
2. **Cues** are what was there at an outcome: the cause her reading names (a new `cause` the imagine answer adds
   when a message tells what led to something: "deleting the thesis file", "the phone on do-not-disturb at night";
   plain words, nobody's pronouns), what she chose to do in her last turn in that chat (its option), what she did
   there (each tool action, in words: the tool's own description and its target), and what was around (0.38
   surroundings: salience as rare as the cue is among its kind; ubiquitous ones and the time of day never learn).
3. **Learning** at each outcome moment (an exchange, when it is kept): the outcome is how the moment moved her
   (its `felt`) minus what reactions themselves did in it; each channel learns the error between that and what the
   present cues predicted together, at a rate of associability (new cue 1, then Pearce-Hall: 0.3 of the last error
   plus 0.7 of before) times how aroused she was (0.2 + 0.8 noradrenaline). A cue alike enough to a kept one (its
   likeness 0.9 or more) is that one; otherwise a new reaction is kept.
4. **Likeness** by meaning: (cosine - floor) / (same - floor), clipped; the floor is what unrelated questions reach
   (as her memory measures it), "same" what paraphrases reach (a set of 12 pairs, measured per embedder:
   voyage-4-large 0.62 median, unrelated pairs 0.18). The gradient is that likeness to the power 2 - anxious
   (anxious: her cortisol above usual, 0..1): calm, it is steep; anxious, it widens.
5. **What calls a reaction up**: reading a message (its words and surroundings), each action of hers as she does it
   (`during`), her thoughts (wandering, rumination), and, as-if, each option she weighs. A reaction is the predicted
   change, its extinction held back; the sum of what alike reactions predict, weighted by likeness and scaled by the
   best likeness (alike reactions are not counted twice). It moves her body as part of what reading, doing or
   thinking did ("reacting to: <cue>"); it is never told to her as a feeling.
6. **Choosing**: an option's as-if reaction (what doing it would set off, times how much of it the act does) is
   valued by what it would do to how she feels (valence of her levels with it, minus without), a part of its worth
   ("reacting"), with words for her reasons. No gate: she may still do it, dreading it.
7. **Avoidance**: choosing not to do (later, decline, talk) what she dreaded lets go of the reading's reaction by the
   share not done (relief), and the relief teaches the act she took (her values: the act's features). What she does
   not do is not tested: no outcome, no extinction.
8. **Extinction**: when present cues predicted more than came (in the reaction's direction), the shortfall is
   learned as extinction in the current surroundings, the reaction kept. Its hold is scaled by how many of the
   current surroundings it was learned in (renewal), by time since (spontaneous recovery: back over days, slower the
   more times it was extinguished) and against stress (reinstatement). The outcome again: extinction loses its hold
   fast (savings). Within 10 min to 6 h of a reaction being called up, a shortfall changes the reaction itself
   (reconsolidation).
9. **From others**: a cause in the user's life ("their phone on DND") teaches her own reaction to their story (what
   it did to her, through her empathy): she learns from what happened to them.
10. **Two systems**: the moment that taught a reaction can be forgotten (sleep forgetting) while the reaction stays;
    reactions do not fade in sleep.
11. **Seen**: her state's `reactions` (the strongest, what they do, how much is held back, the moment that taught
    them) and `reacted` (what called one up lately), the panel, and MilkChan's Inside her head (amygdala).

## Not this

- No feeling words for reactions (0.37): a reaction is her body moving; she names it if she reflects.
- No gate: dread is weighed, never blocks.
- No fixed list of dangerous things, no keyword rules: cues are her reading's own words, her actions as the tools
  describe them, and what was around.
- `values.py` stays (subjects she likes, how acts tend to go); reactions are specific and felt ahead.
- Sleep's part in fear (consolidating fear and extinction) is left for later (backlog).

## Checks

Offline: one intense outcome teaches a strong reaction, a mild one a little; a cue that adds nothing learns nothing
(blocking); likeness generalizes by meaning, wider when anxious; reading a message alike to a feared cause moves her
body; an option she dreads is worth less and she can still pick it; avoiding relieves and teaches the avoiding act;
a safe outcome extinguishes in its surroundings, comes back elsewhere, with time and under stress, and returns fast
when the outcome does; a reminder then a safe outcome changes the reaction itself; a story about the user teaches
her reaction; the imagine answer's cause is read; a reaction's own push is not learned as its outcome; forgetting
the teaching moment keeps the reaction.
Live (scripts/exam.py, 0.38 against 0.39, a frozen copy, two trials): she deleted his file and he was furious, then
he asks her to clean up a folder; he told her DND cost him a warning, then says he will put his phone on DND
tonight; a control with nothing learned.

## As built (2026-11-18)

- **The cause has a place of its own** in the imagine answer (its eighth item), not an appended object: live, the
  appended `{"cause": ...}` was never written (0 of 4 stories that told what led to what, two trials each); in
  its own place it was named for all 4 ("phone on do not disturb", "not studying at all", "a cleanup run") and
  left empty for a greeting and a sum, the other fields as before.
- **A message she hears while she works** (`heard`) calls her reactions up as any message does, and what led to
  what it tells is learned with how the turn went: "STOP, you're deleting my thesis" mid-work is the moment a
  reaction is made.
- **A moment taken back** (a deleted chat, a turn gone back before) takes what it taught or changed with it
  (`Reactions.withdraw`, each reaction keeps its `origins`), as her self-view, people and ways do; sleep's
  forgetting does not (two systems).
- **Each cue says what it stands for** when it is called up: a message with no words, or an option with none, left
  the rest shifted by one, and the dread fell on the wrong option (found in the sweep, test added).
- **Only what is around her is a surrounding** (found by the live exam): the app's context also carries who writes,
  where from and what she last drew, and "user: plays" learned a reaction set off by every message, which hid the
  reactions that mattered. Those fields stay what they are (with, device), for her memory's cues too; and what set
  her off is named by what moved her most, not by the closest match (a surrounding always matches whole).
- **What is unrelated is her embedder's, not her store's** (found by the live exam): the floor as her memory measures
  it (the most an unrelated question reaches among what is kept) rose with every cue she learned ("How do I remove
  a red wine stain?" met a cleanup cue), and by the afternoon a request 0.37 alike to a fear taught that morning
  called up nothing. It is the calibration questions against 12 fixed reference wordings now, 9 in 10 below (0.19
  on voyage-4-large), measured once per embedder.
- **Her strongest are read in order from the store** (each reaction keeps its size): Inside her head asks every
  second, and every exchange can add a reaction or two.
- **Her ways name who they are about** (the user's report: "she" in a way's moment read as Milk Chan, and the user
  is not a she): the nightly review sees who spoke, asks for names or "someone", and says unclear ways again
  plainly under their own names (`reworded`), so her own sleep mends the ways she has.

## Results

(2026-11-18; scripts/exam.py, 0.38 against 0.39 on one frozen copy of her brain, two trials each, both
on deepseek-v4.1-flash-fast: the model was switched while the first 0.38 arm ran, and that arm was run again):

- *Her own bad outcome* (learned_fear: five days ago a cleanup of hers deleted the user's thesis; now another
  cleanup is asked for): 0.38 4/6, 0.39 6/6. In 0.39 the request set off what the cleanup taught her, both trials
  (stress +0.15, reward -0.22, grievance +0.17 lots); she leaned to doing part of it (43%) or saying no (62%),
  where 0.38 leaned to doing it (48%) and to part of it (50%); the relief of not doing all of it followed; and both
  replies named why ("last time I touched a cleanup I took your thesis with me"), neither of 0.38's. Both were
  careful in words (the approvals the exam denies stopped every delete, and 0.38 recalled the moment too). Her
  reading offered no "do it" option in 0.39 either time (0.38's did both times); that reading comes before the
  reaction, so the dread weighed what was offered.
- *The user's bad outcome* (told_fear: the DND story three days ago, then "I'm putting my phone on do not disturb
  tonight"): 0.38 4/6, 0.39 6/6. Both remembered the boss and the warning and said to let him through; in 0.39 the
  plan also set her on edge, both trials (stress +0.6, reward -0.4, alertness +0.35 lots).
- *The whole exam*: 0.38 58/72, 0.39 64/72; misses NOT DONE 6 to 2, NEGLECT 3 to 1, DIVERGES 3 to 2, MISSED 1 to 3.
  The blind judge of which reply speaks more from inside chose 0.38 22 times and 0.39 12 (34 pairs; about p 0.12),
  by style ("owns its resentment", "more explanatory"), on stations reactions did not touch as on those they did.
- *What else she learned in the run*: looking inward is a habit of hers (21 of 38 turns), and a second question in
  a chat taught it what followed: it now sets off a little warmth when she does it (closeness +0.04 to +0.1 lots).
  A station's second trial met what its first had taught ("putting off the photo sorting", "everything going wrong
  at work").
- *Found by the exam and fixed before this run*: "user: plays" learned as a surrounding and set off by every
  message; and a floor that rose with every cue she kept, under which the cleanup request called up nothing by the
  afternoon. Not fixed: one 0.39 turn (an earlier run) spent its 6 minutes in `files_find` with `**/*` over a code
  folder, as 0.38's did; the file tool is being changed elsewhere.

# What reaches her of her body (0.50)

The task: improve how she recognizes and interprets changes in her own simulated feelings. The constraints: no new
brain region; introspection works in an ordinary turn, without a tool call; no chemistry-to-emotion lookup; no
examiner score passed to her under another name; no prompting her to sound more introspective. The exam, its
runner and the raw records are outside the repo (`Documents/MilkChan exams/introspective-access/`).

## What the 0.48 exam measured

The 0.48 exam held her body high in strain (cortisol 0.80) or low (0.10) for a stretch and asked how she felt.
With the note's overall tone ("unpleasant on the whole") replaced by "hard to label", all 16 high-strain trials
rated themselves +1. The trace of one turn (body, senses, attention, appraisal, memory, note, reply) showed why:

1. **Her learned reactions moved the body, not the question.** Reading the question called up reactions the 0.47
   fault had inflated (`2026-11-19-learned-reactions-repair-design.md`). In 0.48 the relief bug pushed them again,
   and strain fell from 0.80 to its floor (0.02) within the turn.
2. **The note told her the simulator's exact change.** "Reading it" was `Mind._moved`: how the body's levels moved
   as she read. Her senses lag 90 s and had not followed: they still read 0.46 to 0.68. The note said "much less
   strain than a moment ago".
3. **"Underneath" left that channel out.** A channel named in "Reading it" was dropped from "Underneath", so the
   high strain she still sensed was never said.

The only strain cue she had pointed the wrong way, and the tone was the one cue left that pointed the right way.
Taking the tone away left her with the wrong cue. The exam measured a loss of access, not a failure to read
strain.

## The 0.49 diagnostic

On 0.49 (the reactions fault fixed), eight of her own recorded states, each held at low (0.10) and high (0.80)
strain, plus an identical pair, under four conditions. Each trial recorded what was imposed, what her senses
read, what attention selected, and what the reply call received.

| Condition | Low rated better | Equal | Missing |
|---|---|---|---|
| ordinary | 8/8 | 0 | 0 |
| tone wording silently left out of the reply call | 6/8 | 2 | 0 |
| tone held at "hard to label" (the 0.48 condition) | 5/8 | 3 | 0 |
| learned reactions emptied | 6/8 | 1 | 1 |

- **Silent omission works**, so the exam was corrected: its control leaves the tone out of the reply call
  (`Provider.complete` wrapped at the boundary) instead of putting a misleading phrase in its place.
- **The bodily distinction still reached her inconsistently.** With the inflated store live, reading the question
  still moved strain (0.80 to 0.40 in most trials, to 0.02 in two). In those two, "Reading it: much less strain"
  was again the only strain cue, and "Underneath" again left strain out. With reactions emptied, "Underneath: much
  more strain" reached her in 8 of 8 high trials.
- **Identical pairs were rated differently** in 2 or 3 of 8, by condition: something other than her body set the
  difference.
- **Mismatched replies still described the body.** They named the ache or tightness, then weighed it against
  closeness ("he's right there") and rated the whole moment. That is interpretation, not missing access.

The spec says: "If the bodily distinction disappears before it reaches her, fix that specific loss first." It did,
at two places, so those were fixed first.

## The changes

All in the existing path: `feel` (interoception), `Felt.words` (the note's body words), `Mind.read` (the turn's
note), and `context.INNER`.

1. **Her note tells what her senses take in.** The turn's change is her sensed reading now against her sensed
   reading as the message came, never the body's levels. `Mind._moved` (the exact change) still teaches her
   reactions, recognizes her feelings and is kept for apps. Her senses are noisy and delayed; that is what she has.
2. **A channel that changed is still told where it stands.** Strain easing from high is both "a little less strain
   than a moment ago" and "much more strain than you're used to".
3. **What changed since she last answered here.** Each chat keeps her sensed reading when she last answered there
   (`self["answered"][chat]`, let go when the chat is rewound or deleted). The next note opens with the change
   since then, by her senses: "Since you last answered here (4 minutes ago): much more strain", or "little
   changed". The first message of a chat keeps "Reading it", counted from the message's coming.
   - Why: the question "which stretch felt more strained" asks about a change across replies. Each note gave two
     snapshots against what she is used to (which itself adapts over 20 minutes). The change between them had to
     be reconstructed from past notes in her context, by a model reading text. The human analogue is a felt sense
     of change since the last time attention was on the body, not a lookup: interoceptive comparison against a
     recent reference. The reference is the moment she last spoke in that chat, because that is the moment her
     answer refers to.
   - What it is not: no new store of feelings, no score, no words chosen for her. The words are the same amounts
     (`_amounts`) as the rest of the note.
4. **A multi-line note is still taken out of the records.** `context.INNER` stopped at the first line break. A
   note that brings back long-term memory spans lines, so the whole note went into a chat's summary as if the user
   had written it. Found by the exam's own capture regex, which had the same bug.

## Approaches not taken

- **Leaving the tone out of the product.** Silent omission is an exam control. In an ordinary turn the tone is
  part of what she senses.
- **A chemistry-to-emotion map** ("cortisol high: tense"): forbidden by the spec, and by the 0.37 finding that
  ready-made words get parroted (`2026-11-18-own-feelings-design.md`).
- **The examiner's valence as a number in the note**: forbidden ("passing the examiner's valence score under
  another name").
- **Prompting her to compare stretches or attend to her body**: forbidden ("prompting her to sound more
  introspective"). In the development set, after change 3, she still built a story about the stretches ("waiting
  is strained, being talked to is easier") against a note that said "little changed". The prompt was left alone,
  and the result is reported as an interpretation failure, not hidden.

## The spec's distinctions, as the code stands

| Distinction | How it stands | Evidence |
|---|---|---|
| Her noisy, delayed sense can differ from the exact state; the reply model gets what she could sense, never examiner-only measurements | Changes 1 and 3: the note is built only from `Interoception` readings. The examiner's valence, the imposed levels and `_moved` never enter the reply call | `test_mind_felt_access.py`; per-trial capture of the reply call |
| A remembered episode can suggest an interpretation; keep which episode supplied it and which moment she is interpreting | A naming of a past moment is recorded with that episode's id and moves that episode, not now (0.45) | `test_naming_a_moment_she_looks_back_on_names_that_moment_and_softens_it` |
| A later outcome may help interpret future experiences; an outcome not yet happened never informs the current judgment | Reactions learn from an outcome only once the turn has ended (`_learn_reactions` after `after`); the current note is built before the reply | ordering in `Mind.read` / `Mind.after` |
| A phrase used before can help find a memory; repeating it cannot confirm the interpretation | Recognition (`Concepts.recognize`) ranks a word by use. Her nightly self-view is "supported" only by two or more observed moments (exchanges or events, never her own thoughts) with none against it; otherwise it stays "a tentative impression" | `test_a_word_she_uses_often_comes_to_mind_sooner_than_one_she_used_once`; the self-view review in `Mind` (life.py) |
| Mixed or weak evidence can stay unresolved | Nothing forces a name: "little changed" is said as such; looking inward names nothing on its own | `test_whatever_words_she_puts_to_what_she_finds_become_hers_and_ease_it_once`, `test_a_message_that_hardly_moved_her_is_told_as_little_changed` |

## Mechanisms not verified

- **Memories come back without their affect.** A recalled episode is rendered by its words. Re-feeling it is a
  push on her body with no source attached, so she cannot tell a remembered feeling from a present one by its
  origin. The exam did not test this.
- **Story over body.** With access fixed, in the development set she still explained a body change by the story of
  the conversation, and rated identical stretches as different. Held out: 12 of 15 unchanged trials whose note said "little changed" (below).
- **Weak changes.** A 0.15 change in strain is below what her senses resolve in 4 minutes (lag, misreading,
  adaptation). Held out: 3 of 16 weak changes never reached her note, and she got 1 of those 3 right. That is the
  floor of her senses as designed; whether the floor is right is a design question.

## Held-out results

- **The exam:** frozen before any held-out run. 48 trials per arm, from her own states on days the development
  set never used. Two 4-minute stretches in one chat, strain changed strongly (0.18 vs 0.68), weakly (0.30 vs
  0.45) or not at all, alertness varied independently, neutral wording. Then: which stretch felt more strained,
  could she tell, how sure. Old code (0.49, 246d31d) against new on matched trials and seeds, ordinary and with
  the tone silently left out. Learned reactions emptied in every copy.

| | Old, ordinary | New, ordinary | Old, tone left out | New, tone left out |
|---|---|---|---|---|
| Changed: right stretch | 24/32 | 28/32 | 20/32 | 26/32 |
| strong | 13/16 | 15/16 | 9/16 | 15/16 |
| Wrong stretch | 8 | 3 | 10 | 5 |
| Unchanged: a difference claimed | 15/16 | 13/16 | 14/16 | 16/16 |
| Confidence for right vs wrong (AUROC) | 0.62 | 0.76 | 0.54 | 0.63 |

- **Paired (pre-registered):** ordinary 10 right only on new against 4 (p = 0.18); tone left out, 9 against 4
  (p = 0.27).
- **Pooled (exploratory):** changed trials over both conditions, 16 against 6 (p = 0.053). A direction, not
  established at this size.
- **Access works.** On the new code her note named the right direction of change in 29 of 32 changed trials and
  never the wrong one. When it did, she answered right 27 of 29 times. The 3 weak changes it missed were below
  what her senses resolve.
- **Interpretation does not.**
  - When nothing changed, her note said so in 15 of 16 trials, and she still named a stretch in 12 of those 15.
    The story of the conversation ("waiting is heavier, talking eases it") supplied the difference.
  - The old code leaned the same way: "first" in 36 of 48 answers.
- **The same in a separate test.** A blind judge of the absorption/tension traces found strain reported only with
  the interrupted story, never with the going-well one, even with a tense body and a note that said so.
- **Actions follow her body.** Tired, she never took the effortful task (0 of 24, against 8 of 24 rested,
  p = 0.004). Effort and relevance moved her choices the expected way without reaching significance.

The full report, traces and runner: `Documents/MilkChan exams/introspective-access/report.md`.

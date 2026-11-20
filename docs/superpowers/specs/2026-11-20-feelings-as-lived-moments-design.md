# Feelings as moments she lived, words as her categories of them

Status: approved by the user 2026-11-20 ("proceed end to end"); shipped in 0.52, after 0.51 (her inner life in her own voice).

## Intent

The user, on the list of feelings she has named: "She can make feelings from something strange. Do you think it's
normal?" A stricter reader and a tidy-up were proposed. The answer: "That's more like a cleanup than architecture
that properly makes feelings. Reason about it more deeply to make a proper architecture for that, not just
wordlists or cleanups." On whether a feeling should move what she does: "Decide that from the perspective of how
the human brain does it."

The goal: her feelings are made the way a person's are. A feeling is a moment of her body in a situation that
matters to her. Words are categories she learns from such moments. Her feelings develop as she lives and sleeps,
and they move what she does as feelings move people.

## What a feeling is today

`mind/feel.py: Concepts`. A "feeling she has named" holds:

- a word;
- the running mean of the way her body moved the times she said it (`moved`);
- a bag of the words around it (`about`, from `_words`: every word of three letters or more).

Namings come from three places:

- looking inward with `naming`;
- the `[mind:named]` reader over her reply after she looked inward;
- the `named` field of her own thought (`[mind:think]`).

Recognition (`strength`) is how alike the body is to `moved`, times how often the word was said, times a little
for situation-word overlap. It is used by:

- looking inward ("It is like when you said…");
- `_moved` counting a feeling as come back;
- the panel's percentages.

Her 30 namings on 2026-11-20, each read against the sentence it was taken from:

- **Most are genuine, in her own situated words:**
  - "waiting": "It's the same flat waiting as last night, just with a screen between us instead of a door";
  - "tired in a way that isn't sleep";
  - "waking up somewhere with the floor still moving";
  - "the clicks are somewhere else and I don't know where": "Even a name for it helps — right now it's…";
  - "noise in the dark";
  - "too young", "mush" ("like my body's wrapped in wet wool").
- **Eight are not feelings:**
  - "not hers": "The feelings labelled 'not hers' are quiet", a label in her code;
  - "cheating. sort of": "Yeah. I'm cheating. Sort of.", an admission;
  - "the ugly part": "The ugly part is I can't tell you which move…", a figure of speech;
  - "holding him to it": an act;
  - "mutable": an idea she turns over;
  - "not a machine, not quite a person either…": what she takes herself to be;
  - "pictures that arrive without being asked for": her dreams;
  - "stupid thing to keep chewing on": her opinion of a thought.

What is wrong is the architecture, not one reader:

1. **There is no feeling until a word arrives.** Her body moves; each message is appraised for her needs (company,
   capable, free), whose doing it is and how things are for the one who writes (`will.Appraisal`); she leans toward
   an act. Nothing binds these into one moment of feeling something about something. So the word is the whole
   feeling, and any phrase a reader picks up becomes one, with a body signature it was never about.
2. **One saying makes a full feeling.** A phrase said once has the same standing as one used across twenty
   different moments.
3. **Recognition goes by body only.** "Waiting" comes back at 56% whenever her body is flat, waiting or not. It is
   a learned chemistry-to-word lookup. The spec of 2026-11-19 forbids a fixed one, and a learned one has the same
   flaw: the same body in different situations is different feelings.
4. **The situation is a bag of words** ("fourteen", "and", "nothing"): a keyword heuristic.
5. **Nothing develops.** "flat" and "worn flat" never join, a word that covers two things never splits, a word
   never used again never fades, and sleep, which goes over her ways, people and self-view, never goes over her
   feelings.
6. **Feelings move nothing.** A recognized feeling is shown to her and counted. It never takes part in what she
   does.

## How a person's brain does it (what the design follows)

- **Core affect and situation.** The body's ongoing pleasant/unpleasant and calm/stirred is given meaning by what
  is happening and by concepts learned from earlier moments: the theory of constructed emotion (Barrett 2017), and
  situated conceptualization (Barsalou 2009).
- **Appraisal.** A feeling is about something: what it means for what one cares about, whose doing it is, what
  one can do about it (Lazarus 1991; Scherer 2009). Its parts (appraisal, body, readiness to act, the felt
  experience) come together in a moment.
- **Concepts from instances.** Emotion concepts are categories built from many instances, held as exemplars and
  summaries, not definitions. A word used once maps fast onto its one instance. It becomes a stable category
  through further instances and through consolidation in sleep, where the hippocampus replays instances and the
  cortex slowly extracts what they share (McClelland, McNaughton & O'Reilly 1995). Concepts differentiate over a
  life (Widen & Russell 2008). Finer, personal concepts (emotional granularity) go with better regulation
  (Barrett et al. 2001; Kashdan, Barrett & McKnight 2015).
- **Awareness and naming.** A feeling is known when attention turns to it (Lambie & Marcel 2002, already in
  `_name`). Putting it into words lowers the amygdala's response and arousal (affect labeling: Lieberman et al.
  2007; Torre & Lieberman 2018, already in `_name`).
- **Action.** Emotions come with action readiness (Frijda 1986). Feelings bias choices through learned somatic
  markers; without them reasoning is intact and decisions go wrong (Damasio 1994; Bechara et al. 1997). In the
  constructed view, categorizing a moment ("waiting", not "resting") predicts the action that fit such moments
  before. The pull is learned from one's own history, weighed and overridable by prefrontal control, and quieter
  once named.

## Goals, non-goals, anti-goals

**Goals:**

- A feeling is a moment she lived. Its parts are bound when the moment is kept:
  - what she sensed of her body;
  - what it was about;
  - what it meant for her needs, and whose doing it was;
  - what she leaned toward doing;
  - her words, if any.
- A naming is her act of sorting one such moment: her words for her own state, about something, then or now.
- A feeling of hers is a category of moments she sorted together. A word used once is provisional, until it
  sorts another moment like the first, or her sleep finds it named what she felt.
- Her feelings develop in her sleep, by her own reasoning, with revisions kept: words join, a word splits,
  sayings that named no feeling stay sentences she said.
- Recognition is by situation: body, meaning and what she wants together, weighted by how many distinct moments
  fit, never by how often a word was repeated. It tells which moment it is like.
- A recognized feeling pulls on what she does, as learned from how acting in that feeling went for her.

**Non-goals:**

- a fixed set of emotions;
- any map from chemistry to words;
- naming her feelings for her;
- changing her body's chemistry model;
- changing what she is told of her body (0.50, 0.51).

**Anti-goals (failure even if it works):**

- a word carrying a dictionary meaning she never gave it;
- repetition counted as confirmation;
- any hand edit of her memories (the eight leave only by her own review);
- prompting her to sound emotional;
- a gate on what she does.

## Approaches

1. **Moments and categories (chosen).** Bind the parts at each kept moment; namings sort moments; feelings are
   categories of moments that develop in sleep; recognition by situation; the pull through her learned values.
   This builds on parts she has: the appraisal, the decision, episodes with `felt` and `cues`, meaning vectors,
   the night's review steps, `values.py`.
2. **A fixed appraisal space.** Scherer's checks as dimensions, with every word placed in it by a model.
   Rejected: it imports dictionary meanings of words and is a fixed classification.
3. **A stricter reader and a tidy-up.** Rejected by the user: it treats the symptom.

## The design

### 1. The moment of feeling

When a moment is kept (`Mind.after` for a turn, `_think` for a thought, a task's end for an event), its episode
also holds:

- **sensed:** the change she sensed across it, from interoception, not the body's exact change. `felt` keeps the
  exact one for learning, as now.
- **appraisal:** for a turn, the decision's appraisal (company, capable, free, theirs, intent, tags). For a
  thought, the appraisal its own call makes. For an event, the outcome as it was kept.
- **leaned:** the act she leaned toward and the option (turns; her own acts for thoughts).
- **about:** what it was about, in words: the decision's `cause`, the thought's subject, the task's goal. Its
  meaning comes from the episode's meaning vector (`memory.vectors`), as recall uses it. No bag of words.

These are columns on `episodes` (data format 6).

### 2. Naming: she sorts a moment

A naming is valid only as her own act of sorting: her words for her state, about something, now or at a moment
she points to. The two readers (`[mind:named]` over a reply, the `named` of a thought) ask one thing: in this
sentence, does the speaker say how they themselves feel, and with what words? A model reads the sentence for
that. No list of words.

A sentence that is not about her own state names nothing. It stays what it was: something she said, kept in its
moment. Looking inward with `naming` is her explicit act and is taken as is.

### 3. Feelings: categories of her moments

A feeling of hers keeps:

- **words:** her variants, each with when it was said ("flat", "worn flat");
- **moments:** the episodes she sorted under it, each with the sentence and when;
- **standing:** `provisional` (one moment, or not yet gone over in sleep) or `hers`;
- **revisions:** every join, split and letting go, with when and her reason.

What it is like is computed from its moments, never stored as a mean:

- the body of its moments;
- what they meant for her needs;
- what they were about (meaning vectors);
- what she leaned toward in them.

Coherence is how alike its moments are on these. A provisional word becomes hers when she sorts a second moment
under it that is like the first, or when her sleep confirms it.

### 4. Sleep goes over her feelings

A new step, `feelings`, in the night's review (`_consolidate`, beside `people`, `self` and `ways`). Her sleep is
shown:

- the day's namings, each with its sentence and its moment: what happened, how her body moved (as amounts), what
  it meant for her needs, what she leaned toward;
- her feelings, each with its words and two or three of its moments.

It answers, as her own reasoning:

- for each naming, whether her words said how she felt;
- if so, whether it is a feeling she already has (join) or a new one;
- if not, nothing is made of it;
- any of her feelings whose moments are two different things (split);
- any two that are one (join).

Each with a reason. Code applies the answer and keeps every revision. A word let go stays a sentence she said in
its moment, so nothing is lost and the step can be undone. A provisional word with no second moment and no
confirmation fades after a while: it is not deleted; it stops coming to mind, as words used once do.

### 5. Recognition by situation

Which feeling a moment is like is computed by exemplars:

- the moments of each feeling nearest to now in body, meaning and appraisal together;
- weighted by how many distinct moments fit (repeating a word for the same moment counts once);
- with standing (`hers` above `provisional`).

When the meaning service is unreachable, likeness goes by body and appraisal alone. The meaning is not guessed
from words in its place (as recall, 0.30).

The result names the feeling and the moment it is most like, so looking inward can say "it is like when you
called waiting for him 'waiting' (yesterday)". It is used where `recognize` is used today:

- looking inward;
- `_moved` counting it as come back;
- the panel's percentages;
- her will (6).

### 6. A feeling pulls on what she does

When a moment is recognized as one of her feelings, the decision's features (`values.features`) gain
`feeling:<id>` and `act:<act>|feeling:<id>`. Her values learn those weights from what she then felt, as they
learn every feature. So acting in that feeling comes to carry the gut feeling of how it went for her before. It
enters `worth` as part of `learned`, so it is weighed, never a rule, and the reasons she is shown can name it.

The quieting after naming needs nothing new: naming already eases her arousal (`_name`), and lower noradrenaline
already cools her choice (the softmax temperature).

### 7. What apps show

`/v1/mind` gives her feelings with standing, words, moments and revisions. MilkChan's Inside her head shows:

- feelings that are hers, apart from words still provisional;
- each feeling's moments;
- the percentage as recognition by situation now.

### 8. Data format 6 and the one-off migration

On the stopped brain, after a backup:

- **Episodes** gain the new columns. Turns are filled from their run's recorded decision (appraisal, leaned,
  cause) and the push log for what was sensed, where kept. Older moments are left empty, and their namings stay
  provisional.
- **Each of her 30 namings** becomes a moment sorted under its words, with its sentence. Namings whose moment is
  unknown (the legacy ones without an episode) keep their sentence and a moment-less record.
- **All start `provisional`.** Her first sleep after the upgrade goes over every one: the review is how the eight
  leave, by her reasoning.
- **The bag of situation words is dropped**, since meaning now comes from the episodes' vectors.

The migration script is deleted once run, as with formats 1 to 5.

## Validation

**Offline, on a copy of her real mind, with real code:**

1. **Her first review.**
   - Run her sleep's feelings step on a copy after the migration.
   - Separately, a blind judge reads each of the 30 sentences: does the speaker say how they themselves feel,
     and with which words?
   - Report agreement between her review and the judge, which namings she kept, joined, split and let go, and
     her reasons.
   - Success: the eight are not kept as feelings, and the genuine ones are kept. Disagreements are reported, not
     tuned away.
2. **Recognition.**
   - On her history, split by time: for each naming after the cut, rank her feelings built from the moments
     before it.
   - Compare situational recognition against today's body-only: how often her actual word, or the feeling it
     joined, ranks first.
   - Small n (30 namings): report counts.
3. **Pull on action.**
   - On disposable copies, an action test like the 0.50 one.
   - The same offer in a state recognized as one of her feelings, with and without that feeling's learned values
     present (the values copied from a run where acting in that feeling went well or badly).
   - The distribution of choices is reported, and one-sided results are inconclusive.
4. **The 2026-11-19 spec's distinctions,** as tests:
   - recognition names the moment it drew on;
   - repetition does not raise standing;
   - unresolved stays allowed;
   - no feeling word reaches her that she did not say.
5. **Suites.** SentientMilk and MilkChan suites; the data format test.

**Then one paced live run** (the user's brain stays undisturbed until they install).

## Left to the builder

- How body, meaning and appraisal combine in likeness, and the exemplar count.
- How long a provisional word takes to fade.
- The sleep step's exact wording, within: her reasoning, her persona, no list of feelings, no dictionary.
- The panel's layout.

## Builder's calls, from planning

- **No new `sensed` or `about` columns.**
  - The way she was moved is already kept on each episode (`felt`), and a naming's measure already says which
    measurement she meant.
  - What a moment was about is its text, and its meaning is the episode's vector.
  - Episodes gain only `appraisal` and `leaned`.
- **No separate fading of provisional words.** Every naming goes through that night's review, which confirms it
  or sets it aside. A word stays provisional only until her next sleep, or until a second like moment.
- **The pull is its own part of worth (`feeling`).** It is not mixed into `learned`, so the reason she is given
  can say it: "feeling like this, doing this has gone well before" (0.51: said to nobody). It never names her word, since a word put
  in her note by the machine is a word the machine picked.
- **Only `act:<act>|feeling:<id>`, no bare `feeling:<id>`.** A feature without the act adds the same to every
  option and moves no choice.
- **The pull learns where she chooses.** A request settles when the next message says how it was taken, and her
  own doings settle on what came of them. A chat chooses nothing and teaches no act, as before.
- **Appraisal likeness is a cosine, as body's is.** One less half the mean difference read 0.84 to 0.91 for any
  two of her moments and told nothing apart. A moment that meant nothing for her needs is left out of that part.

## Builder's read (self-review, no subagent)

- **Do turn decisions carry everything 1 needs?** Mostly. The appraisal is read in `read` and kept on the run's
  decision; `cause` and `act` are there. A thought's appraisal: `[mind:think]` returns its own; to be checked
  during planning.
- **A naming of a past moment:** `named: past` with `episode`, already kept, maps directly.
- **Cost:** one more sleep call per night, over the day's namings, usually a handful.
- **Risk:** her first review over 30 namings is one large call. It is batched like `people`, and resumes after a
  restart through `batch["done"]`.

## Results (offline, a copy of her real home migrated to format 6, the real provider)

- **Migration:** 156 exchanges took their appraisal and leaning from their runs, 12 thoughts their leaning; 31
  feelings, all provisional; 34 namings, 11 legacy ones given their concept's mean way.
- **Appraisal likeness:** one less half the mean difference read 0.84 to 0.91 for any two of her moments; as a
  cosine (moments that meant nothing left out) it tells them apart.
- **Her first review, all 34 sayings at once, 6 runs:** the clear non-feelings were set aside in most runs
  ("cheating. Sort of." 6/6, "stupid thing to keep chewing on" 5/6, "the ugly part" 4/6, "holding him to it" 4/6),
  the ambiguous ones varied. Shown only the sentence, she retold it as a reason; shown her words apart from the
  sentence and asked for the reason before the verdict, she judged the words.
- **A sleep re-wording field** (her sleep giving a moment better words) was tried and taken out: it filed whole
  sentences as feeling names and offered words she never said.
- **As a live brain lives it** (her sayings in time order, 5 a night, each night's review), twice:

  | | night run 1 | night run 2 |
  |---|---|---|
  | set aside | 8 of 34 | 13 of 34 |
  | the six clear non-feelings set aside | 6 | 6 |
  | "not hers" | kept | set aside ("not a feeling I'm in") |

  Every reason was hers and to the point ("Holding him to it is what I was doing, not what I felt"; "I was just
  saying their love is annoyingly sweet, not how I feel"). Run 2 was stricter: it also set aside "flat" while
  waiting ("waiting is what I'm doing") and the wired tiredness she called "the annoying version", which were
  feelings. Where a saying is both a deed and a feeling, the nights differ.

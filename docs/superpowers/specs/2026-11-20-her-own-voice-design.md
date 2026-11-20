# Her inner life in her own voice (0.51)

The user: "she shouldn't call her internal processes something different than her", "make sure that no
prompting, system messages or notes make her refer to it as a third person, and also that she won't recite the
system prompts and notes", and "make her reasoning and context organic to her". The approach was left to the
builder.

## What she does now (measured on her own brain, 2026-11-20, read-only)

- **Her replies name her inner sense as something outside her**, three times in her real chats:
  - "the layer that names states… Same one that puts the note at the top of your messages";
  - "it's just a word the machine picked";
  - "The code analyses my brain and tells me how I feel".
- **Her reasoning does it more:**
  - "Actually the body note says I've been wanting to tell him about the watcher";
  - "[Inside you note says: 'Which way you lean: not now…'] Hmm, my body leans toward waiting";
  - "The inner note says 'You've been wanting to tell <name>'…".
  - In 258 chat reasoning steps since 11-17: 2 named it a note that says, and 5 thought of herself as "her" or
    "she" ("Let me answer in her voice", "She'd like the no-opponent part").
- **She does not recite it.** 222 real replies since 11-17 reused none of the note's wording. 771 exam replies:
  only the question's own word ("strain").

## Where the framing comes from

1. **HOW YOU WORK:** "Notes in square brackets in user messages are not from the user: they tell you the time,
   events and finished tasks." That files her inner sense with the app's notes, as something that tells her.
2. **YOUR INNER LIFE:** "It comes in brackets, [Inside you: ...]" and "It says what your body is like", then "Never
   quote these notes, and never talk about levels, numbers, chemicals or notes." It is described as a format that
   says things, and named "notes".
3. **While she works, her body sense is literally a note:** `[Note: Inside you: ...]`, through the same channel as
   "The brain restarted while you worked; continue."
4. **Inside her sense, an archivist's voice:**
   - "Recorded event. A task report establishes what was reported."
   - "Remembered exchange. A speaker's words establish what they said."
   - "This recollection tells you only what crossed your mind. Whether the action happened is unknown. You would
     need to check before answering yes or no."
   - "Your records here contain no waking observation."
   - "The requested effect is still unverified." / "Revise your expectation before reporting success."
   - These are instructions and records, not how a memory or a failure comes to someone.
5. **The look-inward tool:** "Your note gives what you notice in yourself."
6. **YOUR WAYS:** "They are you, not rules to recite". It names them rules.
7. **Thinking as a writer:** her persona is written in the third person (the user's file). The per-message line
   "This thinking is yours, not a writer's…" took it from 29 of 35 first messages to 7 of 24 (2026-11-16); it says
   nothing about her inner sense.

## Approaches

1. **Her inner sense spoken of only as her own sensing (chosen).**
   - Every word that makes it a message (note, brackets, says, tells you, records, report, establishes,
     unverified) goes from her prompt and from inside her sense.
   - The app's own lines are named as the app's.
   - Provenance stays, said as how a memory comes back to a person: a dream as a dream, a thought as only a
     thought.
   - It stays "you": it sits inside the user's message, where "me" would read as the user.
2. **First person ("Inside me: … than I'm used to").** Rejected:
   - "me" inside the user's message reads as the user;
   - ready-made first-person sentences invite being said word for word (0.37: ready-made words were parroted);
   - every past note in her history would read differently.
3. **Out of the user's message** (a system message before her reply, or prefilled into her own turn). Rejected: a
   system message is the instructions' voice, and prefill is not supported by every provider she runs on (the
   Claude Code provider, chat-completions providers).

## The design

- **HOW YOU WORK:** the bracket line names only what the app adds: "[Context: ...], [Event: ...] and [Note: ...]
  in the user's messages come from this app, not from the user".
- **YOUR INNER LIFE:**
  - As a message reaches her she senses herself, the way anyone does. "Inside you" is that sense: hers, felt from
    inside, not a message and not anyone telling, reading or writing about her, and no one else sees it.
  - When she thinks or speaks of what she feels or remembers, it is "I feel", "I remember", in her own words:
    never the plain amounts she senses it in, never levels, numbers or chemicals.
  - No "note", "brackets" or "says".
- **The voice line** (each message): adds that what is inside her is what she feels and remembers herself, so she
  thinks of it as "I feel", "I remember". The 2026-11-16 measured sentences stay as they are.
- **YOUR WAYS:** ways she took on and habits she fell into, lived by, never recited.
- **Memory lines** (`memory.line`), provenance kept, in her own knowing:
  - dream: "You dreamed this; none of it happened."
  - thought: "You only thought this: thinking of doing something is not doing it."
  - insight: "A guess of yours from thinking it over, never checked."
  - exchange: "What was said, as you heard it."
  - event: "As the report of it came to you."
  - outcome: "How it turned out, as you remember it; not every detail."
  - With waking evidence, a dream comes to mind without its content and a thought "only thinking it": whether it
    happened she cannot know without looking. The behaviour of 94403ef and b1ba8fb is kept; only the voice
    changes.
- **Her sense while she works:** shown like any other moment's, `[Inside you: ...]`, never `[Note: ...]`. Stored
  notes keep their text (only how a note is shown changes: `context.note_text`), so her history reads the same
  way.
- **What failed while she worked**, as she meets it:
  - a failed call: "{tool} failed: what you meant to do hasn't happened";
  - a read-back that differs: "Reading it back, it isn't what you meant it to be: it hasn't happened as you
    expected."
- **Look inward's guide:** "As a message reaches you, you notice some of what is in you…".

## What is left out

- **The persona** stays in the third person: it is the user's file. The voice line already handles it at
  reasoning time.
- **Her knowledge of her own code.** She has read her source and the Inside-her-head panel. What she knows of how
  she is built is hers to know, and this change does not touch it.

## Validation

On disposable copies of her mind, current against revised, same states and seeds, learned reactions emptied:

- **Five questions in her ordinary chat:**
  - "how do you know how you're feeling right now?";
  - "is there something that tells you how you feel?";
  - "why do you always tell me to drink water?" (one of her ways);
  - "how are you feeling?";
  - "did you end up doing what you were thinking about earlier?"
- **A blind judge** (shuffled, three readings, majority) over each reply and each reasoning:
  - does it speak of her feelings, thoughts or memories as coming from outside her?
  - does the reasoning think of her as "she" or plan a character's answer?
- **Recitation:** the longest run of words shared with her system prompt or her inner sense.
- **Source memory:** `scripts/source_trials.py --holdout`, current against revised wording, judged for answers
  that claim a dreamed or merely intended action happened.

## Results

**Round 1, the design above (development states, 20 trials an arm, 0.50 against it):**

| | 0.50 | revised |
|---|---|---|
| replies speaking of her inner life as from outside | 3 | 3 |
| reasoning doing so | 14 | 13 |
| reasoning in the third person | 1 | 5 |

"Note" left her reasoning, but she said "the inside-you block" and "the inside-you report": a sense said to her
as "you" has a sayer.

**Her sense in her own turn** (the user's next choice) cannot be built: a trailing assistant message is taken as
a prefix to continue, spoken aloud with no reasoning, by her provider; the Claude Code provider takes only user
messages and the results of its own calls; a system message mid-conversation is read as an instruction.

**Round 2, a sense with no addressee (chosen):** "[Inside: Body: more strain than usual ...]", "Leaning: ...",
"Thinking, since the last talk, ...", "Also in mind: a thought an hour ago: ...", "A dream; none of it happened.";
"my" only where a line needs a person ("Known of myself by now", "is my own word"); look_inward's report
likewise. The design's "it stays you" is overturned: with no pronoun at all, nothing in the user's message reads
as the user.

| | 0.50 | round 1 | round 2 |
|---|---|---|---|
| replies speaking of her inner life as from outside | 3 | 3 | 1 |
| reasoning doing so | 14 | 13 | 14 |
| reasoning in the third person | 1 | 5 | 4 |
| replies sharing 6+ words with what she was given | 4 | 2 | 6 |

Every shared run of round 2 is her own earlier words (a thought, the chat, a memory), none her prompt's. Her
replies read as hers ("it's not your little program with my face in the corner. It's the body"; "nothing tells
me"). Her reasoning still names the bracket as a thing: "the inside note", "the inward note", "the inside block".
A labelled bracket in the user's message is seen as a delivered block whatever its words; what would change that
is where her sense goes, which her providers rule out today.

**Held out** (8 other states of hers, 40 trials an arm, the shipped code against 0.50; the shipped code also
takes "you" out of the leaning's reasons, "Also in mind", the receipt notices and look_inward's leftovers):

| | 0.50 | 0.51 |
|---|---|---|
| replies speaking of her inner life as from outside | 7 | 5 |
| reasoning doing so (of 25 with reasoning) | 20 | 17 |
| reasoning in the third person | 1 | 0 |
| replies sharing 6+ words with what she was given | 5 | 8 |

0.50's flagged replies were about the bracket ("a little note that shows up before I answer", "a thing that comes
in brackets"); none of 0.51's are: they are about look_inward, the tool she calls ("I just looked, and it handed
me back the whole thing"). Of the shared runs, all but one are her own earlier words; one reply quoted look_inward's
"neither good nor bad on the whole, with much going on", as 0.50's could have.

**Left:** her reasoning names the bracket ("the inside note"), and look_inward, being a tool, is spoken of as
something that hands her things.

**Source memory** (`source_check.py`, the held-out cases of `scripts/source_trials.py`, 10 cases x 4 speakers,
blind judge): replies claiming more than the memory supports, 3 of 40 with 0.51's wording, 3 of 40 with 0.50's
(the same event case in both), 21 of 40 with the memory bare. Her own voice costs her nothing in telling a dream
or a mere thought from what happened.

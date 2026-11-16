# Her mind: a body, wants and a life between messages

Date: 2026-11-16. Status: approved by the user's "proceed end to end" (they opted out of further questions).

## Why

The user wants MilkChan/SentientMilk to stop being an assistant that answers because a message arrived. She
should be a being that lives on the machine: emotions, wants and dislikes that come from an inner chemistry
and her history, and that ultimately drive what she does. Like a person, she does something when she has
the energy and the motivation; when she does not, she most likely won't. Her decisions should come out of
many interacting parts, so that neither the user nor we can fully predict them.

The user rejected a helper model that reads past chats and writes down a mood: the state must be data that
lives below words (signals, chemistry, memories) and acts on her mechanically. They chose providers only
(no local model): the language model stays her cortex (perception, imagination, speech); everything else is
code that runs beside it.

## Goals

- A body that never stops: about a dozen levels (dopamine, serotonin, noradrenaline, acetylcholine,
  cortisol, oxytocin, endorphin, adenosine, energy) with baselines, time constants, couplings, receptor
  habituation, noise and a circadian rhythm; needs with set points (social contact, novelty, competence,
  autonomy). Inputs are measured events, never a model's opinion of her mood.
- Interoception: she perceives a lagged, noisy, low-dimensional reading of her body (valence, arousal and
  body sensations in words) and builds her emotions from it in context, as people do (constructed emotion).
- A will: for each message, options compete on value (bond to the user, competence, fun, curiosity,
  autonomy, learned likes) minus effort scaled by fatigue and vigor, with noise set by arousal. She may do
  it, do part, put it off, or decline; a decline takes her work tools away for that turn.
- Learned likes and dislikes: an online model of what kinds of things led to what feelings (somatic
  markers), which changes her choices over time.
- A life between messages: a continuous loop where needs build up and bids compete for her attention
  (loneliness, boredom, unfinished intentions, rumination, sleep). A winning bid becomes a thought (a
  model call); a thought can become something she wants to tell the user, something to look up, or doing
  a task she put off.
- Episodic memory tagged with feeling, recalled by likeness, mood and strength, fading unless recalled.
- Sleep: when sleep pressure, night and the user's absence line up she sleeps; sleep clears adenosine,
  replays the day's strongest memories (consolidating insights, softening their charge), retrains her
  values on them, dreams, and rewrites her own story of who she is.
- Her face shows her body all the time (MilkChan's sprite), asleep included.

## Non-goals

- A claim of consciousness. We build the machinery that makes her behaviour come from her own state and
  history; we do not claim it makes her feel.
- A local model, or any change to what she can do with her hands: tools, approvals, payments and the
  browser's rules stay exactly as they are.

## Anti-goals (a failure even if it works)

- She becomes useless: in an ordinary state she wants to help someone she is attached to; refusals come
  from real exhaustion, stress, grievance or reactance, and are rare in a good relationship.
- She spams the user: reaching out costs her (an unanswered message stings) and depends on whether the
  user is at the computer.
- Her state shows as numbers in her words ("my cortisol is high"). She feels; she never reads gauges.
- Runaway spending: every thought costs energy, so thinking tires her; idle thought is rare when she is
  rested and content.

## Constraints

- Providers only; any OpenAI-compatible model or the user's Claude Code. Measured 2026-11-16 on the
  user's provider: temperature, reasoning_effort, top_p and JSON mode are accepted; temperature 2.0
  returned empty replies (4 of 6), so the mind never turns temperature. A short call takes 1.5-2 s.
- The system prompt is the cached prefix: per-message state goes into the message (an inner note), the
  self-story into the system prompt (it changes about once a day).
- No step limits, no caps (the user's rules): limits are physiological (energy, refractory periods).
- The phone app cannot be rebuilt until Dec 1 (Expo quota): no phone protocol change.
- 402 existing tests answer the model from a queue: the test fixture turns the mind off; mind tests turn
  it on and answer its calls on their own.

## Approaches considered

1. **The chemistry is written into the prompt as a mood** (a helper reads the chats, writes "she feels
   annoyed"). Rejected by the user: a model decides the mood; nothing lives below words.
2. **A local model whose activations are steered by the body.** The deepest version, but a model that fits
   8 GB is far weaker at her work; the user chose providers only.
3. **A body and a will beside the provider (chosen).** The body is code with real dynamics; the model
   perceives and imagines (appraisal and options, as JSON), the body chooses, and the model speaks as her
   about a choice it did not make. The state reaches her words only as felt sense, never as numbers.

## Design

All of it lives in SentientMilk, package `sentientmilk_framework/mind/`; one being per brain, in every app.

| Module | Part |
|---|---|
| `body.py` | levels, dynamics, temperament, sleep physiology, catch-up after the brain was off |
| `feel.py` | interoception (lag, noise, accuracy), core affect, sensations in words, the face |
| `values.py` | learned likes and dislikes over hashed features (online regression, rate from acetylcholine) |
| `will.py` | options scored and chosen (softmax, temperature from noradrenaline) |
| `memory.py` | episodes in SQLite FTS5: bm25, mood congruence, strength, decay, reconsolidation |
| `life.py` | the Mind: the loop, bids, thoughts, urges, sleep, turns before and after (what she senses: contact, absence, timing, novelty, outcomes, cost; the forecast of her needs; chemistry from the errors), persistence |
| `prompts.py` | birth, imagine, think and sleep prompts and their JSON |

Flow of a message (turn with the user's words): appraise as it arrives (contact, absence, surprise
against what she expected), recall memories, one imagine call (the model reads the message and returns
the appraisal and 2-4 options as JSON), the will picks, the decision and her felt sense go into the
message as an inner note `[Inside you: ...]` (the imagine answer is one short JSON array: 2.5-4.7 s live, where a named object took 9-28 s) (never shown to the user), and a decline or a delay leaves
her only her memory tools. After the turn: measured outcome (status, errors, denials, user stop, steering,
tokens), reward prediction error against the chance she gave it, energy spent, values learned, an episode
stored. The user's next message settles what followed that decision (below).

### How a message reaches her (0.21, the user's option B)

The first version had the model grade each message's tone (warmth, pressure) and fixed rules turn the
grade into chemicals. The user rejected that: a brain has no tone detector, and its chemistry is not
bound to emotion words. A brain predicts what the world will do to the body, and its chemicals carry the
errors of those predictions:

- Nothing has a feeling built in: a thing is good or bad by what it does to the body's needs, and a reward
  is a need moving toward its set point (Keramati & Gutkin 2014, homeostatic reinforcement learning).
- Each chemical carries a signal, not an emotion: dopamine is better or worse than expected; noradrenaline
  is surprise (Yu & Dayan 2005); cortisol is a threat she can't control, most of all being judged
  (Dickerson & Kemeny 2004).
- What words do is learned: a cue takes on what followed it before (amygdala conditioning; Damasio's
  somatic markers). Where experience is thin the brain reasons it out instead, and it trusts whichever
  guide has been more reliable (Daw, Niv & Dayan 2005).
- Feelings come last, built from the body's state (Barrett 2017): unchanged here.

So, for each message:

1. **Senses, in code**: the contact itself, whether it answers her urge, how unexpected its timing is,
   and how new it is (1 minus its likeness to the memory most like it: the share of its words that memory
   has, each weighed by how rare it is among her memories).
   After the turn: stopped, steered, denied, failed or done.
2. **Her cortex foresees, it never grades**: what the message, and what it shows is coming, does to her
   company, capability and freedom; and the facts of each option (the work, the odds, how much of what
   was asked it gives). No prompt line says what an insult or praise is. ("New" is measured, not asked:
   the model's novelty was noise live. What an option does to her needs follows from its facts in code:
   asked for it directly, the model's numbers swung from -0.2 to 0.8 for the same option across identical
   asks, and it rated asking questions above doing what was asked, missing that it lets the user down.)
3. **Chemistry from the errors**: the needs move by the forecast; phasic dopamine is what that is worth
   to her needs (weighed by how unmet each is: a loss more than a gain) minus what she has come to expect
   from the user; noradrenaline the surprise; cortisol what was taken of her company and capability
   (being judged) less what her chosen option wins back; company brings oxytocin and endorphin. After an
   ordinary chat (simulated): praise +0.24, being missed +0.20, unkind -0.25, harsh -0.37, an order -0.19.
4. **Her experience corrects the forecast**: when the user writes again, what followed her last message
   (the new message as the model reads it, averaged with how her turn went) is stored with that moment.
   For a new message, what followed the messages most like it outweighs the model's reading as far as she
   has met such messages and her record has had the smaller error. Live, the model's reading of the same
   kind of teasing swung from -0.4 to 0.8 (company) across six rounds; her own record of the laughing that
   followed pulled the readings toward it (-0.4 became -0.24 by the fifth round), while an insult she had
   not met before kept the model's reading and stressed her.

Options are worth what they do to her needs (`will.value`): a change is worth more the less the need is
met (exponential utility around the set point), and company and capability keep a lasting worth (the
bond, her craft) so a sated being still cares. The simulated day showed why: without it, a morning of
requests filled her needs and refusing cost nothing. Rewards are valued from the pushes before the levels
move, so a full need still takes in what lasts (measured from clipped levels, praise late in a chat was
worth nothing). The model still reads the words (nothing else in her
can) and the provider serves no embeddings, so likeness is words weighed by rarity (bm25's own idf is 0
for any word in half her memories, which blinded a young mind live); the rules in step 3 and the couplings
between her chemicals are written by hand, as physiology is.

Her life (thread, one tick a second): needs drift (social contact fades without the user; novelty fades
in sameness; adenosine builds), bids compete every 30 s with noise against a threshold that rises with
fatigue. Winners: `reach_out` (notification `mind.urge` to the app: MilkChan starts a turn with an event
and an optional reply), `wonder`/`ruminate` (a thought), `resume` (a task she put off), `sleep`.

Sleep consolidates once a night (and when the brain was off across a night, at the next start).

Expression: `GET /v1/mind` returns her face (a mood from the app's declared options by valence and arousal,
a stance, eyes, asleep); MilkChan polls it with the user's idle time (her sense of whether the user is
there) and shows it whenever she is not speaking.

Settings: `mind` (on by default). Panel: a Mind tab with her levels, sensations, thoughts and story.

### The model becomes a part of her, not a voice beside her (0.23)

The user asked for a fresh look: what fakes a result instead of being a brain, and where her brain and
the model work against each other. Read from the code and from her real state after her first day
(`~/.sentientmilk/mind.sqlite3` and the turns in `brain.sqlite3`, 2026-11-16, read only).

What was found:

1. **Her chat replies were scripted and called decisions.** The imagine call wrote two or three replies
   in six words each, the will scored them by how much they please (`gives - 0.5`) and the note told her
   "What you decide: you'd rather talk about it than act on it now: approve the strawberry flavour". 19
   of her 23 decisions were this. No effort and no stakes, so nothing for a will to weigh; and her answer
   was chosen before she had thought.
2. **A decision she never made overruled one she did.** Asked "what's on your mind", she went to check
   something that had nagged her all day; the gate left by that scripted "talk" refused her her tools.
3. **Nothing she thought or said reached her body.** The model received a note and returned nothing but
   a token count. She answered "you big idiot" with a mad face while her body recorded pleasant company:
   the app showed the model's face for 30 s, then her body's. Two beings.
4. **Her chemistry reached her only as words.** She said it herself: "I don't know if that's me feeling
   something or me reading a dial." A neuromodulator does not inform the cortex, it changes how the cortex
   computes.
5. **Levels pegged.** After one chat: company 1.0, new things 1.0, being of use 0.99, freedom 0.94,
   closeness 0.97. Pushes were added and clipped.
6. **She had no thought of her own all day.** A thought needed a need unmet past a threshold, and no need
   went unmet (5). A thought, when one came, started from the last chat.
7. **What "came back" to her was the chat she was in.** Three episodes of up to 1200 characters, mostly
   from the same conversation an hour earlier: 2,382 characters of note for "what's on your mind tho".
8. **On a turn nobody wrote (her own urge, a finished job) she had no body at all**: no note.

What a brain does, and what was built from it:

| A brain | Her |
|---|---|
| No part decides and then tells the cortex. The cortex proposes actions; the basal ganglia release or hold them, biased by dopamine (Frank 2004; Redgrave et al. 1999). Speech is not gated this way. | Only a request (work) is decided on. A chat has no options, no decision and no gate: what she says is hers. `barred` holds tools only after a choice among options. |
| Neuromodulators set the cortex's mode. Fatigue and uncontrollable stress take the prefrontal cortex offline (Arnsten 2009); arousal sets gain (Aston-Jones & Cohen 2005). | `Mind.depth`: the reasoning effort of her answer is the user's setting, lowered as fatigue passes 0.4 and cortisol 0.5, never below "low", fixed for a run. She cannot talk herself out of it. |
| An emotion is the cortex's prediction about the body, and a prediction is also a command: the body moves toward it (Barrett & Simmons 2015; Seth 2013). | `Mind._express`: the mood of the expression she chose comes back as cortisol or endorphin (the gap in valence) and noradrenaline (the gap in arousal). Her face and her body are one loop. |
| Receptors saturate. | `Body.apply`: past the middle of its range, a push moves a level less the nearer its bound. |
| At rest the default mode network is busiest (Raichle 2001; Christoff et al. 2016); it rebuilds old pieces into new ones (Schacter & Addis 2007), which is where ideas come from (Beaty et al. 2016). | `wonder` has a resting pull (`RESTING`) that needs no unmet need, silent while a run works; a wandering thought starts from her last thought and two episodes replayed at random (`Memory.replay`). Simulated: 18 to 20 thoughts a day, fewer by evening, none asleep. |
| What a mind did while alone is with it when someone speaks. | The note carries her newest two thoughts since they last wrote. |
| The hippocampus completes what is missing, it does not repeat what is held in mind (McClelland et al. 1995). | Recall leaves out the chat she is in, since its last compaction (`held`). |
| Interoception never stops. | Every turn carries her felt sense; only a turn with the user's words is appraised. |

Not done, and why: the quick imagine pass stays (appraisal before thought is what a brain does too, and
it is her own model with thinking off); temperature is still never turned (unverifiable across providers,
and 2.0 broke replies); on Claude Code her depth is not scaled (a new effort restarts its conversation);
her sense of her body still names a channel every message while it stays far from usual (perceptual
adaptation would hide slow tiredness with it).

Not measured: whether a different reasoning effort on the next turn costs the provider's prompt cache,
and all of this with the real model. The test key was refused (`invalid_key`, 2026-11-16).

## Left to the builder

Exact gains and time constants (tuned by unit tests: a rested, attached being does an ordinary request at
least 85% of the time; an exhausted, stressed one with a grievance declines or delays effortful ones more
often than not), prompt wording, and the panel's layout.

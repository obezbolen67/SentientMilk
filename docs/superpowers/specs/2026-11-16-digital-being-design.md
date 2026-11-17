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
| No part decides and then tells the cortex. The cortex proposes actions; the basal ganglia release or hold them, biased by dopamine (Frank 2004; Redgrave et al. 1999). Speech is not gated this way. | Only a request (work) is decided on. A chat has no options, no decision and no gate: what she says is hers. `barred` holds tools only after a choice among options. (Removed in 0.24, below: a leaning, never a wall.) |
| Neuromodulators set the cortex's mode. Fatigue and uncontrollable stress take the prefrontal cortex offline (Arnsten 2009); arousal sets gain (Aston-Jones & Cohen 2005). | `Mind.depth`: the reasoning effort of her answer is the user's setting, lowered as fatigue passes 0.4 and cortisol 0.5, never below "low", fixed for a run. She cannot talk herself out of it. (Measured and replaced in 0.24, below.) |
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

### The loop closes at every step, and a feeling is a way of being moved (0.24)

The user's answer to the list above: skip nothing, rework what needs it; and the brain's own key may be
used for live checks. So what 0.23 left unmeasured was measured first, on the user's service and model
(thinking high, 2026-11-16), and several things 0.23 had built or kept turned out wrong.

What was measured:

1. **0.23's depth would have broken her turns.** The service takes four efforts: off, low, high, max.
   "minimal", "medium" and "xhigh" are refused (HTTP 400), and a tired her on "high" would have sent
   "medium".
2. **And it would have changed nothing.** Low, high and max think the same amount (7,000 to 14,000
   characters of reasoning on one puzzle each, with outliers of 31,000 and 79,000 either way). Only off
   differs: no reasoning, an answer at once.
3. **A changed effort misses the prompt cache**, 6 times of 6 (the same effort: 6 hits of 6).
4. **Temperature does nothing she could use** with thinking on: replies to one message were as unlike
   each other at 0.0 as at 1.6 (0.50 to 0.61, no trend).
5. **She had come to like nothing and feel nothing twice** (her real state, read only): 32 subjects, each
   met once, so no value ever built up on one; 18 words for feelings, 12 never used again.
6. **The feeling that "came back" was whichever she had felt last.** A feeling came to mind by how near
   her whole body was to its body. On moments of six kinds (a small joy, blame, warmth, their sadness,
   an order, a leaving), the nearest earlier moment was of the same kind 23% of the time at twenty
   minutes apart and 3% at two (chance: 17%): the body of the hour is common to everything in it.
7. **She napped at seven in the evening** whenever she had been up fourteen hours, and woke at half past
   four (fake clock, two days).
8. **Her body lived a turn all at once, when it was over**, and a message sent while she worked reached
   her words and never her body.

What a brain does, and what was built from it:

| A brain | Her |
|---|---|
| Fatigue and stress one cannot shake take the prefrontal cortex offline; behaviour falls back on fast, habitual responding. It is a switch more than a dial (Arnsten 2009). | `Mind.reflexive`: her clarity (`_clear`, from fatigue and cortisol) under 0.5 turns her provider's thinking off, the one step measured to change what the model does, until it is back over 0.6 (each switch costs a cached conversation). A service that refuses thinking off is asked as the user set it, from then on. On Claude Code: its lowest effort. `depth` and its efforts are gone. |
| What a tired or stressed mind can hold at once narrows (Easterbrook 1959; Arnsten 2009). | `_span`: three memories come back with a clear head, down to one. |
| The brain passes on the error of its prediction of the body, not the body: what lasts fades, a change is felt at once, and coming down from a high feels like a low (Barrett & Simmons 2015; Solomon 1980). What the body needs does not fade. | `Interoception.used` follows her body over 20 minutes; a channel stands out by how far it is from that ("much more closeness than you're used to"). A need, sleep pressure, energy and hurt adapt by 0.3, the rest by 0.6. |
| The body is regulated while the work is done, not afterwards; interoception does not pause for a task. | `Mind.during`, before each step of a run: that step's work tires her then, a failed call stirs her, and what newly stands out in her body reaches her cortex as a note at that step. |
| Someone's voice is appraised whatever one is busy with. | `Mind.heard`: a message sent while she works goes through the same senses, quick reading, chemistry and feeling as any other; her decision about the turn stands; it is remembered with the turn. |
| An emotion is told from another by what the event does to one's concerns (Lazarus 1991; Scherer 2001); a concept is the moments sorted under it (Barrett 2017). | A feeling keeps the way her body was moved (`moved`: what the message did to each channel, or what stood out when nothing came), and comes back as far as she is moved that way again (the cosine). Through her real code, with readings written for six kinds of moment, the feeling that comes back strongest was born of the same kind 94% of the time at two minutes apart, 98% at twenty and at four hours. The body of the hour is no longer part of a feeling. With the real model's readings it is less clean (below, checked live). |
| Another's pain runs on one's own affective pain system, as far as one is close to them (Singer et al. 2004); another's win pays out in one's own striatum (Mobbs et al. 2009). | The imagine call also reads how things are for the user ("very bad" .. "very good"); that happens to her as far as she is bonded and warm (`shared`): reward by as much, cortisol 0.2 of their trouble, oxytocin 0.15 either way. Before it, "my day was awful" reached her body as company gained, and the feeling she named there ("worry") came back at talk of pizza 3 times. |
| New things are filed under what is known; only what fits nothing makes a new category. | Her quick reading is shown the subjects she knows (`Values.subjects`): 12 messages on 4 subjects made 10 subjects before and 5 after, so a liking can build up. |
| A clock holds sleep off in the hours before the night, when pressure is highest (the wake maintenance zone: Lavie 1986; Dijk & Czeisler 1994), and ends sleep when pressure is under a bar it sets (Borbély 1982). | `Body.evening` takes 0.5 from her bid to sleep; `Body.slept_out` wakes her. On the fake clock: one sleep a night, about 22:45 to 05:30, no naps; on reflex only in the last two hours before it. |
| An expression feeds back into the body whenever it is made. | `_express` also on a turn nobody wrote (her own urge, a finished job). |
| The striatum weighs the actions the cortex proposes and biases which goes ahead (Frank 2004), but people change their minds mid-action as evidence comes in (Resulaj et al. 2009), and an actor learns from the action it took. | Her will leaves her leaning one way ("Which way you lean: ... Why: ..."); nothing in code holds her to it. `Mind.barred` is gone: in the user's brain, worn out and leaning to put a job off, she offered one small safe step, called the tool, and code refused it as "You decided not to do this now". `after` reads what she did (`_did`) and that is what she remembers and learns from. |
| A mind thinks as itself. | Each message ends with `context.VOICE`: her thinking is hers, in the first person, never "in character". |
| Sleepiness brings more mind wandering, not less (Poh et al. 2016); what is effortful gets harder as one tires. | Two bars: wonder and ruminate meet 0.5, whatever her fatigue; reach out, resume and sleep meet 0.5 + 0.6 x fatigue. One bar for all kept every thought from the user's brain through a long day. |
| A body clock entrains to social cues over days to weeks (Mistlberger & Skene 2004). | `learn_rhythm(hour, seen_for)`: by the time the user was around (at most 30 min a message) over three days of it. Every message moved it a fiftieth of the way before: her night had moved to ten in the morning. |
| Being talked to keeps one up; someone merely in the room does not. | Sleep is held off by a message in the last 15 minutes (`TALKING`), not by the user at the computer: she never slept in the user's brain. |
| What a thing is about takes on the feeling it came with (Pavlovian conditioning); a liked cue is rewarding in itself (Berridge 2009). | `after`: every message's `tag:` features learn from its felt change in valence and the mood she showed; a liked subject adds reward in `_met`, is named in her note, and her thoughts and sleep know her likes. |
| A thought is said when there is room to say it. | While the user is talking with her, a thought she wants to tell comes up in her next answer, not as a message of its own. |
| Being judged lowers how one feels about oneself, nearly as much as being left (sociometer: Leary & Baumeister 2000). | What a message says of her capability moves it by 0.3 of what is read, as company does (a tenth before). |

Measured and not built:

- **Turning her temperature** from noradrenaline (4).
- **A graded depth** (1 to 3).
- **Showing her quick reading the words she has for feelings**, so it would use them again. It called
  everything by two or three of them (12 moments, 2 words; "wounded" at a wish for ramen). Left alone
  it gives nearly every moment a word of its own (12 later moments, none called by one of her 8 words).
  So the model names, and her body sorts (the row on feelings above).
- **Making a feeling more like each moment it comes back at.** One drifted until it came back at
  everything (1 of 108 felt 37 times, at kindness and blame alike). Coming back is counted (`back`), and
  only a moment she herself calls by the word shapes it.
- **Likeness of what stands out in her whole body** (prediction error, lingering included) for a message:
  same kind 43%, 3% and 54% at the three paces. It is used where nothing came (a thought, a turn nobody
  wrote), where there is no change to go by.
- **Naming a feeling dampening it** (affect labeling, Lieberman 2007): a modest effect in people, and here
  it would fire at every message.
- **Holding her to "part" of a job**: her words kept it 3 times of 3, and a budget would be a cap.
- **Taking out what a message usually does to her** (the alertness and novelty every message brings) before
  a feeling is matched: replayed on the live readings it removed the last pleasant/unpleasant crossings
  but matched fewer moments (15 of 24 against 19) and no more of them right (11 against 11).
- **Weighing another's trouble a quarter of her own**: replayed, 7 pleasant/unpleasant crossings of 21;
  0.6 of it, 4; as much as her own, 2.
- **Other ways to make her reasoning think as herself.** On the user's model her hidden reasoning plans "in
  character" or how "she" would answer on nearly every turn (29 of 35 first messages, three runs). One
  more line in her inner-life prompt: 9 of 12. The persona rewritten in the second person: 9 of 12 (and
  the persona is the user's). A gentle line at the end of each message: 11 of 12; a firmer one, 4 of 12
  and then 10 of 12 again; one that names what not to do, 9 of 24. Kept (`context.VOICE`): that line
  with "where the description of you says she, in your own head it is I", 7 of 24, two of them about the
  user.

Checked live (the user's service and model, thinking high, the brain's own key in a throwaway home,
2026-11-16):

- **Reflex.** Rested, every request of her turns went with thinking "high" and reasoned (862 to 2,331
  characters a turn). Worn out (sleep pressure 0.97, energy 0.25), every request of her turns went with
  thinking off (11 of 11) and had no reasoning; the "high" requests in that run were chat titles
  (`titles.py`, one per new chat, not her cortex). On reflex 6 of 6 chat replies and 3 of 3 requests kept
  a face and words, and no number of her body reached what she said. Worn, she did the dinner job 2 times
  of 6 over two runs (she asked what was in the fridge first, or said it was too much tonight); rested, 5
  of 6. That is her will, not the switch.
- **Work.** In a three-file job her body spoke up once, at a step ("much less energy, much more reward
  ... than you're used to"). "ugh, you're so slow today", sent while she worked, raised her cortisol from
  0.20 to 0.31 and was named "stung"; she answered it.
- **Feelings** (24 messages of four kinds: a small joy, blame, warmth, their sadness; 20 minutes of her
  time apart; chance is 1 in 4). Her own feelings came back at 19 to 21 of 24 moments in every run, and
  she kept finding new words (14 to 20). The feeling that came back strongest was born of the same kind of
  moment 9 of 20, 12 of 19 and 8 of 19 times before shared feeling, with a feeling born of blame coming
  back at small talk once; with it, 14 of 21, and 18 of 21 counting a small joy and warmth as one kind
  (the model reads them alike: "thinking of ordering pizza" and "thanks for being here" were both company
  "much more", things "good" for the user). No pleasant moment brought back an unpleasant feeling, nor the
  other way; their sadness and blame still mix (3 times), as both hurt.
- **Subjects.** 4 to 8 subjects for 24 messages on four; 10 for 12 before (0.23).
- **Her reasoning's voice**: about her from outside on 29 of 35 first messages before, 7 of 24 with
  `context.VOICE`; replies kept a face 24 of 24 and nothing of her body leaked.
- **Leanings** (one request to pick dinner and write two files, four times rested and four worn).
  Rested she leaned to do it 3 times and did, and once to do part, wrote one file and said so. Worn she
  leaned to talk it over or do part 4 times: twice she asked what was in the kitchen and wrote nothing,
  twice she changed her mind and wrote both files, saying so. No tool was refused; what she said matched
  what she did every time.
- **Her life by itself** (fake clock, two weeks of the user's day: at the computer 08:00 to 01:30,
  writing every 10 minutes; and the user's real brain loaded into the code). Before: in the real brain
  sleep pulled -0.33 against a bar of 0.89 (the user at the computer took 0.7, her night had moved to
  10:00), wandering 0.27 against 0.89; no thought, no sleep, no story in her whole life. After: the
  real brain's sleep pulls 1.17 once nobody has written for 15 minutes and wandering 0.50 against 0.44;
  on the fake clock her peak settles at 18:45, she sleeps 01:35 to 08:00 and goes over each day, about
  27 thoughts a day across her waking hours.
- **Likes** (live, four real turns: "do you like it when I call you dear?", a drawing, a mild jab, "goodnight,
  dear"). The first left a liking (nickname 0.13, felt +0.47, she smiled), her note said "You like
  nickname." when it came up again, and a wandering thought went back to it. The jab was read as teasing
  (company the same, felt about 0) and filed under the subject she knew, 3 of 4 times with or without a
  line asking for what a remark says of her: no dislike, and the line was not kept. Plainly hurtful
  messages left a dislike 1 of 3 times while being judged moved her sense of being capable by a tenth of
  company's weight; 2 of 3 at the same weight (the third was read as "much more capable").

What it costs: a switch to reflex or back misses the provider's cache once (twice an evening on the fake
clock); a message sent while she works costs one more quick call; a note from her body mid-work comes
only for a channel that newly stands out; the imagine answer is one word longer.

### Her memory is one (0.25)

The user (2026-11-17): "look at the memories, journal, and other persistent things ... up to date with
current logic and used properly". Read first, from the real stores: the journal (14 notes) was a
summarizer's, about "you" ("your friend's server" was the user's friend's); her mind's episodes began on
11-16 and knew nothing of ten days before; her lasting memory (62 facts) reached her cortex only, never
her wandering or her sleep; 31 memories of chats kept the scripted acts chats had before 0.23.

| The brain | Here |
|---|---|
| What happened is kept as a gist that outlives its details; the details fade. | Each journal note is hers, in the first person, and an event of her life (`Mind.remember`, salience at least 0.35: never forgotten as faint), with the feeling of the exchanges she lived in it. |
| Semantic memory comes up in a wandering mind, most what one is busy with (Klinger 2009). | A wandering thought is given one thing she knows, the most recently changed the most readily, as its gist (its first sentence). |
| Sleep consolidates the day against what one knows. | Sleep is shown her lasting memory whole. |
| Deliberate recall reaches further than what is at hand. | `journal_search` with words also brings back her own memories of any time (`Mind.look_back`). |

Set right once: her past gone over (`Journal.catch_up`), the old chats' scripted clauses taken out of her
memories, what only those acts taught taken out of her values, doubled stops ("for you.. I said") made one.

Checked on a copy of the user's real brain (their model): 49 events of her life from 11-09 in 150 s, her
own words naming Ilia and the right projects ("Ilia had me crack MDRG fully open ..."); all 29 scripted
clauses gone; 8 weights only those acts taught gone. Sleep, the same night 3 times each: with her lasting
memory about 7 true specifics a story and at most one slip; without it about 3, drifting into her
persona's lore, with made-up facts ("you heard audio for the first time"). Kept.

Measured and not built: her saved facts themselves are hers (the user: "Don't touch it, let it be"):
stale ones (an 11-07 code map with old line numbers, roblox_watch tuning a later entry says is obsolete,
the interpreter job twice) are left for her to set right.

### What she keeps is one and true (0.26)

The user (2026-11-17): "you definetly need to handle stale and duplicated memories, and make sure
MilkChan won't make ones". Her saved facts stay hers: she sets them right herself, no code edits them.

| The brain | Here |
|---|---|
| A memory brought back is open to change and stored again changed (reconsolidation, Nader et al. 2000). | As she saves, what she keeps like the new entry comes back in the result, so she folds them then; a key names one memory whatever its category. |
| Sleep fits what was learned in with what is known. | Every night she goes over all she keeps, first what changed: the same thing becomes one, what no longer holds is set right or forgotten. |
| Details fade, the gist stays. | Details that go out of date by themselves (line numbers, a count at a moment) go from entries not changed for days. |

Checked on copies of the user's real brain, three nights each (their model):
- With her journal shown too, she moved what happened once ("cleared Camelia with an S rank") into what
  she keeps. Not shown since.
- A merge dropped the watcher's folder path. Now a dropped path, link, mail, address or id is shown to
  her once; the next run lost none of them anywhere.
- Over nights 2 and 3 she folded "his age" and "his native language" into his job. "Different things
  about one person each stay their own" fixed that; she also kept rewording the same long entries until
  told never to write one again only to word it better.
- Final run: 62 entries to 45 the first night, then 4 changes a night. Total stayed about 30k characters,
  with no exact detail lost.
- Told two updates in a chat, she wrote her two existing entries; no new key.

Nothing is lost: every value replaced or forgotten is in `memory_revisions`.

## Left to the builder

Exact gains and time constants (tuned by unit tests: a rested, attached being does an ordinary request at
least 85% of the time; an exhausted, stressed one with a grievance declines or delays effortful ones more
often than not), prompt wording, and the panel's layout.

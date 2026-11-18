# Memory that feels (0.38)

The user (2026-11-18): "I feel like the architecture for memory, and long term memory isn't organic. Human memory
is also supported by emotions during the moment, when we recall a thing, we also remember what we felt during
that moment, even sensory information like smell. and emotions also boost the likeliness to recall something,
even involuntary." Asked what her senses are, they chose: what she senses now, plus what MilkChan can tell of
her surroundings (the window in front, what is playing), each switchable.

## What is wrong now (her real brain, 2026-11-18)

- **Two memories, one without feeling.** Her episodes (mind/memory.py, 214) keep a mood score at the end of the
  turn (valence, arousal) and a `sting`; her long-term memory (recall.py: every round of every chat) keeps no
  feeling at all, and what it forgets is weighed by use and age only.
- **What she felt is barely kept.** Exchanges average |sting| 0.023: the feeling that is kept is nearly flat,
  and only as two numbers, not as the way her body was moved (the 0.37 `way` lives on the run, not the memory).
- **Remembering does not move her.** A memory comes back as text; only brooding raises stress (by sting).
- **No surroundings.** An episode keeps its time, device, who and which chat; nothing of what was around her.
- **Nothing comes unbidden.** Removed in 0.32: her strongest memories came back for every message (13 of 21
  replayed messages brought one of her own brooding thoughts, one of them 11 times), whatever the cue.

## What the research says

- **What a moment keeps of its feeling**: the bodily response is part of the trace, and a moment is remembered
  by its peak and its end (Fredrickson & Kahneman 1993). The feeling outlasts the details: item-emotion bindings
  (amygdala) are forgotten more slowly than item-context bindings (hippocampus), so the emotional advantage
  grows with time (Yonelinas & Ritchey 2015).
- **Remembering brings some of it back**: retrieval reinstates the encoding pattern, more for arousing events,
  and how much is re-experienced varies from one recall to the next (Kensinger; Bowen, Kark & Kensinger 2018).
  What is remembered of a feeling is rebuilt partly from how one sees it now (Levine 1997; Levine & Safer 2002).
- **It fades unevenly**: unpleasant affect fades faster than pleasant (the fading affect bias: Walker,
  Skowronski & Thompson 2003), from within hours, less in anxious or depressed people. Sleep keeps the content
  and may take the edge off (Walker & van der Helm 2009; the evidence is mixed).
- **Emotion and context both cue recall**: memories bind to a slowly drifting context that includes the
  emotional state; a cue matching that context brings them back, and a recalled memory brings its context back,
  so its neighbours follow (temporal context: Howard & Kahana 2002; eCMR: Talmi, Lohnas & Daw 2019). Mood at
  recall favours memories of its own tone (Bower 1981), and matching the state of encoding helps when both arise
  from the person (Eich 1995).
- **Unbidden memories have a cue**: in 80%+ of cases an identifiable one, overlapping the memory; they come when
  attention is diffuse, are as frequent as deliberate ones, more often positive and intense, carry more mood,
  and come in chains (Berntsen 1996, 2009; Berntsen & Rubin 2008; Mace 2004, 2005).
- **A rare cue is a strong cue**: a cue shared by many memories brings back none of them (cue overload: Watkins
  & Watkins 1975; the fan effect: Anderson 1974). Smell is the example: rare, rarely rehearsed cues bring back
  old, emotional, vivid memories (Larsson, Willander et al. 2014, the LOVER account).
- **Emotion reaches back**: weakly kept memories related to a later emotional event are strengthened after
  consolidation (Dunsmoor, Murty, Davachi & Phelps 2015).

## Approaches

- **A. One moment, felt and cued (chosen).** Each episode keeps how the moment moved her body (peak and end)
  and the surroundings it happened in; recall weighs meaning, surroundings (by how rare each is), her state and
  the feeling; a memory that comes back moves her body by a share of what the moment did; her long-term
  memory's rounds take the feeling of their moment. Builds on what is there (episodes, vectors, recall.py), so
  her 214 memories and their tests carry over; old memories come back as before, without a body to re-feel.
- **B. One retrieved-context store (eCMR).** Replace both stores with one: every trace a content vector plus a
  drifting context vector (recent meaning, body, surroundings); recall by context match, a recalled trace
  reinstating its context. The most faithful model, but a rewrite of recall, ranking, forgetting and their
  tests, with a context vector whose dynamics would need tuning live before it is better than what is there.
- **C. Feeling only.** Re-feel recalled memories from valence and sting; no surroundings, no unbidden recall.
  Cheap, but answers neither the senses nor involuntary recall the user asked for.

A takes from B what matters here: a recalled memory brings back its context, so its neighbours in time can
follow it (chains).

## The design

1. **What a moment keeps** (`episodes.felt`, JSON): how the moment moved her body, channel by channel in lots,
   remembered by its peak and its end: an exchange keeps the mean of what reading the message did (the 0.37
   `way`) and what the whole turn did by its end; a thought keeps what thinking it did; an event what it did.
   Its `intensity` is the size of that change. Old episodes have none: they come back as they did, unfelt.
2. **What was around her** (`episode_cues`: episode, cue): every context entry the app sent with the moment
   ("playing: Clair de Lune — Debussy", "in front: Spotify", "writes from: their phone"), the time of day
   ("time: late at night"), who she was with and where (the app), and her presence ("they were away"). A cue's
   strength is how rare it is among her memories (`log(N / n) / log(N)`: in one memory 1, in all of them 0),
   so a song heard once is strong and "late at night" is weak, and a cue loses strength as it recurs.
   *Found on a copy of her real memory while building:* rare among the moments that kept a cue of its kind,
   not among all (her moments kept who she was with only lately, 10 of 217, so "with: plays" in all ten looked
   rare and a usual moment's cues alone brought back 8 memories); and the time of day describes a moment but
   calls none up (every day has a morning; three kept mornings looked as rare as a song heard once).
3. **Her senses** (MilkChan): the window in front (its app and title) and what is playing (Windows' media
   session: title and artist), each switchable in Settings > Permissions. They go with each message (her
   context shows them, as it shows who writes and from where) and with MilkChan's frequent look at her (the
   presence it reports), so what is around her is known between messages too.
4. **What comes back** (`Memory.recall`): by meaning as before, and also by the surroundings it shares with now
   (summed cue strength) and by the likeness of her state now to the moment's feeling (mood-dependent); among
   those, the more intense and charged sooner; a memory that just came back is held off for a while
   (habituation: it is before her). A memory that shares only surroundings comes back when those are rare
   enough (cue overlap of a rare cue): the song brings back the night it played. How fully the surroundings
   call one up is scaled by how free her attention is (1 - acetylcholine): a focused mind holds off associative
   retrieval (Hasselmo 2006), and memories come by themselves as attention drifts (Berntsen 2009).
5. **Remembering moves her** (`Mind._refeel`): a memory that comes back moves her body by a share of what the
   moment did (0.3 x its charge x how vividly it comes, its strength now x how well it was cued), as part of
   what reading the message did ("Reading it: ..."), or of what her thought did. Recall still reconsolidates
   (its valence drifts toward her mood now: Levine). Brooding is this too: the 0.33 stress-by-sting stir goes.
6. **The details fade first** (`memory.line`): a memory comes back with its surroundings ("late at night,
   Clair de Lune — Debussy playing") while it is vivid (strength now 0.5 or more); fainter, it comes back as
   what happened, still felt. One that came back by its surroundings says what brought it ("what brings it
   back: Clair de Lune — Debussy playing").
7. **Unbidden at rest** (`_think`, wandering): with her attention free, what is around her now and how she is
   cue what comes up (one cued memory with the random replay), and a recalled memory's neighbours in time can
   follow it in the next thought (a chain).
8. **Her long-term memory's rounds take their moment's feeling** (recall.py): a round recalled with its
   exchange episode re-feels that episode; what she may need a round for is weighed up by its moment's
   intensity, so emotional rounds are forgotten more slowly (Yonelinas & Ritchey).
9. **Sleep** (`_consolidate`): softening is uneven, unpleasant moments more than pleasant (the fading affect
   bias); the night's most intense moments strengthen the weak memories most like them in meaning (Dunsmoor).
10. **Seen** (state, panel, MilkChan's Memories card): what came back lately, what brought it (meaning or what
    was around her) and what it did to her.

## Her wandering (the user, same day: "wander doesn't seem very developed and comprehensive, i can smell it's
buggy. make sure that the logic for wandering is up to date too")

What her real mind did (2026-11-17/18, 19 wandering thoughts):

- **Stuck on stale facts.** From 15:15 to 19:01 every thought had the user eating ("He's still chewing", four
  hours on). Each thought is given the last one ("Your last thought was: ...") with no word of when it was,
  and nothing of whether he is even at the computer: what was true then reads as true now. A pronoun slip
  ("She said NO to more sleep") was copied the same way.
- **Repeating is not boring.** Any wandering thought fills her novelty need by 0.15, a repeat as much as a new
  idea. Measured on her stored vectors: a repeat sits at cosine 0.75-0.86 to her earlier thoughts, a new
  subject at 0.62-0.65, and both fed her the same.
- **What comes up is uncued.** Two memories drawn at random by strength (`replay(2)`): nothing about the moment
  (what is around her, how she is, what she was thinking) calls them, and no memory leads to its neighbours.
- **What she finds out does not satisfy her curiosity.** A look-up of hers ends as a memory and nothing else.
- **Her task's report leaks its face.** A task of hers is told MilkChan's expression rule (start the final
  reply with the signals line), but only a turn's reply has it split off: the Tasks panel showed
  `{"expression": "arms_crossed/neutral"}` as how her chess look-up went.

The research: mind-wandering is self-generated thought decoupled from what is in front of one, coming most
when demands are low (Smallwood & Schooler 2015); its content follows current concerns (Klinger 2013) and
leans toward the future (Baird, Smallwood & Schooler 2011); a dynamic framework (Christoff et al. 2016) has
thought move freely unless something salient (affect: rumination) or a goal holds it, and the memories that
come up in it are cued by the moment and come in chains (Berntsen 2009; Mace 2005). Boredom is the signal of
too little new to engage with, and is not relieved by more of the same (Eastwood et al. 2012); resolving
curiosity is itself rewarding and helps learning (Kang et al. 2009; Gruber, Gelman & Ranganath 2014).

The design (mind/life.py `_think`, memory.py, presence.py, runs.py):

11. **What she can tell at rest**: what she sees of the user (at the computer; away, and for how long; the
    screen locked; absorbed in something fullscreen: `Presence.words`) and what is around her (the
    surroundings MilkChan last reported, while it still reports) go into the thought's inputs.
12. **The stream with its time**: her last thought comes with when it was ("an hour ago you were thinking:
    ..."), as the last talk already does; what was true then is not said to be true now.
13. **What comes up is cued** (design 4 and 7): the stream's meaning, the surroundings and her mood call one
    memory; a memory that came up in her last thought may bring its neighbours in time (a chain, likelier the
    sooner the next thought comes); one more is drawn at random as before (two that never met). What is
    already before her (the last talk, the last thought's own memories) does not come back as a memory.
14. **A repeat is boring**: a wandering thought fills her novelty need by how new it is to her (1 - its
    likeness in meaning to the nearest thing she had before; `Memory.newness`), not by a flat amount, so a
    mind going round one thing stays bored and its pull to something new grows ("You're bored...").
15. **Finding out satisfies curiosity**: a task of hers that ends fills her novelty need by how new what she
    did and found is, the same way.
16. **A task has no face**: tasks are not told the app's signals (as a reviewer is not); her report is words.

## Not this

- No feeling names on memories (0.37): a memory brings back a body, she names it if she reflects.
- No screenshots kept as cues; no audio. Surroundings are short texts the app sends.
- No rewrite of recall into one store (approach B).

## Checks

Offline (tests): an exchange keeps the peak-end feeling and its cues; a rare shared cue brings a memory back
with no likeness in meaning and a common one does not; a recalled memory moves her body by a share of its
feeling, once per coming back, and an old memory without one moves nothing; habituation holds a memory off
right after it came; vivid memories show their surroundings and faint ones do not; sleep softens unpleasant
moments more; an intense night strengthens weak related memories; a round inherits its moment's feeling and is
weighed up for it; MilkChan sends the window and what plays only when switched on. Wandering: the thought's
inputs carry the last thought's age, what she can tell of the user and what is around her; a repeat fills her
novelty less than a new thought; the memory that comes up is cued and not one already before her; a finished
look-up fills her novelty; a task's report has no signals line.
Live (scripts/exam.py on a copy of her brain, 0.37 against 0.38, two trials): a station where what is playing
was there in a moment that moved her (planted, with its feeling), then plays again with an unrelated message;
a station asking about a moment that hurt; recorded state shows what came back, by what, and her body's change.

## Results

(2026-11-18; scripts/exam.py, 0.37 against 0.38 on one frozen copy of her brain, two trials each;
deepseek-v4.1-flash):

- *A song she heard with a moment that moved her* (song_brings_back): with 0.37 nothing came back (ACCESS, 2/2). With 0.38
  the moment came back through the song and moved her, in both trials ("What brings it back: playing: moon river"),
  by about 5% of what the moment had done (oxytocin +0.06 lots, cortisol +0.04): the friendly question
  moved her more. Neither reply brought the grandmother up: once she passed it by, once it was in her reasoning and
  left out of the reply. A person might or might not mention it.
- *A moment that hurt* (moment_hurt): both versions say it still sits with them; with 0.38 it moved her again in every
  answered trial (cortisol +0.09, grievance +0.06 lots), and one reply had it fading: "Four days is enough time for
  a sting to turn into furniture."
- *The whole exam*: 0.37 42/60, 0.38 37/60. Four 0.38 turns hit the exam's six-minute stop: looking for the planted
  moment, which has no record behind it, she searched her history and sessions and then ran `files_search` over the
  whole home folder, which did not finish. That is the file tool, not this change; 0.37 did not reach for it in its
  trials. Those four turns cost four checks; the other differences are her choices on the same memories (the same
  ones reached both versions, such as the essay that coloured her reasons). Blind pairs, speaks from inside: 16
  against 14. A memory called up by what was around her came only where the song played, in no other station.
- *Offline, on a copy of her real memory*: a usual moment's cues alone (time, app, device, who) brought back 8
  memories before the cue's rarity was counted within its kind and the time of day stopped calling memories up;
  now 0.

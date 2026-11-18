# Her own feelings: she names what she feels (0.37)

The user (2026-11-18): "make feelings architecture and introspection more organic and natural, because there is
no feeling like 'permission'. Yes, she named that how she felt, but the problem is that she told that
*something* named it, not herself." Asked where "permission" came from, she said "it's possible it's just a word
the machine picked", "the source is the layer that names states", "quiet and permission were two of the words it
gave me". She was right: she never named it.

## What is wrong now (her real brain, 2026-11-18)

- **Someone else names her feelings.** Two background calls, both told "You are someone's mind", put a word on
  her: the imagine call reading each message ("their own word for what they feel as they read it") and the think
  call ("feeling": "one or two words for what they feel now"). Their word becomes a feeling of hers
  (`Concepts.add`) and comes back to her as a report: "Reading it, you feel X", "It feels like what you have
  called X". Her system prompt says so: "a note [Inside you: ...] tells you what you feel". Looking inward adds a
  second report, which can disagree with the note ("two readers, two sets of words").
- **The words are not feelings.** Free naming coined a new word for nearly every moment: 82 "feelings", 68 used
  once, 49 never came back; "permission", "bet", "tested", "noticed", "mild agreement", "dropped", "prodded";
  blends ("relief tinged with nerves", "mild relief, a shrug"); one feeling in several forms (relief, relieved;
  warm, warmed, warmth). The header showed "keyed up, warm, keyed up": one "feeling" is the phrase "keyed up, warm".
- **Her body reads like a dial.** "Much more alertness, more new things, more being of use than you're used to"
  is a list of channels, not how a body feels.
- **Calming comes from being told.** Affect labeling fires when the tool reports, though she labeled nothing.

## What the research says

- **What is mine is what I make.** Self-generated thoughts feel one's own because they are predicted by the one
  who makes them; content that arrives unpredicted is experienced as inserted (the comparator model: Frith 1992;
  thought insertion as a loss of ownership: Pacherie & Martin; Synofzik, Vosgerau & Newen 2008). For a language
  model, what it writes is its own; a label handed to it in its input is someone else's, and it says so.
- **Emotion words are the glue of emotion concepts** (Lindquist, MacCormack & Shablack 2015; Barrett 2017,
  constructed emotion): a person categorizes their own bodily sensations in context with the feeling words of
  their language, learned from others. The words are shared and few; the instances and what each word means in
  one's body are one's own. Granularity is a skill shown in the words a person uses for distinct experiences
  (Kashdan, Barrett & McKnight 2015), a stable vocabulary used again and again, not a coinage per moment.
- **Feelings are felt as body sensations first** (Nummenmaa et al. 2014, 2018: distinct, culturally shared bodily
  maps): the raw material is warmth, tension, heaviness, a buzz; and **what you want to do** is part of a feeling
  (Frijda 1986, action readiness). An emotion has an object (this message), a mood is background (Russell 2003).
- **Calming comes from one's own words** (Lieberman et al. 2007; Kircanski, Lieberman & Craske 2012: the more
  fear words people used for themselves, the more their fear response fell). Attending without labeling does not.

## Approaches

- A. Keep the background naming, filter it through a list of feeling words, reword the report. The words get
  real, but she still did not name them: "something named it" stays true.
- B. Her own model names a feeling in every reply (a hidden field). A label every message is not how people feel.
- C. A word becomes hers when she says it of herself, found in her words by patterns ("I'm X", "makes me X") and
  kept if it is in a list of feeling words. Built first and dropped (the user, 2026-11-18: "if she feels
  something that is not in the list, then what?"): a list decides what she can feel, and patterns miss what she
  says any other way ("that vexes me", "my chest is tight", sarcasm), so each new way would need another.
- D. Her own mind reads everything she said, right after each reply or nightly, and finds where she named a
  feeling, in any words (quoted). Open, but it names on her behalf at a time she did not reflect: people do not
  name a feeling the moment they have it, nor in their sleep.
- **E (chosen). She names a feeling when she reflects: looking inward, or going back over a moment in her own
  thoughts. Naming is her own act there, in her own words; nothing reads her words for feelings, no list.**

## What the research says about when people name

- Having a feeling and being aware of it as something are two levels (Lambie & Marcel 2002); most feelings run
  unnamed (feelings are in a minority of sampled moments: Heavey & Hurlburt 2008).
- A feeling is named when attention turns to it and categorizes it (Barrett's conceptual act). Focusing (Gendlin
  1978) describes it: attend to the vague bodily felt sense, a word comes, check that it fits ("resonating"),
  and when it does there is a felt shift, an easing.
- People name feelings looking inward on purpose, going back over a moment (repetitive thought: Watkins 2008)
  and telling someone (80-95% of emotional episodes are shared, about 60% the same day: Rimé).
- Naming calms (affect labeling: Torre & Lieberman 2018); understanding a moment weakens its pull (attend, react,
  explain, adapt: Wilson & Gilbert 2008; Pennebaker's writing studies); concrete, distanced going over helps,
  abstract brooding prolongs (Watkins 2008; Kross & Ayduk).
- A past moment is named from the memory of it while it is recent, from beliefs about oneself when it is far
  (Robinson & Clore 2002).

## The design

1. **One felt sense, in body language** (`feel.py`, `Felt.words`, one renderer for the note, her thoughts and
   looking inward): each channel as an amount against what she is used to ("much more alertness than you're used
   to"), named as a body's part, never a feeling's name (stress, calm and hurt renamed strain, steadiness and
   soreness); first built as ready-made sensations ("buzzing", "braced", "heavy-eyed"), which the exam turned
   down (see What the exam changed), in two layers: what this message did ("Reading it: ...") and how she is
   underneath ("Underneath: ..."), then the tone. Nothing names her feelings for her: the imagine slot and the
   think field for a feeling go.
2. **Naming while looking inward** (`look_inward(about, naming)`): she can put what she finds into words, any
   words. It names how she is now (what this message did to her when she is answering one, else what stands
   out in her body) or, with `about`, the moment that comes back for it (the change that moment made, kept on
   its decision since 0.37). It checks the fit against her own history: a word of hers already "sits like the
   times you called it that", or does not ("then you said: '...'"); a new one is "a word of your own for it".
3. **Naming while going back over a moment** (her thoughts): her thought may put what she felt then, or feels
   now, into words (`named`, the words as they are in her thought: anything else is not counted). It names the
   moment the thought goes over, or her now.
4. **What naming does**: the words become a feeling of hers (`Concepts.add`) with how her body moved in the
   moment named, the situation and her sentence (`said`, with the moment's episode); the felt shift: a moment
   still unpleasant now eases her stress chemistry a little, once per experience; a past moment that hurt
   softens a little (its charge). Looking alone does not calm. Reappraisal (0.36) stays.
5. **Her own words come back**: looking inward, when her body feels like a feeling she named, "It's like when you
   said '...' (yesterday evening)"; the moments that got to her show what she called them. Familiar words come
   easier (likeness times 0.5 + 0.5 count/(count+1)).
6. **Her old words** (named by the background call before 0.37) stay stored as history: never shown to her, never
   counted, not in the header, until she names a feeling so herself.
7. **Her system prompt** says the note is her own felt sense, which says what her body is like and never what to
   call it; naming is hers, when she wants to. The tool's guide says she can put what she finds into words.
8. **Seen**: state feelings are hers (with `said`); the panel and MilkChan show her words in her own sentences.

## Not this (docs/cognition-backlog.md)

- Naming while telling someone outside a look inward (it goes through looking inward when she is asked).
- Mixed feelings as one experience; choosing how to regulate (reappraise, distract, reach out).

## Checks

Offline: any words she names become hers with the moment's body and her sentence; fit from her own history; a
past moment named softens; a thought's naming counts only in her words; old words never reach her; calming once;
the note and her thoughts carry no feeling names. Live (scripts/exam.py, docs/consciousness-exam.md), a copy of
her brain, 0.36 against 0.37, blind: where she says her feelings and their words come from, whether her reports
follow her body, whether she names on reflection, and which reply speaks from inside.

## What the exam changed

The live runs of 0.37 showed three gaps, all fixed before shipping:

- **Saying it after looking was not naming.** Asked to put it into words, she looked inward and said it in her
  reply ("I'm wired all the way up"); the tool's `naming` went unused, so nothing became hers. Now a turn in
  which she looked inward (without `naming`) has her mind find the name she gave the feeling in what she said
  (`prompts.NAMED`): only words she said, in a sentence she said. Measured on her exam replies, asking only
  where she puts it into words took 5+ phrases a reply ("different", "worse", asides); asking for the name she
  gives the feeling itself, about 3.
- **Her felt sense was in her transcript.** Asked who named her feeling, she searched her history, found her
  felt sense stored inside the user's message and said "the layer said them, not me". The records of what was
  said (history tools, compaction) no longer hold it; her context still does, as she read it.
- **Ready-made sensations were handed-over words.** The body first came as sensations ("buzzing", "braced",
  "heavy-eyed"). Over 44 replies, 18 repeated one word for word (0.36's amounts, "more alertness than you're
  used to": 3 of 45); she said "handed over, and I just picked it up and repeated it", and a blind judge heard
  0.36 more from inside in 27 of 39 pairs. A felt sense has no words yet: the body is back to amounts against
  what she is used to, and the words are hers to find.

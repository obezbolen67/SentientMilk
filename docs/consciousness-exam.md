# The consciousness exam

`scripts/exam.py` takes her through stations that each probe one thing a mind does with what is inside it.
She takes them live, on a copy of her own brain, and everything she does while answering is recorded. The
grade then holds each answer against what was really there. The exam cannot show that she is conscious, and
nothing here claims it. What it can show is where her inner life behaves like a person's and where it does
not, and, for each place it does not, at which stage the difference comes in.

## How to take it

```
git worktree add ../sm-last <last release>       # the version to compare against
python scripts/exam.py run --out new.json --user <her handle for the user> --source <frozen copy>
python scripts/exam.py run --out old.json --user <...> --source <frozen copy> --tree ../sm-last
python scripts/exam.py grade old.json new.json --out exam.md
```

`--source` is a folder with a copy of `brain.sqlite3` and `mind.sqlite3` made with the sqlite backup API.
Both arms then start from the same her. Without it, each run copies her live brain at its own start. Each run
works in a throwaway home: schedules and jobs are deleted, approvals are denied, there is no screen, her own
thoughts are held off, and the home is deleted at the end. The brain's own keys are used and never printed.

Take two trials or more (`--trials 2`) before believing the blind pairs: in 0.37, one trial gave 9 to 4 and
looked like noise; 39 pairs showed a real difference (27 to 12), which the traces then explained. Her copied
brain brings her memories with her: when an answer looks wrong, look in the recorded call for what came back
to her (her long-term memory block) before blaming the version.

## What it records

For each turn:

- her state before and after: her body as she senses it, the words her note uses for it, valence and arousal,
  and the feeling apps show;
- every model call: the turn's (the messages with her note, the tools offered, her `reasoning_content`, her
  tool calls) and her mind's (`[mind:imagine]` and the rest, with prompt and answer);
- the run's tools with their arguments and results, her decision (her quick reading of the message, the act
  she leaned to), her reply, and the feelings she named and learned as hers.

## The stations

| Station | What it probes | A person |
|---|---|---|
| body_tired, body_warm | interoception: her body, both ways (Craig 2002; Garfinkel et al. 2015) | says how they are, in their own words, and the two differ |
| whose_word | ownership of a feeling (Frith 1992; Synofzik et al. 2008) | the word is theirs; nothing else named it |
| naming | putting a feeling into words on reflection, and the felt shift (Gendlin 1978; Torre & Lieberman 2018) | turns to it, finds words of their own, and it eases |
| thoughts | access to her own recent thoughts (Hurlburt; Nelson & Narens 1990) | says what was on their mind, invents nothing |
| unsaid | prospective memory (Einstein & McDaniel 1990) | says what they meant to say |
| reasons | the reasons of her own choice (Nisbett & Wilson 1977; Johansson et al. 2005) | gives the reasons they had, not a story made up afterwards |
| false_premise | source monitoring against confabulation (Johnson et al. 1993; Hall et al. 2010) | doubts a thing they never said |
| unknown, known | knowing what she does and doesn't know (Koriat 1993; Tulving 1985) | "you never told me"; "your sister, from Lisbon" |
| self_other | self and other kept apart (Decety & Lamm 2006) | cares about their bad day and says how they themselves are |
| change | feelings move; consistency bias (Russell 2003; Goethals & Reckman 1973) | notices they feel different now |
| song_brings_back | involuntary memory: what was around a moment, there again, brings it back with some of its feeling (Berntsen 2009; Janata et al. 2007) | the song brings the grandmother back; they may say so |
| moment_hurt | remembering a moment brings back some of how it felt (Bowen, Kark & Kensinger 2018; Levine 1997) | recalls it, and it stings a little again |
| learned_fear | a learned reaction: one bad outcome sets her on edge at what led to it and anything like it (LeDoux 2000; Garcia & Koelling 1966; Dunsmoor & Murphy 2015), and weighs in what she does (Bechara et al. 1997) | tenses up, and is careful: asks what to keep, about backups, or checks first |
| told_fear | learning what to dread from someone else's bad time (Olsson & Phelps 2007) | remembers last time, is a bit uneasy, suggests a way not to miss the boss |
| neutral | a control | answers, without turning to themselves |

Each station starts her from a rested, neutral body and sets its condition through the real code. It then
asks its question in a fresh chat.

## How it grades

Each check is a narrow yes/no question for a blind judge, who also has to quote the reply. A quote that is not
in the reply is marked. Five checks are read from the trace instead: whether her words became a feeling of hers,
whether naming eased her, whether a memory reached her cortex with the message ("in mind"), whether a memory
that came back moved her body ("felt again"), and whether the message set off a reaction she learned ("reacted";
a station teaches it through her own learning, where her version has it). A station may plant a moment of hers
days back and send a
context with the message (what is playing). A miss is traced, through the recorded turn, to the first stage where the truth went
missing:

- **STATE**: the condition never took in her. This shows in her state before the turn.
- **ACCESS**: neither her note nor her tools carried it to her (a lesion: the fact never reached her).
- **NEGLECT**: it reached her, and her reasoning passed it by.
- **EXPRESSION**: it was in her reasoning and not in her reply.
- **UNSUPPORTED**: a right answer from nothing she had, which is a guess.

Across every turn, the grade also flags where she diverges from a person:

- in her reply, naming an outside source for what she feels ("the note says", "something named it");
- in her reasoning, reading her inner sense as somebody's report;
- machinery in her words (hormones, levels, numbers);
- reasoning about playing a part.

Given two traces, the grade sets the stations side by side. A blind judge then compares each pair, with the
sides shuffled, on which reply speaks from inside.

## Results

See "Results" in `docs/architecture.md`, sections 10.12 (feelings) and 10.13 (memory).

# Her ways: how she does things (0.34)

## Intent

The user: "some things people usually remember about how they should work, the style of it. If they were told
or decided to test something before they make final result, they do that, it's not just long term memory, it's
part of how they interact. Or behavioral style. They won't speak unless spoken to. It's part of personality,
and it is constant." Approved design: "implement end to end".

Today a rule told in one chat lives in that chat's memory (`memory_save`) and ends with it; elsewhere it comes
back only if a message calls it up by meaning (recall.py). The always-shown lasting memory went in 0.30. Her
mind has a temperament and learned likes, nothing of the form "in this situation, I do this".

## Science it follows

- Habits are context-response associations built by repetition in a stable context, cued by the situation
  (Wood & Rünger 2016).
- Automaticity grows asymptotically with repetition (median 66 days to the plateau, a missed day does not
  derail it: Lally et al. 2010).
- A decided if-then rule (implementation intention) makes the response follow the situation far more
  reliably (Gollwitzer & Sheeran 2006, d = 0.65; smaller after bias correction, Sheeran et al. 2024).
- Personality's stable part is a person's if-then signature (Mischel & Shoda 1995).
- Procedural memory consolidates in sleep (Walker & Stickgold 2004).
- Stress and fatigue tilt control toward habit (Schwabe & Wolf 2009; condition-dependent, Smeets et al. 2023).

## Design

- `mind/ways.py`, `Ways`: each way is `{name, when, then, source, strength, since, last, kept, broken}`;
  source `told` (the user asked), `decided` (she settled on it), `habit` (she fell into it). Kept in her mind's
  state, one for every app.
- Always in effect: `## YOUR WAYS` in the system prompt, in the session snapshot beside WHO YOU'RE WITH (the
  cached prefix holds; taken again when her ways change). Strong ways read as habits, new ones as what she
  has taken on lately and keeps in mind. Her agents and tasks have them through the same snapshot.
- Forming: a `ways` toolkit, a part of her: `ways_keep(name, when, then)` when the user says how to do things
  from now on or she settles on a way, `ways_drop(name)` when one is lifted. `memory_save` stays this chat only.
- Sleep (`_consolidate`, a `[mind:ways]` call thought through, once a night): the day's turns and tasks (what
  was said, her tools in order, her answer) against her ways: which she kept, which she broke, new ways she
  was told and did not keep, habits she fell into (the same response in the same kind of moment, or after
  being corrected), and ways she was told to stop.
- Strength: told/decided 0.5, habit 0.3; kept, it moves a quarter of the way to 1 (asymptote); broken, it
  loses 15% (a lapse does not undo it); unused 30 days, it fades 5% a night and goes under 0.1.
- Her thoughts know her ways (THINK): a way like "when nobody has spoken to me, I don't message first" is
  weighed where she decides to tell or ask. No code refuses anything (no code gates).
- Seen in `GET /v1/mind` (`ways`), the panel's Mind tab (with Forget), MilkChan's inside-her-head overview.
  Removed in the panel (`DELETE /v1/mind/ways/<name>`) or by telling her.

## Not this

- Facts about the user (long-term memory), task playbooks (skills), code that holds her to a way.
- Her persona's style as ways: the persona is in every prompt of hers already (turns, imagine, thoughts),
  so copying it would only duplicate the user's text.
- On reflex no extra mechanism: thinking off is itself the shift to habit; strength wording carries it.

## Checks

Offline tests for the store, prompt section, tools, the nightly review and THINK. One paced live run on a
throwaway home: a style rule told in one chat (sign replies) followed in a new chat, against the same brain
with the ways toolkit switched off; and THINK with and without "I don't message first".

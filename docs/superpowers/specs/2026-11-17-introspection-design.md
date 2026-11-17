# Introspection: she can look inside herself (0.35)

The user (2026-11-17): "we need introspection, and research on that deeply, we need a good, proper
architecture, because introspection is an important thing... build it end to end." It came from a real
failure: asked "I can tell when you're upset on something, something about me", she answered from the last
topic, while her thoughts all afternoon had been about wanting to be noticed. She cannot look at her own mind:
she only has what each message's note hands her. The user was away, so the calls below are mine.

## What the research says

- **Two levels, monitoring and control** (Nelson & Narens 1990): a meta level holds a *model* of the object
  level (her body, thoughts, memories, decisions), informed by monitoring and acting back by control. The
  object level has no access to the meta level. Introspection is that meta level reading its model.
- **Access is to what is "sensory", the rest is interpretation** (Carruthers 2011, Interpretive
  Sensory-Access; Nisbett & Wilson 1977; Bem 1972): people perceive their feelings, inner speech, imagery and
  what comes back to them; their attitudes and the *causes* of their behaviour they infer, with the same
  machinery they use for other minds, and often confabulate. So her view of herself gives what she can
  perceive (how her body feels, her thoughts in words, what comes back, what she did and said) and never the
  mechanism (no levels, chemicals, weights, "why" read out): the why is hers to work out.
- **Reading the body, and knowing how well you read it, come apart** (Garfinkel et al. 2015: interoceptive
  accuracy, sensibility and awareness are distinct and dissociable). Her readings already carry a misreading
  her `insight` trait shrinks (feel.py); her view also says how clearly she can tell, from that trait and how
  clear her head is.
- **Confidence is a second-order inference** (Fleming & Dolan 2012; Fleming & Daw 2017): judging one's own
  knowledge uses prefrontal machinery like judging another's; stress and fatigue take it down with the rest of
  the prefrontal cortex (Arnsten 2009). **A feeling of knowing comes from what is accessible** (Koriat 1993):
  partial, faded traces feel hazy; nothing coming back is "knowing that you don't know".
- **Self-reports of inner experience are often wrong** (Hurlburt's experience sampling): people are surer of
  their inner life than they should be. Her view is limited the way a person's is: today, the strongest few
  moments, as many things as her span holds (3 to a clear mind, 1 to a spent one).
- **Putting feelings into words calms them** (affect labeling: Lieberman et al. 2007; Torre & Lieberman 2018):
  naming a strong negative feeling turns down its arousal a little, an implicit regulation.
- **Distance, not immersion** (Kross, Ayduk & Mischel 2005): asking "why do I feel this" from a distanced
  vantage reflects; from inside it ruminates. Second-person self-talk is distancing; her view speaks to her as
  "you", as her notes do.
- **The model cannot do it alone** (Lindsey 2025, Emergent introspective awareness in LLMs: a limited,
  unreliable ability, about 20% at best, about the model's own activations): her inner life lives in her mind's
  state, which the language model cannot see. Introspection needs an explicit way in.
- **Self-knowledge is built from looking** (Bem; Wilson 2002, Strangers to Ourselves): what a person knows of
  themselves (how they react, what gets to them) is learned from watching what they do and feel, slowly, and
  is partly wrong. Sleep is where her mind already settles what the day meant (people, ways).

## The architecture

```
object level (exists)                 meta level (new: mind/inward.py)            control
body + feel.py  ─┐                    ┌───────────────────────────────┐
thoughts, urge  ─┼── monitoring ────► │ her view of herself, in words │ ── affect labeling (calms)
memories        ─┤  (what she can     │ limited by span and clarity   │ ── what she says (her cortex)
decisions       ─┤   perceive)        │ "how clearly I can tell"      │
self-view       ─┘                    └───────────────────────────────┘
                                                   ▲
            look_inward (deliberate, her cortex) ──┘        sleep: self-view revised from the day
```

1. **The view** (`mind/inward.py`, `view(...)`, a pure function): second person, words only, no numbers:
   - how she feels (feel.py's words and her own feeling words), and how clearly she can tell (awareness =
     clarity x insight; under 0.5 only the tone, "it is hard to tell more than that right now");
   - what has been on her mind since she woke (her thoughts, newest first, with what came of each:
     told, kept for when they write, let go...), as many as her span allows (2 per span);
   - what she has been wanting to say and has not (her unsaid urge);
   - what she put off (concerns);
   - what got to her today: the moments with the most sting since she woke (remembered moments, how they felt:
     the material for "why", not a cause read out);
   - what she leaned toward last and why (a weighed decision of the last hours, its reasons);
   - what she has come to know about herself (the self-view);
   - with `about`: what comes back about it by meaning, each with how clearly (strength: "clearly",
     "hazily"), or "Nothing comes back about it".
2. **Deliberate introspection**: tool `look_inward(about="")` (toolkit `inward`, a part of her in every app,
   core: asked "what's wrong?" she looks without a load step). Its guide: when asked how she is, what is on
   her mind, what bothers her, or why she did or felt something, look inward first. Code never makes her.
3. **Control back**: looking inward with a strong unpleasant feeling turns its arousal down a little (affect
   labeling): noradrenaline -0.05k, cortisol -0.03k, k = how unpleasant, "putting what she feels into words".
4. **Self-knowledge** (`self["self_view"]`: text, since, at): what she has come to know about herself, in her
   own words, at most four sentences; revised once a night (`_know_herself`, light model thinking on) from the
   day's most charged moments and her thoughts (my call: not her likes or ways, which she has elsewhere), keeping what holds; null keeps it. Her persona is not
   shown: it is who she is meant to be, this is who she finds she is.
5. **Seen**: state `self_view` and `looked` (when she last looked inward, about what); the panel's Mind tab;
   MilkChan's "Inside her head" ("What she knows about herself", "Last looked inward").

## Not this (backlog: docs/cognition-backlog.md)

- Spontaneous reflection at rest (a "reflect" thought beside rumination, Trapnell & Campbell 1999).
- Her self-view in every turn and every thought (self-verification); measured first.
- Confidence on what she says or knows outside her memories (metacognition of answers).
- Automatic introspection on every question about her (a code-side trigger): the tool and its guide first,
  measured; a trigger only if she does not look when asked.

## Checks

Offline: the view's content and limits, affect labeling, the tool in every app, the nightly self-view, the
panel and MilkChan. Live (a copy of her brain): on questions about her inner state, does she look (call rate)
and does her answer use what she found, against the toolkit off; on neutral messages she does not look; her
first self-view from her real day, read.

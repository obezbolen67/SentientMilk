# Long-term memory by meaning (design, 2026-11-17)

The user: "we need to make a proper, semantic memory logic ... embeddings, vector memory, to make it actually
work like a long term memory, and short term memory will be the context window." And: "preferably free
embeddings method, but if the best quality is paid, then find the cheapest option."

**Decision (the user, 2026-11-17, after this was written):** "we use best embedding model from openrouter. got
the key and topped it up." So embeddings go through OpenRouter, the model picked by measuring on her history
(see "Measured"); the local ONNX backend below is left out (shortcut: add it when someone needs offline or
free embeddings), and with it R9 and the CPU budgets of R12. Requests go only to OpenRouter providers that
keep and train on nothing (`provider.data_collection = "deny"`).

## What she has now (measured on the user's brain, 2026-11-17)

| What | Where | How it is found | Size |
|---|---|---|---|
| The chat she is in | context window (`context.project`, compaction, clearing) | it is in front of her | one session |
| Lasting facts | `brain.sqlite3` `memory` | always whole in context | 48 entries |
| Journal notes | `brain.sqlite3` `journal` | newest 20 in context; `journal_search` by `LIKE` | 20 kept |
| Her episodes (mind on) | `mind.sqlite3` `episodes` | `Memory.recall`/`known`: FTS5 bm25 on words | 130 |
| Every past chat | `brain.sqlite3` `events` | `sessions_search`: exact substring | 71 chats, 34,591 events; plain turns 0.56 M tokens (4.3 M with tool results) |

Everything outside the context window is found only by shared words. "what was that game idea" does not
find "a pixel-art platformer", "hi" is new to her after a hundred "hello"s, and two lasting entries about one
subject in different words are not seen as alike (`lasting.related`). With her mind off, nothing from past
chats comes back unless the model thinks to search.

## What the research says

- Memory tiers (CoALA, Sumers et al. 2023; MemGPT/Letta, Packer et al. 2023): working memory is the context;
  long-term memory is searched into it. Letta keeps core memory in context (her lasting facts), recall memory
  (the raw conversation log, `conversation_search`) and archival memory (processed, vector-indexed).
- What to retrieve by (Generative Agents, Park et al. 2023): relevance by embedding similarity, with recency
  and importance. Her `Memory.recall` already weighs strength, salience, recency and mood: only its relevance
  term is words.
- Granularity (LongMemEval, Wu et al., ICLR 2025): store rounds (one user message and the reply), not whole
  sessions; adding extracted facts to a round's key raised recall@k by 9.4% on average ("fact-augmented key
  expansion"); limiting retrieval to a time range taken from the question raised temporal recall 6.8-11.3%.
  Systems lost 30-60% against perfect retrieval: retrieval is the part to get right.
- Keeping facts true (Mem0, Chhikara et al. 2025): a new fact is compared with its nearest stored facts by
  embedding, then added, merged, or the old one removed. Her `memory_save` + `lasting.related` + sleep's
  `tidy` already do this with word overlap; embeddings make the "nearest" right.
- Hybrid search: dense vectors miss exact names, paths and numbers that bm25 finds; reciprocal rank fusion
  (Cormack et al. 2009, score = sum of 1 / (60 + rank)) merges the two without calibrating their scores.

## Embeddings: free vs paid

Her provider (refuseless.com) has no embeddings model (`POST /embeddings`: "Unknown model"); Claude Code has
none either. So embeddings are their own setting.

| Option | Cost | Quality (MMTEB multilingual, vendor-reported) | Notes |
|---|---|---|---|
| Qwen3-Embedding-0.6B, local ONNX | free | 64.3 | Apache-2.0; ~570 MB int8; 1024-d, can be cut to 256 (MRL) |
| EmbeddingGemma-300M, local ONNX | free | 61.2 (768-d), 58.2 (128-d) | Gemma terms; ~200-300 MB quantized |
| multilingual-e5-small, local ONNX | free | ~57 | MIT; ~120 MB int8; fastest |
| potion-multilingual-128M (model2vec) | free | 47.3 | static, numpy only; too weak for this |
| Qwen3-Embedding-8B via DeepInfra/OpenRouter | $0.01 / M tokens | 70.6 (top 3 of the board) | cheapest paid, near the best quality |
| voyage-4-lite | $0.02 / M, 200 M free tokens | not on MTEB | 200 M tokens is centuries at her pace |
| OpenAI text-embedding-3-small | $0.02 / M | lower than the free local models | no reason to pick it |
| gemini-embedding-001 | free tier / $0.15 / M | 68.3 | free tier: Google uses the content to improve its products: not for her chats |

Her whole history costs under $0.01 to embed with Qwen3-Embedding-8B ($0.04 with every tool result); new
turns are cents a year. Paid is not about money: it is another account, and every chat she has goes to one
more company. So: **local and free by default** (her chats never leave the computer), the model picked by
measuring on her own history (Task 3) among the three local candidates; **any OpenAI-compatible
`/embeddings` service as the option** (one backend covers DeepInfra, OpenRouter, Voyage, OpenAI, and Ollama
or LM Studio running locally), with Qwen3-Embedding-8B on DeepInfra named as the cheapest best one.

## Requirements

R1. Short-term memory is the context window and stays as it is. Long-term memory is everything else: past
    chats (their turns), journal notes, her episodes, lasting facts. What is in her context now is never
    brought back to her as a memory: for the chat she is in, only what is before its last compaction is.
R2. Every turn with something the user wrote brings back, unasked, the rounds of past chats that are about
    it: found by meaning and by words (hybrid, RRF k = 60), only what is relevant enough (a calibrated floor,
    R6, or most of the query's words), at most 5, each with when and in which chat. With her mind on or off.
    (Journal notes are not among them: the newest 20 are in her prompt, `journal_search` finds the rest.)
R3. What comes back is written into that turn's input (beside her inner note, `runs.py`), so the log stays
    deterministic: the prompt cache, replay and rewind see the same text.
R4. A unit is a round: one user message and her replies to it (`mentions.turns`), split into chunks of at
    most 1,600 characters with 200 overlapping; no text is left out (no caps: a pasted log is many chunks).
    A journal note is a unit (the gist of its stretch), and so are episodes and lasting facts.
R5. Her mind's recall (`Memory.recall`, `known`) takes relevance from meaning as well as words; its other
    terms (strength, salience, mood, recency, noise, reconsolidation, forgetting) stay.
R6. Relevance is model-independent: cosine is mapped to 0..1 above the most that any of 20 everyday
    questions her past cannot answer reaches among her vectors of that model (measured again when the count
    doubles), so "relevant" means the same whatever the model. What comes back is what is related by
    meaning; words rank it, and decide alone only when meaning cannot. (Changed after measuring: the 95th
    percentile of random pairs of her own units, planned first, sat above many right hits, and words alone
    let something back for 17 of 20 unrelated questions.)
R7. The search tools find by meaning: `sessions_search` lists exact matches first, then what is about the
    query; it takes optional `after` and `before` dates (temporal questions, LongMemEval).
    `journal_search` finds notes and her memories by meaning. `lasting.related` finds the nearest facts by
    meaning (the same subject in other words).
R8. Embeddings: `api` (default: any OpenAI-compatible `/embeddings`, OpenRouter unless another address is
    set; base URL, key, model, optional dimensions) or `off` (words only, as before). Set in the SentientMilk
    control panel (Memory tab); apps have no setting. The panel says the chats go to that service.
R9. Without a key, or with the service down, search is by words only; a turn waits at most 4 s for its query
    to be embedded, and the backfill waits out a busy service (2, 4, 8 s) without holding anything up.
R10. Indexing runs in the background: a backfill of everything at start, then each round as its turn ends,
    each note, episode and fact as it is written. Vectors of another model are never compared with this
    one's: a changed model re-embeds in the background, a row's new vector taking its old one's place.
R11. Forgetting is honoured: a deleted chat's units go; a rewind removes the units of the events it undoes;
    a forgotten fact's unit goes; her forgotten episodes' vectors go with them.
R12. A turn embeds the user's message once (the recall note, her mind's recall and how known it is share
    it); a search over the vectors takes milliseconds (brute force, numpy).
R13. It is measured before it is chosen: recall@5 on questions about her own past chats (paraphrased and
    exact-term), words vs meaning vs hybrid, per candidate model, with latency, backfill time and memory.
    The default model and the relevance floor for `lasting.related` come from that measurement.
R14. Tests use a deterministic stand-in embedder (no download, no network); the real model is checked by an
    opt-in live run. Phone protocol and app API do not change; `GET /v1/stats` gains `recall` status.

## Design

- `embeddings.py`: what turns text into vectors (an OpenAI-compatible service, OpenRouter by default; a
  stand-in for tests). Rows L2-normalized float32; each embedder has a stable `name` that includes its
  dimensions; a query is embedded once and kept (64).
- `vectors.py`: vectors kept beside rows of a SQLite table (`<table>_vectors`: id, model, blob), searched by
  brute-force cosine over a cached numpy matrix (shortcut: brute force; switch to sqlite-vec past ~500k
  units, when a search passes 20 ms), and the relevance floor of R6.
- `recall.py`: the long-term memory index, `~/.sentientmilk/recall.sqlite3` (units + FTS5 + vectors). It is
  derived from the brain and her mind and can be deleted and rebuilt. Its thread backfills and follows
  changes; `search` is the hybrid; `note` renders what comes back for a turn.
- Her mind's `Memory` keeps its episodes' vectors in `mind.sqlite3` (`episodes_vectors`), filled by the
  recall thread; `recall`/`known` use them.
- What changed is found by a sweep (after each turn and every 30 s: new rounds, notes, facts, episodes);
  deletions are hooked so they are immediate: `Brain.delete_session`, `rewind`. Also `runs.py` (the note into
  the input), config, panel, `stats`.

## Measured (2026-11-17, a copy of her brain, scripts/recall_eval.py)

468 units (her rounds, notes, facts). 59 questions written by her light model about a round each, 19 naming
an exact term from it, 40 in other words; a hit is that round among the first results. Hybrid as shipped
(admission by meaning, calibrated floor); query time is OpenRouter's round trip from this laptop:

| | @1 | @5 | MRR | query p50 | dims | cost of her 468 units |
|---|---|---|---|---|---|---|
| words only (before) | 0.32 | 0.34 | 0.33 | - | - | - |
| mongodb/voyage-4-large (chosen) | 0.88 | 1.00 | 0.93 | 477 ms | 1024 | $0.011 |
| openai/text-embedding-3-large | 0.90 | 1.00 | 0.94 | 573 ms | 3072 | $0.012 |
| qwen/qwen3-embedding-8b | 0.81 | 0.95 | 0.86 | 1,102 ms (1 of 20 over 4 s) | 4096 | ~$0.001 |

By meaning alone (no words fused), the other five: cohere/embed-5-pro 0.78 / 0.97, perplexity/pplx-embed-v1-4b
0.75 / 0.93, google/gemini-embedding-2 0.63 / 0.95, google/gemini-embedding-001 0.68 / 0.81 (16 s at worst);
nvidia/nemotron-3.5-embed-8b:free has no provider that keeps nothing. Voyage 4 large and OpenAI 3 large
are one question apart; Voyage was taken for a third of the vector size, the faster answer, and no recall
for 20 questions her past cannot answer (OpenAI: 1). Her lasting facts: pairs on one subject in other words
(the Oracle plan and her stance on Oracle accounts, a Roblox account and the Roblox watcher) reach 0.33-0.52,
most others under 0.1: `lasting.RELATED_AT` stays 0.3.

## Left out

Fact-augmented keys (LongMemEval: a round's key carries the facts of its stretch, +9.4% recall@k) and LLM
fact extraction per round: add them if the plan's Task 3 shows questions spanning chats failing; a reranker
model, a knowledge graph (Zep, HippoRAG), showing recall in MilkChan's
"Inside her head", images (only text is embedded).

## Sources

Packer et al. 2023, MemGPT (arXiv 2310.08560) and https://docs.letta.com/guides/agents/architectures/memgpt;
Park et al. 2023, Generative Agents (arXiv 2304.03442); Sumers et al. 2023, CoALA (arXiv 2309.02427);
Wu et al. 2025, LongMemEval, https://arxiv.org/abs/2410.10813v2; Chhikara et al. 2025, Mem0,
https://www.emergentmind.com/papers/2504.19413; Cormack, Clarke & Buettcher 2009, reciprocal rank fusion;
https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX; https://huggingface.co/Qdrant/Qwen3-Embedding-0.6B-onnx;
https://huggingface.co/minishlab/potion-multilingual-128m; https://openrouter.ai/qwen/qwen3-embedding-8b;
https://docs.voyageai.com/docs/pricing; https://developers.googleblog.com/en/gemini-embedding-available-gemini-api/;
https://ai.google.dev/gemini-api/terms; https://aiapiprices.com/embeddings-api-pricing/.

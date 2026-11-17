# Long-term memory by meaning: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything she lived outside the context window comes back to her by meaning: past chats, journal
notes, her episodes and lasting facts, found by embeddings and words, every turn, with her mind on or off.

**Architecture:** An embedder (local ONNX by default, any OpenAI-compatible `/embeddings` as the option)
turns text into unit vectors; `vectors.py` keeps them beside SQLite rows and searches by cosine; `recall.py`
is a derived index (`recall.sqlite3`: rounds, notes, facts + FTS5 + vectors) with a background thread and a
hybrid search (RRF of cosine and bm25). Each turn's input gets what comes back, beside her inner note; her
mind's `Memory` and the search tools use the same embedder.

**Tech Stack:** Python >= 3.10, SQLite FTS5, numpy, onnxruntime, tokenizers (no torch), pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-long-term-memory-design.md` (requirements R1-R14).

## Global Constraints

- Windows laptop CPU, no GPU; new dependencies only `numpy>=1.26`, `onnxruntime>=1.20`, `tokenizers>=0.20`.
- No caps: every word of every chat is indexed and searchable; the 5 items a turn brings back are a prompt
  budget, the tools reach the rest.
- Default `embeddings = "local"`; chats leave the computer only with `embeddings = "api"`, which the panel
  says in words.
- Budgets (R12): recall in a turn at most 150 ms p95; local model at most 700 MB resident, unloaded after
  15 min unused; backfill of the user's history at most 30 min.
- Tests never download or call out (stand-in embedder); live runs use throwaway homes, the API key only from
  the brain's config, never printed, the home deleted after.
- Phone protocol and app API unchanged; `GET /v1/stats` gains `recall`. Code never refuses her tool calls.
- A known limit gets `# shortcut: <the limit>, <when to upgrade>`. Release bumps `pyproject.toml`,
  `__init__.__version__` and `extension/manifest.json` together (0.29.0).
- Never run the full suite beside a live server; never edit the tree during a background suite.

## Review Focus

- First start offline, or the model download cut off: turns go on with words-only recall, the download
  resumes on the next start (Task 1, Task 5 tests).
- One message of 1.8 M characters (a pasted log): it is all chunked and indexed in the background, its query
  side is cut to the model's 512 tokens, and no turn waits on it (Task 2, Task 4 tests).
- Embeddings settings changed in the middle of a backfill: no cosine between two models' vectors, the rest is
  re-embedded, search meanwhile by words plus what the new model has (Task 4 test).
- A turn running while the indexer writes: separate DB file in WAL, the indexer yields while
  `brain.runs.busy()`, no "database is locked" (Task 4 test).
- Cyrillic and mixed-language text: chunked, FTS5-tokenized and embedded like English (Task 2 test; Task 3
  questions include it where her history has it).

---

### Task 1: Embedders and their settings

**Files:**
- Create: `sentientmilk_framework/embeddings.py`
- Modify: `sentientmilk_framework/config.py` (DEFAULTS, `validate_setting`), `sentientmilk_framework/testing.py`,
  `tests/conftest.py` (brain fixture installs the stand-in), `pyproject.toml` (dependencies)
- Test: `tests/test_embeddings.py`; opt-in `tests/live_embeddings.py` (not collected: no `test_` prefix)

**Interfaces:**
- Produces:
  - `class Embedder`: `name: str` (stable, includes dimensions, e.g. `"local:qwen3-embedding-0.6b@256"`),
    `dim: int`, `embed(texts: List[str], query: bool = False) -> numpy.ndarray` (float32, shape (n, dim),
    rows of length 1; raises `NotReady` while it cannot), `problem() -> Optional[str]` (None: it can embed
    now; else words such as `"downloading the model, 41%"`).
  - `class StandIn(Embedder)`: `__init__(model: str = "default")`, `name = f"stand-in:{model}@256"`, hashed
    words and character trigrams; deterministic (another model name gives other vectors).
  - `class ApiEmbedder(Embedder)`: `__init__(base_url: str, api_key: str, model: str, dimensions: int = 0)`;
    `POST {base_url}/embeddings` `{"model", "input", "dimensions"?}`, batches of 64, 429 retried 3 times
    (2, 4, 8 s); `dim` from the first answer.
  - `class ModelSpec(NamedTuple)`: `repo, revision, files: Dict[str, str]` (path -> sha256), `pooling`
    (`"mean"` or `"last"`), `dim` (after MRL truncation), `query_prefix`, `doc_prefix`, `max_tokens = 512`.
  - `LOCAL_MODELS: Dict[str, ModelSpec]` with `"qwen3-embedding-0.6b"` (Qdrant/Qwen3-Embedding-0.6B-onnx,
    int8, last-token pooling, dim 256, query prefix `"Instruct: Given a message, find the past conversation
    it is about\nQuery: "`), `"embeddinggemma-300m"` (onnx-community, mean, dim 256, prefixes
    `"task: search result | query: "` / `"title: none | text: "`), `"multilingual-e5-small"` (mean, dim
    384, `"query: "` / `"passage: "`); `DEFAULT_LOCAL` set by Task 3.
  - `class LocalEmbedder(Embedder)`: `__init__(spec: ModelSpec, folder: Path)`; downloads missing files on
    a thread into `folder` (HTTP Range resume, sha256 checked, a bad file deleted), loads lazily, unloads
    after `IDLE_UNLOAD = 15 * 60` s unused.
  - `make(values: dict, home: Path) -> Optional[Embedder]`: `"off"` -> None, `"api"` -> ApiEmbedder,
    `"local"` -> LocalEmbedder of `values["embeddings_model"] or DEFAULT_LOCAL` in `home / "models"`.
  - `testing.install_embedder(monkeypatch) -> None`: `make` returns `StandIn(values["embeddings_model"] or
    "default")` unless embeddings is off.
  - Config keys: `"embeddings": "local"`, `"embeddings_model": ""`, `"embeddings_base_url": ""`,
    `"embeddings_api_key": ""`, `"embeddings_dimensions": 0`.

- [ ] **Step 1: Write the failing tests** in `tests/test_embeddings.py`

```python
def test_the_stand_in_is_deterministic_and_alike_text_is_nearer():
    e = StandIn(); a, b, c = e.embed(["a pixel art game idea", "an idea for a pixel game", "tax deadline"])
    assert np.allclose(np.linalg.norm(e.embed(["x y z"]), axis=1), 1.0)
    assert a @ b > a @ c and np.array_equal(e.embed(["tax deadline"])[0], c)

def test_the_api_embedder_batches_prefixes_and_retries(fake_embeddings_server):
    e = ApiEmbedder(fake_embeddings_server.url, "k", "Qwen/Qwen3-Embedding-8B")
    assert e.embed([f"t{i}" for i in range(130)]).shape[0] == 130
    assert [len(r["input"]) for r in fake_embeddings_server.requests] == [64, 64, 2]
    e.embed(["hello"], query=True)
    assert fake_embeddings_server.requests[-1]["input"][0].startswith("Instruct: ")
    fake_embeddings_server.fail_next(429); assert e.embed(["again"]).shape == (1, e.dim)

def test_a_local_model_is_downloaded_checked_and_resumed(tmp_path, file_server):
    spec = ModelSpec(repo=..., files={"model.onnx": sha256_of(file_server.body)}, ...)  # served by file_server
    file_server.cut_after(1000); e = LocalEmbedder(spec, tmp_path); wait_for(lambda: e.problem() and "%" in e.problem())
    file_server.cut_after(None); wait_for(lambda: (tmp_path / "model.onnx").exists())
    assert file_server.ranges[-1].startswith("bytes=1000-")
    bad = LocalEmbedder(spec._replace(files={"model.onnx": "0" * 64}), tmp_path / "b")
    wait_for(lambda: "does not match" in (bad.problem() or "")); assert not (tmp_path / "b" / "model.onnx").exists()

def test_embeddings_settings_are_checked(brain):
    with pytest.raises(BrainError): brain.client.update_config(embeddings="cloud")
    with pytest.raises(BrainError): brain.client.update_config(embeddings_base_url="ftp://x")
```

- [ ] **Step 2: Run them to see them fail.** Run: `.venv/Scripts/python.exe -m pytest tests/test_embeddings.py -q` Expected: FAIL (`ModuleNotFoundError: sentientmilk_framework.embeddings`).
- [ ] **Step 3: Implement `embeddings.py`, the config keys and `install_embedder`;** pin each model's
  revision and file hashes by downloading once by hand (record them in `LOCAL_MODELS`); add the three
  dependencies; conftest's `brain` fixture calls `install_embedder`.
- [ ] **Step 4: Run them to see them pass.** Same command. Expected: 4 passed. Then `python tests/live_embeddings.py` (real models): for each local model, cosine("my cat died", "our pet passed away") > cosine("my cat died", "the train is late").
- [ ] **Step 5: Commit** `feat: embedders for her long-term memory`.

### Task 2: Vectors and the long-term memory index

**Files:**
- Create: `sentientmilk_framework/vectors.py`, `sentientmilk_framework/recall.py`
- Test: `tests/test_vectors.py`, `tests/test_recall.py`

**Interfaces:**
- Consumes: `Embedder.embed`, `Embedder.name` (Task 1).
- Produces:
  - `class Vectors`: `__init__(db: sqlite3.Connection, table: str, lock)` creates `<table>_vectors(id INTEGER
    PRIMARY KEY, model TEXT NOT NULL, vector BLOB NOT NULL)`; `put(rows: List[Tuple[int, np.ndarray]],
    model: str)`, `drop(ids: Iterable[int])`, `pending(model: str, limit: int) -> List[int]` (rows of
    `table` with no vector of `model`), `nearest(query: np.ndarray, model: str, count: int,
    where: Optional[Set[int]] = None) -> List[Tuple[int, float]]` (cosine, best first; only `model`'s
    vectors), `relevance(cosine: float, model: str) -> float` = clamp((cosine - floor) / (1 - floor), 0, 1),
    floor = 95th percentile cosine of 500 random pairs, recomputed when the count doubles.
  - `class Recall`: `__init__(brain, path: Path)`; table `units(id INTEGER PRIMARY KEY, source TEXT, ref
    TEXT, app TEXT, session TEXT, at REAL, text TEXT)`, FTS5 `units_fts`, `Vectors(db, "units")`;
    `add(source: str, ref: str, app: str, session: str, at: float, text: str) -> List[int]` (replaces that
    `(source, ref)`; chunks of `CHUNK = 1600` chars stepping 1400, chunk refs `f"{ref}#{n}"`);
    `remove(source: str, refs: Iterable[str] = (), app: str = "", session: str = "", since: float = 0.0)`;
    `search(query: str, count: int = 5, sources: Tuple[str, ...] = ("turn", "note"),
    held: Optional[Tuple[str, str, float]] = None, after: Optional[float] = None,
    before: Optional[float] = None) -> List[dict]` (keys `id, source, ref, app, session, at, text,
    relevance, lexical, score`); `embedder: Optional[Embedder]` (from `embeddings.make`, remade when the
    settings change).
- `search`: top 40 by cosine (when the embedder has no `problem()`) and top 40 by bm25; `score` = sum of
  `1 / (60 + rank)`; kept when `relevance > 0` or `lexical >= 0.5` (bm25 mapped as in `Memory.recall`:
  `-rank / (1 - rank)`); `held` = (app, session, since) leaves out that chat's units from `since` on; the
  query is cut to the embedder's `max_tokens` before embedding.

- [ ] **Step 1: Write the failing tests** (a test-local `Table` embedder maps given texts to given vectors).

```python
def test_meaning_finds_what_words_miss(index):  # Table: "game idea" ~ "pixel-art platformer"
    index.add("turn", "1", "milk", "a", T0, "We planned a pixel-art platformer.")
    assert index.search("what was that game idea")[0]["ref"] == "1#0"

def test_exact_names_still_come_first_by_words(index):
    index.add("turn", "2", "milk", "a", T0, r"The notes are in C:\Users\me\plans.md")
    assert index.search(r"C:\Users\me\plans.md")[0]["ref"] == "2#0"

def test_nothing_unrelated_comes_back(index): assert index.search("quantum tax law") == []

def test_the_chat_she_is_in_comes_back_only_from_before_its_compaction(index):
    index.add("turn", "3", "milk", "a", T0, "the platformer"); index.add("turn", "4", "milk", "a", T0 + 99, "the platformer again")
    assert [h["ref"] for h in index.search("game idea", held=("milk", "a", T0 + 50))] == ["3#0"]

def test_another_models_vectors_are_never_compared(index):
    index.embedder = Table(name="other@256", ...)
    assert all(h["relevance"] == 0 for h in index.search("what was that game idea"))

def test_long_and_cyrillic_text_is_chunked_whole(index):
    ids = index.add("turn", "5", "milk", "a", T0, "ж" * 5000); assert len(ids) == 4
    assert index.search("жжж", sources=("turn",))  # FTS5 unicode61 tokenizes it

def test_a_huge_query_is_cut_to_what_the_model_takes(index, spy_embedder):
    index.search("word " * 400_000); assert len(spy_embedder.texts[-1]) <= 512 * 8  # ~8 chars a token, at most
```

- [ ] **Step 2: Run to see them fail.** `.venv/Scripts/python.exe -m pytest tests/test_vectors.py tests/test_recall.py -q` Expected: FAIL (no module).
- [ ] **Step 3: Implement `vectors.py` and `Recall` (index and search only, no thread).** Brute-force numpy
  over a cached matrix per model, rebuilt on `put`/`drop`; `# shortcut: brute force; sqlite-vec past ~500k
  units, when nearest passes 20 ms`.
- [ ] **Step 4: Run to see them pass.** Same command. Expected: all passed; `nearest` over 50,000 random
  256-d units under 20 ms (assert in `test_vectors.py`).
- [ ] **Step 5: Commit** `feat: an index of what she lived, by meaning and by words`.

### Task 3: Measure, then choose the model (gate)

**Files:**
- Create: `scripts/recall_eval.py`
- Modify: `sentientmilk_framework/embeddings.py` (`DEFAULT_LOCAL`), the spec (a "Measured" section)

**Interfaces:**
- Consumes: `Recall.add`, `Recall.search`, `LocalEmbedder`, `ApiEmbedder` (Tasks 1-2).
- Produces: `DEFAULT_LOCAL: str`; `RELATED_AT: float` in `lasting.py` (used by Task 7).

- [ ] **Step 1: Write `scripts/recall_eval.py --brain COPY --out DIR [--api-model M]`:** it indexes the
  copy's rounds and notes into one `Recall` per embedder; asks the light model once (cached in
  `DIR/questions.json`) for 60 questions about sampled rounds outside each round's own chat: 40 in other
  words ("do not reuse its names or rare words"), 20 naming an exact term from it; prints recall@1, recall@5
  and MRR for words-only, meaning-only and hybrid, plus query p50/p95 ms, backfill seconds and peak RSS MB.
  `--api-model` reads the key from the env var `EMBED_API_KEY`, never printed.
- [ ] **Step 2: Run it on a copy of the user's brain** in a throwaway folder in the scratchpad, with the
  three local models. Expected: a table per model. Delete the copy after.
- [ ] **Step 3: Pick `DEFAULT_LOCAL`:** the best hybrid recall@5 among those within R12 (150 ms p95,
  700 MB, 30 min). The gate: hybrid recall@5 at least words-only + 0.15 on the paraphrased questions and not
  below words-only on the exact-term ones. If no model passes, stop and report to the user with the table.
- [ ] **Step 4: Set `RELATED_AT`** to the lowest relevance between known duplicates in her
  `memory_revisions` ("saved again as" moves) that stays above 95% of unrelated fact pairs; write both
  numbers and the table into the spec's "Measured" section.
- [ ] **Step 5: Commit** `docs: what her long-term memory was measured to find`.

### Task 4: The indexer, and forgetting

**Files:**
- Modify: `sentientmilk_framework/recall.py` (thread), `sentientmilk_framework/brain.py` (make, start,
  stop, `delete_session`, settings change), `sentientmilk_framework/rewind.py` (after `store.rewind`),
  `sentientmilk_framework/runs.py:575` (wake after `mind.after`), `sentientmilk_framework/mind/memory.py`
  (`self.vectors`, drops in `forget_faint`, `forget_session`, `rewrite`)
- Test: `tests/test_recall.py`

**Interfaces:**
- Consumes: `Recall.add/remove`, `Vectors.pending/put/drop`, `mentions.chats`, `mentions.turns`,
  `store.notes`, `store.memory_entries`, `journal.HELPERS`.
- Produces: `Recall.start()`, `Recall.stop()`, `Recall.wake()`, `Recall.forget_session(app, session)`,
  `Recall.forget_from(app, session, event_id: int)`, `Recall.status() -> dict` (`embeddings`, `model`,
  `state` = `"ready"` | the embedder's `problem()` | `"off"`, `units`, `embedded`); `Memory.vectors:
  Vectors` over `episodes`; `brain.recall: Recall`.
- The sweep (on `wake()` and every 30 s): each app's chats from `mentions.chats` (helpers left out); a
  chat whose last event id passed its mark in `marks(app, session, last_event)` has its rounds from the
  last indexed one on added again (ref = the round's first event id; source `turn`); notes by id (source
  `note`); facts by `category/key` with the value (source `fact`; gone ones removed); then `pending` units
  and episodes are embedded 32 at a time, only while `not brain.runs.busy()`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_finished_turn_is_found_by_meaning_a_moment_later(brain):
    turn(brain, "milk", "let's make a pixel-art platformer"); brain.brain.recall.wake()
    wait_for(lambda: brain.brain.recall.search("that game idea"))

def test_a_deleted_chat_never_comes_back(brain):
    turn(brain, "milk", "my secret plan", session="s"); wait_indexed(brain); brain.client.delete_session("milk", "s")
    assert not brain.brain.recall.search("my secret plan", sources=("turn",))

def test_a_return_to_a_message_forgets_what_it_undid(brain): ...  # rewind to the 2nd message: its round is gone, the 1st stays
def test_a_forgotten_fact_and_episode_are_gone(brain): ...  # memory_forget, Memory.forget_faint: no unit, no vector
def test_nothing_is_embedded_while_a_turn_runs(brain, monkeypatch): ...  # runs.busy() True -> StandIn.embed not called by the sweep
def test_a_changed_model_re_embeds_everything(brain):
    wait_indexed(brain); brain.client.update_config(embeddings_model="multilingual-e5-small")  # stand-in named after it
    wait_for(lambda: brain.brain.recall.status()["embedded"] == brain.brain.recall.status()["units"])
```

- [ ] **Step 2: Run to see them fail.** `.venv/Scripts/python.exe -m pytest tests/test_recall.py -q` Expected: the new ones FAIL.
- [ ] **Step 3: Implement the thread, the hooks and the drops.**
- [ ] **Step 4: Run them, then the mind memory tests.** `... tests/test_recall.py tests/test_mind_memory.py tests/test_mind_memory_whole.py -q` Expected: all passed.
- [ ] **Step 5: Commit** `feat: she keeps an index of everything she lived, and forgets with it`.

### Task 5: What comes back each turn

**Files:**
- Modify: `sentientmilk_framework/recall.py` (`note`), `sentientmilk_framework/runs.py:391-397`
- Test: `tests/test_recall.py`

**Interfaces:**
- Consumes: `Recall.search` (Task 2), the session's last `compaction` event (`at`), `store.session` title.
- Produces: `Recall.note(run: dict, said: str) -> Optional[str]`: None for anything but a `turn` with text,
  or when nothing comes back. Query: `said`; under 6 words, the last 300 characters of her previous reply
  in that chat go before it. `held` = (app, session, at of the last compaction, else 0.0) - R1. Exact text:

```
FROM YOUR LONG-TERM MEMORY (past chats that come back for this message; they may be out of date):
- 3 days ago, in "Pixel game": they: let's make a pixel-art platformer / you: Yes! A small one first...
```

  One line per hit (at most 5), `ago` as `mind.memory.line`, text at most 400 characters. In `runs.py` it
  goes first: `reminders=[r for r in (recalled, inner) if r] + reminders`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_what_comes_back_is_written_into_the_turn_and_stays_in_the_log(brain):
    turn(brain, "milk", "let's make a pixel-art platformer", session="a"); wait_indexed(brain)
    turn(brain, "milk", "remember that game idea?", session="b")
    content = json.dumps(last_input(brain, "milk", "b")["content"])
    assert "FROM YOUR LONG-TERM MEMORY" in content and "pixel-art platformer" in content
    assert project(events(brain, "b"), None) == project(events(brain, "b"), None)  # deterministic

def test_nothing_comes_back_when_nothing_is_about_it(brain): ...  # "what's 2+2" -> no header
def test_with_her_mind_off_it_still_comes_back(brain): ...       # mind=False (the fixture's)
def test_her_own_chat_comes_back_only_from_before_its_compaction(brain): ...
def test_with_the_model_not_ready_words_still_bring_it_back(brain, monkeypatch): ...  # problem() = "downloading"
```

- [ ] **Step 2: Run to see them fail.** Expected: FAIL (no header).
- [ ] **Step 3: Implement `note` and the `runs.py` line.**
- [ ] **Step 4: Run** `... tests/test_recall.py tests/test_runs.py tests/test_context.py -q` Expected: all passed.
- [ ] **Step 5: Commit** `feat: what she lived comes back to her as she reads a message`.

### Task 6: Her mind recalls by meaning

**Files:**
- Modify: `sentientmilk_framework/mind/memory.py` (`recall`, `known`), `sentientmilk_framework/mind/life.py`
  (gives `self.memory.embedder = brain.recall.embedder` at start and on a settings change)
- Test: `tests/test_mind_memory.py`

**Interfaces:**
- Consumes: `Memory.vectors` (Task 4), `Vectors.nearest`, `Vectors.relevance`.
- Produces: `Memory.embedder: Optional[Embedder]`. `recall`: candidates add the 40 nearest episodes;
  `relevance = max(lexical, semantic)`; the rest of its score unchanged. `known`: likeness = the largest
  `max(lexical, semantic)` among candidates; what followed is weighed by it over the 8 most alike.

- [ ] **Step 1: Write the failing tests.**

```python
def test_she_recalls_by_meaning(memory_with_table):  # "my cat died" ~ "our pet passed away"
    memory_with_table.add("exchange", "our pet passed away", -0.8, 0.6, 0.8)
    assert memory_with_table.recall("my cat died", -0.5, NOW)[0]["text"] == "our pet passed away"

def test_a_greeting_in_other_words_is_familiar(memory_with_table):
    for _ in range(10): memory_with_table.add("exchange", "hello", 0.3, 0.2, 0.2)
    assert memory_with_table.known("hi", before=NOW)[0] > 0.5  # words alone: 0

def test_without_an_embedder_she_recalls_as_before(memory): ...  # an existing recall test's numbers unchanged
```

- [ ] **Step 2: Run to see them fail.** `... tests/test_mind_memory.py -q` Expected: the two new ones FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `... tests/test_mind_memory.py tests/test_mind_life.py tests/test_mind_every_part.py -q` Expected: all passed.
- [ ] **Step 5: Commit** `feat: her mind recalls by meaning`.

### Task 7: The tools and her lasting memory find by meaning

**Files:**
- Modify: `sentientmilk_framework/toolkits/sessions.py` (`sessions_search`), `sentientmilk_framework/toolkits/journal.py`
  (`journal_search`), `sentientmilk_framework/lasting.py` (`related`)
- Test: `tests/test_sessions_toolkit.py`, `tests/test_lasting.py`, journal tests

**Interfaces:**
- Consumes: `Recall.search` (sources `turn`, `note`, `fact`), `RELATED_AT` (Task 3).
- Produces: `sessions_search(ctx, query: str, after: str = "", before: str = "")`: exact matches as now,
  then `About this (by meaning):` with up to 10 rounds not listed above; `after`/`before` are ISO dates
  (`datetime.fromisoformat`), else `ToolError("after and before are dates, like 2026-11-03.")`.
  `journal_search`: notes by words, then notes by meaning, then her memories (`look_back`).
  `lasting.related(entries, key, value, skip=(), count=3)`: facts with relevance >= `RELATED_AT` first,
  then the word-overlap ones, `count` in all.

- [ ] **Step 1: Write the failing tests:** `test_sessions_search_lists_exact_matches_then_what_is_about_it`,
  `test_sessions_search_keeps_to_the_dates_given`, `test_journal_search_finds_a_note_in_other_words`,
  `test_saving_one_subject_in_other_words_shows_the_one_she_keeps` (with a `Table` embedder: "works as an
  interpreter" ~ "job: translator").
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement**; tool docstrings say the query may be words or a description.
- [ ] **Step 4: Run** `... tests/test_sessions_toolkit.py tests/test_lasting.py tests/test_journal.py -q` Expected: all passed.
- [ ] **Step 5: Commit** `feat: her searches find by meaning`.

### Task 8: Settings in the control panel, status in stats

**Files:**
- Modify: `sentientmilk_framework/brain.py:590` (`stats`), `sentientmilk_framework/panel.py` (Memory tab, id
  `journal`)
- Test: `tests/test_recall.py`, `tests/test_panel.py`

**Interfaces:**
- Consumes: `Recall.status()` (Task 4), config keys (Task 1).
- Produces: `stats()["recall"]`; a "Long-term memory" section: a select (`Local: free, stays on this
  computer` / `A service (OpenAI-compatible)` / `Off: by words only`), model, base URL, key (password),
  dimensions, the status line, and with a service: "Every chat she has is sent to this service to be
  embedded."

- [ ] **Step 1: Write the failing tests:** `test_stats_say_how_far_her_long_term_memory_is`;
  `test_the_panel_sets_where_her_memory_is_embedded` (pilot: choose the service, fill the fields, save:
  config has them; the warning shows).
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `... tests/test_panel.py tests/test_recall.py -q` Expected: all passed.
- [ ] **Step 5: Commit** `feat: where her memory is embedded is set in the panel`.

### Task 9: Live, packaged, documented, shipped

**Files:**
- Modify: `C:\Users\plays\Code\Python\MilkChan\MilkChan.spec` (hiddenimports `onnxruntime`, `tokenizers`;
  `collect_dynamic_libs("onnxruntime")`), `docs/architecture.md` (a "Long-term memory" section),
  `README.md`, the spec, `pyproject.toml` / `__init__.py` / `extension/manifest.json` (0.29.0)

- [ ] **Step 1: Live:** a throwaway home with a copy of the user's brain, the real default model, the
  user's provider; one paced turn asking, in other words, about a chat from over a week ago. Expected: the
  input event holds that chat's round under the header; the recall took at most 150 ms; the backfill time
  and RSS within R12. Delete the throwaway home.
- [ ] **Step 2: Docs and version:** architecture and README say what is short-term (the context) and
  long-term (the index), the settings, and the privacy of `api`.
- [ ] **Step 3: Full suites, one at a time:** SentientMilk `.venv/Scripts/python.exe -m pytest tests -q`,
  then MilkChan `.venv-win/Scripts/python.exe -m pytest tests -q`. Expected: all passed.
- [ ] **Step 4: Ship:** commit and push SentientMilk; in MilkChan `python scripts/project.py pin`, commit
  `build: ship SentientMilk <sha>`, push; `build.bat`; start the built brain in a throwaway home and check
  `GET /v1/stats` reports `recall.state` (the frozen build loads onnxruntime).
- [ ] **Step 5: Memory notes:** a `long-term-memory` note (model chosen, numbers measured, lessons) and its
  line in `MEMORY.md`.

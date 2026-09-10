# Full-context efficiency

The default optimizations change representation and avoid unnecessary requests;
they do not summarize, truncate, or retrieve only selected history. Full history
still occupies the model's finite context window. Once it exceeds that window,
the provider may reject the request; nothing is silently dropped. Preserving
previously discarded tool results and screenshots can initially increase input
tokens compared with the old, incomplete history.

## Durable conversations

Pass a `Conversation` to `LLM.completion`, both streaming and non-streaming.
It appends complete assistant messages (including tool requests and provider
fields), and commits each tool result before executing the next tool. Multimodal
user content is preserved as supplied. SQLite persistence is enabled with
`Conversation(path="conversation.sqlite3")`. Alternatively, supply `on_append`
for synchronous application-owned storage. Serialize turns on each LLM instance.
Treat messages as immutable after appending; use `append`, `extend`, and `clear`,
not other list mutation methods, for a journal-backed conversation.

Completed tools survive a later API failure. On resume, missing results in an
interrupted group become explicit unknown-outcome results, not automatic tool
replays. A process can crash after a side effect but before its result commits:
this is not an exactly-once execution guarantee. The model must inspect state
before retrying. Failed/incomplete streamed responses are not committed as
complete assistant messages.

Plain lists remain supported and are not modified for backward compatibility.
Their complete request transcript is available in `llm.last_messages`; callers
must retain it themselves. The CLI now uses `Conversation` automatically and
resumes `~/.sentientmilk/conversation.sqlite3`. Override with `SENTIENTMILK_HISTORY`.
`/clear` clears that journal; `/export` includes tool calls/results, not only UI text.
Old missing tool results/images cannot be reconstructed retrospectively.

## Compact tools

- Dictionary/list results use compact Unicode JSON, preserving every decoded field.
- `read` defaults to one file/start-line/line-count header followed by exact UTF-8
  text, including mixed newlines. `numbered=True` restores per-line labels.
- `read_files(files=[...])` reads independent files in one tool request, preserving
  order and per-file errors. It does not silently truncate results.
- `replace_text(file, old, new)` replaces exactly one unique block without counting
  lines, preserving newline bytes. Ambiguous/absent matches fail without changes.
- The prompt encourages independent calls in one round. Dependent calls still
  wait; tools are not automatically reordered or run concurrently.

## Measurement and caching

`llm.last_usage` aggregates all model rounds, not just the final response. It
reports request count, prompt/completion tokens, cached input and reasoning
tokens when supplied, plus raw per-round usage dictionaries. Missing fields
remain `None` rather than falsely reporting zero. Cache and reasoning counters
are subsets of prompt/completion totals, not additional tokens to add to them.
The CLI `/stats` displays last-turn totals.

Streaming usage must be supported by your backend: opt in with
`Settings(stream_include_usage=True)` or CLI `SENTIENTMILK_STREAM_USAGE=1`.
No provider-specific retention/cache parameters are sent by default. Prefix
caching remains provider-controlled: stable prompts, tool ordering and an
append-only history make reuse possible, but do not guarantee a cache hit.
Caching reduces repeated processing/cost on supporting providers; it does not
reduce the context-window footprint. Compare actual usage using the same model
and workload; no blanket percentage reduction is promised.

Content-reference deduplication remains deferred: retaining bytes in storage is
not equivalent to keeping them in the active model context. It will require
exact-recall and editing evaluations before becoming a default optimization.

MilkChan uses the optional `message_transform` argument to create a transport-only
projection of screenshot history. The durable conversation remains exact; every
image item remains in the request, with older images encoded as small JPEG
thumbnails to stay below the configured reverse-proxy body budget. This preserves
visual chronology but not the original pixel resolution in later requests. If
even that projection is too large, the request fails locally rather than dropping
messages. Applications with strict pixel-level historical tasks should increase
their gateway limit and transport budget.

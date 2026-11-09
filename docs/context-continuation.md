# Context continuation

All ordinary turns, tasks and agents use one event-log projection. Claude Code super agents retain their native session lifecycle.

## Checkpoints and recovery

At compaction the brain writes a versioned `checkpoint` event containing the original requests and source IDs, model summary, current todos, worker progress notes, observed workspace/Git state, relevant files, command exits and failures. Command records are observed evidence; a summary, todo or progress note is a model claim. No inferred test pass count is treated as evidence.

Checkpoint records live in the scoped SQLite log, outside the projected conversation. They are removed atomically by clear, delete and rewind. They are not copied into the shared output directory. A compact prompt contains a bounded checkpoint excerpt, current todo/progress where space permits, references to the full record, and recent original events. The newest exchange is retained for short multi-turn chats; long exchanges retain complete recent steps. Manual compaction also keeps recent history.

Every run has `history_read` and `history_search`, subject to tool rules. They recover only that run's own app/session. Listing returns bounded previews and stable event IDs. `history_read(event=ID, offset=N)` pages a full original event in 12,000-character chunks; image attachments are restored on the first page. No file toolkit is needed and no private history copy is spilled to output files. Other conversations remain available through the sessions toolkit.

Large old tool results are cleared first, protecting short results and the latest five. Compaction runs only if still necessary. Model summaries are validated and bounded; checkpoints and other runtime metadata cannot trigger another summary on their own. Current memory is refreshed before the continuation request. Tool/skill catalogs remain available, and the checkpoint records definitions that may need reloading.

The model can call `context_compact(note=...)` after a milestone. The request is handled after its current batch of tool calls settles, so a tool call is not separated from an outstanding result.

## Live usage

Each completed provider response emits `context` on the run stream. The session endpoint exposes the same fields:

```json
{"used": 4331, "window": 256000, "clear_at": 0.5, "compact_at": 0.75,
 "source": "provider", "input_tokens": 4321, "output_tokens": 10}
```

`used` is the latest measured input plus output, never accumulated billing usage. Missing output is `null`; a valid zero remains zero. Rewrites emit an estimate with null input/output counts. Estimates include system instructions and tool schemas but remain approximate. A remote provider cannot precisely count the next request before processing it. Desktop and phone therefore label estimates and expose exact last-call integers in their details.

Live session events supersede older asynchronous fetches. Rewind restores matching usage metadata from the retained response; clear resets it. Older phone hosts retain the end-of-turn refresh fallback.

## Verification

Run `sentientmilk eval context-continuity --context-pair --report results.json` to compare the same three-turn coding task with no injected compaction and with two forced compactions. The checker verifies actual files, interfaces, numeric behavior, the original marker and the unchanged contract. The report includes provider usage, compactions and tool counts. The 2026-11-09 live results are in `verification/2026-11-09-context-continuity.json`.

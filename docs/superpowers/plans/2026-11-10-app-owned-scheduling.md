# App-owned scheduling implementation plan

**Goal:** Deliver scheduled instructions to the owning app's normal workflow in a persistent scheduled session.
**Spec:** ../specs/2026-11-10-app-owned-scheduling.md
**Execution:** Inline, no subagents, as explicitly requested.

- [x] 1. Calendar: add named-zone recurrence, validation and DST regression tests; declare/install tzlocal (Windows tzdata dependency).
- [x] 2. Persistence: add occurrence table; transactional schedule/session creation, due/outbox/advance, coalescing and lifecycle controls; migration and isolation tests.
- [x] 3. Delivery: idempotent scheduled normal turns, one stream consumer, resumable output/approvals and safe uncertain-action handling; app-scoped SDK/API endpoints and tests.
- [x] 4. MilkChan: scheduled sessions, notification/reconnect recovery, normal ChatWorker dispatch, unread/error handling and schedule management; integration tests.
- [x] 5. Verification: complete Python suites and lint, isolated live provider, self-review against the spec, docs/version updates.
- [x] 6. Release: commit/push backend, pin/commit/push MilkChan, build/install production packages, verify installed runtime and preserve user data/background services.

## Progress

2026-11-10: Both repositories clean on reused isolated worktrees, new codex/app-owned-scheduling branches. Existing scheduler traced: wake notifications to source chat or separate task runs; no durable occurrence ledger. Previous release installation confirmed at SentientMilk 0.5.1, with two measured provider usage events from its installed runtime. Architecture above is this task's chosen implementation, based on the user's requested flow.

Implemented and individually exercised calendar, durable delivery, migration, isolation, restart/action
recovery and actual MilkChan worker dispatch. Live provider evaluation in a temporary home passed:
missing time clarified without creating a schedule; weekdays 09:00 Europe/Warsaw extracted; two
occurrences executed memory tools and reports in the same dedicated session; repeated claims reused
the original run; source history stayed unchanged; pause/delete preserved reports. Full release
verification and installed-runtime checks follow after source review.

Release verification: backend full suite 308 passed, plus the added reconnect-approval regression
passed separately; all 27 scheduling cases passed. MilkChan full suite 354 passed. Both repositories'
Ruff checks passed. Phone client 22 tests, lint and typecheck passed. Self-review covered transactional
outbox failure, stream ownership/replay races, ID reuse, legacy migration, session deletion and rewind.
Versions: SentientMilk 0.6.0 and MilkChan 1.1.0. Release/install evidence is recorded in the release
response after production verification, since those steps follow these committed sources.

Final reconnect review reproduced an action emitted just before the run entered input_required.
The uncertain-mutation check now also covers working runs. The regression first failed by executing
the action a second time; all four read-only/mutating and working/paused combinations pass after
the correction. Production packages are rebuilt from this correction before installation.

## Completed release — 2026-11-10

- Final full suites: SentientMilk 311 passed; MilkChan 355 passed; phone client 22 passed.
  Both Python lint checks and phone lint/typecheck passed. The scheduling/loop/task regression group
  also passed all 81 cases. No subagents were used.
- Released runtime code: SentientMilk `ee465becfa2ea3efd14819b9966fe2f33c5f390f`;
  MilkChan `2e7cfec5d54c581f5baeefed15ae24a1243228a3`, both pushed to master. MilkChan pins
  that exact backend commit; this subsequent documentation-only record does not change runtime code.
- Standalone backend bundle, combined Windows installer and phone production web export built.
  Installer: `C:\Users\plays\Code\Python\MilkChan\dist\MilkChan-Setup-1.1.0.exe`.
  SHA256: `4B1F793B47A9C5FCB21357A1AB9FB1E13191BE8653D823B8BB527317CD505AF6`.
  Web export: `C:\Users\plays\Code\Python\MilkChan\mobile\dist\production-1.1.0`.
- Silent installation exited 0; installed SentientMilk 0.6.0 and MilkChan 1.1.0 are running.
  All 155 bundled Python source files match (CRLF/LF normalized). The installed Qt notification handler
  passed completed/failed recovery checks. Installed Windows timezone data passed the Warsaw DST check.
- Installed-runtime live provider check passed missing-time clarification, weekday/time/zone extraction,
  normal tool execution in two occurrences of one session, idempotent replay, pause and deletion with
  retained history. Seven provider context updates equalled measured input plus output tokens. All
  provider checks used temporary homes and created no schedules in the real user database.
- Backup: `C:\Users\plays\.sentientmilk\backups\scheduling-upgrade-20261110-153309`.
  SQLite integrity passed; 1 app, 32 sessions, 24,816 events, 34 memory entries and 0 real schedules remain.
  Provider/configuration and plugin configuration hashes are unchanged. Only installed MilkChan/brain
  processes were stopped, without terminating their child process trees or unrelated services.
- Limits: installer remains unsigned (no signing certificate configured); physical phone testing was
  not performed. The owning app must be available to execute work; offline deliveries wait/coalesce.

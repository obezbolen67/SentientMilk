# App-owned scheduling implementation plan

**Goal:** Deliver scheduled instructions to the owning app's normal workflow in a persistent scheduled session.
**Spec:** ../specs/2026-11-10-app-owned-scheduling.md
**Execution:** Inline, no subagents, as explicitly requested.

- [x] 1. Calendar: add named-zone recurrence, validation and DST regression tests; declare/install tzlocal (Windows tzdata dependency).
- [x] 2. Persistence: add occurrence table; transactional schedule/session creation, due/outbox/advance, coalescing and lifecycle controls; migration and isolation tests.
- [x] 3. Delivery: idempotent scheduled normal turns, one stream consumer, resumable output/approvals and safe uncertain-action handling; app-scoped SDK/API endpoints and tests.
- [x] 4. MilkChan: scheduled sessions, notification/reconnect recovery, normal ChatWorker dispatch, unread/error handling and schedule management; integration tests.
- [x] 5. Verification: complete Python suites and lint, isolated live provider, self-review against the spec, docs/version updates.
- [ ] 6. Release: commit/push backend, pin/commit/push MilkChan, build/install production packages, verify installed runtime and preserve user data/background services.

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

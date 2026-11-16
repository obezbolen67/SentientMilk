# Plan: her mind (design: specs/2026-11-16-digital-being-design.md)

Each step ends with its tests passing.

- [x] 1. `mind/body.py` + tests: levels, couplings, habituation, circadian, sleep, catch-up, seed
- [x] 2. `mind/feel.py` + tests: interoception, valence/arousal, sensations, face from declared options
- [x] 3. `mind/values.py`, `mind/will.py` + tests: learning, Monte Carlo choice calibration
- [x] 4. `mind/memory.py` + tests: FTS5 episodes, recall scoring, decay, reconsolidation
- [x] 5. `mind/prompts.py` (appraisal folded into life.py), `mind/life.py`: Mind, birth, before/after turn, bids,
      thoughts, urges, sleep consolidation, persistence; Brain wiring; Loop wiring (inner note, tool gate,
      effort); config `mind`; FakeProvider answers mind calls; conftest mind off
- [x] 6. API `GET /v1/mind`, client.mind(); panel Mind tab; README + architecture
- [x] 7. Integration tests (fake provider): turn with mind, decline gating, urge, sleep, off switch
- [x] 8. Live experiment on the user's provider (throwaway brain): decisions vs state, latency, idle cost
- [x] 9. MilkChan: face polling + idle time, mind.urge turns, proactive timer and pace removed, header words
- [x] 10. Full suites, version bumps, commit/push both, pin, installer, memory notes

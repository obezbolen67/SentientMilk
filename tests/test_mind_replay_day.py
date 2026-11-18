"""A full day through production turn, memory and polling paths with a virtual clock."""

import random
import shutil
import time
from types import SimpleNamespace

from conftest import Meaning
from test_mind_day import MORNING, stand_in
from test_mind_memory import embedded

from sentientmilk_framework.mind import life
from sentientmilk_framework.mind.body import Body, Temperament
from sentientmilk_framework.mind.feel import Interoception


def test_full_day_observer_independence(tmp_path, monkeypatch):
    now = [MORNING]
    monkeypatch.setattr(life, "time", SimpleNamespace(time=lambda: now[0], strftime=time.strftime))

    def replay(hz):
        now[0] = MORNING
        brain, runs = stand_in(tmp_path / str(hz))
        brain.runs = SimpleNamespace(busy=lambda: False)
        brain.config.values = lambda: {"light_model": "test", "provider": "test", "thinking_mode": "none"}
        calls = []
        provider = brain.provider
        def counted(*args, **kwargs):
            calls.append(len(runs))
            return provider(*args, **kwargs)
        brain.provider = counted
        mind = life.Mind(brain)
        mind.body = Body(Temperament.born(seed=71), at=MORNING)
        mind.senses = Interoception(mind.body, 71)
        mind.rng = random.Random(71)
        mind.self["born"] = True
        mind.memory.add("exchange", "Fix the failing test", 0.2, 0.3, 0.4, at=MORNING-100, app="other")
        embedded(mind.memory, Meaning())
        stages, actions, evidence = [], [], []
        try:
            for second in range(0, 86400, 5):
                now[0] = MORNING + second
                mind._live_until(now[0])
                if second == 15 * 3600:
                    mind.body.fall_asleep()
                stage = mind.body.stage()
                if not stages or stages[-1][1] != stage:
                    stages.append((second, stage))
                if second < 12 * 3600 and second % 1800 == 0:
                    run = {"id": len(runs)+1, "kind": "turn", "app": "milk", "session": "main", "options": {},
                           "status": "completed", "usage": {"completion_tokens": 100}, "result": {"reply": "Done."}}
                    mind.presence.report(0, False, False, now[0])
                    mind.before(run, {"persona": "You are Milk."}, "Fix the failing test.")
                    run["options"] = runs[run["id"]]
                    mind.after(run)
                    actions.append(run["options"]["mind"]["act"])
                    evidence.append(run["options"]["mind"]["selected"])
                for sample in range(5 * hz):
                    now[0] = MORNING + second + sample / hz
                    mind.state(brief=sample != 0 or second % 1800 != 0)
            mind._live_until(MORNING + 86400)
            assert len(stages) > 2 and any(evidence) and len(actions) == 24
            return stages, actions, evidence, calls, mind.body.to_dict(), mind.senses.seen
        finally:
            mind.memory.close()

    baseline = replay(0)
    assert replay(1) == baseline
    assert replay(4) == baseline


def test_nap_transfers_a_correction_on_an_old_cue_after_restart(tmp_path):
    brain, _ = stand_in(tmp_path / "checkpoint")
    mind = life.Mind(brain)
    now = MORNING
    mind.body = Body(Temperament.born(seed=71), at=now)
    mind.senses = Interoception(mind.body, 71)
    mem = mind.memory
    def episode(words, offset, kind="exchange"):
        return mem.add(kind, words, 0.0, 0.2, 0.15, at=now-offset, actor="ada", app="milk", session="main")
    old = episode("invoice cedar", 60)
    corrected = episode("Correction: use amber", 50)
    mem.supersede(old, corrected)
    distractor = episode("invoice hazel", 40)
    neutral = episode("cat", 30)
    dream = episode("invoice cedar", 20, "dream")
    mind.self["forecasts"] = {"keep": {"episode": neutral}}
    embedded(mem, Meaning())
    mind.save()
    mem.close()
    scores = []
    for arm in ("awake", "nap", "nap-without-replay"):
        target = tmp_path / arm
        shutil.copytree(brain.home, target)
        copy, _ = stand_in(target)
        # Open without applying wall time catch-up to this historical fixture.
        from unittest.mock import patch
        with patch.object(life, "time", SimpleNamespace(time=lambda: now, strftime=time.strftime)):
            subject = life.Mind(copy)
        if arm.startswith("nap"):
            subject.body.fall_asleep()
            subject.body.levels["adenosine"] = 0.65
        if arm == "nap-without-replay":
            subject.memory.soften = lambda ids, share: None
        later = now + 25 * 60
        subject._live_until(later)
        assert bool(subject.self.get("nap_replayed")) == arm.startswith("nap")
        subject.save()
        subject.memory.close()
        with patch.object(life, "time", SimpleNamespace(time=lambda: later, strftime=time.strftime)):
            subject = life.Mind(copy)
        try:
            memory = subject.memory
            memory.embedder = Meaning()
            hits = []
            for seed in range(50):
                memory._rng.seed(seed)
                item, = memory.recall("invoice", 0, later, kinds=["exchange"], count=1, strengthen=False)
                assert item["id"] in (corrected, distractor)
                hits.append(item["id"] == corrected)
            assert memory.recall("cat", 0, later, count=1, strengthen=False)[0]["id"] == neutral
            assert memory.by_ids([dream])[0]["kind"] == "dream"
            assert memory.by_ids([old])[0]["superseded_by"] == corrected
            scores.append(sum(hits))
        finally:
            subject.memory.close()
    assert scores[0] == scores[2] and scores[1] > scores[0], scores
    print("Corrected source in first slot over 50 matched seeds (awake, nap, replay disabled)", scores)

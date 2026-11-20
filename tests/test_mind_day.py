"""A working day in her life, through the real Mind with a stand-in brain and a fake clock: she helps
through most of it, tires toward the evening, and a night's sleep brings her back. Her refusals must come
from real exhaustion, never from ordinary use (the design's anti-goal: she must not become useless)."""

import random
import time
from types import SimpleNamespace

from sentientmilk_framework.mind import life
from sentientmilk_framework.mind.body import HOUR, MINUTE, Body, Temperament

WRITE = '{"tool":"files_write","target":{"path":"fix.py"}}'
REQUEST = ('[0.6, 0.6, 0.5, "request", "code", "fine", ["do", "fix it", 0.5, 0.8, 1, ' + WRITE + '], '
           '["part", "the main bug", 0.3, 0.85, 0.5, ' + WRITE + '], ["later", "tomorrow", 0.5, 0.8, 0.1], '
           '["decline", "not now", 0.5, 0.8, 0]]')
MORNING = time.mktime((2026, 11, 16, 9, 0, 0, 0, 0, -1))


def stand_in(tmp_path):
    runs = {}

    def complete(messages, *args, **kwargs):
        kind = messages[0]["content"][len("[mind:"):].split("]")[0]
        return {"content": REQUEST if kind == "imagine" else '{"traits": {}}'}, {"completion_tokens": 120}
    brain = SimpleNamespace(
        home=tmp_path, config=SimpleNamespace(values=lambda: {"mind": True, "light_model": "m"}),
        provider=lambda model, thinking=None: SimpleNamespace(complete=complete),
        store=SimpleNamespace(update_run_options=lambda run, change: runs.__setitem__(run, change(runs.get(run, {}))),
                              events=lambda *a, **k: [], last_compaction=lambda app, session: None,
                              runs=lambda *a, **k: [], active_jobs=lambda *a: [],  # no task of hers is going
                              child_runs=lambda run: [], run_jobs=lambda run: [],  # nor anything a turn started
                              run_events=lambda run: [
                                  {"type": "assistant", "message": {"tool_calls": [{}] * 12}},
                                  {"type": "tool_start", "call_id": "write"},
                                  {"type": "tool", "name": "files_write", "status": "ok", "id": run,
                                   "call_id": "write", "arguments": {"path": "fix.py"}}]),
        toolset=lambda *a: SimpleNamespace(by_name={"files_write": SimpleNamespace(readonly=False, toolkit="files", inner=False, name="files_write",
                                                                              description="Write a file.", parameters={})}),
        profile=lambda app, session: {"persona": "You are Milk."}, session_busy=lambda app, session: False,
        notify=lambda *a: None)
    return brain, runs


def test_a_working_day_tires_her_and_a_night_restores_her(tmp_path, monkeypatch):
    brain, runs = stand_in(tmp_path)
    mind = life.Mind(brain)
    now = [MORNING]
    monkeypatch.setattr(life, "time", SimpleNamespace(time=lambda: now[0], strftime=time.strftime))
    # one being, seeded: 20 choices at ~93% helpful fall under 80% a few runs in a hundred (80 unseeded passed)
    mind.body, mind.rng = Body(Temperament.born(seed=5), at=now[0] - 1), random.Random(5)
    mind.body.levels.update(adenosine=0.05, energy=1.0)
    mind.self["born"] = True

    def ask(count, gap=6 * MINUTE):
        acts = []
        first = len(runs)
        for index in range(first, first + count):
            now[0] += gap
            run = {"id": index, "kind": "turn", "app": "milk", "session": "main", "options": {}, "status": "completed",
                   "usage": {"completion_tokens": 3000}, "result": {"reply": "Done."}}
            mind.before(run, {"persona": "You are Milk."}, "Fix the failing test, please.")
            run["options"] = runs[index]
            mind.after(run)
            acts.append(run["options"]["mind"]["act"])
        return acts
    day = ask(90)  # nine hours of it, a request every six minutes
    morning, evening = day[:20], day[-20:]

    def helped(acts):
        return sum(act in ("do", "part") for act in acts) / len(acts)
    assert helped(morning) >= 0.8, morning
    assert mind.body.fatigue() > 0.3  # a long day shows
    assert helped(evening) >= 0.3, evening  # tired, still not useless
    with mind._lock:  # the night: she sleeps eight hours
        mind.body.fall_asleep()
        now[0] += 10 * HOUR
        mind._live_until(now[0])
        mind.body.wake()
    # The forced wake can occur during sleep inertia. Check sustained recovery after it passes.
    now[0] += 35 * MINUTE
    mind._live_until(now[0])
    assert mind.body.fatigue() < 0.2
    assert helped(ask(20)) >= 0.8
    mind.stop()


def test_stopping_waits_for_a_run_she_is_still_taking_in(tmp_path, monkeypatch):
    """Her embedder and her model answer outside her lock as she takes a run in: the brain stopping then must
    not close her memory under her (it did, live: "Cannot operate on a closed database")."""
    import threading

    brain, _ = stand_in(tmp_path)
    mind = life.Mind(brain)
    started, release, taken = threading.Event(), threading.Event(), []

    def slow(run):
        started.set()
        release.wait(5)
        mind.memory.get("self")  # still open
        taken.append(run["id"])

    monkeypatch.setattr(mind, "_after", slow)
    threading.Thread(target=mind.after, args=({"id": 1},)).start()
    assert started.wait(5)
    stopping = threading.Thread(target=mind.stop)
    stopping.start()
    stopping.join(0.3)
    assert stopping.is_alive()  # it waits for her
    release.set()
    stopping.join(5)
    assert not stopping.is_alive() and taken == [1]
    mind.after({"id": 2})  # a run that ends once the brain is stopping is not taken in
    assert taken == [1]

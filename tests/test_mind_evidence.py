import json
import random
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.body import CHEMICALS, Body, Temperament
from sentientmilk_framework.mind.feel import core
from sentientmilk_framework.mind.life import Mind
from sentientmilk_framework.mind.memory import line
from sentientmilk_framework.mind.values import Values
from sentientmilk_framework.mind.will import Appraisal, Option, choose, worth
from sentientmilk_framework.testing import tool_call


def test_checkpoint_continues_the_same_noise():
    body = Body(at=1000)
    body.advance(1060)
    restored = Body.from_dict(json.loads(json.dumps(body.to_dict())))
    restored.advance(1180)
    body.advance(1180)
    assert body.levels == restored.levels


def test_alerting_and_social_context_have_distinct_effects_on_action():
    # Same situation, same latent draws. First change alerting, then change only the appraisal.
    options = [Option("do", effort=0.5, chance=0.85, gives=0.9), Option("decline", gives=0.1)]
    total = {"quiet": 0.0, "alert": 0.0, "coerced": 0.0}
    chosen = {key: [] for key in total}
    for seed in range(50):
        body = Body(Temperament.born(seed=seed), at=12000)
        for key, alert, freedom in (("quiet", 0.35, 0.5), ("alert", 0.95, 0.5), ("coerced", 0.95, -0.9)):
            body.levels["noradrenaline"] = alert
            result = choose(options, Appraisal(free=freedom), body, Values(), lambda option: [],
                            random.Random(seed))
            total[key] += result.chances["do"]
            chosen[key].append(result.option.act)
    assert total["quiet"] > total["alert"] > total["coerced"]
    assert chosen["quiet"] != chosen["alert"] and chosen["alert"] != chosen["coerced"]


@pytest.mark.mind
def test_recover_after_appraisal_before_transcript_write(brain):
    run_id = brain.store.add_run("cli", "main", "turn", {})
    run = brain.store.run(run_id)
    profile = brain.brain.profile("cli", "main")
    mind = brain.brain.mind
    note = mind.before(run, profile, "How are you?")
    restored = Mind(brain.brain)
    try:
        body = restored.body.to_dict()
        assert restored.before(run, profile, "How are you?") == note
        assert restored.body.to_dict() == body
        assert restored.self["appraised"]
    finally:
        restored.memory.close()


@pytest.mark.mind
def test_retry_preserves_steering_and_separates_the_user_from_helper_messages(brain, monkeypatch):
    runs = brain.brain.runs
    run_id = brain.store.add_run("cli", "main", "turn", {})
    run = brain.store.run(run_id)
    mind = brain.brain.mind
    mind.before(run, brain.brain.profile("cli", "main"), "Start here.")
    for message, user in (("User correction", True), ("Internal update", False)):
        runs.steer(run_id, [{"type": "text", "text": message}], refuse_approvals=user)
    with monkeypatch.context() as failed:
        def unavailable(*args, **kwargs):
            raise OSError("interrupted transcript write")
        failed.setattr(brain.store, "add_event", unavailable)
        with pytest.raises(OSError):
            runs.take_messages(run, lambda event: None)
    with mind._lock:
        body = mind.body.to_dict()
        events = runs.take_messages(run, lambda event: None)
        assert mind.body.to_dict() == body
    assert [e["display"] for e in events] == ["User correction", "Internal update"]
    assert [e["sources"][0]["user"] for e in events] == [True, False]
    assert len({e["sources"][0]["id"] for e in events}) == 2
    assert not runs.take_messages(run, lambda event: None)


@pytest.mark.mind
@pytest.mark.parametrize("same_target", [False, True])
def test_tool_learning_requires_the_predicted_operation_on_the_predicted_target(brain, same_target):
    path = str(brain.work / "brief.txt")
    target = path if same_target else str(brain.work / "other.txt")
    check = {"tool": "files_write", "target": {"path": target}}
    brain.provider.mind_replies["imagine"] = [json.dumps([
        "same", "same", "same", "fine", "request", "writing", "curious",
        ["do", "write a brief", 0.1, 0.8, 1, check]])]
    brain.provider.replies += [tool_call("files_write", {"path": path, "content": "draft"}), "Done."]
    result = turn(brain, "cli", "Write the brief.", on_approval=lambda _: "allow")
    mind = brain.brain.mind
    wait_for(lambda: mind.memory.recorded(result["run"]))
    outcome = mind.self["decided"]["outcome"]
    assert outcome["predicted_operation"] == check
    assert ("capable" in outcome["measured"]) == same_target
    assert (outcome["resolved_by"] is not None) == same_target
    assert (brain.work / "brief.txt").read_text() == "draft"
    run = brain.store.run(result["run"])
    with mind._lock:
        mind.body.stress_drive = 0.5
        mind.look_inward(strategy="reappraise", run=run)
        assert mind.body.stress_drive == pytest.approx(0.425 if same_target else 0.5)
        mind.look_inward(strategy="reappraise", run=run)
        assert mind.body.stress_drive == pytest.approx(0.425 if same_target else 0.5)


@pytest.mark.mind
def test_episode_identity_survives_deletion_and_restart(brain):
    memory = brain.brain.mind.memory
    previous = memory.add("exchange", "first", 0, 0, 0, app="cli", session="discard")
    memory.retract("cli", "discard")
    restored = Mind(brain.brain)
    try:
        assert restored.memory.add("thought", "second", 0, 0, 0) > previous
    finally:
        restored.memory.close()


@pytest.mark.mind
def test_operation_forecasts_against_held_out_files_and_speakers(brain):
    mind = brain.brain.mind
    obstruction = brain.work / "unwritable-parent"
    obstruction.write_text("file, not directory")

    def run_case(phase, index, write, succeeds):
        name = f"{phase}-{index}.txt"
        path = (obstruction if write and not succeeds else brain.work) / name
        if not write and succeeds:
            path.write_text("sample")
        name = "files_write" if write else "files_read"
        check = {"tool": name, "target": {"path": str(path)}}
        brain.provider.mind_replies["imagine"] = [json.dumps({
            "appraisal": {"intent": "request"}, "options": [
                {"act": "do", "what": name, "chance": 0.8, "check": check}]})]
        arguments = dict(check["target"])
        if write:
            arguments["content"] = "sample"
        brain.provider.replies.extend([tool_call(name, arguments), "I checked the result."])
        result = turn(brain, "cli", f"Please use {name} on {path}.", context={"user": phase},
                      on_approval=lambda _: "allow")
        wait_for(lambda: mind.memory.recorded(result["run"]))
        observed = mind.self["decided"]["outcome"]
        assert observed["resolved_by"] and (observed["receipts"][-1]["status"] == "ok") == succeeds
        return check

    for i in range(12):
        run_case("training", 2*i, True, i < 10)
        run_case("training", 2*i+1, False, i >= 10)
    frozen = json.loads(json.dumps(mind.self["operations"]["cli"]))
    assert frozen["files_read"] == {"resolved": 12, "succeeded": 2}
    assert frozen["files_write"] == {"resolved": 12, "succeeded": 10}
    errors = []
    for i in range(6):
        for write, success in ((True, i != 4), (False, i == 2)):
            check = run_case("holdout", 2*i + int(write), write, success)
            option = Option("do", chance=0.8, check=check)
            option.calibrate(frozen)
            errors.append((option.chance - success) ** 2)
    assert len(errors) == 12 and sum(errors) / len(errors) == pytest.approx(83 / 588)


@pytest.mark.mind
@pytest.mark.parametrize("route,changed", [(True, False), (True, True), (False, True)])
def test_selected_write_triggers_independent_check_and_encodes_its_outcome(brain, monkeypatch, route, changed):
    mind = brain.brain.mind
    path = brain.work / "statement.txt"
    check = {"tool": "files_write", "target": {"path": str(path)}, "readback": True}
    brain.provider.mind_replies["imagine"] = [json.dumps({
        "appraisal": {"intent": "request"}, "options": [{"act": "do", "what": "save statement", "check": check}]})]
    brain.provider.replies.extend([tool_call("files_write", {"path": str(path), "content": "expected\r\n"}),
                                   "Here is my report."])
    during = mind.during
    def intervene(run, events):
        during(run, events)
        if events and events[-1]["type"] == "tool" and events[-1]["name"] == "files_write":
            if changed:
                path.write_bytes(b"changed independently")
            if not route:
                mind._working[run["id"]]["selected"] = []
    monkeypatch.setattr(mind, "during", intervene)
    monkeypatch.setattr(brain.brain, "note", lambda *args: None)
    result = turn(brain, "cli", "Save my statement and check its contents.", on_approval=lambda _: "allow")
    episode = wait_for(lambda: mind.memory.recent(1, ("exchange",)))[0]
    events = brain.store.run_events(result["run"])
    reads = [e for e in events if e["type"] == "tool" and e["name"] == "files_read"]
    outcome = mind.self["decided"]["outcome"]
    assert len(reads) == int(route)
    assert ("capable" in outcome["measured"]) == route
    if route:
        assert reads[0]["matched"] == (not changed)
        assert outcome["resolved_by"] == reads[0]["id"]
        assert json.loads(episode["attention"])[0]["id"] == reads[0]["id"]
        assert ("file contents differed" if changed else "file contents matched") in episode["text"]
    else:
        assert outcome["resolved_by"] is None and "unverified" in episode["text"]


def test_recalled_dream_is_identified_even_if_its_words_sound_factual():
    episode = {"kind": "dream", "at": 1000, "text": "The door was red."}
    assert "dream" in line(episode, 1200).lower() and "red" in line(episode, 1200)
    assert "red" not in line(episode, 1200, waking_evidence=True)


@pytest.mark.mind
def test_panel_reads_do_not_change_checkpoint(brain):
    mind = brain.brain.mind
    with mind._lock:
        before = mind.body.to_dict()
        for brief in (True, False, False):
            mind.state(brief=brief)
        assert mind.body.to_dict() == before


@pytest.mark.mind
def test_poll_rate_and_backwards_clock_do_not_change_the_seeded_path(brain):
    live = brain.brain.mind
    with live._lock:
        live.save()
        paths = []
        for frequency in (0, 1, 4):
            replay = Mind(brain.brain)
            try:
                start = replay.body.at
                for tick in range(1, 121):
                    now = start + tick / 4
                    if frequency and tick % (4 // frequency) == 0:
                        replay.state(brief=tick % 20 != 0)
                    if tick % 20 == 0:
                        replay._live_until(now)
                    if tick == 60:
                        replay._live_until(start - 200)
                    if tick == 80:
                        replay.body.apply({"reward": -0.2}, "scheduled surprise")
                paths.append((replay.body.to_dict(), replay.senses.reading(replay.body), replay.rng.getstate()))
            finally:
                replay.memory.close()
        assert paths[0] == paths[1] == paths[2]


@pytest.mark.parametrize("seed", range(50))
def test_reward_stress_and_waiting_with_matched_noise(seed):
    rich = Body(Temperament.born(seed=seed), at=12000)
    sparse = Body.from_dict(rich.to_dict())
    for minute in range(1, 31):
        rich.apply({"reward_rate": 0.1})
        rich.advance(12000 + minute * 60)
        sparse.advance(12000 + minute * 60)
    assert rich["reward"] == sparse["reward"]
    assert rich["dopamine"] > sparse["dopamine"]
    task = Option("do", effort=0.8)
    assert worth(task, Appraisal(), rich, 0)["cost"] > worth(task, Appraisal(), sparse, 0)["cost"]
    rich.levels["dopamine"] = sparse["dopamine"]
    assert worth(task, Appraisal(), rich, 0)["cost"] == worth(task, Appraisal(), sparse, 0)["cost"]

    threat = Body.from_dict(sparse.to_dict())
    threat.stress_drive = 0.7
    assert threat["cortisol"] == sparse["cortisol"]
    for other in (threat, sparse):
        other.advance(other.at + 600)
    peak_gap = threat["cortisol"] - sparse["cortisol"]
    assert peak_gap > 0.03
    for other in (threat, sparse):
        other.advance(other.at + 4 * 3600)
    assert abs(threat["cortisol"] - sparse["cortisol"]) < peak_gap
    steady = Body.from_dict(sparse.to_dict())
    steady.levels["serotonin"] = 1
    assert worth(task, Appraisal(), steady, 0) == worth(task, Appraisal(), sparse, 0)
    for chance in (0, 0.9):
        delay = Option("later", chance=chance)
        difference = worth(delay, Appraisal(), steady, 0)["patience"] - worth(delay, Appraisal(), sparse, 0)["patience"]
        assert (difference > 0) == bool(chance)


@pytest.mark.mind
def test_locked_desktop_phone_turn_and_idempotent_end(brain):
    mind = brain.brain.mind
    mind.presence.report(0, True)
    brain.provider.replies.append("I can talk it through.")
    result = turn(brain, "milk", "Please create the report.", context={"origin": "phone", "user": "Alex"})
    episode = wait_for(lambda: mind.memory.recent(1, ("exchange",)))[0]
    assert episode["device"] == "phone" and episode["actor"] == "alex"
    assert mind.presence.locked and episode["run_id"] == result["run"]
    assert mind.self["decided"]["outcome"]["evidence"] == "reply returned"
    with mind._lock:
        levels = dict(mind.body.levels)
        mind.after(brain.store.run(result["run"]))
        assert levels == mind.body.levels and mind.memory.count() == 1


@pytest.mark.mind
def test_review_retry_reuses_batch_and_skips_completed_effects(brain, monkeypatch):
    mind = brain.brain.mind
    episode = mind.memory.add("exchange", "Ada said the meeting moved.", 0, 0.3, 0.5, at=time.time() - 60)
    brain.provider.mind_replies["sleep"] = ['{"dream":"A meeting on the moon"}']

    def offline(*args, **kwargs):
        raise ConnectionError("synthetic interruption")

    monkeypatch.setattr(mind, "_know_herself", offline)
    with pytest.raises(ConnectionError):
        mind._consolidate()
    before = mind.memory.by_ids([episode])[0]
    renewed = Mind(brain.brain)
    try:
        renewed._consolidate()
        assert len(renewed.memory.recent(3, ("dream",))) == 1
        assert renewed.memory.by_ids([episode])[0]["strength"] == before["strength"]
        assert renewed.self["review"] is None
    finally:
        renewed.memory.close()


@pytest.mark.mind
def test_rule_out_obsolete_claim_and_undo_it_without_deleting_history(brain):
    mind = brain.brain.mind
    brain.provider.replies.extend(["Tuesday, noted.", "Thursday, understood."])
    turn(brain, "cli", "The meeting is on Tuesday.", context={"user": "Ada"})
    first = wait_for(lambda: mind.memory.recent(1, ("exchange",)))[0]
    brain.provider.mind_replies["imagine"] = [json.dumps({
        "appraisal": {"intent": "chat"}, "correction": {"replaces": "on Tuesday", "quote": "on Thursday"}})]
    result = turn(brain, "cli", "Correction, the meeting is on Thursday.", context={"user": "Ada"})
    wait_for(lambda: mind.memory.recorded(result["run"]))
    second = mind.memory.recent(1, ("exchange",))[0]
    assert mind.memory.corrections()[first["event_id"]] == second["id"]
    brain.client.rewind("cli", "main", second["event_id"])
    assert mind.memory.by_ids([first["id"]])[0]["superseded_by"] is None
    assert not mind.memory.by_ids([second["id"]])


@pytest.mark.mind
def test_sleep_replays_local_evidence_once_even_without_a_model(brain):
    mind = brain.brain.mind
    with mind._lock:
        now = mind.body.at
        original = mind.memory.add("exchange", "The date is Friday", 0, 0.2, 0.1, at=now - 120, event_id=1)
        corrected = mind.memory.add("exchange", "Correction, Thursday", 0, 0.2, 0.1, at=now - 60)
        mind.memory.supersede(original, corrected)
        mind.body.fall_asleep()
        mind.body.levels["adenosine"] = 0.65
        mind._live_until(now + 5 * 60)
        before = mind.memory.by_ids([corrected])[0]
        mind._live_until(now + 25 * 60)
        after = mind.memory.by_ids([corrected])[0]
        assert after["strength"] > before["strength"]
        assert after["encoding_valence"] == before["encoding_valence"]
        mind._live_until(now + 30 * 60)
        assert mind.memory.by_ids([corrected])[0] == after
        assert not brain.provider.mind_requests


@pytest.mark.mind
def test_new_forecast_uses_only_selected_independent_evidence(brain):
    mind = brain.brain.mind
    run = {"id": 120, "app": "milk", "session": "main", "options": {"context": {"user": "Ada"}}}
    with mind._lock:
        now = mind.body.at
        key = mind.memory.add("exchange", "Ada reported a successful repair", 0, 0.5, 0.7,
                              actor="ada", app="milk", event_id=10)
        mind.memory.follow(key, {"capable": 0.9})
        observed = dict(mind.memory.by_ids([key])[0], relevance=0.9)
        imagined = mind.memory.add("dream", "I broke the device", 0, 0.5, 0.7)
        dreamed = dict(mind.memory.by_ids([imagined])[0], relevance=0.1)
        mind.body.levels.update(energy=0, adenosine=1, cortisol=1)
        known = (0.9, {"capable": -0.9}, 10)
        def access(items):
            return mind._arrives(run, "device", 0, now, (mind._revision, known, items, [], True, None))
        selected = access([observed, dreamed])
        disconnected = access([dreamed])
        assert selected["selected"][0]["id"] == key and selected["followed"] == {"capable": 0.9}
        assert disconnected["followed"] == {} and "broke" not in disconnected["memories"][0]


@pytest.mark.parametrize("name", tuple(CHEMICALS))
def test_channel_impulse_recovery_and_selective_clamp(name):
    """Drive one channel, withdraw input, and read its actual downstream consumer with matched noise."""
    def consumer(body):
        if name == "serotonin":
            return worth(Option("later", chance=0.9), Appraisal(), body, 0)["patience"]
        if name in ("dopamine", "cortisol"):
            return worth(Option("do", effort=0.8), Appraisal(), body, 0)["cost"]
        if name == "oxytocin":
            return worth(Option("do", gives=1), Appraisal(), body, 0)["company"]
        if name in ("noradrenaline", "acetylcholine"):
            return core(body.levels)[1]
        return core(body.levels)[0]

    for seed in range(50):
        quiet = Body(Temperament.born(seed=seed), at=12000)
        driven = Body.from_dict(quiet.to_dict())
        baseline = consumer(quiet)
        driven.apply({name: 0.15})
        assert abs(consumer(driven) - baseline) > 0.0001
        pulse = driven[name] - quiet[name]
        driven.levels[name] = quiet[name]
        assert consumer(driven) == baseline
        driven.levels[name] += pulse
        for _ in range(12):
            driven.apply({name: 0.15})
            for body in (driven, quiet):
                body.advance(body.at + 60)
        assert CHEMICALS[name].low <= driven[name] <= CHEMICALS[name].high
        gap = abs(driven[name] - quiet[name])
        for body in (driven, quiet):
            body.advance(body.at + 4 * CHEMICALS[name].tau)
        assert abs(driven[name] - quiet[name]) < gap

"""Agents: full copies of the model with a fresh context that work on parts of a job in the background, in
their own sessions; the run that started them (the lead) waits for them, messages them, answers their
questions, watches and stops them, and each report, question and update reaches it exactly once."""

import json
import threading

from conftest import turn, wait_for

from sentientmilk_framework import agents as agents_module

AGENT = "## YOU ARE AN AGENT"


def calls(*items) -> dict:
    """One assistant message with calls (name, arguments, id)."""
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        for name, arguments, call_id in items]}


def is_agent(payload) -> bool:
    return AGENT in payload["messages"][0]["content"]


def text_of(payload) -> str:
    return json.dumps(payload["messages"], ensure_ascii=False)


def results(payload) -> dict:
    return {m["tool_call_id"]: m["content"] for m in payload["messages"] if m["role"] == "tool"}


def sent_names(payload) -> set:
    return {t["function"]["name"] for t in payload.get("tools") or []}


def main_requests(brain) -> list:
    return [payload for payload in brain.provider.sent if not is_agent(payload)]


def agent_runs(brain, status=None) -> list:
    return [r for r in brain.store.runs(kind="agent") if status is None or r["status"] == status]


def test_agents_work_at_once_and_each_report_comes_back_once(brain):
    both = threading.Barrier(2, timeout=10)

    def route(payload):
        if is_agent(payload):
            listed = payload["messages"][0]["content"].split("## MORE TOOLS")[-1]
            assert {"shell_run", "web_search", "tools_load", "ask_lead", "task_progress"} <= sent_names(payload)
            assert "files_write" in listed and "schedule_create" in listed  # her tools, to load as she does
            assert "agent_start" not in listed + str(sent_names(payload))  # no agents of its own
            both.wait()  # both are at work at the same time
            return "Report A." if "Say A." in text_of(payload) else "Report B."
        if not results(payload):
            return calls(("agent_start", {"name": "alpha", "task": "Say A."}, "s1"),
                         ("agent_start", {"name": "beta", "task": "Say B."}, "s2"), ("agents_wait", {}, "w"))
        return "Both reported."

    brain.provider.replies += [route] * 4
    assert turn(brain, "cli", "split it")["reply"] == "Both reported."
    waited = results(main_requests(brain)[1])["w"]
    assert "alpha" in waited and "Report A." in waited and "beta" in waited and "Report B." in waited
    runs = agent_runs(brain, "completed")
    assert len(runs) == 2 and all(r["session"] == f"agent-{r['id']}" for r in runs)
    assert {brain.store.session("cli", r["session"])["settings"]["title"] for r in runs} == {"alpha", "beta"}
    brain.provider.replies += ["ok"]
    turn(brain, "cli", "thanks")
    assert "Report A." not in brain.provider.last_user_text()  # not a second time, as a note
    assert not [n for n in brain.store.notifications("cli") if n["type"] == "agent.finished"]


def test_an_agent_shows_as_done_only_once_its_report_waits_for_the_lead(brain, monkeypatch):
    seen = []
    update_run = brain.store.update_run

    def watched(run_id, **changes):  # the moment anyone could see the agent done
        run = brain.store.run(run_id)
        if run["kind"] == "agent" and changes.get("status") == "completed":
            seen.append(brain.store.has_mail("cli", run["options"]["parent_session"], "report"))
        return update_run(run_id, **changes)

    monkeypatch.setattr(brain.store, "update_run", watched)
    brain.provider.replies += [lambda p: "Report A." if is_agent(p) else calls(("agent_start", {"name": "a", "task": "A."},
                                                                                "s")),
                               lambda p: "Report A." if is_agent(p) else "started", lambda p: "ok"]
    turn(brain, "cli", "go")
    wait_for(lambda: seen)
    assert seen == [True]


def test_a_report_after_the_turn_ended_reaches_the_chat_and_the_app(brain):
    release = threading.Event()

    def route(payload):
        if is_agent(payload):
            assert release.wait(10)
            return "Slow report."
        return "Started it." if results(payload) else calls(("agent_start", {"name": "slow", "task": "Go slow."}, "s"))

    brain.provider.replies += [route] * 3
    assert turn(brain, "cli", "do it in the background")["reply"] == "Started it."
    release.set()
    finished = wait_for(lambda: [n for n in brain.store.notifications("cli") if n["type"] == "agent.finished"])
    assert finished[0]["session"] == "main"
    assert [(a["name"], a["status"]) for a in finished[0]["data"]["agents"]] == [("slow", "completed")]
    assert any("Slow report." in n["text"] for n in brain.store.events("cli", "main", types=("note",)))
    brain.provider.replies += ["It went slowly."]
    turn(brain, "cli", "how did it go?")
    assert brain.provider.last_user_text().count("Slow report.") == 1


def test_a_report_reaches_a_turn_still_working_at_its_next_step(brain):
    def route(payload):
        if is_agent(payload):
            return "Quick report."
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "quick", "task": "Be quick."}, "s"))
        if "f" not in done:
            wait_for(lambda: agent_runs(brain, "completed"))  # it finishes while this turn works
            return calls(("files_find", {"pattern": "*"}, "f"))
        return "Done."

    brain.provider.replies += [route] * 4
    assert turn(brain, "cli", "go")["reply"] == "Done."
    last = main_requests(brain)[-1]
    assert text_of(last).count("Quick report.") == 1 and "Agent quick" in text_of(last)
    assert not [n for n in brain.store.notifications("cli") if n["type"] == "agent.finished"]


def test_a_message_continues_a_finished_agent_with_what_it_knows(brain):
    def route(payload):
        if is_agent(payload):
            return "It was 7." if "What number was it?" in text_of(payload) else "Noted 7."
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "mem", "task": "Remember 7."}, "s"), ("agents_wait", {}, "w1"))
        if "m" not in done:
            return calls(("agent_message", {"agent": "mem", "message": "What number was it?"}, "m"),
                         ("agents_wait", {"agents": ["mem"]}, "w2"))
        return "It says 7."

    brain.provider.replies += [route] * 6
    assert turn(brain, "cli", "remember and recall")["reply"] == "It says 7."
    last = results(main_requests(brain)[-1])
    assert "Noted 7." in last["w1"] and "It was 7." in last["w2"] and "Noted 7." not in last["w2"]
    first, second = sorted(agent_runs(brain), key=lambda r: r["id"])
    assert first["session"] == second["session"]  # one agent, one history
    asked = [p for p in brain.provider.sent if is_agent(p) and "What number was it?" in text_of(p)][0]
    assert "Remember 7." in text_of(asked) and "Noted 7." in text_of(asked)


def test_a_message_reaches_a_working_agent_at_its_next_step(brain):
    steered = threading.Event()

    def route(payload):
        if is_agent(payload):
            if not results(payload):
                assert steered.wait(10)
                return calls(("files_find", {"pattern": "*"}, "a"))
            return "Checked A and B." if "Also check B." in text_of(payload) else "Checked A."
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "w", "task": "Check A."}, "s"),
                         ("agent_message", {"agent": "w", "message": "Also check B."}, "m"))
        if "x" not in done:
            steered.set()
            return calls(("agents_wait", {}, "x"))
        return "Done."

    brain.provider.replies += [route] * 6
    turn(brain, "cli", "check")
    assert "next step" in results(main_requests(brain)[1])["m"]
    assert "Checked A and B." in results(main_requests(brain)[-1])["x"]
    assert len(agent_runs(brain)) == 1


def test_a_writing_agent_asks_the_user_and_the_app_hears_whose_request_it_is(brain):
    def route(payload):
        if is_agent(payload):
            assert "files_write" in payload["messages"][0]["content"]  # listed: it may change things
            if not results(payload):
                return calls(("files_write", {"path": "out.txt", "content": "made"}, "w"))
            return "Wrote out.txt."
        if not results(payload):
            return calls(("agent_start", {"name": "writer", "task": "Write out.txt."}, "s"))
        return "Started."

    brain.provider.replies += [route] * 4
    turn(brain, "cli", "write it")
    asked = wait_for(lambda: [n for n in brain.store.notifications("cli") if n["type"] == "agent.input_required"])
    data = asked[0]["data"]
    assert data["name"] == "writer" and asked[0]["session"] == "main"
    waiting = brain.client.run(data["run"])["waiting"]
    assert [w["name"] for w in waiting] == ["files_write"]
    brain.client.answer(data["run"], call_id="w", decision="allow")
    wait_for(lambda: agent_runs(brain, "completed"))
    assert (brain.work / "out.txt").read_text(encoding="utf-8") == "made"


def test_names_are_unique_working_agents_are_capped_and_mistakes_explained(brain, monkeypatch):
    monkeypatch.setattr(agents_module, "MAX_WORKING", 1)
    hold = threading.Event()

    def route(payload):
        if is_agent(payload):
            assert hold.wait(10)
            return "done"
        if not results(payload):
            return calls(("agent_start", {"name": "one", "task": "Work."}, "a"),
                         ("agent_start", {"name": "one", "task": "Again."}, "b"),
                         ("agent_start", {"name": "two", "task": "More."}, "c"),
                         ("agent_start", {"name": "bad name!", "task": "x"}, "d"),
                         ("agent_start", {"name": "three", "task": " "}, "e"),
                         ("agent_message", {"agent": "nobody", "message": "hi"}, "f"))
        return "ok"

    brain.provider.replies += [route] * 3
    turn(brain, "cli", "many")
    hold.set()
    got = results(main_requests(brain)[1])
    assert got["a"].startswith("Started agent one")
    assert "already" in got["b"] and "agent_message" in got["b"]
    assert "1 agents are working" in got["c"]
    assert got["d"].startswith("Error:") and "name" in got["d"]
    assert got["e"].startswith("Error:") and "task is empty" in got["e"]
    assert got["f"].startswith("Error:") and "one" in got["f"]  # the agents it has


def test_stopping_an_agent_closes_it_and_the_user_can_stop_one_too(brain):
    def route(payload):
        if is_agent(payload):
            assert stopped.wait(10)
            return "too late"
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "a", "task": "Loop."}, "s1"),
                         ("agent_start", {"name": "b", "task": "Loop."}, "s2"))
        if "x" not in done:
            return calls(("agent_stop", {"agent": "a"}, "x"), ("agents_status", {}, "st"),
                         ("agent_message", {"agent": "a", "message": "hi"}, "m"))
        return "ok"

    stopped = threading.Event()
    brain.provider.replies += [route] * 6
    turn(brain, "cli", "start and stop")
    got = results(main_requests(brain)[-1])
    assert "Stopped agent a" in got["x"]
    assert "b (#" in got["st"] and "a (#" not in got["st"]
    assert got["m"].startswith("Error:")
    listed = brain.client.agents("cli", "main")
    assert [a["name"] for a in listed] == ["b"] and listed[0]["status"] == "working"
    brain.client.stop_agent(listed[0]["id"])
    stopped.set()
    sessions = {r["session"] for r in agent_runs(brain)}
    wait_for(lambda: not agent_runs(brain))  # killed: its runs and session are gone once they end
    assert brain.client.agents("cli", "main") == [] and not sessions & {s["id"] for s in brain.store.sessions("cli")}
    assert any("The user stopped your agent b" in n["text"] for n in brain.store.events("cli", "main", types=("note",)))


def test_watching_an_agent_shows_its_steps(brain):
    (brain.work / "a.txt").write_text("x", encoding="utf-8")
    gate = threading.Event()

    def route(payload):
        if is_agent(payload):
            if not results(payload):
                return calls(("files_find", {"pattern": "*.txt"}, "f"))
            assert gate.wait(10)
            return "Found a.txt."
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "finder", "task": "Find text files."}, "s"))
        if "st" not in done:
            wait_for(lambda: brain.store.events("cli", agent_runs(brain)[0]["session"], types=("tool",)))
            return calls(("agents_status", {"agent": "finder"}, "st"))
        gate.set()
        return "ok"

    brain.provider.replies += [route] * 5
    turn(brain, "cli", "watch it")
    status = results(main_requests(brain)[-1])["st"]
    assert "finder (#" in status and "working" in status and "Find text files." in status
    assert "files_find" in status and "a.txt" in status
    agent = brain.client.agent(agent_runs(brain)[0]["options"]["agent"])
    assert agent["name"] == "finder" and [s["name"] for s in agent["steps"]] == ["files_find"]


def test_agents_resume_after_a_restart(brain):
    run = brain.store.add_run("cli", "agent-90", "agent", {"input": None, "agent": 90, "parent_session": "main",
                                                           "profile": {"from_session": "main"}},
                              status="working")
    brain.store.update_session("cli", "agent-90", "settings", lambda s: {"title": "r", "agent": {
        "name": "r", "parent": "main", "task": "t", "created": 0}})
    brain.store.add_event("cli", "agent-90", run, "input", {"content": "t", "display": "t"})
    brain.provider.replies.append("finished after the restart")
    brain.brain.runs.recover()
    assert wait_for(lambda: brain.store.run(run)["status"] == "completed")
    assert "The brain restarted" in brain.provider.last_user_text()
    wait_for(lambda: any("finished after the restart" in n["text"]  # handed over just after it ends
                         for n in brain.store.events("cli", "main", types=("note",))))


def test_deleting_a_chat_deletes_its_agents(brain):
    brain.provider.replies += [calls(("agent_start", {"name": "gone", "task": "x"}, "s")), "agent done", "ok"]
    turn(brain, "cli", "start one", session="chat-1")
    wait_for(lambda: agent_runs(brain, "completed"))
    session = agent_runs(brain)[0]["session"]
    brain.client.delete_session("cli", "chat-1")
    assert not [s for s in brain.store.sessions("cli") if s["id"] in (session, "chat-1")]


def test_moving_on_from_a_waiting_turn_leaves_its_agents_working(brain):
    hold = threading.Event()

    def route(payload):
        if is_agent(payload):
            assert hold.wait(10)
            return "late"
        if not results(payload):
            return calls(("agent_start", {"name": "bg", "task": "Work."}, "s"),
                         ("shell_run", {"command": "echo hi"}, "ask"))
        return "ok"

    brain.provider.replies += [route] * 2
    run, _ = brain.brain.runs.start_turn("cli", "main", [{"type": "text", "text": "go"}], {}, subscribe=False)
    wait_for(lambda: brain.store.run(run)["status"] == "input_required")
    brain.provider.replies += ["new turn"]
    turn(brain, "cli", "never mind")  # gives up the waiting turn
    assert brain.store.run(run)["status"] == "cancelled" and agent_runs(brain)[0]["status"] == "working"
    hold.set()
    wait_for(lambda: agent_runs(brain, "completed"))


def test_a_stop_from_the_user_stops_the_agents_the_turn_started(brain):
    hold = threading.Event()

    def route(payload):
        if is_agent(payload) or results(payload):
            assert hold.wait(10)
            return "late"
        return calls(("agent_start", {"name": "fg", "task": "Work."}, "s"))

    brain.provider.replies += [route] * 3
    run, _ = brain.brain.runs.start_turn("cli", "main", [{"type": "text", "text": "go"}], {}, subscribe=False)
    wait_for(lambda: len(main_requests(brain)) == 2 and agent_runs(brain))
    brain.client.cancel(run)
    wait_for(lambda: brain.store.run(run)["status"] == "cancelled")
    wait_for(lambda: agent_runs(brain)[0]["status"] == "cancelled")
    hold.set()


def test_deleting_a_chat_while_its_agent_works_stops_it_and_it_goes_when_it_ends(brain):
    hold = threading.Event()

    def route(payload):
        if is_agent(payload):
            assert hold.wait(10)
            return "late"
        return "Started." if results(payload) else calls(("agent_start", {"name": "busy", "task": "x"}, "s"))

    brain.provider.replies += [route] * 3
    turn(brain, "cli", "start one", session="chat-2")
    run = agent_runs(brain)[0]
    brain.client.delete_session("cli", "chat-2")
    wait_for(lambda: brain.store.run(run["id"]) is None)  # it ended (stopped), then its session went
    hold.set()
    assert not [s for s in brain.store.sessions("cli") if s["id"] in (run["session"], "chat-2")]


def test_an_agent_runs_the_apps_actions_too(brain):
    """It has her actions: the app hears agent.input_required with the action waiting, runs it, answers."""
    brain.client.declare_app("acts", toolkits=["files", "agents"], actions=[
        {"name": "look", "description": "See the screen.", "readonly": True, "core": True}])

    def route(payload):
        if is_agent(payload):
            assert "look" in sent_names(payload)
            if not results(payload):
                return calls(("look", {}, "l"))
            return "I saw: " + results(payload)["l"]
        return "Started." if results(payload) else calls(("agent_start", {"name": "eyes", "task": "Look."}, "s"))

    brain.provider.replies += [route] * 4
    turn(brain, "acts", "look with an agent")
    asked = wait_for(lambda: [n for n in brain.store.notifications("acts") if n["type"] == "agent.input_required"])
    run = asked[0]["data"]["run"]
    assert [(w["kind"], w["name"]) for w in brain.client.run(run)["waiting"]] == [("action", "look")]
    brain.client.answer(run, call_id="l", result="a cat")
    finished = wait_for(lambda: [n for n in brain.store.notifications("acts") if n["type"] == "agent.finished"])
    assert finished and any("I saw: a cat" in n["text"] for n in brain.store.events("acts", "main", types=("note",)))


def test_an_agent_asks_the_lead_and_goes_on_with_the_answer(brain):
    def route(payload):
        if is_agent(payload):
            if not results(payload):
                return calls(("ask_lead", {"question": "Which file, a or b?"}, "q"))
            assert "answered" in results(payload)["q"] and "Use b." in text_of(payload)
            return "Used b."
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "picky", "task": "Edit the file."}, "s"), ("agents_wait", {}, "w1"))
        if "m" not in done:
            assert "picky" in done["w1"] and "asks" in done["w1"] and "Which file, a or b?" in done["w1"]
            return calls(("agent_message", {"agent": "picky", "message": "Use b."}, "m"), ("agents_wait", {}, "w2"))
        return "It used b."

    brain.provider.replies += [route] * 7
    assert turn(brain, "cli", "edit it with an agent")["reply"] == "It used b."
    assert "Used b." in results(main_requests(brain)[-1])["w2"]
    assert len(agent_runs(brain)) == 1  # it went on in the same run


def test_a_question_while_the_lead_is_idle_becomes_news(brain, monkeypatch):
    monkeypatch.setattr(agents_module, "ASK_WAIT", 0.5)

    def route(payload):
        if is_agent(payload):
            if not results(payload):
                return calls(("ask_lead", {"question": "Shall I delete the cache?"}, "q"))
            assert "No answer came" in results(payload)["q"]
            return "I kept the cache."
        return "Started." if results(payload) else calls(("agent_start", {"name": "careful", "task": "Clean up."}, "s"))

    brain.provider.replies += [route] * 4
    turn(brain, "cli", "clean up with an agent")
    asked = wait_for(lambda: [n for n in brain.store.notifications("cli") if n["type"] == "agent.asked"])
    assert asked[0]["session"] == "main" and asked[0]["data"]["name"] == "careful"
    assert asked[0]["data"]["question"] == "Shall I delete the cache?"
    assert any("Shall I delete the cache?" in n["text"] for n in brain.store.events("cli", "main", types=("note",)))
    wait_for(lambda: agent_runs(brain, "completed"))  # no answer in time: it went on by itself


def test_progress_notes_reach_the_lead_once_and_the_report_replaces_them(brain):
    noted, release = threading.Event(), threading.Event()

    def route(payload):
        if is_agent(payload):
            if not results(payload):
                return calls(("task_progress", {"note": "Half of the files read."}, "p"))
            noted.set()
            assert release.wait(10)
            return "All read."
        done = results(payload)
        if not done:
            return calls(("agent_start", {"name": "reader", "task": "Read all."}, "s"))
        if "f" not in done:
            assert noted.wait(10)
            return calls(("files_find", {"pattern": "*"}, "f"))
        if "f2" not in done:
            release.set()
            wait_for(lambda: agent_runs(brain, "completed"))
            return calls(("files_find", {"pattern": "*"}, "f2"))
        return "ok"

    brain.provider.replies += [route] * 7
    turn(brain, "cli", "read with an agent")
    requests = main_requests(brain)
    assert "Half of the files read." in text_of(requests[2]) and "reader" in text_of(requests[2])
    assert text_of(requests[-1]).count("Half of the files read.") == 1  # not again
    assert "All read." in text_of(requests[-1])


def test_apps_hear_when_agents_start_and_end(brain):
    brain.provider.replies += [calls(("agent_start", {"name": "news", "task": "x"}, "s")), "report", "ok"]
    turn(brain, "cli", "start one")
    updated = wait_for(lambda: [n["data"]["status"] for n in brain.store.notifications("cli")
                                if n["type"] == "agent.updated"][-1:] == ["done"] and
                       [n for n in brain.store.notifications("cli") if n["type"] == "agent.updated"])
    assert [n["data"]["status"] for n in updated] == ["working", "done"]
    assert updated[0]["session"] == "main" and updated[0]["data"]["name"] == "news"


def test_an_agent_idle_for_a_day_is_deleted_when_the_next_starts(brain):
    brain.provider.replies += [calls(("agent_start", {"name": "old", "task": "x"}, "s")), "old report", "ok"]
    turn(brain, "cli", "start one")
    old = wait_for(lambda: agent_runs(brain, "completed"))[0]
    with brain.store._db() as db:
        db.execute("UPDATE runs SET updated = updated - 90000 WHERE id = ?", (old["id"],))
    assert brain.client.agents("cli", "main") == []  # closed: not listed
    brain.provider.replies += [calls(("agent_start", {"name": "old", "task": "y"}, "s2")), "new report", "ok"]
    turn(brain, "cli", "start another")  # the name is free again, and the old one goes
    assert old["session"] not in {s["id"] for s in brain.store.sessions("cli")}
    assert [a["name"] for a in brain.client.agents("cli", "main")] == ["old"]

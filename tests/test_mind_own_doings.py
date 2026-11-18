"""What she does on her own is hers (0.42): a task her own thought started, and the jobs it left running, stay with
her whatever happens to the chat she was in; a thought goes with a deleted chat only if it grew from what was
said there; she is told what she did and what is still going, she sees it looking inward, and her session tools
find and open it.

In her real mind (2026-11-18) a wandering thought looked up an address at 15:04 and left a reverse-DNS sweep
(job 447) running; the chat she had last talked in was deleted at 15:15, and with it every thought and task of
hers since 09:45. Asked "what is this job 447?" in a new chat, she searched her sessions in vain."""

import json
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.memory import cue
from sentientmilk_framework.toolkits import ToolContext
from sentientmilk_framework.toolkits import sessions as kit
from sentientmilk_framework.toolkits.shell import job_ended

pytestmark = pytest.mark.mind  # her mind lives in these tests

SONG = cue("playing", "Clair de Lune — Debussy")


def talked(brain, said="hello", session="main"):
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", said, session=session)
    wait_for(lambda: not brain.brain.session_busy("milk", session))
    brain.client.mind("milk", idle=5)  # the app is there


def look_up(brain, what, found):
    """A wandering thought of hers looks something up; the task it started, once it has ended."""
    mind = brain.brain.mind
    brain.provider.replies += [found]
    brain.provider.mind_replies["think"] = [json.dumps({
        "thought": f"I wonder about {what}.", "feeling": "curious", "want": "look_up", "look_up": what})]
    mind._think("wonder", None)
    task = wait_for(lambda: [t for t in brain.store.runs(app="milk", kind="task") if t["status"] == "completed"])[0]
    wait_for(lambda: mind.memory.recorded(task["id"]))
    return task


def job(brain, task, command, lines=("begin",)):
    log = brain.brain.home / f"job-{task['id']}.log"
    log.write_text("\n".join(lines), encoding="utf-8")
    return brain.store.add_job(task["id"], "milk", task["session"], command, str(brain.brain.home), str(log))


def thought(mind, text):
    return next(e for e in mind.memory.recent(-1, ("thought",)) if e["text"] == text)


def note(brain):
    return brain.provider.last_user_text().split("[Inside you:")[1]


def test_her_task_is_marked_hers_with_what_she_meant_and_the_thought_it_came_from(brain):
    talked(brain)
    task = look_up(brain, "92.5.89.27", "An Oracle Cloud machine in Frankfurt.")
    own = task["options"]["own"]
    assert own["want"] == "look_up" and own["what"] == "92.5.89.27"
    assert own["thought"] == "I wonder about 92.5.89.27." and own["episode"]
    assert "in the language the goal is written in" in brain.provider.sent[-1]["messages"][0]["content"]


def test_what_she_did_on_her_own_stays_when_the_chat_she_was_in_is_deleted(brain):
    mind = brain.brain.mind
    talked(brain)
    task = look_up(brain, "92.5.89.27", "An Oracle Cloud machine in Frankfurt.")
    deed = mind.memory.recent(1, ("event",))[0]
    assert deed["run_id"] == task["id"] and deed["session"] == task["session"]  # where it happened
    brain.brain.delete_session("milk", "main")
    assert mind.memory.recorded(task["id"])
    assert "Out of my own curiosity I looked up: 92.5.89.27" in mind.memory.recent(1, ("event",))[0]["text"]


def test_a_thought_goes_with_its_chat_only_if_it_grew_from_what_was_said_there(brain, monkeypatch):
    mind = brain.brain.mind
    talked(brain, "my cat has been sneezing all day")
    said = mind.memory.recent(1, ("exchange",))[0]["id"]
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Poor cat.", "want": "nothing"})]
    mind._think("wonder", None)  # goes back over what was said
    over = thought(mind, "Poor cat.")
    assert json.loads(over["grew_from"]) == [said] and over["session"] == "main"
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Maybe it's dust.", "want": "nothing"})]
    mind._think("wonder", None)  # her stream goes on from that thought
    on = thought(mind, "Maybe it's dust.")
    assert json.loads(on["grew_from"]) == [over["id"]]
    now = time.time()
    elsewhere = mind.memory.add("thought", "I like rain on the window.", 0.2, 0.2, 0.3, at=now)
    mind.self["thoughts"] = [{"at": now, "kind": "wonder", "thought": "I like rain on the window.",
                              "want": "nothing", "episode": elsewhere}] + mind.self["thoughts"]
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "Rain makes the room smaller.", "want": "nothing"})]
    monkeypatch.setattr(mind, "_unbidden", lambda *args: [])  # nothing of the chat comes up in it by chance
    mind._think("wonder", None)  # filed under the chat she was last in, grown from nothing said there
    own = thought(mind, "Rain makes the room smaller.")
    assert own["session"] == "main" and json.loads(own["grew_from"]) == [elsewhere]
    brain.brain.delete_session("milk", "main")
    left = {e["id"] for e in mind.memory.recent(-1, ("thought",))}
    assert {own["id"], elsewhere} <= left and not {over["id"], on["id"]} & left


def test_she_is_told_what_she_did_on_her_own_and_what_is_still_going_whatever_chat_she_is_in(brain):
    talked(brain)
    task = look_up(brain, "92.5.89.27", "It's an Oracle Cloud machine in Frankfurt.")
    sweep = job(brain, task, "nslookup -type=PTR 92.5.89.1")
    brain.brain.delete_session("milk", "main")  # the chat she was in is gone
    talked(brain, "what is this job hmm?", session="other")
    told = note(brain)
    assert "What you did since you last talked: " in told
    assert "Out of my own curiosity I looked up: 92.5.89.27" in told and "Oracle Cloud machine" in told
    assert f"Still going: job {sweep}, from your task {task['id']} on your own (looking up 92.5.89.27): " \
           "nslookup -type=PTR 92.5.89.1" in told
    talked(brain, "and now?", session="other")
    told = note(brain)
    assert "What you did since you last talked" not in told and f"job {sweep}" in told  # told once; still going


def test_a_job_her_task_left_running_is_hers_to_remember_when_it_ends(brain):
    mind = brain.brain.mind
    talked(brain)
    task = look_up(brain, "92.5.89.27", "An Oracle Cloud machine.")
    sweep = job(brain, task, "nslookup -type=PTR 92.5.89.1", ["begin", "1.89.5.92.in-addr.arpa name = oracle.vm"])
    job_ended(brain.brain, sweep, 0)
    ended = mind.memory.recent(1, ("event",))[0]
    assert ended["session"] == task["session"] and ended["run_id"] is None
    assert ended["text"].startswith(f"The job I left running on my own (looking up 92.5.89.27) ended: job {sweep}")
    assert "finished with exit code 0" in ended["text"] and "name = oracle.vm" in ended["text"]
    talked(brain, "anything new?", session="other")
    assert f"job {sweep}" in note(brain) and "Still going" not in note(brain)


def test_looking_inward_she_sees_what_she_did_today_and_what_is_still_going(brain):
    mind = brain.brain.mind
    talked(brain)
    task = look_up(brain, "92.5.89.27", "An Oracle Cloud machine.")
    sweep = job(brain, task, "nslookup -type=PTR 92.5.89.1")
    seen = mind.look_inward()
    assert "What you did today: " in seen and "Out of my own curiosity I looked up: 92.5.89.27" in seen
    assert f"Still going: job {sweep}, from your task {task['id']} on your own" in seen


def test_her_session_tools_find_and_open_what_she_did_on_her_own(brain):
    talked(brain)
    task = look_up(brain, "92.5.89.27", "It belongs to Oracle Svenska AB, a Frankfurt VM.")
    sweep = job(brain, task, "nslookup -type=PTR 92.5.89.1")
    brain.brain.delete_session("milk", "main")
    run = brain.store.add_run("milk", "other", "turn", {}, status="working")
    ctx = ToolContext(brain.brain, brain.store.run(run), brain.brain.profile("milk", "other"), "call-1")
    listed = kit.sessions_list.func(ctx)
    assert f'{task["session"]} "on your own: looking up 92.5.89.27" · completed' in listed
    summary = kit.sessions_read.func(ctx, task["session"])
    assert "Out of my own curiosity I looked up: 92.5.89.27" in summary and "Oracle Svenska" in summary
    assert f"job {sweep} (running): nslookup -type=PTR 92.5.89.1" in summary
    steps = kit.sessions_read.func(ctx, task["session"], part="turns")
    assert "look this up for yourself: 92.5.89.27" in steps and "Oracle Svenska" in steps
    brain.brain.recall.sweep()
    found = kit.sessions_search.func(ctx, "Oracle Svenska AB, a Frankfurt VM")  # the stand-in measures shared words
    assert found.startswith(f'{task["session"]} "on your own: looking up 92.5.89.27"')


def test_what_she_did_and_kept_nothing_of_is_taken_in_when_she_starts(brain):
    mind = brain.brain.mind
    store = brain.store
    goal = "Out of your own curiosity, look this up for yourself: why do youtube thumbnails look the same."
    lost = store.add_run("milk", "pending", "task", {"goal": goal, "parent_session": "gone", "quiet": True,
                                                       "input": [{"type": "text", "text": goal}]})
    store.update_run(lost, session=f"task-{lost}", status="completed", result={"reply": "They copy what gets clicks."})
    sweep = store.add_job(lost, "milk", f"task-{lost}", "sleep 60", str(brain.brain.home), "")
    ended = store.run(lost)["updated"]
    filed = store.add_run("milk", "pending", "task", {"goal": "This comes from you: nobody asked. You were thinking: "
                                                              '"tidy up" and you decided to do it: sort my notes',
                                                      "parent_session": "main"})
    store.update_run(filed, session=f"task-{filed}", status="completed", result={"reply": "Sorted."})
    kept = mind.memory.add("event", "I decided on my own to sort my notes. How it went: Sorted.", 0.1, 0.2, 0.4,
                           app="milk", session="main", run_id=filed)  # filed under the chat, before 0.42
    mind._take_in_deeds()
    deed = [e for e in mind.memory.recent(-1, ("event",)) if e["run_id"] == lost][0]
    assert deed["at"] == ended and deed["session"] == f"task-{lost}"
    assert deed["text"] == ("Out of my own curiosity I looked up: why do youtube thumbnails look the same. "
                            f"How it went: They copy what gets clicks. Jobs I started: {sweep} (sleep 60).")
    assert store.run(lost)["options"]["own"] == {"want": "look_up", "what": "why do youtube thumbnails look the same",
                                                 "thought": "", "episode": None}
    assert store.run(filed)["options"]["own"]["thought"] == "tidy up"
    assert mind.memory.by_ids([kept])[0]["session"] == f"task-{filed}"
    count = mind.memory.count()
    mind._take_in_deeds()
    assert mind.memory.count() == count  # once


def test_what_she_thought_in_a_chat_comes_back_there_and_what_was_said_does_not(brain):
    memory = brain.brain.mind.memory
    now = time.time()
    for song in ("Gymnopedie No. 1", "Nocturne Op. 9", "Spiegel im Spiegel"):  # what was played, other times
        memory.add("exchange", f"We listened to {song}", 0.1, 0.2, 0.3, app="milk", session="old", at=now - 86400,
                   cues=[cue("playing", song)])
    said = memory.add("exchange", "They played me Clair de Lune", 0.3, 0.4, 0.5, app="milk", session="main",
                      at=now - 7200, cues=[SONG])
    mused = memory.add("thought", "That piece sounds like moonlight on water", 0.3, 0.4, 0.5, app="milk",
                       session="main", at=now - 3600, cues=[SONG])
    back = {e["id"] for e in memory.recall("song", 0.0, now, count=4, cues=[SONG], held=("milk", "main", 0.0))}
    assert mused in back and said not in back  # what was said is in her context; what she thought is not

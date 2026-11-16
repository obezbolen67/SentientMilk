"""Her mind in the brain: a message is felt and decided on, a refusal keeps her tools from her, an outcome is
remembered, thoughts become urges the app hears, sleep rewrites her story, and the switch turns it all off."""

import json
import time

from conftest import turn, wait_for

from sentientmilk_framework.mind.life import SLEPT_IF_OFF
from sentientmilk_framework.testing import tool_call

DECLINE = '[0.1, 0.2, 0.2, 0.4, "request", "files", "fed up", ["decline", "reading the file", 0.5, 0.8, 0, 0]]'
LATER = '[0.1, 0.2, 0.2, 0.5, "request", "report", "tired", ["later", "the weekly report", 0.8, 0.7, -0.2, 0]]'


def mind_on(brain):
    brain.client.update_config(mind=True)
    return brain.brain.mind


def test_she_feels_and_decides_before_she_answers_and_the_user_never_sees_it(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Sure, here it is."]
    result = turn(brain, "cli", "Can you sum up my notes?")
    assert result["reply"] == "Sure, here it is."
    sent = brain.provider.last_user_text()
    assert "[Inside you: You feel" in sent and "What you decide: you'll do it" in sent
    assert "Can you sum up my notes?" in sent
    imagine = next(r for r in brain.provider.mind_requests if r["messages"][0]["content"].startswith("[mind:imagine]"))
    assert "Can you sum up my notes?" in imagine["messages"][1]["content"]
    shown = brain.client.history("cli", "main")
    assert all("Inside you" not in json.dumps(item) for item in shown)
    assert "## YOUR INNER LIFE" in brain.provider.sent[-1]["messages"][0]["content"]
    run = brain.store.run(result["run"])
    assert run["options"]["mind"]["act"] == "do"
    episode = wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))[0]  # once the run has ended
    assert "Can you sum up my notes?" in episode["text"] and "I did it" in episode["text"]


def test_when_she_declines_her_work_tools_stay_unused_for_that_turn(brain):
    mind_on(brain)
    brain.provider.mind_replies["imagine"] = [DECLINE]
    (brain.work / "a.txt").write_text("secret plans", encoding="utf-8")
    brain.provider.replies += [tool_call("files_read", {"path": str(brain.work / "a.txt")}), "Not now, sorry."]
    result = turn(brain, "cli", "Read a.txt for me")
    assert result["reply"] == "Not now, sorry."
    assert "you won't do it (reading the file)" in brain.provider.sent[0]["messages"][-1]["content"]
    after = json.dumps(brain.provider.sent[-1]["messages"])
    assert "You decided not to do this now" in after and "secret plans" not in after


def test_what_she_puts_off_she_keeps_in_mind(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = [LATER]
    brain.provider.replies += ["Later, okay?"]
    turn(brain, "cli", "Write the weekly report")
    concern = mind.state()["concerns"][0]
    assert concern["what"] == "the weekly report" and concern["app"] == "cli"


def test_the_next_message_tells_her_how_her_decision_was_taken(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = [DECLINE, '[-0.9, 0.5, 0.1, 0.5, "chat", "insult", "hurt"]']
    brain.provider.replies += ["No.", "Sorry."]
    turn(brain, "cli", "Read a.txt for me")
    before = mind.values.predict(["act:decline", "tag:files"])
    turn(brain, "cli", "Wow, that is useless.")
    assert mind.values.predict(["act:decline", "tag:files"]) < before
    assert mind.body["grievance"] > 0.0


def test_a_thought_she_wants_to_share_reaches_the_app_that_is_there(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", "hello")
    brain.client.mind("milk", idle=5)  # MilkChan asks how she is: it is there to hear her
    brain.provider.mind_replies["think"] = [json.dumps({
        "thought": "I keep thinking about their garden.", "feeling": "fond", "want": "tell",
        "say": "How are the tomatoes doing?"})]
    mind._think("reach_out", None)
    urge = [n for n in brain.store.notifications("milk", 0) if n["type"] == "mind.urge"][-1]
    assert urge["data"]["want"] == "tell" and "tomatoes" in urge["data"]["text"]
    assert urge["session"] == "main" and mind.state()["thoughts"][0]["thought"].startswith("I keep thinking")


def test_sleep_goes_over_the_day_and_rewrites_who_she_has_become(brain):
    mind = mind_on(brain)
    episode = mind.memory.add("exchange", "The user thanked me for fixing their game", 0.8, 0.7, 0.8)
    brain.provider.mind_replies["sleep"] = [json.dumps({
        "insights": ["Helping with their game makes me happy."], "dream": "A castle made of code.",
        "story": "You are someone who loves fixing things with the user."})]
    mind._consolidate()
    state = mind.state()
    assert state["story"].startswith("You are someone who loves fixing")
    assert mind.memory.recent(1, kinds=("insight",))[0]["text"] == "Helping with their game makes me happy."
    assert next(e for e in mind.memory.recent(10) if e["id"] == episode)["charge"] < 1.0
    assert "## WHO YOU HAVE BECOME\nYou are someone who loves fixing" in mind.section()


def test_a_long_time_away_she_has_slept_through_and_goes_over_it_when_she_can(brain):
    mind = mind_on(brain)
    with mind._lock:
        mind.body.at -= SLEPT_IF_OFF + 3600
        mind.body.levels["adenosine"] = 0.9
        mind._live_until(time.time())
    assert mind.self["consolidate"] and mind.body["adenosine"] < 0.3 and not mind.body.asleep


def test_her_face_for_an_app_is_one_of_its_own_expressions(brain):
    mind_on(brain)
    state = brain.client.mind("milk", idle=2)
    assert state["on"] and state["face"]["mood"] in ("neutral", "smile") and state["present"]
    assert state["face"]["eyes"] in ("open", "half") and not any(ch.isdigit() for ch in state["felt"])


def test_with_her_mind_off_she_answers_as_asked_and_nothing_of_it_shows(brain):
    brain.provider.replies += ["Done."]
    turn(brain, "cli", "Do the thing")
    assert not brain.provider.mind_requests and "Inside you" not in brain.provider.last_user_text()
    assert "YOUR INNER LIFE" not in brain.provider.sent[-1]["messages"][0]["content"]
    assert brain.client.mind("milk") == {"on": False, "face": None}


def test_what_wins_her_attention_comes_from_how_she_is(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", "hello")
    wait_for(lambda: not brain.brain.session_busy("milk", "main"))
    mind.presence("milk", 1)
    now = time.time()

    def winners(**levels):
        found = []
        with mind._lock:
            mind.body.levels.update(levels)
            for _ in range(100):
                mind.self["fired"] = {}
                found.append(mind._winner(now)[0])
        return found
    lonely = winners(social=0.02, bond=0.95, oxytocin=0.7, adenosine=0.2, energy=1.0, novelty=0.6)
    assert lonely.count("reach_out") >= 90
    content = winners(social=0.7, novelty=0.6, cortisol=0.2, grievance=0.0)
    assert content.count(None) >= 95  # nothing nags a content mind: she thinks rarely, and costs little
    mind.last_active = 0.0  # the user is away
    mind.body.peak = (mind.body.hour(now) + 12) % 24  # and it is her night
    assert winners(adenosine=0.95, energy=0.3).count("sleep") >= 95
    assert "sleep" not in winners(adenosine=0.05, energy=0.9)  # slept out at night: she stays up


def test_her_quick_parts_think_with_thinking_off_unless_the_provider_refuses(brain):
    mind = mind_on(brain)
    brain.client.update_config(thinking_mode="high")
    brain.provider.replies += ["Hi."]
    turn(brain, "cli", "hello")
    assert brain.provider.mind_requests[-1]["reasoning_effort"] == "none"
    assert brain.provider.sent[-1]["reasoning_effort"] == "high"  # her answer thinks as the user set it
    brain.provider.mind_replies["imagine"] = [400]
    brain.provider.replies += ["Hi again."]
    turn(brain, "cli", "hello again")
    assert not mind._quick and brain.provider.mind_requests[-1]["reasoning_effort"] == "high"


def test_a_conversation_the_user_deletes_leaves_her_memory_with_it(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = [LATER]
    brain.provider.replies += ["Later.", "Hi."]
    turn(brain, "cli", "My bank PIN is in notes.txt, write the weekly report", session="secret")
    turn(brain, "cli", "hello")
    wait_for(lambda: len(mind.memory.recent(5, kinds=("exchange",))) == 2)
    brain.client.delete_session("cli", "secret")
    assert all("PIN" not in e["text"] for e in mind.memory.recent(10))
    assert mind.state()["concerns"] == [] and len(mind.memory.recent(5, kinds=("exchange",))) == 1


def test_while_her_last_urge_is_unanswered_her_thoughts_stay_hers(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Hi.", "Hello!"]
    turn(brain, "milk", "hello")
    brain.client.mind("milk", idle=5)
    tell = json.dumps({"thought": "That bug again.", "feeling": "uneasy", "want": "tell", "say": "About that bug..."})
    brain.provider.mind_replies["think"] = [tell, tell, tell, tell]
    for kind in ("reach_out", "ruminate", "wonder"):
        mind._think(kind, {"id": 0, "text": "the bug"} if kind == "ruminate" else None)

    def urges():
        return [n for n in brain.store.notifications("milk", 0) if n["type"] == "mind.urge"]
    assert len(urges()) == 1 and len(mind.state()["thoughts"]) == 3
    turn(brain, "milk", "what bug?")  # the user answered her
    brain.client.mind("milk", idle=5)
    mind._think("wonder", None)
    assert len(urges()) == 2


def test_her_curiosity_is_her_own_and_nobody_is_told_when_it_ends(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Hi.", "Tomatoes stop growing below 10 C."]
    turn(brain, "milk", "hello")
    wait_for(lambda: not brain.brain.session_busy("milk", "main"))
    brain.client.mind("milk", idle=5)
    brain.provider.mind_replies["think"] = [json.dumps({
        "thought": "Do tomatoes mind the cold?", "feeling": "curious", "want": "look_up",
        "look_up": "tomato cold tolerance"})]
    mind._think("wonder", None)
    task = wait_for(lambda: [t for t in brain.client.tasks("milk") if t["status"] == "completed"])[0]
    assert "tomato cold tolerance" in json.dumps(task)
    told = [n["type"] for n in brain.store.notifications("milk", 0)]
    assert not {"task.completed", "task.failed", "mind.urge"} & set(told)  # MilkChan would start a turn

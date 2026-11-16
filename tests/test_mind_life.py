"""Her mind in the brain: a message is felt and decided on, a refusal keeps her tools from her, an outcome is
remembered, thoughts become urges the app hears, sleep rewrites her story, and the switch turns it all off."""

import json
import math
import time

import pytest
from conftest import turn, wait_for

from sentientmilk_framework.mind.life import SLEPT_IF_OFF
from sentientmilk_framework.testing import tool_call

DECLINE = '[0.5, 0.5, 0.4, "request", "files", "fed up", ["decline", "reading the file", 0.5, 0.8, 0]]'
LATER = '[0.5, 0.5, 0.4, "request", "report", "tired", ["later", "the weekly report", 0.8, 0.7, 0.1]]'
INSULT = '[0.2, 0.2, 0.5, "chat", "insult", "hurt", ["talk", "answer it", 0.2, 0.6, 1]]'
# the model reads teasing as an order that takes her freedom (as it did live); what follows says otherwise
BANTER = '[0.6, 0.5, 0.2, "chat", "banter", "amused", ["talk", "laugh along", 0.1, 0.9, 1]]'
LAUGH = '[0.9, 0.7, 0.6, "chat", "laughing", "glad", ["talk", "laugh too", 0.1, 0.9, 1]]'


def mind_on(brain):
    brain.client.update_config(mind=True)
    return brain.brain.mind


def test_she_feels_and_decides_before_she_answers_and_the_user_never_sees_it(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Sure, here it is."]
    result = turn(brain, "cli", "Can you sum up my notes?")
    assert result["reply"] == "Sure, here it is."
    sent = brain.provider.last_user_text()
    assert ("[Inside you: Your body" in sent or "[Inside you: Nothing stands out" in sent) \
        and "What you decide: you'll do it" in sent
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


def test_when_she_would_rather_talk_first_she_may_look_but_changes_nothing(brain):
    mind_on(brain)  # live, "talk first" wrote all three files 2 times in 3 when nothing kept her from it
    brain.provider.mind_replies["imagine"] = ['["asked for poems", "same", "same", "same", "request", "poems", "unsure",'
                                              ' ["talk", "ask what they should be about", 0.2, 0.9, 0.1]]']
    (brain.work / "a.txt").write_text("rain and tea", encoding="utf-8")
    brain.provider.replies += [tool_call("files_read", {"path": str(brain.work / "a.txt")}),
                               tool_call("files_write", {"path": str(brain.work / "b.txt"), "content": "a poem"}),
                               "What should they be about?"]
    turn(brain, "cli", "Write a poem in b.txt, like the ones in a.txt")
    after = json.dumps(brain.provider.sent[-1]["messages"])
    assert "rain and tea" in after and "You decided not to do this now" in after
    assert not (brain.work / "b.txt").exists()


def test_what_she_puts_off_she_keeps_in_mind(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = [LATER]
    brain.provider.replies += ["Later, okay?"]
    turn(brain, "cli", "Write the weekly report")
    concern = mind.state()["concerns"][0]
    assert concern["what"] == "the weekly report" and concern["app"] == "cli"


def test_the_next_message_tells_her_how_her_decision_was_taken(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = [DECLINE, INSULT]
    brain.provider.replies += ["No.", "Sorry."]
    turn(brain, "cli", "Read a.txt for me")
    before = mind.values.predict(["act:decline", "tag:files"])
    episode = wait_for(lambda: mind.self["waiting"]["cli\nmain"]["episode"])  # how her turn went is in
    turn(brain, "cli", "Wow, that is useless.")
    assert mind.values.predict(["act:decline", "tag:files"]) < before
    assert mind.body["grievance"] > 0.0
    followed = json.loads(next(e for e in mind.memory.recent(5) if e["id"] == episode)["follows"])
    # the next message took company and her sense of being capable; her own no won back some freedom
    assert followed["company"] < -0.4 and followed["capable"] < -0.5 and followed["free"] > 0


def test_what_followed_comes_from_the_same_chat_and_a_long_time_apart_takes_company(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = [BANTER, INSULT, BANTER]
    brain.provider.replies += ["Ha.", "Hm.", "Hi again."]
    turn(brain, "cli", "lol you goof", session="a")
    episode = wait_for(lambda: mind.self["waiting"]["cli\na"]["episode"])
    turn(brain, "cli", "you're terrible at this", session="b")  # another chat: not what followed chat a
    assert "cli\na" in mind.self["waiting"] and "cli\nb" in mind.self["waiting"]
    assert next(e for e in mind.memory.recent(5) if e["id"] == episode)["follows"] is None
    with mind._lock:  # then the user is gone for hours, far longer than their usual minutes
        mind.self["gap"] = math.log(120)
        mind.self["contact"]["at"] -= 4 * 3600
    turn(brain, "cli", "back!", session="a")
    learned = mind.self["decided"]["path"]["learned"]
    assert learned["act"] == "talk" and learned["measured"]["company"] < -0.5
    followed = json.loads(next(e for e in mind.memory.recent(9) if e["id"] == episode)["follows"])
    assert followed["company"] < 0  # the absence counted, not just the banter (read +0.2)
    turn_b = mind.self["waiting"]["cli\nb"]
    brain.client.delete_session("cli", "b")
    assert "cli\nb" not in mind.self["waiting"] and turn_b


def test_what_a_message_brings_her_she_learns_from_what_followed_messages_like_it(brain):
    mind = mind_on(brain)
    foreseen = []
    for _ in range(6):  # teasing that ends in laughing together; insults followed by more of them
        brain.provider.mind_replies.setdefault("imagine", []).extend([BANTER, LAUGH, INSULT, INSULT])
        for text, reply in (("lol you idiot, that was hilarious, do it again", "Ha."), ("hahaha perfect", "Hehe."),
                            ("you're terrible at this", "Hm."), ("still terrible, honestly", "Okay.")):
            brain.provider.replies.append(reply)
            result = turn(brain, "cli", text)
            wait_for(lambda: mind.self["waiting"]["cli\nmain"]["episode"])
            if text.startswith("lol"):
                foreseen.append(brain.store.run(result["run"])["options"]["mind"]["foreseen"])
    assert foreseen[0]["free"] == -0.6  # at first only the model's reading: teasing takes her freedom
    assert foreseen[-1]["free"] > -0.3 and foreseen[-1]["company"] > foreseen[0]["company"]
    trust = mind.self["trust"]
    assert trust["own"]["free"] < trust["model"]["free"]  # her own record proved the better guide here
    brain.provider.mind_replies["imagine"].append(INSULT)
    brain.provider.replies.append("...")
    result = turn(brain, "cli", "you're terrible at this")
    hurt = brain.store.run(result["run"])["options"]["mind"]["foreseen"]
    # what keeps hurting is not unlearned (that the user stayed, writing again at once, softens company a little)
    assert hurt["company"] < -0.3 and hurt["capable"] < -0.4


def test_a_loss_she_can_undo_stresses_her_less_and_a_blow_from_someone_usually_kind_hurts_more(brain):
    from sentientmilk_framework.mind.will import Appraisal, Option
    mind = mind_on(brain)
    hurt = Appraisal(company=-0.6, capable=-0.6)

    def cortisol(option):
        with mind._lock:
            mind.body.levels.update(cortisol=0.25, grievance=0.0)
            mind._threat(hurt, option)
            return mind.body["cortisol"]
    # doing it over well wins back what was taken; saying no wins back none of it
    assert cortisol(Option("do", effort=0.6, chance=0.9, gives=1.0)) < cortisol(Option("decline", gives=0.0)) - 0.03

    def reward(expected):
        with mind._lock:
            mind.body.levels.update(reward=0.0, social=0.6, competence=0.6)
            mind.self["expected"] = expected
            mind._met(Appraisal(company=-0.5, capable=-0.5, novelty=0.2), 0.1, 0.0)
            return mind.body["reward"]
    assert reward(0.3) < reward(0.0) - 0.2 and reward(0.0) < 0


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


def test_her_state_shows_what_drives_what_and_what_wants_her_attention(brain):
    mind = mind_on(brain)
    with mind._lock:
        mind.body.levels.update(energy=0.5, cortisol=0.5, oxytocin=0.6, reward_rate=0.2)
    seen = brain.client.mind("milk", idle=5)
    edges = {(source, output): weight for source, output, weight in seen["wiring"]}
    assert abs(edges[("reward_rate", "dopamine")] - 0.45) < 0.01  # dopamine's target: +0.45 per unit
    assert edges[("cortisol", "serotonin")] < 0 and edges[("oxytocin", "cortisol")] < 0  # stress and its brakes
    assert edges[("energy", "valence")] > 0 and edges[("cortisol", "arousal")] > 0 and edges[("oxytocin", "valence")] > 0
    assert abs(mind.body.levels["energy"] - 0.5) < 0.01 and abs(mind.body.levels["cortisol"] - 0.5) < 0.01
    assert "cortisol" in seen["sensed"] and seen["feelings"] == [] and set(seen["attention"]["bids"]) == {
        "sleep", "reach_out", "wonder", "ruminate", "resume"}
    assert 0 < seen["attention"]["threshold"] and seen["decided"] is None
    assert set(seen["targets"]) >= {"dopamine", "cortisol"} and seen["set_points"]["social"] == 0.7
    assert seen["paces"]["serotonin"] > seen["paces"]["reward"] and set(seen["receptors"]) >= {"reward"}
    brain.provider.replies += ["Sure."]
    turn(brain, "milk", "Could you tidy my notes?")
    seen = wait_for(lambda: (lambda s: s if (s["decided"] or {}).get("outcome") else None)(brain.client.mind("milk", idle=5)))
    decided = seen["decided"]
    assert decided["act"] == "do" and decided["at"] > 0
    path = decided["path"]  # the way the message went through her, step by step
    assert path["said"] == "Could you tidy my notes?" and set(path["senses"]) >= {"contact", "timing", "novelty"}
    assert set(path["read"]) == {"company", "capable", "free"} and set(path["met"]["pushes"]) >= {"social"}
    assert path["met"]["gained"] - path["met"]["expected"] == pytest.approx(path["met"]["moved"]["reward"], abs=0.01)
    assert [o["act"] for o in path["options"] if o["picked"]] == ["do"] and "cost" in path["options"][0]["parts"]
    assert path["temperature"] > 0 and "lost" in path["threat"] and path["learned"] is None
    assert decided["outcome"]["status"] == "completed" and "free" in decided["outcome"]["measured"]
    brain.provider.replies += ["Done again."]
    turn(brain, "milk", "Thanks, now the other folder too.")
    learned = wait_for(lambda: brain.client.mind("milk", idle=5)["decided"]["path"]["learned"])
    assert learned["act"] == "do" and set(learned["followed"]) == {"company", "capable", "free"}
    feelings = brain.client.mind("milk", idle=5)["feelings"]  # the stand-in model named what she felt
    assert feelings and feelings[0]["count"] == 2 and len(feelings[0]["place"]) == 3
    brief = brain.client.mind("milk", idle=5, brief=True)  # a face's frequent look stays small as she grows
    assert set(brief) == {"on", "asleep", "present", "felt", "feeling", "valence", "arousal", "face"}

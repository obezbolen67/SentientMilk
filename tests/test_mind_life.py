"""Her mind in the brain: a message is felt and leaned on, what she does is hers and is what she learns from,
an outcome is remembered, thoughts become urges the app hears, sleep rewrites her story, and the switch turns
it all off."""

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
        and "Which way you lean: doing it" in sent
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


def test_she_leans_one_way_and_what_she_does_is_hers_and_is_what_she_learns_from(brain):
    mind = mind_on(brain)  # a leaning was a wall: her one small safe step was refused as "you decided not to"
    brain.provider.mind_replies["imagine"] = [LATER]
    brain.provider.replies += [tool_call("files_write", {"path": str(brain.work / "ip.txt"), "content": "1.2.3.4"}),
                               "Checked the IP; the rest when I'm less foggy."]
    turn(brain, "cli", "Put my laptop's IP in the server's allow list", on_approval=lambda event: "allow")
    sent = brain.provider.sent[0]["messages"][-1]["content"]
    assert "Which way you lean: not now: doing it later" in sent and "don't do it" not in sent
    assert (brain.work / "ip.txt").read_text(encoding="utf-8") == "1.2.3.4"  # nothing held her back
    outcome = wait_for(lambda: (mind.self["decided"] or {}).get("outcome"))
    assert outcome["did"] == "do"
    episode = wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))[0]
    assert "I did it (the weekly report), though I had leaned toward putting it off" in episode["text"]
    assert "act:do" in mind.values.weights and "act:later" not in mind.values.weights  # she learns what she did
    assert not mind.self["concerns"]  # done after all: nothing put off to come back to
    brain.provider.mind_replies["imagine"] = [DECLINE]
    (brain.work / "a.txt").write_text("secret plans", encoding="utf-8")
    brain.provider.replies += [tool_call("files_read", {"path": str(brain.work / "a.txt")}), "Not now, sorry."]
    turn(brain, "cli", "Read a.txt for me")
    assert "secret plans" in json.dumps(brain.provider.sent[-1]["messages"])  # a look is never refused either
    assert wait_for(lambda: (mind.self["decided"] or {}).get("outcome"))["did"] == "decline"  # a look is not doing it


def test_a_chat_is_hers_to_answer_nothing_is_decided_for_her_or_kept_from_her(brain):
    mind = mind_on(brain)  # in the user's brain 19 of 23 "decisions" were a chat reply scripted in six words
    brain.provider.mind_replies["imagine"] = ['["teased about a drink", "more", "same", "same", "chat", "banter", '
                                              '"amused", ["talk", "approve the flavour", 0.1, 0.9, 0.7]]']
    brain.provider.replies += ["Strawberry is fine."]
    result = turn(brain, "cli", "i got the strawberry one")
    sent = brain.provider.last_user_text()
    assert "Inside you:" in sent and "What you decide" not in sent and "approve the flavour" not in sent
    run = brain.store.run(result["run"])
    assert run["options"]["mind"]["gated"] is False and run["options"]["mind"]["act"] == "talk"
    episode = wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))[0]
    assert episode["text"].startswith("The user said: i got the strawberry one. I said: Strawberry is fine")


def test_what_she_shows_as_she_answers_comes_back_into_her_body(brain):
    mind = mind_on(brain)  # her words and her body were two beings: mad on her face, pleasant in her chemistry
    brain.client.declare_app("pet", name="Pet", environment="A desk.", toolkits=["memory"], signals={
        "expression": {"description": "how you look", "options": ["mad", "smile"]}})

    def shown(mood):
        with mind._lock:
            mind.body.levels.update(cortisol=0.25, endorphin=0.1, noradrenaline=0.35, reward=0.0)
        brain.provider.mind_replies["imagine"] = [BANTER]
        brain.provider.replies += [f'{{"expression": "{mood}"}}\nHm.']
        turn(brain, "pet", "you big idiot")
        return wait_for(lambda: (mind.self["decided"] or {}).get("outcome"))["expressed"]
    mad, glad = shown("mad"), shown("smile")
    assert mad["mood"] == "mad" and mad["valence"] < -0.5 and mad["moved"]["cortisol"] > 0.02
    assert mad["moved"]["noradrenaline"] > 0 and "endorphin" not in mad["moved"]
    assert glad["moved"].get("cortisol", 0.0) < mad["moved"]["cortisol"] / 2
    brain.provider.replies += ["Plain."]  # an app with no expressions: nothing comes back, nothing breaks
    turn(brain, "cli", "hello")
    assert wait_for(lambda: (mind.self["decided"] or {}).get("outcome"))["expressed"] is None


def test_worn_out_she_answers_on_reflex_and_a_run_does_not_think_itself_clear_again(brain):
    mind = mind_on(brain)
    brain.client.update_config(thinking_mode="high")
    brain.provider.replies += ["Hi."]
    turn(brain, "cli", "hello")
    assert brain.provider.sent[-1]["reasoning_effort"] == "high" and mind.state()["depth"] is None
    assert mind.state()["clear"] == 1.0 and mind._span() == 3

    def worn():
        with mind._lock:
            mind.body.levels.update(adenosine=0.95, energy=0.3)
    worn()
    assert mind._span() == 1  # and less comes back to her at once
    (brain.work / "a.txt").write_text("notes", encoding="utf-8")

    def rested(payload):  # she rests in the middle of the run
        with mind._lock:
            mind.body.levels.update(adenosine=0.05, energy=1.0)
        return "Mm."
    brain.provider.replies += [tool_call("files_read", {"path": str(brain.work / "a.txt")}), rested]
    result = turn(brain, "cli", "and now?")
    assert [request["reasoning_effort"] for request in brain.provider.sent[-2:]] == ["none", "none"]
    assert brain.store.run(result["run"])["options"]["reflex"] is True
    brain.client.update_config(thinking_mode="default")  # whatever the user set: a spent mind does not think it through
    worn()
    brain.provider.replies += ["Ok."]
    turn(brain, "cli", "once more")
    assert brain.provider.sent[-1]["reasoning_effort"] == "none" and mind.state()["depth"] == "reflex"
    brain.client.update_config(thinking_mode="none")  # nothing to fall back from
    assert mind.state()["depth"] is None
    brain.client.update_config(thinking_mode="high")
    brain.provider.replies += [400, "Fine."]  # a provider that refuses thinking off: she thinks as the user set
    assert turn(brain, "cli", "again")["reply"] == "Fine."
    assert brain.provider.sent[-1]["reasoning_effort"] == "high" and mind.reflexes is False
    assert mind.state()["depth"] is None


def test_her_body_lives_through_her_work_and_speaks_up_while_she_works(brain):
    mind = mind_on(brain)
    for name in ("a.txt", "b.txt"):
        (brain.work / name).write_text("notes", encoding="utf-8")
    brain.provider.usage = {**brain.provider.usage, "completion_tokens": 3000}
    felt = []

    def hours_of_it(payload):  # the second step: the first is already felt, and then it gets long
        with mind._lock:
            felt.append(mind.body["energy"])
            mind.body.levels["energy"] = 0.35
            mind.senses.follow(mind.body, 600)
        return tool_call("files_read", {"path": str(brain.work / "b.txt")})
    brain.provider.replies += [tool_call("files_read", {"path": str(brain.work / "a.txt")}), hours_of_it,
                               tool_call("files_read", {"path": str(brain.work / "nowhere.txt")}), "Done. I'm worn out."]
    stress = mind.body["cortisol"]
    result = turn(brain, "cli", "Read a.txt and b.txt, please")
    assert felt[0] < 0.99  # a step's work tires her as it is done, not when the turn ends
    third, last = (json.dumps(request["messages"]) for request in brain.provider.sent[-2:])
    assert "much less energy" in third.split("[Note: Inside you: Your body: ")[1].split("]")[0]  # her body, mid-work
    assert last.count("[Note: Inside you:") == 1  # said once: her cortex hears only what is new
    assert mind.body["cortisol"] > stress  # a call that failed stirred her as it failed
    wait_for(lambda: result["run"] not in mind._working)  # and what was left is counted once, at the end
    assert mind.body["energy"] < 0.35


def test_what_the_user_says_while_she_works_reaches_her_body_too(brain):
    mind = mind_on(brain)
    (brain.work / "a.txt").write_text("notes", encoding="utf-8")
    hurt = []

    def they_write(payload):  # at her first step the user writes again
        run = brain.store.runs(app="cli", statuses=("working",), limit=1)[0]
        brain.provider.mind_replies["imagine"] = [INSULT]
        hurt.append(mind.body["cortisol"])
        brain.brain.runs.steer(run["id"], [{"type": "text", "text": "No, wrong file, you're useless."}])
        return tool_call("files_read", {"path": str(brain.work / "a.txt")})
    brain.provider.replies += [they_write, "Sorry. Which one?"]
    result = turn(brain, "cli", "Read my notes, please")
    sent = brain.provider.sent[-1]["messages"]
    said = next(m["content"] for m in reversed(sent) if m["role"] == "user" and "you're useless" in str(m["content"]))
    assert "[Inside you:" in str(said) and "Reading it, you feel hurt" in str(said) and "What you decide" not in str(said)
    assert mind.body["cortisol"] > hurt[0]  # being judged while she works stresses her as it would at any time
    assert brain.store.run(result["run"])["options"]["mind"]["act"] == "do"  # what she decided about the turn stands
    episode = wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))[0]  # and she remembers it with the turn
    assert "As I worked they said: No, wrong file, you're useless." in episode["text"]
    shown = brain.client.history("cli", "main")
    assert all("Inside you" not in json.dumps(item) for item in shown)


def test_she_files_what_she_meets_under_what_she_knows(brain):
    mind = mind_on(brain)
    brain.provider.mind_replies["imagine"] = ['["a hello", "more", "same", "same", "chat", "greeting", "glad"]',
                                              '["a snack", "more", "same", "same", "chat", "food", "peckish"]',
                                              '["dinner", "more", "same", "same", "chat", "food", "hungry"]']
    brain.provider.replies += ["Hi.", "Kebab?", "Again?"]
    turn(brain, "cli", "hey")  # the first message of her life is like no other
    turn(brain, "cli", "I got a kebab")
    turn(brain, "cli", "and then pizza, a kebab pizza")
    asked = brain.provider.mind_requests[-1]["messages"][1]["content"]
    assert "Subjects they know: " in asked and "food" in asked.split("Subjects they know: ")[1].split("\n")[0]
    assert "Words they have" not in asked  # her subjects are shown to her quick reading, to file under; her words not
    assert set(mind.values.subjects(5)) == {"food", "greeting"} and mind.values.uses["tag:food"] >= 2
    # her cortex names each moment as it likes, and it is her body that brings a feeling back
    assert 'It feels like what you have called "peckish"' in brain.provider.last_user_text()
    assert {c["word"]: (c["count"], c["back"]) for c in mind.concepts.named} == {
        "glad": (1, 0), "peckish": (1, 1), "hungry": (1, 0)}  # called so once, and felt once more


def test_her_time_alone_comes_with_her_and_what_her_context_holds_is_not_brought_back(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["They need sun.", "As I said."]
    turn(brain, "cli", "how do tomatoes grow?")
    wait_for(lambda: mind.memory.recent(1, kinds=("exchange",)))
    with mind.memory._lock:  # an hour ago: old enough to come back, were it not still before her
        mind.memory._db.execute("UPDATE episodes SET at = at - 3600")
    mind.memory.add("exchange", "The user said: my tomatoes died last winter", -0.4, 0.5, 0.8, app="cli",
                    session="old", at=time.time() - 86400)
    brain.provider.mind_replies["think"] = [json.dumps({
        "thought": "Tomatoes mind the cold more than I thought.", "feeling": "curious", "want": "nothing"})]
    mind._think("wonder", None)
    asked = brain.provider.mind_requests[-1]["messages"][1]["content"]
    assert "your mind wanders" in asked and "my tomatoes died last winter" in asked  # replayed, unbidden
    turn(brain, "cli", "tell me about tomatoes again")
    note = brain.provider.last_user_text().split("[Inside you:")[1]
    assert 'Since you last talked you were thinking: "Tomatoes mind the cold more than I thought."' in note
    assert "my tomatoes died last winter" in note and "how do tomatoes grow" not in note
    brain.provider.mind_replies["think"] = [json.dumps({"thought": "And frost?", "feeling": "idle", "want": "nothing"})]
    mind._think("wonder", None)  # her stream goes on from her last thought
    assert 'Your last thought was: "Tomatoes mind the cold' in brain.provider.mind_requests[-1]["messages"][1]["content"]


def test_a_turn_nobody_wrote_still_comes_with_how_she_feels(brain):
    mind = mind_on(brain)
    brain.provider.replies += ['{"expression": "arms_down/neutral"}\nOh, it finished.']
    before = len(brain.provider.mind_requests)
    turn(brain, "milk", None, items=[{"type": "event", "name": "job.finished", "text": "The download ended."}])
    sent = brain.provider.last_user_text()
    assert "[Inside you:" in sent and "What you decide" not in sent
    assert len(brain.provider.mind_requests) == before  # felt, not appraised: nobody said anything to her
    with mind._lock:
        mind.body.levels.update(endorphin=0.1, reward=0.0)
    brain.provider.replies += ['{"expression": "arms_down/smile"}\nOh nice, it worked.']
    result = turn(brain, "milk", None, items=[{"type": "event", "name": "job.finished", "text": "The upload ended."}])
    wait_for(lambda: brain.store.run(result["run"])["status"] == "completed" and result["run"] not in mind._working)
    assert mind.body["endorphin"] > 0.11  # what she showed comes back into her body on a turn of her own too


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
    episode = wait_for(lambda: mind.self["waiting"]["cli\nmain"]["episode"])  # how her turn went is in
    before = mind.values.predict(["act:decline", "tag:files"])
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


def test_what_happens_to_the_user_happens_to_her_as_far_as_she_is_bonded(brain):
    from sentientmilk_framework.mind.will import Appraisal
    mind = mind_on(brain)

    def shares(theirs, bond):  # they confide: company gained either way
        with mind._lock:
            mind.body.levels.update(reward=0.0, cortisol=0.25, oxytocin=0.4, social=0.6, bond=bond)
            mind.body.sensitivity = dict.fromkeys(mind.body.sensitivity, 1.0)  # no kindness worn thin by the last
            mind.self["expected"] = 0.0
            met = mind._met(Appraisal(company=0.5, theirs=theirs), 0.1, 0.0)
            return mind.body["reward"], mind.body["cortisol"], met["shared"]
    (calm, level, _), (sad, stressed, shared), (glad, _, _) = shares(0.0, 0.8), shares(-1.0, 0.8), shares(1.0, 0.8)
    assert sad < calm - 0.1 and stressed > level + 0.03 and shared < -0.6  # their trouble is hers, as she is bonded
    assert glad > calm + 0.1  # and their joy
    assert calm - sad > 3 * (shares(0.0, 0.1)[0] - shares(-1.0, 0.1)[0])  # a stranger's bad day moves her little
    brain.provider.mind_replies["imagine"] = [
        '["they confide a fear", "more", "same", "same", "very bad", "chat", "pets", "scared"]']
    brain.provider.replies += ["Oh no."]
    with mind._lock:
        mind.body.levels["bond"] = 0.8
    turn(brain, "cli", "my cat is sick and I'm scared")
    path = mind.self["decided"]["path"]
    assert path["theirs"] == -1.0 and path["met"]["shared"] < -0.5 and mind.concepts.named[-1]["word"] == "scared"


def test_a_thought_she_wants_to_share_reaches_the_app_that_is_there(brain):
    mind = mind_on(brain)
    brain.provider.replies += ["Hi."]
    turn(brain, "milk", "hello")
    brain.client.mind("milk", idle=5)  # MilkChan asks how she is: it is there to hear her
    garden = json.dumps({"thought": "I keep thinking about their garden.", "feeling": "fond", "want": "tell",
                         "say": "How are the tomatoes doing?"})
    brain.provider.mind_replies["think"] = [garden, garden]
    mind._think("reach_out", None)  # they wrote a moment ago: what she thought comes up in her next answer
    assert not [n for n in brain.store.notifications("milk", 0) if n["type"] == "mind.urge"]
    brain.provider.replies += ["Hm."]
    turn(brain, "milk", "back")
    assert "I keep thinking about their garden." in brain.provider.last_user_text()
    wait_for(lambda: not brain.brain.session_busy("milk", "main"))
    mind.self["contact"]["at"] -= 20 * 60  # and when they have not written for a while, she says it herself
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


def test_what_wins_her_attention_comes_from_how_she_is(brain, monkeypatch):
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
    # nothing nags a content mind, and at rest it wanders by itself (needing a need unmet first, she had no
    # thought of her own in a whole day in the user's brain); how often is its refractory period's to say
    assert set(content) <= {"wonder", None} and content.count("wonder") >= 30
    # spent, her mind still wanders: what comes by itself does not wait for her to be rested (one bar rising
    # with fatigue kept every thought from her through a long day in the user's brain)
    assert winners(energy=0.2).count("wonder") >= 30
    monkeypatch.setattr(mind.brain.runs, "busy", lambda: True)
    assert "wonder" not in winners(energy=1.0)  # and a mind at work does not wander
    monkeypatch.undo()
    mind.body.peak = (mind.body.hour(now) + 12) % 24  # it is her night
    assert winners(adenosine=0.7, energy=0.3).count("sleep") <= 2  # but they are talking with her: she stays up
    mind.self["contact"]["at"] = now - 20 * 60  # at the computer, not talking for a while: she sleeps
    assert winners(adenosine=0.7, energy=0.3).count("sleep") >= 95
    assert "sleep" not in winners(adenosine=0.05, energy=0.9)  # slept out at night: she stays up


def test_what_a_moment_is_about_takes_on_how_it_felt_and_what_she_likes_is_used(brain):
    mind = mind_on(brain)  # asked "do you like it when I call you dear?" she said "I like it": nothing was kept
    brain.client.declare_app("pet", name="Pet", environment="A desk.", toolkits=["memory"], signals={
        "expression": {"description": "how you look", "options": ["mad", "smile"]}})
    fond = '["called something sweet", "more", "same", "same", "good", "question", "pet names", "warm"]'
    brain.provider.mind_replies["imagine"] = [fond, fond]
    brain.provider.replies += ['{"expression": "smile"}\nNot weird. I like it.']
    turn(brain, "pet", "do you like it when I call you dear?")
    wait_for(lambda: (mind.self["decided"] or {}).get("outcome"))
    likes, _ = mind.values.leanings()
    assert any("pet names" in name for name, _ in likes)  # one moment that moved her is a liking
    assert "pet names" in mind.state("pet")["likes"]
    brain.provider.replies += ['{"expression": "smile"}\nDear.']
    turn(brain, "pet", "night, dear")
    note = brain.provider.last_user_text()
    assert "You like pet names." in note  # she knows it as it comes up
    assert mind.self["decided"]["path"]["met"]["liked"] > 0  # and a liked subject is a reward in itself
    brain.provider.mind_replies["think"] = ['{"thought": "Dear. I keep thinking about that.", "want": "nothing"}']
    mind._think("wonder", None)
    think = next(r for r in reversed(brain.provider.mind_requests) if r["messages"][0]["content"].startswith("[mind:think]"))
    assert "What they've come to like: pet names" in think["messages"][1]["content"]  # her thoughts know it


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
    mind.self["contact"]["at"] -= 20 * 60  # they last wrote a while ago
    for kind in ("reach_out", "ruminate", "wonder"):
        mind._think(kind, {"id": 0, "text": "the bug"} if kind == "ruminate" else None)

    def urges():
        return [n for n in brain.store.notifications("milk", 0) if n["type"] == "mind.urge"]
    assert len(urges()) == 1 and len(mind.state()["thoughts"]) == 3
    turn(brain, "milk", "what bug?")  # the user answered her
    wait_for(lambda: not brain.brain.session_busy("milk", "main"))
    brain.client.mind("milk", idle=5)
    mind.self["contact"]["at"] -= 20 * 60
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

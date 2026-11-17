"""Her long-term memory: past chats, and the notes and facts kept before 0.30, come back by meaning every turn,
and go when they are deleted (docs/superpowers/specs/2026-11-17-long-term-memory-design.md)."""

import json
import time
from types import SimpleNamespace

import pytest
from conftest import Meaning, turn, use

from sentientmilk_framework.exceptions import BrainError
from sentientmilk_framework.recall import CHUNK, HEADER, chunks
from sentientmilk_framework.toolkits import ToolError
from sentientmilk_framework.toolkits import sessions as sessions_kit

FILLER = ["the weather was grey all week", "we fixed the printer driver", "a recipe for lentil soup",
          "notes about the quarterly budget", "she read about volcanoes", "music for focus playlists",
          "a bug in the calendar sync", "plans to repaint the kitchen", "the train schedule changed",
          "how to prune tomato plants", "a podcast about chess openings", "renewing the passport",
          "backing up the photos", "a birthday gift for a friend", "the router kept dropping wifi",
          "learning a few words of Portuguese", "the bike needed new brakes", "sorting old receipts",
          "a documentary about whales", "choosing a new desk lamp"]


def filled(brain):
    recall = brain.brain.recall
    for n, text in enumerate(FILLER):
        recall.add("turn", f"f{n}", "milk", "old", time.time() - 86400 * 30, f"they: {text}\nyou: Sure.")
    return recall


def said(brain, app, session, text, reply="Sure."):
    brain.provider.replies.append(reply)
    turn(brain, app, text, session=session)


def last_input(brain, app, session) -> str:
    return json.dumps(brain.store.events(app, session, types=("input",))[-1]["content"], ensure_ascii=False)


def old_note(brain, app, session, text, at=None):
    """A journal note, as the journal kept them before 0.30."""
    with brain.store._db() as db:
        db.execute("INSERT INTO journal(at, app, session, note) VALUES (?, ?, ?, ?)",
                   (time.time() if at is None else at, app, session, text))


def test_meaning_finds_what_words_miss(brain):
    recall = filled(brain)
    use(brain, Meaning())
    recall.add("turn", "1", "milk", "a", time.time() - 3 * 86400, "they: We planned a pixel-art platformer.")
    recall.sweep()
    hit = recall.search("what was that game idea")[0]
    assert "platformer" in hit["text"] and 0.0 < hit["relevance"] <= 1.0 and "lexical" not in hit


def test_an_exact_path_comes_back_by_meaning_too(brain):
    recall = filled(brain)
    use(brain, Meaning())
    recall.add("turn", "2", "milk", "a", time.time(), r"they: The notes are in C:\Users\me\plans.md")
    recall.sweep()
    assert recall.search(r"C:\Users\me\plans.md")[0]["ref"] == "2#0"


def test_nothing_unrelated_comes_back(brain):
    recall = filled(brain)
    use(brain, Meaning())
    recall.add("turn", "3", "milk", "a", time.time(), "they: We planned a pixel-art platformer.")
    recall.sweep()
    assert recall.search("quantum tax law") == []


def test_long_and_cyrillic_text_is_kept_whole(brain):
    recall = filled(brain)
    use(brain, Meaning())
    assert len(recall.add("turn", "4", "milk", "a", time.time(), "ж" * 5000)) == 4
    assert all(len(piece) <= CHUNK for piece in chunks("x" * 5000)) and "".join(chunks("ab" * 900))[:1800] == "ab" * 900
    recall.add("turn", "5", "milk", "a", time.time(), "они обсуждали платформер про котов")
    recall.sweep()
    assert recall.search("они обсуждали платформер про котов", sources=("turn",))[0]["ref"] == "5#0"


@pytest.mark.mind
def test_what_comes_back_is_written_into_the_turn_and_stays_in_the_log(brain):
    filled(brain)
    use(brain, Meaning())
    brain.client.update_session("milk", "a", title="Pixel game")
    said(brain, "milk", "a", "let's make a pixel-art platformer", "Yes! A small one first.")
    brain.brain.recall.sweep()
    said(brain, "milk", "b", "remember that game idea?")
    seen = last_input(brain, "milk", "b")
    assert HEADER in seen and "pixel-art platformer" in seen and '\\"Pixel game\\"' in seen
    said(brain, "milk", "a", "and the game idea, the levels?")  # her own chat she has before her: not again
    assert "pixel-art platformer" not in last_input(brain, "milk", "a").split(HEADER)[-1]
    said(brain, "milk", "c", "what's 2+2")
    assert HEADER not in last_input(brain, "milk", "c")


def test_her_chat_comes_back_from_before_its_compaction(brain):
    filled(brain)
    use(brain, Meaning())
    said(brain, "milk", "a", "let's make a pixel-art platformer")
    brain.brain.recall.sweep()
    brain.store.add_event("milk", "a", None, "compaction", {"summary": "We talked."})
    note = brain.brain.recall.note({"kind": "turn", "app": "milk", "session": "a"}, "that game idea?")
    assert note and "pixel-art platformer" in note


@pytest.mark.mind
def test_with_the_service_down_nothing_comes_back_and_a_search_says_why(brain):
    filled(brain)
    use(brain, Meaning(problem="the embeddings service failed: 503"))
    said(brain, "milk", "a", "let's make a pixel-art platformer")
    brain.brain.recall.sweep()
    said(brain, "milk", "b", "that pixel-art platformer?")  # the turn goes on, without
    assert HEADER not in last_input(brain, "milk", "b")
    ctx = SimpleNamespace(brain=brain.brain, store=brain.store, app="milk", session="b", run={"kind": "turn"},
                          profile={}, call_id="c")
    with pytest.raises(ToolError, match="cannot be searched now: the embeddings service failed: 503"):
        sessions_kit.sessions_search.func(ctx, "platformer")


def test_a_deleted_chat_never_comes_back(brain):
    filled(brain)
    use(brain, Meaning())
    said(brain, "milk", "s", "my secret plan is a pixel-art platformer")
    old_note(brain, "milk", "s", "We planned a secret platformer.")
    recall = brain.brain.recall
    recall.sweep()
    assert recall.search("secret platformer", sources=("turn", "note"))
    brain.client.delete_session("milk", "s")
    recall.sweep()  # its journal note is still in the journal: it does not come back either
    assert not recall.search("secret platformer", sources=("turn", "note"))


def test_a_cleared_chat_is_not_brought_back_and_what_is_said_after_is(brain):
    filled(brain)
    use(brain, Meaning())
    said(brain, "milk", "s", "my secret plan is a pixel-art platformer")
    recall = brain.brain.recall
    recall.sweep()
    brain.client.clear_history("milk", "s")
    said(brain, "milk", "s", "my cat is called Biscuit")
    recall.sweep()
    assert not recall.search("secret platformer", sources=("turn",))
    assert "Biscuit" in recall.search("my pet", sources=("turn",))[0]["text"]


def test_a_return_to_a_message_forgets_what_it_undid(brain):
    filled(brain)
    use(brain, Meaning())
    said(brain, "milk", "main", "we planned a pixel-art platformer")
    said(brain, "milk", "main", "my cat died yesterday")
    recall = brain.brain.recall
    recall.sweep()
    second = [e for e in brain.brain.history("milk", "main") if e["role"] == "user"][1]["id"]
    brain.client.rewind("milk", "main", second)
    recall.sweep()
    assert recall.search("platformer game") and not recall.search("our pet passed away")


@pytest.mark.mind
def test_a_note_and_a_fact_kept_before_come_back_by_meaning_in_a_turn(brain):
    filled(brain)
    use(brain, Meaning())
    brain.client.update_session("milk", "old", title="Work talk")
    brain.store.remember("milk", "user", "job", "works as an interpreter")
    old_note(brain, "milk", "old", "We talked about their pet cat Biscuit.", at=time.time() - 86400)
    brain.brain.recall.sweep()
    said(brain, "milk", "new", "what is my job?")
    assert "something you kept: job: works as an interpreter" in last_input(brain, "milk", "new")
    said(brain, "milk", "new", "what was my cat called?")
    seen = last_input(brain, "milk", "new")
    assert 'your note about \\"Work talk\\": We talked about their pet cat Biscuit.' in seen


def test_a_faded_episode_is_gone_with_its_vector(brain):
    recall = brain.brain.recall
    use(brain, Meaning())
    episode = brain.brain.mind.memory.add("exchange", "they told me about their cat", 0.2, 0.3, 0.1, at=1.0)
    recall.sweep()
    assert brain.brain.mind.memory.vectors.count("meaning@64") == 1
    brain.brain.mind.memory.forget_faint(time.time())
    assert brain.brain.mind.memory.vectors.count("meaning@64") == 0 and episode


def test_a_changed_model_embeds_everything_again(brain):
    said(brain, "milk", "a", "we planned a pixel-art platformer")
    recall = brain.brain.recall
    recall.sweep()
    status = brain.client.stats()["recall"]
    assert status["state"] == "ready" and status["embedded"] == status["units"] > 0
    with recall._sweeping:
        brain.client.update_config(embeddings_model="other")
        assert brain.client.stats()["recall"]["embedded"] == 0
    recall.sweep()
    status = brain.client.stats()["recall"]
    assert status["embedded"] == status["units"] and recall.vectors.count("stand-in:default@256") == 0


def test_her_mind_and_her_long_term_memory_cannot_be_switched_off(brain):
    for switch in ({"embeddings": "off"}, {"mind": False}, {"session_summaries": False}):
        with pytest.raises(BrainError, match="Unknown setting"):
            brain.client.update_config(**switch)


def test_in_her_sleep_what_she_no_longer_needs_lets_go_and_stays_gone(brain):
    recall, now, long_ago = brain.brain.recall, time.time(), time.time() - 400 * 86400
    use(brain, Meaning())
    recall.add("turn", "1", "milk", "a", long_ago, "they: hi hello\nyou: hey")
    recall.add("turn", "2", "milk", "b", long_ago, "they: hello hi\nyou: hey")  # the same said again
    recall.add("turn", "3", "milk", "c", long_ago, "they: my cat died\nyou: I am sorry about your pet")
    recall.add("turn", "4", "milk", "d", long_ago, "they: the tax deadline\nyou: april")
    recall.add("turn", "5", "milk", "e", long_ago, "they: the tax deadline\nyou: april")
    brain.client.update_session("milk", "main", title="Today")
    for _ in range(2):
        old_note(brain, "milk", "main", "We sketched levels for the platformer.", at=long_ago)
    recall.sweep()
    recall._db.execute("UPDATE units SET uses = 3 WHERE ref = '4#0'")  # she came back to it
    assert recall.search("my cat died")[0]["ref"] == "3#0"  # and to this one: what comes back is stronger
    assert recall._db.execute("SELECT uses FROM units WHERE ref = '3#0'").fetchone()[0] == 1
    # one of each alike pair goes (held by the other, or by the one she came back to); the rest stay: a memory
    # nothing else holds lasts decades unused
    assert recall.forget(now, sleep_review=True) == 3
    assert recall.forget(now, sleep_review=True) == 0
    assert {r[0] for r in recall._db.execute("SELECT ref FROM units WHERE source = 'turn'")} == {"2#0", "3#0", "4#0"}
    assert recall._db.execute("SELECT text FROM forgotten WHERE ref = '1#0'").fetchone()[0].startswith("they: hi")
    recall.sweep()  # a note she let go of is not taken in again
    assert recall._db.execute("SELECT COUNT(*) FROM units WHERE source = 'note'").fetchone()[0] == 1
    assert brain.client.stats()["recall"]["forgotten"] == 3
    recall.forget_session("milk", "a")  # a deleted chat leaves nothing, not even what she let go of
    assert brain.client.stats()["recall"]["forgotten"] == 2

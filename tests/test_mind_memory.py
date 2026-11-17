"""Her episodic memory: recalled by likeness and by mood, strengthened by recall, softened by sleep, and
what is faint and unimportant fades away."""

from sentientmilk_framework.mind.memory import Memory, line

DAY = 86400.0
NOW = 1_763_294_400.0


def memory(tmp_path, seed=0):
    return Memory(tmp_path / "mind.sqlite3", seed=seed)


def test_a_cue_brings_back_what_is_like_it(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "The user showed me their RimWorld colony and the raid that burned the farms",
             0.3, 0.6, 0.6, at=NOW - DAY)
    mind.add("exchange", "We talked about taxes and the deadline in April", -0.2, 0.4, 0.4, at=NOW - DAY)
    found = mind.recall("how is the rimworld colony doing?", 0.0, NOW)
    assert "RimWorld" in found[0]["text"]
    assert all("taxes" not in episode["text"] for episode in found[:1])


def test_what_she_still_has_before_her_is_not_brought_back_and_a_resting_mind_replays_at_random(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "we talked about the garden today", 0.2, 0.4, 0.5, app="milk", session="main", at=NOW - 600)
    mind.add("exchange", "the garden flooded in spring", -0.3, 0.5, 0.6, app="milk", session="main", at=NOW - 9 * DAY)
    mind.add("exchange", "a garden party with the neighbours", 0.5, 0.5, 0.5, app="milk", session="other", at=NOW - 300)
    held = ("milk", "main", NOW - DAY)  # her context holds that chat since yesterday
    texts = [e["text"] for e in mind.recall("the garden", 0.0, NOW, count=5, strengthen=False, held=held)]
    assert "we talked about the garden today" not in texts and len(texts) == 2
    assert len(mind.recall("the garden", 0.0, NOW, count=5, strengthen=False)) == 3
    replayed = mind.replay(2)
    assert len(replayed) == 2 and replayed[0]["id"] != replayed[1]["id"] and len(mind.replay(9)) == 3


def test_a_mood_finds_memories_of_its_own_kind(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "the user and I played chess, I won and they laughed", 0.8, 0.5, 0.5, at=NOW - DAY)
    mind.add("exchange", "the user and I played chess, I lost and they mocked me", -0.8, 0.5, 0.5, at=NOW - DAY)
    sad = [mind.recall("chess", -0.9, NOW, count=1, strengthen=False)[0]["valence"] for _ in range(20)]
    glad = [mind.recall("chess", 0.9, NOW, count=1, strengthen=False)[0]["valence"] for _ in range(20)]
    assert sum(v < 0 for v in sad) >= 15 and sum(v > 0 for v in glad) >= 15


def test_recalling_strengthens_a_memory_and_colours_it_with_the_mood_she_recalls_it_in(tmp_path):
    mind = memory(tmp_path)
    episode = mind.add("exchange", "the user forgot my name", -0.6, 0.6, 0.6, at=NOW - 10 * DAY)
    before = mind.recent(1)[0]
    faded = Memory.strength_now(before, NOW)
    mind.recall("my name", 0.6, NOW)
    after = mind.recent(1)[0]
    assert after["id"] == episode and after["recalls"] == 1
    assert Memory.strength_now(after, NOW) > faded and after["valence"] > before["valence"]


def test_sleep_softens_what_she_replays(tmp_path):
    mind = memory(tmp_path)
    episode = mind.add("exchange", "a frightening error ate the user's work", -0.9, 0.9, 0.9, at=NOW)
    mind.soften([episode])
    assert mind.recent(1)[0]["charge"] < 0.7


def test_faint_unimportant_memories_fade_away_and_what_mattered_stays(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "small talk about the weather", 0.1, 0.1, 0.05, at=NOW - 400 * DAY)
    mind.add("exchange", "the day the user told me their dog died", -0.8, 0.8, 0.9, at=NOW - 400 * DAY)
    assert mind.forget_faint(NOW) == 1 and "dog" in mind.recent(1)[0]["text"]


def test_since_gives_the_most_charged_first_and_words_survive_odd_characters(tmp_path):
    mind = memory(tmp_path)
    mind.add("thought", "nothing much", 0.0, 0.1, 0.1, at=NOW)
    mind.add("exchange", "they shouted at me", -0.9, 0.9, 0.9, at=NOW)
    assert mind.since(NOW - 10)[0]["text"] == "they shouted at me"
    assert mind.recall('"unbalanced quote OR (* NEAR', 0.0, NOW) is not None  # no FTS syntax from her words
    assert "minutes ago" in line(mind.recent(1)[0], NOW + 600)


def test_a_message_like_her_memories_is_familiar_and_what_followed_such_messages_comes_back(tmp_path):
    mind = memory(tmp_path)
    for text, follows in (("The user said: lol you idiot, do it again. I said: Ha.", {"company": 0.8, "free": 0.1}),
                          ("The user said: you idiot, again! I said: Hehe.", {"company": 0.6, "free": 0.0}),
                          ("The user said: fix the parser please. I did it.", {"company": 0.1, "free": 0.0}),
                          ("I wondered about tomatoes in the cold", None)):
        episode = mind.add("exchange" if follows else "thought", text, 0.0, 0.3, 0.4, at=NOW - DAY)
        if follows:
            mind.follow(episode, follows)
    likeness, followed, evidence = mind.known("lol you idiot, do it again", before=NOW)
    assert likeness > 0.6 and evidence > 0.6 and 0.6 < followed["company"] <= 0.8
    new, _, _ = mind.known("siphonophores are colonies of tiny animals", before=NOW)
    assert new < 0.2
    assert mind.known("ok", before=NOW) == (None, {}, 0.0)  # no words to go by
    assert mind.known("lol you idiot", before=NOW - 2 * DAY)[0] == 0.0  # only what came before


def test_a_mind_from_before_gains_what_followed_its_exchanges(tmp_path):
    import sqlite3
    old = sqlite3.connect(str(tmp_path / "mind.sqlite3"))
    old.executescript("CREATE TABLE episodes (id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, "
                      "text TEXT NOT NULL, app TEXT, session TEXT, valence REAL NOT NULL, arousal REAL NOT NULL, "
                      "salience REAL NOT NULL, strength REAL NOT NULL, recalls INTEGER NOT NULL DEFAULT 0, "
                      "recalled REAL, charge REAL NOT NULL);")
    old.close()
    mind = memory(tmp_path)
    mind.follow(mind.add("exchange", "hello there friend", 0.1, 0.2, 0.3, at=NOW), {"company": 0.5})
    assert mind.known("hello friend", before=NOW + 1)[1] == {"company": 0.5}


def test_her_own_state_is_kept_beside_her_memories(tmp_path):
    mind = memory(tmp_path)
    mind.put("body", {"levels": {"cortisol": 0.4}})
    assert memory(tmp_path).get("body") == {"levels": {"cortisol": 0.4}} and mind.get("nothing", 1) == 1


def embedded(mind, embedder):
    """Her memory with an embedder, its episodes embedded as her long-term memory's sweep does."""
    mind.embedder = embedder
    found = mind.vectors.texts(mind.vectors.pending(embedder.name, 1000))
    mind.vectors.put([(i, row) for (i, _), row in zip(found, embedder.embed([t for _, t in found]))], embedder.name)
    return mind


def test_she_recalls_by_meaning_as_well_as_by_words(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    mind.add("exchange", "Our pet passed away last spring", -0.8, 0.6, 0.8, at=NOW - 30 * DAY)
    mind.add("exchange", "We talked about taxes and the deadline in April", -0.2, 0.4, 0.4, at=NOW - DAY)
    assert not [e for e in mind.recall("my cat died", -0.5, NOW, strengthen=False) if e["relevance"]]  # no shared word
    embedded(mind, Meaning())
    found = mind.recall("my cat died", -0.5, NOW)
    assert found[0]["text"] == "Our pet passed away last spring" and found[0]["relevance"] > 0.5


def test_a_greeting_in_other_words_is_not_new_to_her(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    for n in range(10):
        episode = mind.add("exchange", "hello there", 0.3, 0.2, 0.2, at=NOW - n * DAY)
        mind.follow(episode, {"social": 0.1})
    assert mind.known("hi", before=NOW)[0] is None  # no word of three letters: nothing to go by
    embedded(mind, Meaning())
    likeness, followed, evidence = mind.known("hi", before=NOW)
    assert likeness > 0.5 and followed["social"] > 0.05 and evidence > 1.0


def test_without_its_service_she_recalls_by_words_as_before(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    mind.add("exchange", "The user showed me their RimWorld colony", 0.3, 0.6, 0.6, at=NOW - DAY)
    mind.embedder = Meaning(problem="the embeddings service failed: 503")
    assert "RimWorld" in mind.recall("how is the rimworld colony doing?", 0.0, NOW)[0]["text"]


def test_of_two_alike_faint_memories_the_one_the_other_holds_goes(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    for text in ("we said hello and hi", "we said hi and hello", "the tax deadline in April"):
        mind.add("exchange", text, 0.1, 0.1, 0.2, at=NOW - 40 * DAY)
    assert mind.forget_faint(NOW) == 0  # by strength alone all of them stay this long
    embedded(mind, Meaning())
    assert mind.forget_faint(NOW) == 1
    assert sorted(e["text"] for e in mind.recent(5)) == ["the tax deadline in April", "we said hi and hello"]

"""Her episodic memory: recalled by likeness in meaning and by mood, strengthened by recall, softened by sleep,
and what is faint and unimportant fades away."""

from conftest import Meaning

from sentientmilk_framework.mind.memory import Memory, line

DAY = 86400.0
NOW = 1_763_294_400.0


def memory(tmp_path, seed=0):
    """Her episodic memory, with an embedder that knows what means the same (her long-term memory's)."""
    mind = Memory(tmp_path / "mind.sqlite3", seed=seed)
    mind.embedder = Meaning()
    return mind



def test_a_cue_brings_back_what_is_like_it(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "The user showed me their RimWorld colony and the raid that burned the farms",
             0.3, 0.6, 0.6, at=NOW - DAY)
    mind.add("exchange", "We talked about taxes and the deadline in April", -0.2, 0.4, 0.4, at=NOW - DAY)
    found = embedded(mind, mind.embedder).recall("how is the rimworld colony doing?", 0.0, NOW)
    assert [e["text"] for e in found] == ["The user showed me their RimWorld colony and the raid that burned the farms"]


def test_only_what_the_cue_calls_up_comes_back(tmp_path):
    """Her strongest memories came back with every message, related or not, each recall making them stronger
    (a brooding thought of hers with 11 of 21 messages, the user's brain, 2026-11-17)."""
    mind = memory(tmp_path)
    mind.add("thought", "I keep thinking about their assignments", -0.6, 0.7, 0.9, at=NOW - 600)
    mind.add("exchange", "My cat knocked the plant over", 0.2, 0.4, 0.3, at=NOW - DAY)
    embedded(mind, mind.embedder)
    for _ in range(5):
        assert [e["text"] for e in mind.recall("the cat again", -0.6, NOW)] == ["My cat knocked the plant over"]
    assert mind.recent(5, kinds=("thought",))[0]["recalls"] == 0  # never brought back, never made stronger


def test_what_she_still_has_before_her_is_not_brought_back_and_a_resting_mind_replays_at_random(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "we talked about my cat today", 0.2, 0.4, 0.5, app="milk", session="main", at=NOW - 600)
    mind.add("exchange", "the dog was ill in spring", -0.3, 0.5, 0.6, app="milk", session="main", at=NOW - 9 * DAY)
    mind.add("exchange", "a pet show with the neighbours", 0.5, 0.5, 0.5, app="milk", session="other", at=NOW - 300)
    embedded(mind, mind.embedder)
    held = ("milk", "main", NOW - DAY)  # her context holds that chat since yesterday
    texts = [e["text"] for e in mind.recall("my pet", 0.0, NOW, count=5, strengthen=False, held=held)]
    assert "we talked about my cat today" not in texts and len(texts) == 2
    assert len(mind.recall("my pet", 0.0, NOW, count=5, strengthen=False)) == 3
    replayed = mind.replay(2)
    assert len(replayed) == 2 and replayed[0]["id"] != replayed[1]["id"] and len(mind.replay(9)) == 3


def test_a_mood_finds_memories_of_its_own_kind(tmp_path):
    mind = memory(tmp_path)
    mind.add("exchange", "chess with the user: I won", 0.8, 0.5, 0.5, at=NOW - DAY)  # alike to the cue
    mind.add("exchange", "chess with the user: I lost", -0.8, 0.5, 0.5, at=NOW - DAY)
    embedded(mind, mind.embedder)
    sad = [mind.recall("chess", -0.9, NOW, count=1, strengthen=False)[0]["valence"] for _ in range(20)]
    glad = [mind.recall("chess", 0.9, NOW, count=1, strengthen=False)[0]["valence"] for _ in range(20)]
    assert sum(v < 0 for v in sad) >= 15 and sum(v > 0 for v in glad) >= 15


def test_recalling_strengthens_a_memory_and_colours_it_with_the_mood_she_recalls_it_in(tmp_path):
    mind = memory(tmp_path)
    episode = mind.add("exchange", "the user forgot my name", -0.6, 0.6, 0.6, at=NOW - 10 * DAY)
    before = embedded(mind, mind.embedder).recent(1)[0]
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
    assert mind.recall('"unbalanced quote OR (* NEAR', 0.0, NOW) is not None  # odd characters are only text
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
    embedded(mind, mind.embedder)
    likeness, followed, evidence = mind.known("lol you idiot, do it again", before=NOW)
    assert likeness > 0.5 and evidence > 0.5 and 0.6 < followed["company"] <= 0.8
    new, _, _ = mind.known("siphonophores are colonies of tiny animals", before=NOW)
    assert new < 0.2
    assert Memory(tmp_path / "other.sqlite3").known("lol you idiot", before=NOW) == (None, {}, 0.0)  # no meaning
    assert mind.known("lol you idiot", before=NOW - 2 * DAY)[0] == 0.0  # only what came before
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


def test_she_recalls_by_meaning(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    mind.add("exchange", "Our pet passed away last spring", -0.8, 0.6, 0.8, at=NOW - 30 * DAY)
    mind.add("exchange", "We talked about taxes and the deadline in April", -0.2, 0.4, 0.4, at=NOW - DAY)
    assert not [e for e in mind.recall("my cat died", -0.5, NOW, strengthen=False) if e["relevance"]]  # not embedded yet
    embedded(mind, Meaning())
    found = mind.recall("my cat died", -0.5, NOW)
    assert found[0]["text"] == "Our pet passed away last spring" and found[0]["relevance"] > 0.5


def test_a_greeting_in_other_words_is_not_new_to_her(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    for n in range(10):
        episode = mind.add("exchange", "hello there", 0.3, 0.2, 0.2, at=NOW - n * DAY)
        mind.follow(episode, {"social": 0.1})
    assert mind.known("hi", before=NOW)[0] == 0.0  # not embedded yet: nothing like it
    embedded(mind, Meaning())
    likeness, followed, evidence = mind.known("hi", before=NOW)
    assert likeness > 0.5 and followed["social"] > 0.05 and evidence > 1.0


def test_without_its_service_nothing_comes_back(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    mind.add("exchange", "The user showed me their RimWorld colony", 0.3, 0.6, 0.6, at=NOW - DAY)
    embedded(mind, mind.embedder).embedder = Meaning(problem="the embeddings service failed: 503")
    assert mind.recall("how is the rimworld colony doing?", 0.0, NOW) == []  # she cannot tell what is alike
    assert mind.known("the rimworld colony", before=NOW) == (None, {}, 0.0)  # she cannot tell


def test_of_two_alike_faint_memories_the_one_the_other_holds_goes(tmp_path):
    from conftest import Meaning
    mind = memory(tmp_path)
    for text in ("we said hello and hi", "we said hi and hello", "the tax deadline in April"):
        mind.add("exchange", text, 0.1, 0.1, 0.2, at=NOW - 40 * DAY)
    assert mind.forget_faint(NOW) == 0  # by strength alone all of them stay this long
    embedded(mind, Meaning())
    assert mind.forget_faint(NOW) == 1
    assert sorted(e["text"] for e in mind.recent(5)) == ["the tax deadline in April", "we said hi and hello"]


OTHER = ["We talked about taxes and the deadline in April", "The user showed me a platformer level they built",
         "Their cat knocked a glass off the desk", "They asked how to keep basil alive on a windowsill",
         "We planned a walk to the river on Sunday", "They said the new keyboard clicks too loudly",
         "I read about how bread rises overnight", "They were annoyed that the train was late again",
         "We argued about which film to watch tonight", "They fixed the wobbly chair with a folded card"]


def test_an_old_memory_comes_back_with_what_came_of_it_and_a_set_right_one_with_what_it_was(tmp_path):
    # the audit (finding 3): her guess that the user buys 2% milk came back twice and the user's "it's 3.2%" never;
    # at 20:46 a thought of hers had the essay skeleton still in the folder two hours after she deleted it as asked
    mind = memory(tmp_path)
    for index, text in enumerate(OTHER):
        mind.add("exchange", text, 0.0, 0.3, 0.3, at=NOW - 5 * DAY + index)
    guess = mind.add("exchange", "They asked when the interpreter job starts. I said: in May, I think",
                     0.2, 0.4, 0.5, at=NOW - DAY)
    mind.add("thought", "The interpreter job in May, I am sure of it", 0.0, 0.3, 0.3, at=NOW - DAY + 60)
    fixed = mind.add("exchange", "They said: the interpreter job starts in June, not May", 0.3, 0.4, 0.5,
                     at=NOW - DAY + 120)
    embedded(mind, mind.embedder)
    came = {e["id"]: e for e in mind.recall("when does their interpreter job start", 0.0, NOW, count=4,
                                            strengthen=False)}
    assert came[guess]["later"]["id"] == fixed  # what came of it: what was said after, not her own later thought
    assert not came[fixed].get("later")
    told = line(came[guess], NOW)
    assert "What came of it (" in told and "June" in told.split("What came of it")[1]
    mind.supersede(guess, fixed)  # set right (by a correction, or in her sleep): the guess is what it was
    back = mind.recall("when does their interpreter job start", 0.0, NOW, count=4, strengthen=False)
    assert guess not in [e["id"] for e in back]
    now_kept = next(e for e in back if e["id"] == fixed)
    assert "in May, I think" in now_kept["was"] and "Before it was set right: " in line(now_kept, NOW)

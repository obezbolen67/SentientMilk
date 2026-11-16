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


def test_her_own_state_is_kept_beside_her_memories(tmp_path):
    mind = memory(tmp_path)
    mind.put("body", {"levels": {"cortisol": 0.4}})
    assert memory(tmp_path).get("body") == {"levels": {"cortisol": 0.4}} and mind.get("nothing", 1) == 1

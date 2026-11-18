"""Her memories as a network, for an app to draw: every memory with its real values, and the links she has."""

from conftest import Meaning
from test_mind_memory import DAY, NOW, embedded, memory


def kept(tmp_path):
    mind = memory(tmp_path)
    first = mind.add("exchange", "Sam said the cat died last spring", -0.8, 0.6, 0.9, app="milk", session="a",
                     at=NOW - 3 * DAY, sting=-0.5, felt={"cortisol": 0.4}, cues=["playing: Clair de Lune"])
    second = mind.add("exchange", "Sam said the dog is fine", 0.4, 0.3, 0.4, app="milk", session="a",
                      at=NOW - 3 * DAY + 60, cues=["playing: Clair de Lune"])
    third = mind.add("exchange", "We sorted the taxes before the deadline", 0.1, 0.4, 0.3, app="milk", session="b",
                     at=NOW - DAY, cues=["in front: spreadsheet", "playing: lo-fi beats"])
    for song in ("rain sounds", "jazz"):  # other days, other songs: the one they share is rare
        mind.add("event", f"A quiet evening with {song}", 0.2, 0.2, 0.2, at=NOW - 5 * DAY, cues=[f"playing: {song}"])
    insight = mind.add("insight", "Losing a pet stays with Sam", -0.3, 0.3, 0.6, at=NOW - DAY / 2,
                       origins=[first, second])
    return mind, first, second, third, insight


def test_every_memory_comes_with_its_real_values(tmp_path):
    mind, first, *_rest = kept(tmp_path)
    network = mind.network()
    found = {episode["id"]: episode for episode in network["episodes"]}
    assert len(found) == 6 and found[first]["text"] == "Sam said the cat died last spring"
    episode = found[first]
    assert (episode["kind"], episode["valence"], episode["sting"], episode["felt"]) == ("exchange", -0.8, -0.5,
                                                                                       {"cortisol": 0.4})
    assert episode["strength"] == 0.95 and episode["recalls"] == 0 and episode["charge"] == 1.0
    assert episode["cues"] == ["playing: clair de lune"]


def test_its_links_are_the_ones_she_has(tmp_path):
    mind, first, second, third, insight = kept(tmp_path)
    links = {(a, b, kind): weight for a, b, kind, weight in mind.network()["links"]}
    assert (first, second, "then") in links  # one chat's moments, in order
    assert (second, third, "then") not in links  # another chat is not what followed
    assert links[(insight, first, "origin")] == 1.0 and (insight, second, "origin") in links  # made in her sleep
    assert 0.5 < links[(first, second, "cue")] < 0.6  # what was around both, rare among her songs (2 of 5)
    assert not any(kind == "cue" and third in (a, b) for a, b, kind in links)
    assert not any(kind == "meaning" for _a, _b, kind in links)  # meaning needs her embedder


def test_alike_in_meaning_on_the_scale_her_sleep_forgets_by(tmp_path):
    mind, first, second, third, insight = kept(tmp_path)
    embedder = Meaning()
    embedded(mind, embedder)
    network = mind.network(embedder.name)
    meaning = {(a, b): weight for a, b, kind, weight in network["links"] if kind == "meaning"}
    assert (min(first, insight), max(first, insight)) in meaning  # the pet, both
    assert all(0.0 < weight <= 1.0 for weight in meaning.values())
    assert (min(first, third), max(first, third)) not in meaning  # a pet and taxes
    floor = mind.vectors.usual(embedder.name)  # nearer than a memory's nearest usually is
    ids, rows = mind.vectors._matrix(embedder.name)
    at = {int(i): n for n, i in enumerate(ids)}
    cosine = float(rows[at[first]] @ rows[at[insight]])
    assert abs(meaning[(min(first, insight), max(first, insight))] - (cosine - floor) / (1 - floor)) < 1e-3


def test_its_revision_changes_only_when_her_memory_does(tmp_path):
    mind, first, *_rest = kept(tmp_path)
    before = mind.network()["revision"]
    assert mind.revision() == before and mind.network()["revision"] == before
    mind.reevoked(mind.by_ids([first])[0])  # recalled
    recalled = mind.revision()
    assert recalled != before
    mind.add("thought", "I wonder how the dog is", 0.2, 0.3, 0.3, at=NOW)
    assert mind.revision() != recalled


def test_an_app_asks_for_the_network_when_her_memory_changed(brain):
    from test_mind_life import mind_on
    mind = mind_on(brain)
    mind.memory.add("exchange", "Sam said hello", 0.3, 0.3, 0.3, app="milk", session="main")
    state = brain.client.mind("milk", idle=2)
    assert state["memory"] == {"revision": mind.memory.revision(), "count": 1}
    network = brain.client.memory_network()
    assert network["revision"] == state["memory"]["revision"]
    assert [episode["text"] for episode in network["episodes"]] == ["Sam said hello"]

"""Vectors beside SQLite rows: nearest by cosine, one model at a time, gone with their rows."""

import sqlite3
import threading
import time

import numpy as np

from sentientmilk_framework.embeddings import StandIn, unit
from sentientmilk_framework.vectors import CALIBRATION, Vectors


def store(rows=0):
    db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT)")
    db.executemany("INSERT INTO notes (id, text) VALUES (?, ?)", [(i, f"note {i}") for i in range(1, rows + 1)])
    return db, Vectors(db, "notes", threading.RLock())


def test_the_nearest_of_one_model_only_and_only_where_asked():
    db, vectors = store(3)
    vectors.put([(1, unit([[1, 0, 0]])[0]), (2, unit([[0.8, 0.6, 0]])[0]), (3, unit([[0, 0, 1]])[0])], "a")
    assert [i for i, _ in vectors.nearest(unit([[1, 0, 0]])[0], "a", 2)] == [1, 2]
    assert vectors.nearest(unit([[1, 0, 0]])[0], "a", 3, where={2, 3})[0][0] == 2
    vectors.put([(1, unit([[0, 1, 0]])[0])], "b")  # a row keeps one vector: another model's takes its place
    assert vectors.nearest(unit([[1, 0, 0]])[0], "b", 3) == [(1, 0.0)]
    assert [i for i, _ in vectors.nearest(unit([[1, 0, 0]])[0], "a", 3)] == [2, 3]
    assert vectors.pending("b", 10) == [3, 2] and vectors.texts([3, 9]) == [(3, "note 3")]


def test_a_vector_goes_with_its_row_and_a_changed_text_needs_a_new_one():
    db, vectors = store(2)
    vectors.put([(1, unit([[1, 0]])[0]), (2, unit([[0, 1]])[0])], "a")
    assert len(vectors.nearest(unit([[1, 0]])[0], "a", 5)) == 2
    db.execute("DELETE FROM notes WHERE id = 1")
    db.execute("UPDATE notes SET text = 'new words' WHERE id = 2")
    assert vectors.nearest(unit([[1, 0]])[0], "a", 5) == [] and vectors.pending("a", 5) == [2]
    vectors.put([(2, unit([[0, 1]])[0])], "a")
    vectors.drop(other_than="z")
    assert vectors.count("a") == 0


def test_related_is_measured_against_what_an_unrelated_question_reaches():
    db, vectors = store(3)
    e = StandIn()
    rows = e.embed(["we planned a pixel platformer", "the tax deadline in april", "my cat sleeps all day"])
    vectors.put(list(zip((1, 2, 3), rows)), e.name)
    floor = vectors.floor(e)
    reached = float((e.embed(list(CALIBRATION), query=True) @ rows.T).max())
    assert floor == min(0.95, reached) and 0.0 < floor < 1.0
    assert vectors.relevance(floor, e) == 0.0 and vectors.relevance(1.0, e) == 1.0
    assert vectors.floor(StandIn("other")) == 1.0  # none of its vectors yet: nothing is related


def test_a_search_over_fifty_thousand_takes_milliseconds():
    db, vectors = store(50_000)
    rows = unit(np.random.default_rng(2).normal(size=(50_000, 256)))
    vectors.put([(i + 1, row) for i, row in enumerate(rows)], "a")
    vectors.nearest(rows[0], "a", 40)  # loads the matrix once
    took = min(_time(lambda: vectors.nearest(rows[7], "a", 40)) for _ in range(3))
    assert vectors.nearest(rows[7], "a", 1)[0][0] == 8 and took < 0.05


def _time(call):
    start = time.perf_counter()
    call()
    return time.perf_counter() - start

"""Her data has one shape, the current one: each database is stamped with it when it is made, and data of another
shape is refused, never read by code that knows old shapes (a migration script brings it to this one, once)."""

import sqlite3
from types import SimpleNamespace

import pytest

from sentientmilk_framework import dataformat
from sentientmilk_framework.mind.memory import Memory
from sentientmilk_framework.recall import Recall
from sentientmilk_framework.store import Store


def opened(kind, path):
    if kind == "brain":
        return Store(path)
    if kind == "mind":
        return Memory(path)
    return Recall(SimpleNamespace(config=SimpleNamespace(values=lambda: {})), path)


@pytest.mark.parametrize("kind", ["brain", "mind", "recall"])
def test_a_new_database_is_made_in_the_current_format_and_opens_again(tmp_path, kind):
    path = tmp_path / f"{kind}.sqlite3"
    opened(kind, path)
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == dataformat.FORMAT
    opened(kind, path)


@pytest.mark.parametrize("kind", ["brain", "mind", "recall"])
def test_data_of_another_shape_is_refused_and_left_as_it_was(tmp_path, kind):
    path = tmp_path / f"{kind}.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY)")  # made by a SentientMilk before the stamp
    db.commit()
    db.close()
    with pytest.raises(dataformat.WrongFormat, match="migration"):
        opened(kind, path)
    db = sqlite3.connect(path)
    assert [row[0] for row in db.execute("SELECT name FROM sqlite_master")] == ["episodes"]
    assert db.execute("PRAGMA user_version").fetchone()[0] == 0

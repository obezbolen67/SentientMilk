"""The shape of her data. Each database (brain, mind, long-term memory) is stamped with ``FORMAT`` (SQLite's
user_version) when it is made, and opens only at that format. Data of another shape is brought to this one by a
migration script, run once on the stopped brain (it lives in the git history of the change that needed it); the
code here knows only the current shape. A change to any table's shape raises ``FORMAT`` and comes with its script.
"""

import sqlite3
from pathlib import Path
from typing import Union

FORMAT = 3


class WrongFormat(RuntimeError):
    """A database of another shape: the brain does not start on it."""


def opened(db: sqlite3.Connection, path: Union[str, Path]) -> None:
    """Stamp a database that is new (nothing in it yet) with the current format; refuse one of another."""
    found = db.execute("PRAGMA user_version").fetchone()[0]
    if found == FORMAT:
        return
    if found == 0 and db.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0:
        db.execute(f"PRAGMA user_version = {FORMAT}")
        return
    raise WrongFormat(f"{path} holds data of format {found}, not {FORMAT}: bring it to format {FORMAT} with its "
                      "migration script (in SentientMilk's git history) before the brain starts on it")

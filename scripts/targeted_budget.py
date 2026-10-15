"""Cross-process round lock and durable reservations for the declared API caps."""
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4


class TargetedBudget:
    LIMITS: ClassVar[dict[str, int]] = {"glm": 24, "dino": 2}

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS reservations (identity TEXT PRIMARY KEY, kind TEXT, created_at TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS round_lock (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT)")

    def reserve(self, identity: str, kind: str):
        if kind not in self.LIMITS:
            raise ValueError("Unknown request kind")
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("SELECT count(*) FROM reservations WHERE kind=?", (kind,)).fetchone()[0]
            if count >= self.LIMITS[kind]:
                raise ValueError("Declared whole-round request cap exhausted; no request sent")
            try:
                connection.execute("INSERT INTO reservations VALUES (?,?,?)", (
                    identity, kind, datetime.now(UTC).isoformat()))
            except sqlite3.IntegrityError:
                raise ValueError("Request identity already reserved; no duplicate request sent") from None

    @contextmanager
    def exclusive(self):
        owner = uuid4().hex
        with sqlite3.connect(self.path) as connection:
            try:
                connection.execute("INSERT INTO round_lock VALUES (1,?)", (owner,))
            except sqlite3.IntegrityError:
                raise ValueError("Another acceptance process holds this round; no concurrent request sent") from None
        try:
            yield
        finally:
            with sqlite3.connect(self.path) as connection:
                connection.execute("DELETE FROM round_lock WHERE owner=?", (owner,))

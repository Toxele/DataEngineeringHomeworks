import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from kazoo.exceptions import BadVersionError


class PublicationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    name TEXT PRIMARY KEY,
                    fencing INTEGER NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 0,
                    pointer_version INTEGER NOT NULL DEFAULT 0,
                    pointer TEXT
                );
                CREATE TABLE IF NOT EXISTS publications (
                    id INTEGER PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    body TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_run(self, name: str, fencing: bool):
        with self.connect() as connection:
            connection.execute("INSERT INTO runs(name, fencing) VALUES (?, ?)", (name, fencing))

        return self.inspect(name)

    def claim(self, name: str, epoch: int):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT epoch FROM runs WHERE name=?", (name,)).fetchone()

            if current is None or epoch <= current["epoch"]:
                raise BadVersionError(f"Cannot claim epoch {epoch}")

            connection.execute("UPDATE runs SET epoch=? WHERE name=?", (epoch, name))

        return self.inspect(name)

    def publish(self, name: str, body: dict):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT * FROM runs WHERE name=?", (name,)).fetchone()

            if current is None:
                raise ValueError("Unknown calculation")

            if current["fencing"] and body["epoch"] != current["epoch"]:
                raise BadVersionError(
                    f"Stale epoch {body['epoch']}; receiver expects {current['epoch']}"
                )

            payload = json.dumps(body, ensure_ascii=False)
            connection.execute(
                "INSERT INTO publications(scenario, body) VALUES (?, ?)", (name, payload)
            )
            connection.execute(
                "UPDATE runs SET pointer=?, pointer_version=pointer_version+1 WHERE name=?",
                (payload, name),
            )

        return self.inspect(name)

    def inspect(self, name: str):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE name=?", (name,)).fetchone()

            if row is None:
                return None

            result = dict(row)
            result["pointer"] = json.loads(result["pointer"]) if result["pointer"] else None
            result["publications"] = [
                json.loads(item["body"])
                for item in connection.execute(
                    "SELECT body FROM publications WHERE scenario=? ORDER BY id", (name,)
                )
            ]

        return result

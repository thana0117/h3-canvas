"""SQLite storage for projects, canvas cards, generated assets and jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  style TEXT NOT NULL DEFAULT '',
  negative TEXT NOT NULL DEFAULT '',
  templates TEXT NOT NULL DEFAULT '{}',
  image_workflow TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  aspect TEXT NOT NULL DEFAULT '1:1',
  x REAL NOT NULL DEFAULT 0,
  y REAL NOT NULL DEFAULT 0,
  hero_asset_id TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  card_id TEXT REFERENCES cards(id) ON DELETE CASCADE,
  job_id TEXT,
  media TEXT NOT NULL,
  file TEXT NOT NULL,
  thumb TEXT,
  width INTEGER,
  height INTEGER,
  prompt TEXT NOT NULL DEFAULT '',
  seed INTEGER,
  workflow TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  card_id TEXT REFERENCES cards(id) ON DELETE CASCADE,
  workflow TEXT NOT NULL,
  params TEXT NOT NULL,
  status TEXT NOT NULL,
  prompt_id TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_project ON cards(project_id);
CREATE INDEX IF NOT EXISTS idx_assets_card ON assets(card_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

# pending: waiting to be sent to the engine; queued/running: inside ComfyUI.
ACTIVE_STATUSES = ("pending", "queued", "running")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)

    def close(self):
        self._conn.close()

    def all(self, sql: str, *args) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def one(self, sql: str, *args) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def run(self, sql: str, *args) -> int:
        with self._lock:
            return self._conn.execute(sql, args).rowcount

    def insert(self, table: str, row: dict) -> dict:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.run(f"INSERT INTO {table} ({cols}) VALUES ({marks})", *row.values())
        return row

    def update(self, table: str, row_id: str, fields: dict) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.run(f"UPDATE {table} SET {sets} WHERE id = ?", *fields.values(), row_id)

    # settings
    def get_setting(self, key: str, default=None):
        row = self.one("SELECT value FROM settings WHERE key = ?", key)
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.run(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            key,
            json.dumps(value),
        )

    # jobs
    def active_jobs(self) -> list[dict]:
        marks = ", ".join("?" for _ in ACTIVE_STATUSES)
        return self.all(
            f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY created_at", *ACTIVE_STATUSES
        )

    def set_job(self, job_id: str, **fields) -> None:
        self.update("jobs", job_id, {**fields, "updated_at": time.time()})

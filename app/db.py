from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trial_sites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('启用','停用','观察')),
  quota INTEGER NOT NULL DEFAULT 50,
  region TEXT NOT NULL DEFAULT '',
  principal TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS protocols (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  protocol_code TEXT NOT NULL UNIQUE,
  version TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('草稿','生效','废止')),
  required_fields TEXT NOT NULL DEFAULT '[]',
  visit_codes TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS visit_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_code TEXT NOT NULL UNIQUE,
  site_id INTEGER NOT NULL REFERENCES trial_sites(id),
  protocol_id INTEGER REFERENCES protocols(id),
  status TEXT NOT NULL CHECK (status IN ('采集中','已收齐','已关闭')),
  item_count INTEGER NOT NULL DEFAULT 0,
  gap_count INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS visit_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES visit_batches(id),
  subject_key TEXT NOT NULL,
  visit_code TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '',
  quality TEXT NOT NULL CHECK (quality IN ('合格','缺字段','编码空','重复键')),
  status TEXT NOT NULL CHECK (status IN ('待检','已入库','待补采','已关闭')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(batch_id, subject_key, visit_code)
);

CREATE TABLE IF NOT EXISTS qc_findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  row_id INTEGER NOT NULL REFERENCES visit_rows(id),
  field_name TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('提示','一般','严重')),
  message TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK (status IN ('开放','已关闭')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backfill_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_code TEXT NOT NULL UNIQUE,
  row_id INTEGER NOT NULL REFERENCES visit_rows(id),
  status TEXT NOT NULL CHECK (status IN ('排队','执行中','成功','失败')),
  attempt INTEGER NOT NULL DEFAULT 1,
  message TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reconcile_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  summary TEXT NOT NULL,
  gap_rows INTEGER NOT NULL DEFAULT 0,
  open_findings INTEGER NOT NULL DEFAULT 0,
  pending_jobs INTEGER NOT NULL DEFAULT 0,
  mismatch INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL DEFAULT 'admin',
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL DEFAULT 0,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def ensure_db() -> Path:
    Config.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    path = Config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return path


@contextmanager
def get_db(db_path: str | Path | None = None):
    path = Path(db_path) if db_path else Config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _meta_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None

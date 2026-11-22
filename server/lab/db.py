"""SQLite 저장소. 스키마는 첫 실행 때 만든다.

templates     템플릿 버전. shared(공용) 행은 승격할 때마다 새로 쌓인다(최신 = 현재 shared).
experiments   조건 + 프롬프트 1건. 같은 프롬프트로 여러 장을 만들면 images가 여러 행.
images        생성 이미지 1장. scores = {"cond":1~5, "struct":1~5, "nobeauty":1~5}
real_photos   업로드한 실제 사진과 비교한 생성 이미지 id 목록
usage         사용자별·날짜별 실제 API 호출 수 (캐시 적중은 세지 않음)
"""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
DB_PATH = SERVER / "lab.db"
DATA = SERVER / "lab_data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  owner TEXT NOT NULL,
  parent_id INTEGER REFERENCES templates(id),
  templates_yaml TEXT NOT NULL,
  rules_yaml TEXT NOT NULL,
  delta_yaml TEXT NOT NULL,
  note TEXT DEFAULT '',
  is_shared INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user TEXT NOT NULL,
  spot TEXT NOT NULL,
  target_datetime TEXT NOT NULL,
  overrides TEXT NOT NULL DEFAULT '{}',
  template_id INTEGER REFERENCES templates(id),
  template_edits TEXT NOT NULL DEFAULT '{}',   -- 저장하지 않은 편집을 적용해 만든 경우 그 편집
  prompt_text TEXT NOT NULL,
  block_keys TEXT NOT NULL DEFAULT '{}',
  model TEXT NOT NULL,
  grid_cell TEXT,                               -- 그리드 실행이면 조건 이름 (예: "golden_1630")
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id INTEGER NOT NULL REFERENCES experiments(id),
  path TEXT NOT NULL,                           -- lab_data 기준 상대 경로
  cache_key TEXT NOT NULL,
  sample_index INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,                 -- 이번에 실제로 쓴 비용 (캐시 재사용이면 0)
  latency REAL,
  cached INTEGER NOT NULL DEFAULT 0,
  scores TEXT NOT NULL DEFAULT '{}',
  note TEXT DEFAULT '',
  metrics TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS real_photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  spot TEXT NOT NULL,
  taken_at TEXT NOT NULL,
  taken_at_source TEXT NOT NULL,                -- exif | manual
  path TEXT NOT NULL,
  uploader TEXT NOT NULL,
  matched_image_ids TEXT NOT NULL DEFAULT '[]',
  baseline TEXT NOT NULL DEFAULT '{}',          -- 기준 사진 그대로(변화 없음) vs 실제 지표
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
  user TEXT NOT NULL,
  day TEXT NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user, day)
);
CREATE INDEX IF NOT EXISTS idx_exp_filter ON experiments(spot, user, template_id);
CREATE INDEX IF NOT EXISTS idx_img_key ON images(cache_key);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DATA.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
        return _conn


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict | None:
    r = q(sql, args)
    return r[0] if r else None


def ex(sql: str, args: tuple = ()) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def unj(s: str | None, default=None):
    if not s:
        return default
    return json.loads(s)

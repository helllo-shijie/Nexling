"""SQLite storage: database, migrations, unit-of-work, and the monolithic repository.

The repository is the single writer for every aggregate in the app (single-writer,
WAL mode). Domain services duck-type it (see docs/contracts.md); they never import
this module directly.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from ...shared.errors import err
from ...shared.ids import new_id

logger = logging.getLogger("nexling.db")

_JSON_SCHEMA = {
    "schema_meta": "(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "banks": """(
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, name TEXT NOT NULL,
        src_lang TEXT NOT NULL DEFAULT '*', tgt_lang TEXT NOT NULL DEFAULT '*',
        domain TEXT NOT NULL DEFAULT 'general', readonly INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 1, entry_count INTEGER NOT NULL DEFAULT 0,
        owner TEXT NOT NULL DEFAULT 'local', created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '')""",
    "entries": """(
        id TEXT PRIMARY KEY, bank_id TEXT NOT NULL, source_term TEXT NOT NULL,
        target_term TEXT NOT NULL, src_lang TEXT NOT NULL, tgt_lang TEXT NOT NULL,
        domain TEXT NOT NULL DEFAULT 'general', part_of_speech TEXT,
        definition TEXT, case_sensitive INTEGER NOT NULL DEFAULT 0,
        match_mode TEXT NOT NULL DEFAULT 'exact', forced INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active', confidence REAL NOT NULL DEFAULT 1.0,
        origin TEXT NOT NULL DEFAULT 'manual', tags TEXT NOT NULL DEFAULT '[]',
        version INTEGER NOT NULL DEFAULT 1, refs TEXT NOT NULL DEFAULT '{}',
        scene_variants TEXT NOT NULL DEFAULT '{}',
        deleted_at TEXT)""",
    "scenes": """(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
        is_builtin INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
        profile_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '')""",
    "tasks": """(
        id TEXT PRIMARY KEY, source_text TEXT NOT NULL, src_lang TEXT NOT NULL,
        tgt_lang TEXT NOT NULL, detected_lang TEXT,
        mode TEXT NOT NULL DEFAULT 'fluent', scene_profile_id TEXT,
        resolved_scene TEXT NOT NULL DEFAULT '{}', domain TEXT NOT NULL DEFAULT 'general',
        input_kind TEXT NOT NULL DEFAULT 'text', media_refs TEXT,
        status TEXT NOT NULL DEFAULT 'queued', checkpoint_seq INTEGER NOT NULL DEFAULT 0,
        resumable INTEGER NOT NULL DEFAULT 0, risk_tier TEXT NOT NULL DEFAULT 'L0',
        routing TEXT NOT NULL DEFAULT 'auto_finalize',
        budget_limit REAL NOT NULL DEFAULT 0.5, cost_total REAL NOT NULL DEFAULT 0.0,
        segment_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT '',
        completed_at TEXT, batch_total INTEGER NOT NULL DEFAULT 0,
        failed_batches TEXT NOT NULL DEFAULT '[]')""",
    "segments": """(
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL, idx INTEGER NOT NULL,
        text TEXT NOT NULL, span TEXT NOT NULL, lang TEXT NOT NULL DEFAULT '',
        token_estimate INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
        forced INTEGER NOT NULL DEFAULT 0)""",
    "versions": """(
        id TEXT PRIMARY KEY, segment_id TEXT NOT NULL,
        parent_version_id TEXT, target_text TEXT NOT NULL, origin TEXT NOT NULL,
        provider TEXT NOT NULL, model TEXT NOT NULL,
        prompt_fingerprint TEXT NOT NULL DEFAULT '', term_bank_version INTEGER,
        routing_at_creation TEXT NOT NULL DEFAULT '', source_channel TEXT NOT NULL DEFAULT 'online',
        confidence REAL, created_at TEXT NOT NULL DEFAULT '',
        spans TEXT NOT NULL DEFAULT '[]', words TEXT NOT NULL DEFAULT '[]', tones TEXT NOT NULL DEFAULT '[]',
        sentiment TEXT NOT NULL DEFAULT '{}', emotions TEXT NOT NULL DEFAULT '[]')""",
    # 旧版 reviews/decisions 表仅为旧库兼容保留建表，程序不再读写。
    "reviews": """(
        id TEXT PRIMARY KEY, task_id TEXT NOT NULL, scope TEXT NOT NULL,
        policy_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'opened',
        required_segment_ids TEXT NOT NULL DEFAULT '[]', decided TEXT NOT NULL DEFAULT '{}',
        reviewer_id TEXT NOT NULL DEFAULT 'local', opened_at TEXT NOT NULL DEFAULT '',
        signed_at TEXT, attestation TEXT)""",
    "decisions": """(
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, segment_id TEXT NOT NULL,
        base_version_id TEXT NOT NULL, action TEXT NOT NULL,
        result_version_id TEXT, comment TEXT, actor_id TEXT NOT NULL DEFAULT 'local',
        created_at TEXT NOT NULL DEFAULT '')""",
    "tm": """(
        id TEXT PRIMARY KEY, source_hash TEXT NOT NULL, source_text TEXT NOT NULL,
        target_text TEXT NOT NULL, lang_pair TEXT NOT NULL,
        domain TEXT NOT NULL DEFAULT 'general', scene_profile_id TEXT,
        approved INTEGER NOT NULL DEFAULT 0, quality REAL NOT NULL DEFAULT 0.8,
        glossary_version INTEGER NOT NULL DEFAULT 0, prompt_fingerprint TEXT NOT NULL DEFAULT '',
        stale INTEGER NOT NULL DEFAULT 0, use_count INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '')""",
    "usage": """(
        id TEXT PRIMARY KEY, task_id TEXT, segment_id TEXT, provider TEXT NOT NULL,
        model TEXT NOT NULL, purpose TEXT NOT NULL, input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL DEFAULT 0,
        amount REAL NOT NULL DEFAULT 0.0, currency TEXT NOT NULL DEFAULT 'USD',
        created_at TEXT NOT NULL DEFAULT '')""",
    "config": "(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "calls": """(
        id TEXT PRIMARY KEY, task_id TEXT, segment_id TEXT, provider TEXT NOT NULL,
        model TEXT NOT NULL, purpose TEXT NOT NULL, user_input TEXT NOT NULL DEFAULT '',
        prompt TEXT NOT NULL DEFAULT '[]', response TEXT NOT NULL DEFAULT '',
        input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
        amount REAL NOT NULL DEFAULT 0.0, latency_ms INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT '')""",
    "providers": """(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
        base_url TEXT NOT NULL, model TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        is_default INTEGER NOT NULL DEFAULT 0, secret_handle TEXT NOT NULL DEFAULT '',
        config_json TEXT NOT NULL DEFAULT '{}')""",
    "term_candidates": """(
        id TEXT PRIMARY KEY, normalized TEXT NOT NULL, source_term TEXT NOT NULL,
        target_term TEXT, lang TEXT NOT NULL DEFAULT '', target_lang TEXT NOT NULL DEFAULT '',
        task_id TEXT, segment_id TEXT, bank_id TEXT NOT NULL DEFAULT '', context TEXT NOT NULL DEFAULT '',
        occurrences INTEGER NOT NULL DEFAULT 1, confidence REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'pending', evidence TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')""",
    "task_terms": """(
        task_id TEXT NOT NULL, source_term TEXT NOT NULL, target_term TEXT NOT NULL,
        term_id TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT 'model',
        segment_id TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(task_id, source_term))""",
}

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_entries_bank ON entries(bank_id)",
    "CREATE INDEX IF NOT EXISTS idx_entries_deleted ON entries(bank_id, deleted_at)",
    "CREATE INDEX IF NOT EXISTS idx_segments_task ON segments(task_id, idx)",
    "CREATE INDEX IF NOT EXISTS idx_versions_segment ON versions(segment_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_task_terms_task ON task_terms(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_tm_hash ON tm(lang_pair, source_hash)",
    "CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage(provider, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_calls_created ON calls(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_calls_task ON calls(task_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_term_cand_key ON term_candidates(normalized, target_lang, task_id)",
    "CREATE INDEX IF NOT EXISTS idx_term_cand_status ON term_candidates(status, updated_at)",
]

_ADD_COLUMNS = [
    "ALTER TABLE providers ADD COLUMN secret_handle TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE entries ADD COLUMN scene_variants TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE versions ADD COLUMN spans TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE versions ADD COLUMN words TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE versions ADD COLUMN tones TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE versions ADD COLUMN sentiment TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE versions ADD COLUMN emotions TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE term_candidates ADD COLUMN bank_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE tm ADD COLUMN created_at TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE segments ADD COLUMN forced INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN batch_total INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN failed_batches TEXT NOT NULL DEFAULT '[]'",
]


def _loads(s: Optional[str], default: Any) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Database:
    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        self._write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.Error:
            pass
        return conn

    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @contextmanager
    def tx(self):
        with self._write_lock:
            conn = self.conn()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise


class Migrator:
    # 加列是幂等的：每次启动都逐列尝试，已存在的列忽略。
    # 曾用一次性标记跳过，导致旧库升级到新版本时新列永远加不上（V10 真实故障），
    # 因此不再依赖标记决定是否加列；标记只作为迁移记录保留。
    MARKER = "migrations_v8"

    REQUIRED_COLUMNS = {
        "versions": ("spans", "words", "tones", "sentiment", "emotions"),
        "providers": ("secret_handle",),
        "entries": ("scene_variants",),
        "tm": ("created_at",),
        "term_candidates": ("bank_id",),
        "segments": ("forced",),
        "tasks": ("batch_total", "failed_batches"),
    }

    def __init__(self, db: Database):
        self.db = db

    def migrate(self) -> None:
        applied_columns = 0
        with self.db.tx() as conn:
            for name, ddl in _JSON_SCHEMA.items():
                conn.execute(f"CREATE TABLE IF NOT EXISTS {name} {ddl}")
            # 旧库：逐列补齐。只有“列已存在”可以忽略；
            # 其它错误（如库被锁、磁盘写失败）必须抛出，否则会在翻译时才暴露。
            for add in _ADD_COLUMNS:
                try:
                    conn.execute(add)
                    applied_columns += 1
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                (self.MARKER, "1"),
            )
            # 术语候选唯一键从 (normalized, target_lang) 扩到含 task_id；
            # 旧库里的两列索引没法被 IF NOT EXISTS 覆盖，先比对再重建。
            self._rebuild_term_index(conn)
            for idx in _CREATE_INDEXES:
                conn.execute(idx)
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', '1')"
            )
            self._validate(conn)
        logger.info("schema migrated: columns_added=%d marker=%s path=%s",
                    applied_columns, self.MARKER, self.db.path)

    @staticmethod
    def _rebuild_term_index(conn: sqlite3.Connection) -> None:
        """把旧的 (normalized, target_lang) 唯一索引升级成三列版本。"""
        try:
            rows = conn.execute("PRAGMA index_info(idx_term_cand_key)").fetchall()
        except sqlite3.OperationalError:
            return
        cols = [str(r["name"]) for r in rows]
        if cols and cols != ["normalized", "target_lang", "task_id"]:
            conn.execute("DROP INDEX IF EXISTS idx_term_cand_key")

    def _validate(self, conn: sqlite3.Connection) -> None:
        """迁移后校验：缺表/缺列直接报错，避免运行到一半才暴露。"""
        for table, columns in self.REQUIRED_COLUMNS.items():
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            names = {str(r["name"]) for r in rows}
            if not names:
                raise RuntimeError(f"迁移校验失败：缺少数据表 {table}")
            missing = [c for c in columns if c not in names]
            if missing:
                raise RuntimeError(f"迁移校验失败：{table} 缺少列 {missing}")


class UnitOfWork:
    """A single-writer transaction boundary (one command -> one transaction)."""

    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self._ctx = self.db.tx()
        return self._ctx.__enter__()

    def __exit__(self, *exc) -> bool:
        return self._ctx.__exit__(*exc)


def _fields(values: Dict[str, Any]) -> str:
    return ", ".join(values.keys())


def _placeholders(values: Dict[str, Any]) -> str:
    return ", ".join("?" for _ in values)


def _upsert(conn, table: str, values: Dict[str, Any]) -> None:
    cols = list(values.keys())
    assigns = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO {table} ({_fields(values)}) VALUES ({_placeholders(values)}) "
        f"ON CONFLICT(id) DO UPDATE SET {assigns}",
        list(values.values()),
    )


class LaaRepository:
    """Monolithic SQLite-backed repository implementing the duck-typed interface."""

    def __init__(self, db: Database):
        self.db = db

    # ---- glossary ----
    def list_banks(self) -> List[dict]:
        rows = self.db.conn().execute("SELECT * FROM banks ORDER BY scope, name").fetchall()
        return [dict(r) for r in rows]

    def get_bank(self, bank_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM banks WHERE id=?", (bank_id,)).fetchone()
        return dict(row) if row else None

    def save_bank(self, bank: dict) -> None:
        with self.db.tx() as c:
            _upsert(c, "banks", bank)

    def list_entries(self, bank_id: str) -> List[dict]:
        rows = self.db.conn().execute(
            "SELECT * FROM entries WHERE bank_id=? AND deleted_at IS NULL ORDER BY source_term",
            (bank_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = _loads(d["tags"], [])
            d["refs"] = _loads(d["refs"], {})
            d["scene_variants"] = _loads(d["scene_variants"], {})
            out.append(d)
        return out

    def get_entry(self, entry_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = _loads(d["tags"], [])
        d["refs"] = _loads(d["refs"], {})
        d["scene_variants"] = _loads(d["scene_variants"], {})
        return d

    def save_entry(self, entry: dict) -> None:
        v = dict(entry)
        v["tags"] = _dumps(v.get("tags", []))
        v["refs"] = _dumps(v.get("refs", {}))
        v["scene_variants"] = _dumps(v.get("scene_variants", {}))
        with self.db.tx() as c:
            _upsert(c, "entries", v)
            c.execute("UPDATE banks SET entry_count=(SELECT COUNT(*) FROM entries WHERE bank_id=? AND deleted_at IS NULL) WHERE id=?", (v.get("bank_id"), v.get("bank_id")))

    def delete_entry(self, entry_id: str, hard: bool = False) -> None:
        with self.db.tx() as c:
            if hard:
                c.execute("DELETE FROM entries WHERE id=?", (entry_id,))
            else:
                c.execute("UPDATE entries SET deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (entry_id,))

    def next_bank_version(self, bank_id: str) -> int:
        row = self.db.conn().execute("SELECT version FROM banks WHERE id=?", (bank_id,)).fetchone()
        return (row["version"] if row else 0) + 1

    # ---- scenes ----
    def list_scenes(self) -> List[dict]:
        rows = self.db.conn().execute("SELECT * FROM scenes ORDER BY is_default DESC, name").fetchall()
        out = []
        for r in rows:
            d = _loads(r["profile_json"], {})
            d.update(id=r["id"], name=r["name"], is_default=bool(r["is_default"]),
                     is_builtin=bool(r["is_builtin"]), version=r["version"],
                     created_at=r["created_at"], updated_at=r["updated_at"])
            out.append(d)
        return out

    def get_scene(self, scene_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not row:
            return None
        d = _loads(row["profile_json"], {})
        d.update(id=row["id"], name=row["name"], is_default=bool(row["is_default"]),
                 is_builtin=bool(row["is_builtin"]), version=row["version"],
                 created_at=row["created_at"], updated_at=row["updated_at"])
        return d

    def save_scene(self, scene: dict) -> None:
        s = dict(scene)
        profile_json = {k: v for k, v in s.items() if k not in ("id", "name", "is_default", "is_builtin", "version", "created_at", "updated_at")}
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO scenes (id,name,is_default,is_builtin,version,profile_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,is_default=excluded.is_default,"
                "is_builtin=excluded.is_builtin,version=excluded.version,profile_json=excluded.profile_json,"
                "created_at=excluded.created_at,updated_at=excluded.updated_at",
                (s["id"], s["name"], int(s.get("is_default", 0)), int(s.get("is_builtin", 0)),
                 s.get("version", 1), _dumps(profile_json), s.get("created_at", ""), s.get("updated_at", "")),
            )

    def delete_scene(self, scene_id: str, hard: bool = False) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM scenes WHERE id=?", (scene_id,))

    # ---- tasks / segments / versions ----
    def save_task(self, task: dict) -> None:
        v = dict(task)
        v["resolved_scene"] = _dumps(v.get("resolved_scene", {}))
        v["media_refs"] = _dumps(v.get("media_refs")) if v.get("media_refs") is not None else None
        with self.db.tx() as c:
            _upsert(c, "tasks", v)

    def get_task(self, task_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["resolved_scene"] = _loads(d["resolved_scene"], {})
        d["media_refs"] = _loads(d["media_refs"], None)
        return d

    def list_tasks(self) -> List[dict]:
        rows = self.db.conn().execute("SELECT id, status, created_at, completed_at, source_text FROM tasks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def update_task(self, task_id: str, patch: dict) -> Optional[dict]:
        cur = self.get_task(task_id)
        if not cur:
            return None
        merged = {**cur, **patch}
        self.save_task(merged)
        return merged

    def save_segment(self, seg: dict) -> None:
        v = dict(seg)
        v["span"] = _dumps(v.get("span", []))
        with self.db.tx() as c:
            _upsert(c, "segments", v)

    def list_segments(self, task_id: str) -> List[dict]:
        rows = self.db.conn().execute("SELECT * FROM segments WHERE task_id=? ORDER BY idx", (task_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["span"] = _loads(d["span"], [])
            out.append(d)
        return out

    def save_version(self, version: dict) -> None:
        v = dict(version)
        spans = [s.to_dict() if hasattr(s, "to_dict") else s for s in (v.get("spans") or [])]
        words = [dict(w) for w in (v.get("words") or []) if isinstance(w, dict)]
        tones = [dict(t) for t in (v.get("tones") or []) if isinstance(t, dict)]
        sentiment = v.get("sentiment") or {}
        emotions = [dict(e) for e in (v.get("emotions") or []) if isinstance(e, dict)]
        v["spans"] = _dumps(spans)
        v["words"] = _dumps(words)
        v["tones"] = _dumps(tones)
        v["sentiment"] = _dumps(sentiment if isinstance(sentiment, dict) else {})
        v["emotions"] = _dumps(emotions)
        with self.db.tx() as c:
            _upsert(c, "versions", v)

    @staticmethod
    def _version_row(r) -> dict:
        d = dict(r)
        d["spans"] = _loads(d.get("spans"), [])
        d["words"] = _loads(d.get("words"), [])
        d["tones"] = _loads(d.get("tones"), [])
        d["sentiment"] = _loads(d.get("sentiment"), {})
        d["emotions"] = _loads(d.get("emotions"), [])
        return d

    def list_versions(self, segment_id: str) -> List[dict]:
        rows = self.db.conn().execute("SELECT * FROM versions WHERE segment_id=? ORDER BY created_at", (segment_id,)).fetchall()
        return [self._version_row(r) for r in rows]

    def latest_version(self, segment_id: str) -> Optional[dict]:
        row = self.db.conn().execute(
            "SELECT * FROM versions WHERE segment_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (segment_id,)
        ).fetchone()
        return self._version_row(row) if row else None

    def get_version(self, version_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
        return self._version_row(row) if row else None

    def get_segment(self, segment_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM segments WHERE id=?", (segment_id,)).fetchone()
        return dict(row) if row else None

    # ---- 任务级术语译法（全篇一致性） ----
    _TERM_ORIGIN_RANK = {"model": 1, "glossary": 2, "user": 3}

    def list_task_terms(self, task_id: str) -> List[dict]:
        rows = self.db.conn().execute(
            "SELECT * FROM task_terms WHERE task_id=? ORDER BY updated_at, source_term", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_task_term(self, row: dict) -> dict:
        """按来源优先级写入：user > glossary > model，低优先级不得覆盖高优先级。"""
        task_id = row["task_id"]
        source = row["source_term"]
        origin = row.get("origin") or "model"
        with self.db.tx() as c:
            cur = c.execute(
                "SELECT * FROM task_terms WHERE task_id=? AND source_term=?", (task_id, source)
            ).fetchone()
            if cur:
                prev = dict(cur)
                prev_rank = self._TERM_ORIGIN_RANK.get(prev.get("origin"), 0)
                new_rank = self._TERM_ORIGIN_RANK.get(origin, 0)
                if new_rank < prev_rank:
                    return prev
                c.execute(
                    "UPDATE task_terms SET target_term=?, term_id=?, origin=?, segment_id=?, updated_at=? "
                    "WHERE task_id=? AND source_term=?",
                    (row["target_term"], row.get("term_id") or "", origin,
                     row.get("segment_id") or "", row.get("updated_at") or "", task_id, source),
                )
            else:
                c.execute(
                    "INSERT INTO task_terms (task_id, source_term, target_term, term_id, origin, segment_id, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (task_id, source, row["target_term"], row.get("term_id") or "", origin,
                     row.get("segment_id") or "", row.get("updated_at") or ""),
                )
        return {
            "task_id": task_id, "source_term": source, "target_term": row["target_term"],
            "term_id": row.get("term_id") or "", "origin": origin,
            "segment_id": row.get("segment_id") or "", "updated_at": row.get("updated_at") or "",
        }

    # ---- tm ----
    def upsert_tm(self, entry: dict) -> None:
        with self.db.tx() as c:
            _upsert(c, "tm", entry)

    def list_tm(self) -> List[dict]:
        # 最老优先：created_at 为空的老条目排在最前，rowid 兜底保证确定性
        rows = self.db.conn().execute("SELECT * FROM tm ORDER BY created_at ASC, rowid ASC").fetchall()
        return [dict(r) for r in rows]

    def find_tm_exact(self, source_hash: str, lang_pair: str) -> List[dict]:
        rows = self.db.conn().execute("SELECT * FROM tm WHERE source_hash=? AND lang_pair=?", (source_hash, lang_pair)).fetchall()
        return [dict(r) for r in rows]

    def delete_tm(self, entry_id: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute("DELETE FROM tm WHERE id=?", (entry_id,))
            return cur.rowcount > 0

    # ---- usage ledger ----
    def append_usage(self, entry: dict) -> None:
        with self.db.tx() as c:
            _upsert(c, "usage", entry)

    def sum_usage(self, group_by: str = "provider", exclude_providers=None) -> List[dict]:
        if group_by == "day":
            col = "substr(created_at,1,10)"
        else:
            col = group_by if group_by in ("provider", "purpose", "model", "task", "task_id", "segment_id") else "provider"
        where, params = "", ()
        excluded = [p for p in (exclude_providers or []) if p]
        if excluded:
            where = " WHERE provider NOT IN (" + ",".join("?" for _ in excluded) + ")"
            params = tuple(excluded)
        rows = self.db.conn().execute(
            f"SELECT {col} AS k, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(amount) AS amount, COUNT(*) AS n FROM usage{where} GROUP BY {col}",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def usage_totals(self, exclude_providers=None) -> dict:
        where, params = "", ()
        excluded = [p for p in (exclude_providers or []) if p]
        if excluded:
            where = " WHERE provider NOT IN (" + ",".join("?" for _ in excluded) + ")"
            params = tuple(excluded)
        row = self.db.conn().execute(
            "SELECT COALESCE(SUM(input_tokens),0) AS input_tokens, COALESCE(SUM(output_tokens),0) AS output_tokens, "
            f"COALESCE(SUM(amount),0) AS amount, COUNT(*) AS calls FROM usage{where}",
            params,
        ).fetchone()
        return dict(row) if row else {"input_tokens": 0, "output_tokens": 0, "amount": 0.0, "calls": 0}

    def usage_range(self) -> dict:
        row = self.db.conn().execute(
            "SELECT MIN(created_at) AS first_at, MAX(created_at) AS last_at FROM usage"
        ).fetchone()
        return dict(row) if row else {"first_at": None, "last_at": None}

    def list_usage(self, limit: int = 50, offset: int = 0, provider: Optional[str] = None) -> dict:
        conn = self.db.conn()
        if provider:
            rows = conn.execute(
                "SELECT * FROM usage WHERE provider=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (provider, limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM usage WHERE provider=?", (provider,)).fetchone()["n"]
        else:
            rows = conn.execute(
                "SELECT * FROM usage ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM usage").fetchone()["n"]
        return {"items": [dict(r) for r in rows], "total": int(total or 0)}

    # ---- model call log（调用历史：提示词 / 回复 / 花费） ----
    def append_call(self, entry: dict) -> None:
        with self.db.tx() as c:
            _upsert(c, "calls", entry)

    def list_calls(self, limit: int = 20, offset: int = 0, task_id: Optional[str] = None) -> dict:
        conn = self.db.conn()
        if task_id:
            rows = conn.execute(
                "SELECT * FROM calls WHERE task_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (task_id, limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM calls WHERE task_id=?", (task_id,)).fetchone()["n"]
        else:
            rows = conn.execute(
                "SELECT * FROM calls ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()["n"]
        return {"items": [dict(r) for r in rows], "total": int(total or 0)}

    def get_call(self, call_id: str) -> Optional[dict]:
        row = self.db.conn().execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        return dict(row) if row else None

    def count_calls(self) -> int:
        row = self.db.conn().execute("SELECT COUNT(*) AS n FROM calls").fetchone()
        return int((row["n"] if row else 0) or 0)

    def trim_calls(self, keep: int) -> int:
        """只裁剪调用历史，不动 usage 账本（账单聚合仍完整）。"""
        keep = max(0, int(keep))
        with self.db.tx() as c:
            cur = c.execute(
                "DELETE FROM calls WHERE id NOT IN "
                "(SELECT id FROM calls ORDER BY created_at DESC, id DESC LIMIT ?)",
                (keep,),
            )
            return int(cur.rowcount or 0)

    def delete_calls_before(self, cutoff: str) -> int:
        with self.db.tx() as c:
            cur = c.execute("DELETE FROM calls WHERE created_at < ?", (cutoff,))
            return int(cur.rowcount or 0)

    def clear_calls(self) -> int:
        with self.db.tx() as c:
            cur = c.execute("DELETE FROM calls")
            return int(cur.rowcount or 0)

    def list_tasks_page(self, limit: int = 30, offset: int = 0) -> dict:
        """翻译历史：按时间倒序分页返回任务摘要。"""
        conn = self.db.conn()
        rows = conn.execute(
            "SELECT id, source_text, src_lang, tgt_lang, mode, status, segment_count, created_at, completed_at "
            "FROM tasks ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        items = []
        for r in rows:
            d = dict(r)
            items.append({
                "task_id": d["id"], "source_text": d.get("source_text") or "",
                "src_lang": d.get("src_lang") or "auto", "tgt_lang": d.get("tgt_lang") or "",
                "mode": d.get("mode") or "fluent", "status": d.get("status") or "",
                "segment_count": int(d.get("segment_count") or 0),
                "created_at": d.get("created_at") or "", "completed_at": d.get("completed_at"),
            })
        return {"items": items, "total": int(total or 0)}

    # ---- config / providers ----
    def get_config(self, key: str, default=None):
        row = self.db.conn().execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        return _loads(row["value"], default)

    def set_config(self, key: str, value) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO config (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, _dumps(value)),
            )

    def list_providers(self) -> List[dict]:
        rows = self.db.conn().execute("SELECT * FROM providers").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["config_json"] = _loads(d["config_json"], {})
            out.append(d)
        return out

    def save_provider(self, profile: dict) -> None:
        v = dict(profile)
        known = ("id", "kind", "name", "base_url", "model", "enabled", "is_default", "secret_handle", "config_json")
        cfg = {k: val for k, val in v.items() if k not in known}
        merged_cfg = dict(v.get("config_json") or {})
        merged_cfg.update(cfg)
        v["config_json"] = _dumps(merged_cfg)
        for k in list(v.keys()):
            if k.startswith("cfg:") or (k not in known and k != "config_json"):
                v.pop(k, None)
        with self.db.tx() as c:
            _upsert(c, "providers", v)

    def delete_provider(self, provider_id: str) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM providers WHERE id=?", (provider_id,))

    # ---------- term candidates（术语发现闭环） ----------
    def upsert_term_candidate(self, cand: dict) -> None:
        """按 (normalized, target_lang, task_id) 合并候选：累加出现次数、保留更强证据。

        带上 task_id 是为了让候选归属稳定：术语页按任务过滤，若跨任务合并，
        先扫描的任务会把候选"抢走"，后扫描的任务反而看不到它。
        已是 accepted / ignored 的词条不再被扫描结果覆盖，避免反复出现。
        """
        with self.db.tx() as c:
            row = c.execute(
                "SELECT id, occurrences, status, confidence, task_id FROM term_candidates "
                "WHERE normalized=? AND target_lang=? AND task_id=?",
                (cand.get("normalized", ""), cand.get("target_lang", ""), cand.get("task_id", "")),
            ).fetchone()
            cand = {**cand, "evidence": _dumps(cand.get("evidence") or [])}
            if row is None:
                _upsert(c, "term_candidates", cand)
                return
            if (row["status"] or "pending") != "pending":
                return
            merged = dict(cand)
            merged["id"] = row["id"]
            # 同一任务重复扫描（自动扫描 + 手动补扫）不应把出现次数越滚越大
            merged["occurrences"] = max(int(row["occurrences"] or 1), int(cand.get("occurrences", 1)))
            merged["confidence"] = max(float(row["confidence"] or 0), float(cand.get("confidence", 0)))
            _upsert(c, "term_candidates", merged)

    def list_term_candidates(self, status: Optional[str] = None, limit: int = 200,
                             task_id: Optional[str] = None) -> List[dict]:
        sql = "SELECT * FROM term_candidates"
        conds: List[str] = []
        params: List[Any] = []
        if status:
            conds.append("status=?")
            params.append(status)
        if task_id:
            conds.append("task_id=?")
            params.append(task_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY confidence DESC, occurrences DESC, updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows = self.db.conn().execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["evidence"] = _loads(d.get("evidence"), [])
            out.append(d)
        return out

    def get_term_candidate(self, cand_id: str) -> Optional[dict]:
        r = self.db.conn().execute(
            "SELECT * FROM term_candidates WHERE id=?", (cand_id,)
        ).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["evidence"] = _loads(d.get("evidence"), [])
        return d

    def update_term_candidate(self, cand_id: str, patch: dict) -> Optional[dict]:
        cur = self.get_term_candidate(cand_id)
        if cur is None:
            return None
        merged = {**cur, **patch, "id": cand_id}
        merged["evidence"] = _dumps(merged.get("evidence") or [])
        with self.db.tx() as c:
            _upsert(c, "term_candidates", merged)
        return self.get_term_candidate(cand_id)

    def count_term_candidates(self, task_id: Optional[str] = None) -> dict:
        sql = "SELECT status, COUNT(*) AS n FROM term_candidates"
        params: List[Any] = []
        if task_id:
            sql += " WHERE task_id=?"
            params.append(task_id)
        sql += " GROUP BY status"
        rows = self.db.conn().execute(sql, params).fetchall()
        out = {"pending": 0, "accepted": 0, "ignored": 0}
        for r in rows:
            out[r["status"] or "pending"] = int(r["n"])
        return out

    def trim_term_candidates(self, status: str, keep: int) -> int:
        """只保留最新 keep 条（按 created_at 最老优先删除），返回删除条数。"""
        if keep < 0:
            return 0
        with self.db.tx() as c:
            total = c.execute(
                "SELECT COUNT(*) AS n FROM term_candidates WHERE status=?", (status,)
            ).fetchone()["n"]
            excess = int(total) - keep
            if excess <= 0:
                return 0
            rows = c.execute(
                "SELECT id FROM term_candidates WHERE status=? ORDER BY created_at ASC, rowid ASC LIMIT ?",
                (status, excess),
            ).fetchall()
            ids = [r["id"] for r in rows]
            c.executemany("DELETE FROM term_candidates WHERE id=?", [(i,) for i in ids])
        return len(ids)

    def delete_term_candidates(self, status: Optional[str] = None, task_id: Optional[str] = None) -> int:
        conds, params = [], []
        if status:
            conds.append("status=?")
            params.append(status)
        if task_id:
            conds.append("task_id=?")
            params.append(task_id)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        with self.db.tx() as c:
            cur = c.execute(f"DELETE FROM term_candidates{where}", params)
            return int(cur.rowcount or 0)


def _open_db(path: str) -> Database:
    if not path:
        raise err("LAA-7001", message="database path required")
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    db = Database(path)
    if not os.path.exists(path):
        db.conn().execute("PRAGMA journal_mode=WAL")
    Migrator(db).migrate()
    return db
"""SQLite-backed store for the RunningHub async workflow task pool.

Scope: global pool, no project/batch grouping. Completion is detected at the
pool level (outstanding count drops to 0); an edge latch is armed at enqueue
time so even very fast tasks cannot miss the completion edge.

Task status:
  PENDING        enqueued locally, not yet sent to RunningHub
  DISPATCHED     create succeeded, rh_task_id known (RH: QUEUED/RUNNING)
  SUCCESS        terminal
  FAILED         terminal (RH reported failure)
  SUBMIT_FAILED  terminal (create failed before a taskId was obtained)
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

# Status groups
OUTSTANDING_STATUSES = ("PENDING", "DISPATCHED")
TERMINAL_STATUSES = ("SUCCESS", "FAILED", "SUBMIT_FAILED")


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------ conn
    def _new_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        """Connection that is actually closed (sqlite's `with conn` is not)."""
        conn = self._new_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id    TEXT NOT NULL,
                    instance_type  TEXT NOT NULL DEFAULT 'default',
                    node_overrides TEXT,            -- JSON list
                    request_json   TEXT,            -- JSON, api key excluded
                    rh_task_id     TEXT,            -- set once DISPATCHED
                    status         TEXT NOT NULL DEFAULT 'PENDING',
                    submitted_at   INTEGER,         -- local create-to-RH (ms)
                    started_at     INTEGER,         -- first observed running (ms)
                    updated_at     INTEGER NOT NULL,
                    finished_at    INTEGER,
                    cost_money     REAL,
                    cost_time_s    INTEGER,
                    error_code     TEXT,
                    error_type     TEXT,
                    error_message  TEXT,
                    results_json   TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_rh_id
                    ON tasks(rh_task_id) WHERE rh_task_id IS NOT NULL;
                """
            )
            self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))

    # ------------------------------------------------------------------ meta
    @staticmethod
    def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._db() as conn:
            self._set_meta(conn, key, value)

    # --------------------------------------------------------------- enqueue
    def enqueue(self, jobs: Iterable[dict]) -> list[int]:
        """Insert jobs as PENDING. Each job:
        workflow_id, instance_type?, node_overrides?(list), request_json?(dict).
        Arms the completion edge so even a task that finishes before the next
        poll still produces a drain notification.
        """
        ts = now_ms()
        ids: list[int] = []
        with self._db() as conn:
            for job in jobs:
                cur = conn.execute(
                    """
                    INSERT INTO tasks (workflow_id, instance_type, node_overrides,
                                       request_json, status, updated_at)
                    VALUES (?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (
                        str(job["workflow_id"]),
                        str(job.get("instance_type") or "default"),
                        json.dumps(job.get("node_overrides") or [], ensure_ascii=False),
                        json.dumps(job.get("request_json") or {}, ensure_ascii=False),
                        ts,
                    ),
                )
                ids.append(int(cur.lastrowid))
            # Arm the completion edge immediately.
            self._set_meta(conn, "armed", "1")
        return ids

    # ------------------------------------------------------------- retrieval
    def get_pending(self, limit: int) -> list[sqlite3.Row]:
        with self._db() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM tasks WHERE status='PENDING' "
                    "ORDER BY id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
            )

    def get_active(self) -> list[sqlite3.Row]:
        """Dispatched, not terminal (need RH polling)."""
        with self._db() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM tasks WHERE status='DISPATCHED' ORDER BY id ASC"
                ).fetchall()
            )

    def count_status(self) -> dict[str, int]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM tasks GROUP BY status"
            ).fetchall()
        counts = {r["status"]: r["c"] for r in rows}
        counts["outstanding"] = sum(counts.get(s, 0) for s in OUTSTANDING_STATUSES)
        return counts

    def get_task(self, *, pool_id: int | None = None,
                 rh_task_id: str | None = None) -> sqlite3.Row | None:
        with self._db() as conn:
            if pool_id is not None:
                return conn.execute("SELECT * FROM tasks WHERE id=?", (pool_id,)).fetchone()
            if rh_task_id is not None:
                return conn.execute(
                    "SELECT * FROM tasks WHERE rh_task_id=?", (rh_task_id,)
                ).fetchone()
        return None

    def list_tasks(self, status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        with self._db() as conn:
            if status:
                return list(conn.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall())
            return list(conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall())

    # ----------------------------------------------------------- transitions
    def mark_dispatched(self, pool_id: int, rh_task_id: str) -> None:
        ts = now_ms()
        with self._db() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status='DISPATCHED', rh_task_id=?, submitted_at=COALESCE(submitted_at, ?),
                       updated_at=?
                   WHERE id=? AND status='PENDING'""",
                (str(rh_task_id), ts, ts, pool_id),
            )

    def mark_submit_failed(self, pool_id: int, error_type: str,
                           error_code: str = "", error_message: str = "") -> None:
        ts = now_ms()
        with self._db() as conn:
            conn.execute(
                """UPDATE tasks
                   SET status='SUBMIT_FAILED', error_type=?, error_code=?,
                       error_message=?, finished_at=?, updated_at=?
                   WHERE id=? AND status='PENDING'""",
                (error_type, error_code, error_message, ts, ts, pool_id),
            )

    def apply_query_result(self, pool_id: int, status: str, *,
                           rh_status: str | None = None,
                           results: list[dict] | None = None,
                           cost_money: float | None = None,
                           cost_time_s: int | None = None,
                           error_code: str = "",
                           error_type: str = "",
                           error_message: str = "") -> None:
        """Apply a normalized RH query snapshot to a DISPATCHED task."""
        ts = now_ms()
        with self._db() as conn:
            if status == "SUCCESS":
                conn.execute(
                    """UPDATE tasks SET status='SUCCESS', results_json=?,
                           cost_money=COALESCE(?, cost_money),
                           cost_time_s=COALESCE(?, cost_time_s),
                           finished_at=COALESCE(finished_at, ?), updated_at=?
                       WHERE id=?""",
                    (json.dumps(results or [], ensure_ascii=False), cost_money,
                     cost_time_s, ts, ts, pool_id),
                )
            elif status == "FAILED":
                conn.execute(
                    """UPDATE tasks SET status='FAILED', error_code=?, error_type=?,
                           error_message=?, cost_money=COALESCE(?, cost_money),
                           finished_at=COALESCE(finished_at, ?), updated_at=?
                       WHERE id=?""",
                    (error_code, error_type, error_message, cost_money, ts, ts, pool_id),
                )
            else:
                # Still pending on RH; record first observed RUNNING as started.
                if rh_status == "RUNNING":
                    conn.execute(
                        """UPDATE tasks SET started_at=COALESCE(started_at, ?),
                               updated_at=? WHERE id=?""",
                        (ts, ts, pool_id),
                    )
                else:
                    conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (ts, pool_id))

    # ------------------------------------------------------------- edge/notify
    def drain_just_happened(self) -> bool:
        """True on the edge: pool had outstanding work (armed at enqueue) and is
        fully terminal now. The latch is re-armed automatically whenever new
        tasks are enqueued.
        """
        outstanding = self.count_status()["outstanding"]
        with self._db() as conn:
            if outstanding > 0:
                # Defensive re-arm while work is still in flight.
                self._set_meta(conn, "armed", "1")
                return False
            if self.get_meta("armed", "0") == "1":
                self._set_meta(conn, "armed", "0")
                return True
            return False


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("node_overrides", "request_json", "results_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d

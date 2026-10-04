#!/usr/bin/env python3
"""Adapter: explainer-studio stage scripts -> runninghub task pool (pool.py).

Mirrors vox-director-rh/scripts/rh_pool_client.py:

    enqueue --manual  -> ledger rows + batchId + poolIds
    tick              -> non-blocking advance (drives the WHOLE pool)
    status            -> one row as JSON / --lines protocol rows

A stage is enqueued as ONE batch; this process drives ticks until every pool id
of the batch is terminal. Slow tasks are never resubmitted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

POOL_SCRIPT = os.environ.get(
    "RUNNINGHUB_POOL",
    str(Path(__file__).resolve().parent.parent.parent / "runninghub"
        / "scripts" / "rh_pool" / "pool.py"),
)

TERMINAL_STATUSES = {"SUCCESS", "FAILED", "SUBMIT_FAILED"}
DEFAULT_INTERVAL_S = 15
DEFAULT_TIMEOUT_S = 50 * 60


class PoolError(RuntimeError):
    pass


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, POOL_SCRIPT, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )


def ensure_pool_script() -> None:
    if not Path(POOL_SCRIPT).exists():
        raise PoolError(f"task pool script not found: {POOL_SCRIPT} "
                        f"(set RUNNINGHUB_POOL to override)")


def enqueue_batch(jobs: list[dict]) -> tuple[int, list[int]]:
    ensure_pool_script()
    fd, tmp = tempfile.mkstemp(prefix="explainer-pool-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        proc = _run(["enqueue", "--from-file", tmp, "--manual"])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if proc.returncode != 0:
        raise PoolError(f"enqueue failed (exit {proc.returncode}):\n"
                        f"{proc.stdout}\n{proc.stderr}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PoolError(f"unparseable enqueue output:\n{proc.stdout}") from exc
    batch_id = payload.get("batchId")
    pool_ids = payload.get("poolIds") or []
    if not isinstance(batch_id, int) or not pool_ids:
        raise PoolError(f"enqueue returned no batch/pool ids: {payload}")
    if len(pool_ids) != len(jobs):
        raise PoolError(f"enqueue id count mismatch: {len(pool_ids)} != {len(jobs)}")
    return batch_id, [int(x) for x in pool_ids]


def tick() -> dict:
    proc = _run(["tick"])
    if proc.returncode != 0:
        raise PoolError(f"tick failed (exit {proc.returncode}):\n"
                        f"{proc.stdout}\n{proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PoolError(f"unparseable tick output:\n{proc.stdout}") from exc


def task_status(pool_id: int) -> dict:
    proc = _run(["status", "--pool-id", str(pool_id)])
    if proc.returncode != 0:
        raise PoolError(f"status failed for pool {pool_id}:\n"
                        f"{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout)


def task_lines(pool_id: int) -> dict[str, str]:
    proc = _run(["status", "--pool-id", str(pool_id), "--lines"])
    if proc.returncode != 0:
        raise PoolError(f"status --lines failed for pool {pool_id}:\n"
                        f"{proc.stdout}\n{proc.stderr}")
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def wait_for(pool_ids: list[int], interval_s: int = DEFAULT_INTERVAL_S,
             timeout_s: int = DEFAULT_TIMEOUT_S, progress=print) -> dict[int, dict]:
    deadline = time.monotonic() + timeout_s
    last_snapshot: dict[int, dict] = {}
    while True:
        tick()
        snapshot: dict[int, dict] = {}
        outstanding = 0
        for pid in pool_ids:
            row = task_status(pid)
            snapshot[pid] = row
            if row.get("status", "?") not in TERMINAL_STATUSES:
                outstanding += 1
        last_snapshot = snapshot
        tally: dict[str, int] = {}
        for row in snapshot.values():
            tally[row.get("status", "?")] = tally.get(row.get("status", "?"), 0) + 1
        progress("pool: " + " ".join(f"{k}:{v}" for k, v in sorted(tally.items())))
        if outstanding == 0:
            return snapshot
        if time.monotonic() >= deadline:
            pending = [pid for pid, r in last_snapshot.items()
                       if r.get("status") not in TERMINAL_STATUSES]
            raise PoolError(
                f"timed out after {timeout_s}s; unfinished pool ids: {pending}. "
                f"Tasks stay in the ledger — inspect with pool.py ls and recover "
                f"outputs with pool.py outputs; this script will not resubmit them.")
        time.sleep(interval_s)

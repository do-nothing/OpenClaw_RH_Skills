"""Watch-job management for the RunningHub task pool.

A single standing watcher runs as a supervised stream source. It advances the
pool every interval and prints a marker line when a batch drains; the stream
job matches that line and wakes the agent to process results and notify.

Why not a per-interval trigger script: trigger evaluations run in code mode
with a 30s budget, are aborted on plugin-runtime refresh ("Plugin runtime
changed"), and reach a shell via exec (Windows quoting pitfalls). A supervised
standing process avoids all three. The Gateway restarts it if it dies.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parents[1]              # runninghub/

WATCH_DECLARATION_KEY = "rh-pool-watch"
WATCH_NAME = "rh-pool-watch"
WATCH_INTERVAL_S = 60
WATCH_WATCHER = SKILL_DIR / "scripts" / "rh_pool" / "watcher.py"
WATCH_MATCH = "RH_POOL_DRAINED"
WATCH_MESSAGE = (
    "RunningHub 任务池已排空：所有任务都到达终态。"
    "请读取台账（pool status）并处理产物/通知。"
)


def _openclaw_bin() -> str | None:
    """Locate the openclaw CLI (env override, PATH, or a sibling install)."""
    override = os.environ.get("OPENCLAW_BIN")
    if override and Path(override).exists():
        return override
    found = shutil.which("openclaw")
    if found:
        return found
    # Fall back to the currently running package's launcher, if discoverable.
    cand = Path(sys.executable).parent / "openclaw"
    if cand.exists():
        return str(cand)
    return None


def _run_cli(args: list[str], timeout: int = 60) -> tuple[int, str]:
    exe = _openclaw_bin()
    if not exe:
        return -1, "openclaw CLI not found (set OPENCLAW_BIN)"
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)
    return proc.returncode, (proc.stdout or proc.stderr or "")


def list_jobs() -> list[dict]:
    code, out = _run_cli(["automations", "list", "--all", "--json"])
    if code != 0:
        return []
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return data.get("jobs") or data.get("items") or []
    return data if isinstance(data, list) else []


def find_watch_jobs() -> list[dict]:
    return [j for j in list_jobs()
            if j.get("declarationKey") == WATCH_DECLARATION_KEY
            or j.get("name") == WATCH_NAME]


def remove_job(job_id: str) -> bool:
    code, _ = _run_cli(["automations", "remove", job_id])
    return code == 0


def ensure_watch(pool_py: Path, data_dir: Path, *, outstanding: int) -> dict:
    """Create the standing watcher when work is outstanding; no-op otherwise.

    Guarantees at most one instance: existing watch jobs are reused; a stale
    disabled one is removed first, then a fresh job is added under the same
    declaration key.
    """
    if outstanding <= 0:
        # Nothing to watch; clean up any leftover job so it cannot linger.
        for job in find_watch_jobs():
            remove_job(job.get("id") or job.get("jobId"))
        return {"action": "none", "reason": "pool empty"}

    existing = find_watch_jobs()
    enabled = [j for j in existing if j.get("enabled", True)]
    if enabled:
        return {"action": "reuse",
                "jobId": enabled[0].get("id") or enabled[0].get("jobId")}

    # Drop disabled/stale duplicates, then create exactly one.
    for job in existing:
        remove_job(job.get("id") or job.get("jobId"))

    argv = [str(Path(sys.executable)),
            str(WATCH_WATCHER),
            "--interval", str(WATCH_INTERVAL_S)]
    args = [
        "automations", "add",
        "--name", WATCH_NAME,
        "--description", "RunningHub task pool drain watcher (standing process)",
        "--stream-command", json.dumps(argv),
        "--stream-cwd", str(SKILL_DIR),
        "--stream-mode", "match",
        "--stream-match", WATCH_MATCH,
        "--system-event", WATCH_MESSAGE,
        "--session", "main",
        "--wake", "now",
        "--declaration-key", WATCH_DECLARATION_KEY,
        "--json",
    ]
    code, out = _run_cli(args, timeout=90)
    if code != 0:
        return {"action": "error", "message": out[-500:], "cliArgs": args}
    job_id = None
    try:
        payload = json.loads(out[out.index("{"):])
        job_id = (payload.get("id") or payload.get("jobId")
                  or (payload.get("job") or {}).get("id"))
    except (ValueError, json.JSONDecodeError):
        pass
    return {"action": "created", "jobId": job_id, "argv": argv}

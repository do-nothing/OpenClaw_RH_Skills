"""Standing RunningHub pool watcher (supervised stream source).

Runs as a long-lived supervised command under the Gateway scheduler (a stream
schedule). Every `interval` seconds it advances the pool in-process — dispatch
within the concurrency budget, poll active tasks, download results — and, when
a batch drains, prints exactly one marker line to stdout. The stream job
matches that line and wakes the agent to process results and notify.

Why a standing process instead of a per-interval trigger script:
  trigger evaluations run in code mode with a 30s wall-clock budget, are
  aborted when the plugin runtime refreshes ("Plugin runtime changed"), and
  their exec calls go through a shell (Windows quoting pitfalls). A plain
  supervised process has none of those failure modes: no code mode, no budget,
  no shell, and the Gateway restarts it if it dies.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[0]))  # .../scripts

from rh_pool import pool as pool_mod          # noqa: E402
from rh_pool.config import load_config        # noqa: E402
from rh_pool.store import Store               # noqa: E402
from runninghub import resolve_api_key        # noqa: E402

DRAIN_MARKER = "RH_POOL_DRAINED"
DEFAULT_INTERVAL_S = 60


def _interval(argv: list[str]) -> int:
    if "--interval" in argv:
        try:
            return max(5, int(argv[argv.index("--interval") + 1]))
        except (ValueError, IndexError):
            pass
    return DEFAULT_INTERVAL_S


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    interval = _interval(argv)

    cfg = load_config()
    api_key = resolve_api_key(None)
    if not api_key:
        print("WATCHER_NO_API_KEY", file=sys.stderr, flush=True)
        return 2
    store = Store(cfg.db_path)

    # Announce readiness once so a bad start is visible in the stream log.
    print(f"WATCHER_READY interval={interval}s", flush=True)

    while True:
        try:
            summary = pool_mod.run_tick(cfg, api_key, maintain_watch=False)
        except Exception as exc:  # noqa: BLE001
            # Never die on a transient error; the next cycle retries.
            print(f"WATCHER_ERROR {type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)
            summary = None

        if summary and summary.get("drained") and not summary.get("skipped"):
            # Persistent drain signal: clear it now that it has been reported,
            # so this batch notifies exactly once. A later enqueue re-arms it.
            store.ack_drain()
            counts = json.dumps(summary.get("counts") or {}, ensure_ascii=False)
            print(f"{DRAIN_MARKER} {counts}", flush=True)

        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())

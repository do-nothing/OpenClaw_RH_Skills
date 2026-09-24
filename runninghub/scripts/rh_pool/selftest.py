"""M1 self-tests for config + store. Run: python -m rh_pool.selftest
Uses a temp data dir (RH_POOL_DATA_DIR) so the real ledger is untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Allow running both as module and as a plain script.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from rh_pool.config import load_config  # noqa: E402
from rh_pool.store import Store, row_to_dict  # noqa: E402


def check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"ok - {name}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["RH_POOL_DATA_DIR"] = tmp
        cfg = load_config()
        check("config db path under temp", str(cfg.db_path).startswith(tmp))
        check("default concurrency >= 1", cfg.concurrency >= 1)

        store = Store(cfg.db_path)

        # Empty pool: no drain edge (nothing was ever outstanding).
        check("empty pool no edge", store.drain_just_happened() is False)

        # Enqueue 3 jobs
        ids = store.enqueue([
            {"workflow_id": "wfA", "instance_type": "plus",
             "node_overrides": [{"nodeId": "6", "fieldName": "text", "fieldValue": "cat"}]},
            {"workflow_id": "wfA", "instance_type": "default"},
            {"workflow_id": "wfB", "instance_type": "ultra"},
        ])
        check("enqueue returns 3 ids", len(ids) == 3)

        counts = store.count_status()
        check("3 pending", counts.get("PENDING") == 3)
        check("outstanding == 3", counts["outstanding"] == 3)
        check("non-empty pool no edge", store.drain_just_happened() is False)

        # Pending retrieval with limit
        pending = store.get_pending(2)
        check("pending limit respected", len(pending) == 2)

        # Dispatch first task
        store.mark_dispatched(ids[0], "RH-1001")
        active = store.get_active()
        check("one active", len(active) == 1 and active[0]["rh_task_id"] == "RH-1001")
        check("dispatched not outstanding-pending", store.count_status().get("PENDING") == 2)
        check("outstanding still 3", store.count_status()["outstanding"] == 3)

        # Submit failure on second task (terminal, no retry)
        store.mark_submit_failed(ids[1], "AUTH", "401", "bad key")
        t2 = row_to_dict(store.get_task(pool_id=ids[1]))
        check("submit failed terminal", t2["status"] == "SUBMIT_FAILED" and t2["error_type"] == "AUTH")

        # First task succeeds via query result with cost
        store.apply_query_result(ids[0], "SUCCESS",
                                 results=[{"url": "http://x/a.png", "outputType": "png"}],
                                 cost_money=0.12, cost_time_s=42)
        t1 = row_to_dict(store.get_task(pool_id=ids[0]))
        check("success recorded", t1["status"] == "SUCCESS")
        check("cost recorded", t1["cost_money"] == 0.12 and t1["cost_time_s"] == 42)
        check("results url recorded", t1["results_json"][0]["url"] == "http://x/a.png")

        # Third task: intermediate running updates, then failed
        store.mark_dispatched(ids[2], "RH-1003")
        store.apply_query_result(ids[2], "PENDING", rh_status="RUNNING")
        t3 = row_to_dict(store.get_task(pool_id=ids[2]))
        check("started_at set on running", t3["started_at"] is not None)
        store.apply_query_result(ids[2], "FAILED", error_code="E5",
                                 error_type="RENDER_FAILED", error_message="boom")
        t3 = row_to_dict(store.get_task(pool_id=ids[2]))
        check("failed terminal", t3["status"] == "FAILED" and t3["error_type"] == "RENDER_FAILED")

        # Now all terminal: drain edge should fire once, then not again.
        check("outstanding == 0", store.count_status()["outstanding"] == 0)
        check("drain edge fires", store.drain_just_happened() is True)
        check("drain edge no repeat", store.drain_just_happened() is False)

        # New work re-arms the latch; completion can fire again.
        new_ids = store.enqueue([{"workflow_id": "wfC"}])
        check("new work outstanding", store.count_status()["outstanding"] == 1)
        store.mark_dispatched(new_ids[0], "RH-2001")
        store.apply_query_result(new_ids[0], "SUCCESS", cost_money=0.01)
        check("second drain edge fires", store.drain_just_happened() is True)

        # Listing / ledger query
        check("list all tasks", len(store.list_tasks(limit=50)) == 4)
        check("list failed only", len(store.list_tasks(status="FAILED")) == 1)

    print("\nAll M1 self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""M2 self-tests: dispatch/poll orchestration with a fake RH client.

Patches rh_pool.pool.create_workflow / query_task so no network is used.
Run: python -m rh_pool.selftest_m2
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import rh_pool.pool as pool  # noqa: E402
from rh_pool.config import load_config  # noqa: E402
from rh_pool.store import Store, row_to_dict  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"ok - {name}")


class FakeRH:
    """Scripted create + query behavior keyed by workflow id.

    outcomes: workflow_id -> 'SUCCESS' | 'FAILED'
    create keeps an in-flight counter to emulate concurrency server-side.
    """

    def __init__(self, outcomes, fail_create_ids=()):
        self.outcomes = outcomes
        self.fail_create_ids = set(fail_create_ids)
        self.create_calls = 0
        # rh_task_id -> outcome
        self.rh_state: dict[str, str] = {}

    def create(self, api_key, payload, timeout=60):
        self.create_calls += 1
        wf = payload["workflowId"]
        if wf in self.fail_create_ids:
            return {"ok": False, "error_type": "AUTH", "error_code": "403",
                    "error_message": "forbidden", "raw": "", "http_rc": 0}
        rh_id = f"RH-{self.create_calls}"
        self.rh_state[rh_id] = self.outcomes.get(wf, "SUCCESS")
        return {"ok": True, "task_id": rh_id, "task_status": "QUEUED", "raw": {}}

    def query(self, api_key, rh_task_id, timeout=30):
        outcome = self.rh_state.get(rh_task_id, "SUCCESS")
        if outcome == "SUCCESS":
            return {"ok": True, "terminal": True, "status": "SUCCESS",
                    "rh_status": "SUCCESS",
                    "results": [{"url": f"http://x/{rh_task_id}.png", "outputType": "png"}],
                    "cost_money": 0.1, "cost_time_s": 10}
        return {"ok": True, "terminal": True, "status": "FAILED",
                "rh_status": "FAILED", "error_code": "E1",
                "error_type": "RENDER_FAILED", "error_message": "boom"}


def main():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["RH_POOL_DATA_DIR"] = tmp
        cfg = load_config()
        # Force concurrency=2 via the config object behavior by writing a config.
        cfg_path = Path(tmp) / "pool-config.json"
        cfg_path.write_text('{"concurrency": 2}', encoding="utf-8")
        os.environ["RH_POOL_CONFIG"] = str(cfg_path)
        cfg = load_config()
        check("concurrency forced to 2", cfg.concurrency == 2)

        store = Store(cfg.db_path)
        fake = FakeRH(outcomes={"wf1": "SUCCESS", "wf2": "SUCCESS",
                                "wf3": "FAILED", "wf4": "SUCCESS",
                                "wf5": "SUCCESS"})
        # Patch the names pool.py imported.
        orig_create, orig_query = pool.create_workflow, pool.query_task
        pool.create_workflow = fake.create
        pool.query_task = fake.query
        try:
            ids = store.enqueue([{"workflow_id": w} for w in
                                 ["wf1", "wf2", "wf3", "wf4", "wf5"]])

            # First dispatch: only 2 of 5 due to concurrency=2.
            d1 = pool._dispatch_pending(store, "KEY", 2)
            check("dispatch 2", d1["dispatched"] == 2 and d1["submit_failed"] == 0)
            check("create called twice", fake.create_calls == 2)
            check("3 still pending", store.count_status().get("PENDING") == 3)
            check("2 active", len(store.get_active()) == 2)

            # Nothing terminal yet: dispatch again -> free slots = 0.
            d2 = pool._dispatch_pending(store, "KEY", 2)
            check("no over-dispatch", d2["dispatched"] == 0)

            # Poll while (simulate) still running by overriding query transiently.
            def running_query(api_key, rh_task_id, timeout=30):
                return {"ok": True, "terminal": False, "status": "PENDING",
                        "rh_status": "RUNNING"}
            pool.query_task = running_query
            p_run = pool._poll_active(store, "KEY")
            check("active tasks seen running", p_run["pending"] == 2)
            check("still 2 active after running poll", len(store.get_active()) == 2)

            # Restore terminal query; poll -> both finish (one SUCCESS one wf pending?
            # Both currently active are wf1,wf2 = SUCCESS).
            pool.query_task = fake.query
            p1 = pool._poll_active(store, "KEY")
            check("first 2 succeed", p1["succeeded"] == 2 and p1["failed"] == 0)
            check("0 active now", len(store.get_active()) == 0)

            # Dispatch next 2 (wf3=FAILED, wf4=SUCCESS)
            d3 = pool._dispatch_pending(store, "KEY", 2)
            check("dispatch next 2", d3["dispatched"] == 2)
            p2 = pool._poll_active(store, "KEY")
            check("one success one failed", p2["succeeded"] == 1 and p2["failed"] == 1)
            failed = store.list_tasks(status="FAILED")
            check("failed isolated w/ type",
                  len(failed) == 1 and row_to_dict(failed[0])["error_type"] == "RENDER_FAILED")

            # Last task wf5
            d4 = pool._dispatch_pending(store, "KEY", 2)
            check("dispatch final 1", d4["dispatched"] == 1)
            p3 = pool._poll_active(store, "KEY")
            check("final success", p3["succeeded"] == 1)

            # All terminal -> drain edge exactly once.
            counts = store.count_status()
            check("4 success 1 failed",
                  counts.get("SUCCESS") == 4 and counts.get("FAILED") == 1)
            check("outstanding 0", counts["outstanding"] == 0)
            check("drain edge fires", store.drain_just_happened() is True)
            check("drain edge no repeat", store.drain_just_happened() is False)

            # No automatic resubmission ever: create calls == 5 (one per task).
            check("exactly 5 creates, zero retries", fake.create_calls == 5)
        finally:
            pool.create_workflow = orig_create
            pool.query_task = orig_query

        # --- create-failure path becomes SUBMIT_FAILED but pool keeps going ---
        store2 = Store(Path(tmp) / "p2.sqlite")
        fake2 = FakeRH(outcomes={"bad": "SUCCESS", "ok": "SUCCESS"},
                       fail_create_ids=("bad",))
        pool.create_workflow = fake2.create
        pool.query_task = fake2.query
        try:
            ids2 = store2.enqueue([{"workflow_id": "bad"}, {"workflow_id": "ok"}])
            d = pool._dispatch_pending(store2, "KEY", 2)
            check("one submit failed counted", d["submit_failed"] == 1 and d["dispatched"] == 1)
            p = pool._poll_active(store2, "KEY")
            check("other task still succeeds", p["succeeded"] == 1)
            check("submit-failed task terminal",
                  row_to_dict(store2.get_task(pool_id=ids2[0]))["status"] == "SUBMIT_FAILED")
            check("pool drains despite submit failure", store2.drain_just_happened() is True)
        finally:
            pool.create_workflow = orig_create
            pool.query_task = orig_query

    print("\nAll M2 self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

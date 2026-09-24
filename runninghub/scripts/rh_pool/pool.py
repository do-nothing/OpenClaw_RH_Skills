"""RunningHub async workflow task pool — core orchestration / CLI.

Commands:
  enqueue   Add one or more workflow jobs to the global pool (PENDING).
  tick      One non-blocking advance: dispatch within concurrency budget,
            poll active tasks, write results, report pool-drain edge.
  status    Query the ledger (counts / task detail).
  reconcile Re-poll all DISPATCHED tasks and sync state (after restart).

Designed to be driven by a headless automation trigger (no LLM): `tick` is
idempotent, non-blocking, emits JSON, exit code 0. When the pool just drained,
the trigger fires a systemEvent + wake into the main session.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parents[0]))  # .../scripts

from rh_pool.client import create_workflow, query_task  # noqa: E402
from rh_pool.config import load_config  # noqa: E402
from rh_pool.store import Store, row_to_dict  # noqa: E402
from rh_pool import workflow_def  # noqa: E402
from runninghub import resolve_api_key  # noqa: E402


# --------------------------------------------------------------------- parsing
def parse_node_arg(arg: str) -> dict:
    """nodeId:fieldName=value -> {nodeId, fieldName, fieldValue}."""
    ci = arg.find(":")
    ei = arg.find("=", ci + 1) if ci != -1 else -1
    if ci == -1 or ei == -1:
        raise ValueError(f"invalid --node '{arg}', expected nodeId:fieldName=value")
    raw = arg[ei + 1:]
    try:
        value: object = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    return {"nodeId": arg[:ci], "fieldName": arg[ci + 1:ei], "fieldValue": value}


def build_job_from_args(args) -> dict:
    nodes = [parse_node_arg(n) for n in (args.node or [])]
    instance = args.instance_type or "default"
    return {
        "workflow_id": args.workflow_id,
        "instance_type": instance,
        "node_overrides": nodes,
        "request_json": {"workflowId": args.workflow_id, "instanceType": instance},
    }


# ------------------------------------------------------------------- commands
def cmd_enqueue(args) -> int:
    jobs: list[dict]
    if args.from_file:
        jobs = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        if isinstance(jobs, dict):
            jobs = [jobs]
    else:
        if not args.workflow_id:
            print("enqueue requires --workflow-id or --from-file", file=sys.stderr)
            return 2
        jobs = [build_job_from_args(args)]

    cfg = load_config()
    store = Store(cfg.db_path)
    ids = store.enqueue(jobs)
    print(json.dumps({"enqueued": len(ids), "poolIds": ids,
                      "counts": store.count_status()}, ensure_ascii=False, indent=2))
    return 0


def _dispatch_pending(store: Store, api_key: str, concurrency: int) -> dict:
    active = store.get_active()
    free = max(0, concurrency - len(active))
    summary = {"dispatched": 0, "submit_failed": 0}
    if free == 0:
        return summary
    for row in store.get_pending(free):
        payload: dict = {"apiKey": api_key, "workflowId": row["workflow_id"]}
        nodes = _loads(row["node_overrides"])
        if nodes:
            payload["nodeInfoList"] = nodes
        if row["instance_type"] and row["instance_type"] != "default":
            payload["instanceType"] = row["instance_type"]
        result = create_workflow(api_key, payload)
        if result.get("ok"):
            store.mark_dispatched(row["id"], result["task_id"])
            summary["dispatched"] += 1
        else:
            store.mark_submit_failed(
                row["id"], result.get("error_type", "UNKNOWN"),
                result.get("error_code", ""), result.get("error_message", ""),
            )
            summary["submit_failed"] += 1
    return summary


def _poll_active(store: Store, api_key: str) -> dict:
    summary = {"succeeded": 0, "failed": 0, "pending": 0, "poll_errors": 0}
    for row in store.get_active():
        result = query_task(api_key, row["rh_task_id"])
        if not result.get("ok"):
            # Poll/network problem only — do NOT terminalize, do NOT resubmit.
            summary["poll_errors"] += 1
            continue
        if not result.get("terminal"):
            store.apply_query_result(row["id"], "PENDING",
                                     rh_status=result.get("rh_status"))
            summary["pending"] += 1
        elif result["status"] == "SUCCESS":
            store.apply_query_result(
                row["id"], "SUCCESS", results=result.get("results"),
                cost_money=result.get("cost_money"),
                cost_coins=result.get("cost_coins"),
                cost_time_s=result.get("cost_time_s"),
            )
            summary["succeeded"] += 1
        else:
            store.apply_query_result(
                row["id"], "FAILED", error_code=result.get("error_code", ""),
                error_type=result.get("error_type", "UNKNOWN"),
                error_message=result.get("error_message", ""),
            )
            summary["failed"] += 1
    return summary


def cmd_tick(args) -> int:
    cfg = load_config()
    store = Store(cfg.db_path)
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print(json.dumps({"error": "NO_API_KEY"}))
        return 2

    dispatch = _dispatch_pending(store, api_key, cfg.concurrency)
    poll = _poll_active(store, api_key)
    drained = store.drain_just_happened()
    out = {
        "dispatched": dispatch,
        "polled": poll,
        "drained": drained,
        "counts": store.count_status(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_reconcile(args) -> int:
    """Force a full poll sync of every DISPATCHED task (post-restart)."""
    cfg = load_config()
    store = Store(cfg.db_path)
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print(json.dumps({"error": "NO_API_KEY"}))
        return 2
    poll = _poll_active(store, api_key)
    print(json.dumps({"reconciled": poll, "counts": store.count_status()},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_workflow(args) -> int:
    """Inspect task-type definitions and validate them against raw exports."""
    if args.wf_command == "list":
        types = workflow_def.load_task_types()
        out = [{
            "typeId": t.typeId, "displayName": t.displayName,
            "workflowId": t.workflowId, "instanceType": t.instanceType,
            "params": [p.name for p in t.params],
        } for t in types]
        print(json.dumps({"types": out}, ensure_ascii=False, indent=2))
        return 0

    if args.wf_command == "info":
        t = workflow_def.get_task_type(args.type_id)
        print(json.dumps({
            "typeId": t.typeId, "version": t.version,
            "displayName": t.displayName, "description": t.description,
            "workflowId": t.workflowId, "instanceType": t.instanceType,
            "params": [vars(p) for p in t.params],
            "fixedOverrides": t.fixedOverrides,
        }, ensure_ascii=False, indent=2))
        return 0

    # validate [typeId]
    reports = ([workflow_def.validate_type(workflow_def.get_task_type(args.type_id))]
               if args.type_id else workflow_def.validate_all())
    payload = [{"typeId": r.typeId, "ok": r.ok,
                "errors": r.errors, "warnings": r.warnings} for r in reports]
    print(json.dumps({"reports": payload}, ensure_ascii=False, indent=2))
    return 0 if all(r.ok for r in reports) else 1


def cmd_status(args) -> int:
    cfg = load_config()
    store = Store(cfg.db_path)
    if args.pool_id is not None or args.rh_task_id:
        row = store.get_task(pool_id=args.pool_id, rh_task_id=args.rh_task_id)
        print(json.dumps(row_to_dict(row) if row else {"error": "NOT_FOUND"},
                         ensure_ascii=False, indent=2))
        return 0 if row else 1
    rows = store.list_tasks(status=args.status_filter, limit=args.limit)
    out = {
        "counts": store.count_status(),
        "tasks": [row_to_dict(r) for r in rows],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _loads(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


# ----------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RunningHub async workflow task pool")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("enqueue", help="Add workflow job(s)")
    pe.add_argument("--workflow-id")
    pe.add_argument("--node", action="append", help="nodeId:fieldName=value")
    pe.add_argument("--instance-type", choices=["default", "plus", "ultra"])
    pe.add_argument("--from-file", help="JSON file: job or list of jobs")

    pt = sub.add_parser("tick", help="One non-blocking advance")
    pt.add_argument("--api-key", "-k")

    pr = sub.add_parser("reconcile", help="Resync active tasks with RH")
    pr.add_argument("--api-key", "-k")

    pw = sub.add_parser("workflow", help="Inspect/validate task-type definitions")
    pw.add_argument("wf_command", choices=["list", "info", "validate"])
    pw.add_argument("type_id", nargs="?")

    ps = sub.add_parser("status", help="Query ledger")
    ps.add_argument("--pool-id", type=int)
    ps.add_argument("--rh-task-id")
    ps.add_argument("--status-filter")
    ps.add_argument("--limit", type=int, default=50)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "enqueue": cmd_enqueue,
        "tick": cmd_tick,
        "reconcile": cmd_reconcile,
        "workflow": cmd_workflow,
        "status": cmd_status,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

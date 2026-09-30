#!/usr/bin/env python3
"""Generate Vox MVP collage keyframes through the runninghub TASK POOL.

Pipeline:
- Build one typed pool job per planned shot (type image-gen-qwen, zero-cash).
- Dry-run by default: prints the exact jobs JSON, submits nothing.
- --submit enqueues the whole stage as ONE pool batch (pool concurrency applies),
  then drives pool ticks in-process until every task is terminal. A task is never
  resubmitted because it is slow.
- Reuses existing non-empty keyframe files unless --force is provided.
- Stops the stage if any task FAILED; per-shot errors are written to beats.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from new_project import validate_doc
import rh_pool_client as pool

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

POOL_TYPE = "image-gen-qwen"
ASPECT = "16:9 (Widescreen)"


def load_doc(project_dir: Path) -> dict:
    beats_path = project_dir / "beats.json"
    if not beats_path.exists():
        raise SystemExit(f"beats.json not found: {beats_path}")
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=True, project_dir=project_dir)
    if errors:
        print("Strict validation failed; refusing to generate keyframes:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    return doc


def save_doc(project_dir: Path, doc: dict) -> None:
    (project_dir / "beats.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def planned_shots(doc: dict, only: set[str] | None) -> list[dict]:
    shots = doc["shots"]
    if only:
        shots = [shot for shot in shots if shot.get("id") in only]
        missing = only - {shot.get("id") for shot in doc["shots"]}
        if missing:
            raise SystemExit(f"Unknown shot ID(s): {sorted(missing)}")
    return shots


def existing_output(shot: dict) -> Path | None:
    value = shot.get("keyframe_path")
    if value:
        path = Path(value)
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return path
    return None


def run(project_dir: Path, only: set[str] | None, force: bool, submit: bool) -> int:
    doc = load_doc(project_dir)
    pool.ensure_pool_script()

    keyframe_dir = project_dir / "keyframes"
    keyframe_dir.mkdir(exist_ok=True)

    planned: list[tuple[dict, dict]] = []
    for shot in planned_shots(doc, only):
        sid = shot["id"]
        if not shot.get("keyframe_prompt"):
            raise SystemExit(f"{sid} is missing keyframe_prompt; run generate_keyframe_prompts.py first")
        if existing_output(shot) and not force:
            print(f"[{sid}] Reusing existing keyframe file: {existing_output(shot)}")
            continue
        job = {
            "type": POOL_TYPE,
            "params": {"prompt": shot["keyframe_prompt"], "aspectRatio": ASPECT},
            "outputDir": str(keyframe_dir),
            "outputName": f"kf_{sid}",
        }
        planned.append((shot, job))

    if not planned:
        print("Nothing to generate (all keyframes exist).")
        return 0

    shots = [s for s, _ in planned]
    jobs = [j for _, j in planned]

    if not submit:
        print(f"DRY-RUN: would enqueue {len(jobs)} keyframe task(s) "
              f"({POOL_TYPE}, RH coins, no third-party cash) as one batch:")
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        print("\nDRY-RUN only: no task was submitted and no cost was incurred.")
        print("After explicit paid-generation approval, rerun with --submit.")
        return 0

    print(f"Enqueuing {len(jobs)} keyframe task(s) as one pool batch...")
    batch_id, pool_ids = pool.enqueue_batch(jobs)
    print(f"batch {batch_id}: pool ids {pool_ids}")
    for shot, pid in zip(shots, pool_ids):
        shot["image_pool_id"] = pid
    save_doc(project_dir, doc)  # persist pool ids BEFORE the long wait

    snapshot = pool.wait_for(pool_ids)

    failed = 0
    coins_total = 0
    for shot, pid in zip(shots, pool_ids):
        sid = shot["id"]
        row = snapshot[pid]
        status = row.get("status")
        lines = pool.task_lines(pid)
        out = lines.get("OUTPUT_FILE")
        ok = status == "SUCCESS" and out and Path(out).exists() and Path(out).stat().st_size > 0
        if not ok:
            failed += 1
            shot["last_error"] = (row.get("error_message")
                                  or f"pool {pid} ended {status} with no output file")
            print(f"[{sid}] FAILED (pool {pid}): {shot['last_error']}")
            save_doc(project_dir, doc)
            continue
        shot["keyframe_path"] = out
        shot.pop("last_error", None)
        coins = int(lines.get("COINS") or 0)
        shot["image_coins"] = coins
        coins_total += coins
        print(f"[{sid}] Saved: {out} ({coins} coins)")
        save_doc(project_dir, doc)

    if failed:
        print(f"\n{failed}/{len(shots)} keyframe task(s) failed. Successful outputs "
              f"were kept; rerun with --submit to enqueue the missing shots (existing "
              f"files are reused, nothing is resubmitted automatically).")
        return 1

    doc["status"] = "keyframes"
    save_doc(project_dir, doc)
    print(f"\nKeyframe stage complete — {len(shots)} image(s), {coins_total} RH coins.")
    print("Review every image before entering the video stage.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Vox MVP keyframes via the RH task pool")
    parser.add_argument("project_dir", help="Project directory containing beats.json")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s1,s2")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a local keyframe exists")
    parser.add_argument("--submit", action="store_true", help="Actually submit billable pool tasks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.force, args.submit)


if __name__ == "__main__":
    raise SystemExit(main())

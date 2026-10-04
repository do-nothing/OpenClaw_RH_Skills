#!/usr/bin/env python3
"""Generate Vox MVP image-to-video clips through the runninghub TASK POOL.

- One typed pool job per planned shot: MiniMax H3 first-frame-to-video
  (type i2v-minimax-h3-first-frame, plus instance), 8 s, 16:9.
- Dry-run by default. --submit enqueues the whole stage as ONE pool batch and
  drives ticks until terminal; a slow task is never resubmitted.
- Existing non-empty clips are reused unless --force.
- H3 clips carry native sound, but assemble.py rebuilds all audio (-an on every
  segment), so the source soundtrack is irrelevant.
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

POOL_TYPE = "i2v-minimax-h3-first-frame"
SOURCE_DURATION_S = 8      # H3 accepts 4-15 s; assemble budget assumes 8 s sources
ASPECT_SELECT = 5          # 1=1:1 2=3:4 3=4:3 4=9:16 5=16:9 6=follow first frame


def planned_shots(doc: dict, only: set[str] | None) -> list[dict]:
    shots = doc["shots"]
    if only:
        shots = [shot for shot in shots if shot.get("id") in only]
        missing = only - {shot.get("id") for shot in doc["shots"]}
        if missing:
            raise SystemExit(f"Unknown shot ID(s): {sorted(missing)}")
    return shots


def existing_clip(shot: dict) -> Path | None:
    value = shot.get("clip_path")
    if value:
        path = Path(value)
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return path
    return None


def run(project_dir: Path, only: set[str] | None, force: bool, submit: bool) -> int:
    beats_path = project_dir / "beats.json"
    if not beats_path.exists():
        raise SystemExit(f"beats.json not found: {beats_path}")
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=True, project_dir=project_dir)
    if errors:
        print("Strict validation failed; refusing to generate clips:")
        for error in errors:
            print(f"- {error}")
        return 1
    pool.ensure_pool_script()

    clip_dir = project_dir / "clips"
    clip_dir.mkdir(exist_ok=True)

    planned: list[tuple[dict, dict]] = []
    for shot in planned_shots(doc, only):
        sid = shot["id"]
        if not shot.get("clip_prompt"):
            raise SystemExit(f"{sid} is missing clip_prompt; run generate_clip_prompts.py first")
        keyframe_path = Path(str(shot.get("keyframe_path", "")))
        if not keyframe_path.exists():
            raise SystemExit(f"{sid} keyframe file does not exist: {keyframe_path}")
        if existing_clip(shot) and not force:
            print(f"[{sid}] Reusing existing clip file: {existing_clip(shot)}")
            continue
        duration_s = int(shot.get("video_source_duration_s") or SOURCE_DURATION_S)
        job = {
            "type": POOL_TYPE,
            "params": {
                "image": str(keyframe_path),
                "prompt": shot["clip_prompt"],
                "durationSeconds": duration_s,
                "aspectSelect": ASPECT_SELECT,
            },
            "outputDir": str(clip_dir),
            "outputName": f"clip_{sid}",
        }
        planned.append((shot, job))

    if not planned:
        print("Nothing to generate (all clips exist).")
        return 0

    shots = [s for s, _ in planned]
    jobs = [j for _, j in planned]

    if not submit:
        print(f"DRY-RUN: would enqueue {len(jobs)} H3 clip task(s) "
              f"({SOURCE_DURATION_S}s, 16:9, plus instance, RH coins) as one batch:")
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        print("\nDRY-RUN only: no task was submitted and no cost was incurred.")
        print("After explicit approval, rerun with --submit.")
        return 0

    print(f"Enqueuing {len(jobs)} clip task(s) as one pool batch (video can take "
          f"several minutes per task, 3 run concurrently)...")
    batch_id, pool_ids = pool.enqueue_batch(jobs)
    print(f"batch {batch_id}: pool ids {pool_ids}")
    for shot, pid in zip(shots, pool_ids):
        shot["video_pool_id"] = pid
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")  # persist pool ids BEFORE the long wait

    snapshot = pool.wait_for(pool_ids)

    failed = 0
    coins_total = 0
    for shot, pid in zip(shots, pool_ids):
        sid = shot["id"]
        duration_s = int(shot.get("video_source_duration_s") or SOURCE_DURATION_S)
        row = snapshot[pid]
        status = row.get("status")
        lines = pool.task_lines(pid)
        out = lines.get("OUTPUT_FILE")
        ok = status == "SUCCESS" and out and Path(out).exists() and Path(out).stat().st_size > 0
        if not ok:
            failed += 1
            shot["last_video_error"] = (row.get("error_message")
                                        or f"pool {pid} ended {status} with no output file")
            print(f"[{sid}] FAILED (pool {pid}): {shot['last_video_error']}")
            beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue
        shot["clip_path"] = out
        shot["clip_source_duration_s"] = duration_s
        shot.pop("last_video_error", None)
        coins = int(lines.get("COINS") or 0)
        shot["video_coins"] = coins
        coins_total += coins
        print(f"[{sid}] Saved: {out} ({coins} coins)")
        beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if failed:
        print(f"\n{failed}/{len(shots)} clip task(s) failed. Successful clips were "
              f"kept; rerun with --submit for the missing shots (no auto-resubmit).")
        return 1

    doc["status"] = "clips"
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nClip stage complete — {len(shots)} clip(s), {coins_total} RH coins.")
    print("Review each source clip before audio/assembly.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Vox MVP clips via the RH task pool")
    parser.add_argument("project_dir")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s1,s2")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a clip file exists")
    parser.add_argument("--submit", action="store_true", help="Actually submit billable video tasks")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.force, args.submit)


if __name__ == "__main__":
    raise SystemExit(main())

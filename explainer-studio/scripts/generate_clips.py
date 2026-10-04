#!/usr/bin/env python3
"""Stage 5: image-to-video clips via the RH pool — ONE mixed batch.

  first_frame shots        -> i2v-minimax-h3-first-frame
  first_last_frame shots   -> i2v-minimax-h3-first-last-frame
Integer durationSeconds = clamp(ceil(used_duration_s),4,15); aspectSelect from
the project aspect map. Downloaded clips are ffprobe-checked to actually cover
their used duration. Dry-run by default; never auto-resubmitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from explainer_common import find_tool, load_doc, probe_duration, save_doc
import rh_pool_client as pool


def run(project_dir: Path, only: set[str] | None, force: bool, submit: bool) -> int:
    doc = load_doc(project_dir)
    pool.ensure_pool_script()
    shots = doc["shots"]
    if only:
        shots = [s for s in shots if s["id"] in only]
        missing = only - {s["id"] for s in doc["shots"]}
        if missing:
            raise SystemExit(f"Unknown shot id(s): {sorted(missing)}")

    clip_dir = project_dir / "clips"
    clip_dir.mkdir(exist_ok=True)
    aspect_select = int(doc["aspect_map"]["video"])

    planned: list[tuple[dict, dict]] = []
    for s in shots:
        sid = s["id"]
        if not s.get("clip_prompt"):
            raise SystemExit(f"{sid}: run generate_clip_prompts.py first")
        first = Path(str(s.get("first_frame_path") or ""))
        if not first.exists():
            raise SystemExit(f"{sid}: first frame missing: {first}")
        if s["mode"] == "first_last_frame":
            last = Path(str(s.get("last_frame_path") or ""))
            if not last.exists():
                raise SystemExit(f"{sid}: last frame missing: {last}")
        existing = s.get("clip_path")
        if existing and Path(existing).exists() and Path(existing).stat().st_size > 0 and not force:
            if s.get("clip_prompt_hash") != s.get("clip_prompt_sha256"):
                print(f"[{sid}] clip exists but video prompt changed; needs --force")
                continue
            print(f"[{sid}] Reusing clip: {existing}")
            continue

        dur = int(s["submit_duration_s"])
        if s["mode"] == "first_frame":
            job = {
                "type": doc["endpoints"]["video_first_frame"]["type"],
                "params": {"image": str(first), "prompt": s["clip_prompt"],
                           "durationSeconds": dur, "aspectSelect": aspect_select},
                "outputDir": str(clip_dir), "outputName": f"clip_{sid}",
            }
        else:
            job = {
                "type": doc["endpoints"]["video_first_last_frame"]["type"],
                "params": {"firstFrame": str(first), "lastFrame": str(last),
                           "prompt": s["clip_prompt"],
                           "durationSeconds": dur, "aspectSelect": aspect_select},
                "outputDir": str(clip_dir), "outputName": f"clip_{sid}",
            }
        planned.append((s, job))

    if not planned:
        print("Nothing to generate (all clips exist).")
        return 0

    jobs = [j for _, j in planned]
    if not submit:
        print(f"DRY-RUN: would enqueue {len(jobs)} video task(s) as ONE mixed batch:")
        for s, j in planned:
            print(f"  {s['id']:7s} {j['type']:34s} {s['submit_duration_s']:2d}s "
                  f"use={s['used_duration_s']:.2f}s")
        print("\n" + json.dumps(jobs, ensure_ascii=False, indent=2))
        print("\nDRY-RUN only: no cost. Rerun with --submit after approval.")
        return 0

    print(f"Enqueuing {len(jobs)} video task(s) as one mixed batch (minutes per task)...")
    batch_id, pool_ids = pool.enqueue_batch(jobs)
    print(f"batch {batch_id}: pool ids {pool_ids}")
    for (s, _j), pid in zip(planned, pool_ids):
        s["video_pool_id"] = pid
    save_doc(project_dir, doc)

    snapshot = pool.wait_for(pool_ids)
    ffprobe = find_tool("ffprobe")
    failed = 0
    coins_total = 0
    for (s, _j), pid in zip(planned, pool_ids):
        sid = s["id"]
        row = snapshot[pid]
        status = row.get("status")
        lines = pool.task_lines(pid)
        out = lines.get("OUTPUT_FILE")
        ok = status == "SUCCESS" and out and Path(out).exists() and Path(out).stat().st_size > 0
        if not ok:
            failed += 1
            s["last_video_error"] = (row.get("error_message")
                                     or f"pool {pid} ended {status} with no output file")
            print(f"[{sid}] FAILED (pool {pid}): {s['last_video_error']}")
            save_doc(project_dir, doc)
            continue
        src_dur = probe_duration(ffprobe, Path(out))
        if src_dur + 0.02 < float(s["used_duration_s"]):
            failed += 1
            s["last_video_error"] = (f"source clip {src_dur:.2f}s shorter than required "
                                     f"used {s['used_duration_s']:.2f}s")
            print(f"[{sid}] FAILED local check: {s['last_video_error']}")
            save_doc(project_dir, doc)
            continue
        s["clip_path"] = out
        s["clip_source_duration_s"] = round(src_dur, 3)
        s["clip_prompt_hash"] = s.get("clip_prompt_sha256")
        s.pop("last_video_error", None)
        coins = int(lines.get("COINS") or 0)
        s["video_coins"] = coins
        coins_total += coins
        print(f"[{sid}] saved {src_dur:.2f}s ({coins} coins) -> {Path(out).name}")
        save_doc(project_dir, doc)

    if failed:
        print(f"\n{failed}/{len(planned)} clip task(s) failed/short. Others kept; rerun "
              "--submit for missing shots (no auto-resubmit).")
        return 1

    doc["status"] = "clips"
    save_doc(project_dir, doc)
    print(f"\nClip stage complete — {len(planned)} clip(s), {coins_total} RH coins.")
    print("Next: python scripts/assemble.py")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 5 mixed video batch")
    p.add_argument("project_dir")
    p.add_argument("--only", help="Comma-separated shot ids")
    p.add_argument("--force", action="store_true")
    p.add_argument("--submit", action="store_true")
    args = p.parse_args(argv or sys.argv[1:])
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.force, args.submit)


if __name__ == "__main__":
    raise SystemExit(main())

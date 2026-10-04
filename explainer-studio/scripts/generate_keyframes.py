#!/usr/bin/env python3
"""Stage 4: keyframes via the RH task pool, in TWO waves within one payment gate.

  --wave first  image-gen-qwen       text-to-image for every shot's first frame
  --wave last   image-edit-qwen      single-image edit producing the last frame
                                     (first_last_frame shots only)

Run wave first, review the images, then wave last. Dry-run by default;
--submit enqueues that wave as ONE pool batch and never auto-resubmits.
Existing non-empty files are reused unless --force; images whose English prompt
hash changed refuse to submit without --force.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from explainer_common import load_doc, save_doc
import rh_pool_client as pool

FIRST_TYPE = "image-gen-qwen"
LAST_TYPE = "image-edit-qwen"


def run(project_dir: Path, wave: str, only: set[str] | None,
        force: bool, submit: bool) -> int:
    doc = load_doc(project_dir)
    pool.ensure_pool_script()
    shots = doc["shots"]
    if only:
        shots = [s for s in shots if s["id"] in only]
        missing = only - {s["id"] for s in doc["shots"]}
        if missing:
            raise SystemExit(f"Unknown shot id(s): {sorted(missing)}")

    kf_dir = project_dir / "keyframes"
    kf_dir.mkdir(exist_ok=True)
    aspect_image = doc["aspect_map"]["image"]

    planned: list[tuple[dict, dict, str]] = []
    stale: list[str] = []

    for s in shots:
        sid = s["id"]
        if wave == "first":
            if not s.get("keyframe_prompt"):
                raise SystemExit(f"{sid}: run generate_keyframe_prompts.py first")
            out = Path(str(s.get("first_frame_path") or kf_dir / f"kf_{sid}_first"))
            if out.exists() and out.stat().st_size > 0 and not force:
                if s.get("first_frame_prompt_hash") != s.get("keyframe_prompt_sha256"):
                    stale.append(sid)
                    print(f"[{sid}] image exists but prompt changed; not reusing without --force")
                    continue
                print(f"[{sid}] Reusing first frame: {out}")
                continue
            planned.append((s, {
                "type": FIRST_TYPE,
                "params": {"prompt": s["keyframe_prompt"], "aspectRatio": aspect_image},
                "outputDir": str(kf_dir), "outputName": f"kf_{sid}_first",
            }, "first"))
        else:
            if s["mode"] != "first_last_frame":
                continue
            first = Path(str(s.get("first_frame_path") or ""))
            if not first.exists():
                raise SystemExit(f"{sid}: first frame missing — finish --wave first and review it")
            if not s.get("last_frame_prompt"):
                raise SystemExit(f"{sid}: last_frame_prompt missing; rerun generate_keyframe_prompts.py")
            out = Path(str(s.get("last_frame_path") or kf_dir / f"kf_{sid}_last"))
            if out.exists() and out.stat().st_size > 0 and not force:
                if s.get("last_frame_prompt_hash") != s.get("last_frame_prompt_sha256"):
                    stale.append(sid)
                    print(f"[{sid}] last frame exists but edit prompt changed; needs --force")
                    continue
                print(f"[{sid}] Reusing last frame: {out}")
                continue
            planned.append((s, {
                "type": LAST_TYPE,
                "params": {"prompt": s["last_frame_prompt"],
                           "image": str(first),
                           "aspectRatio": aspect_image},
                "outputDir": str(kf_dir), "outputName": f"kf_{sid}_last",
            }, "last"))

    if stale:
        print(f"\n这些镜头的提示词已变且已有成图：{stale}。确认视觉返工后加 --force 重滚。")
    if not planned:
        print("Nothing to generate for this wave (all images exist).")
        return 0

    jobs = [j for _, j, _ in planned]
    type_id = FIRST_TYPE if wave == "first" else LAST_TYPE
    if not submit:
        print(f"DRY-RUN: would enqueue {len(jobs)} {type_id} task(s) as one batch "
              f"(wave={wave}, aspect={aspect_image}, RH coins):")
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        print("\nDRY-RUN only: no cost. Rerun with --submit after approval.")
        return 0

    print(f"Enqueuing {len(jobs)} {type_id} task(s) (wave {wave})...")
    batch_id, pool_ids = pool.enqueue_batch(jobs)
    print(f"batch {batch_id}: pool ids {pool_ids}")
    for (s, _j, kind), pid in zip(planned, pool_ids):
        s["last_image_pool_id" if kind == "last" else "image_pool_id"] = pid
    save_doc(project_dir, doc)

    snapshot = pool.wait_for(pool_ids)
    failed = 0
    coins_total = 0
    for (s, _j, kind), pid in zip(planned, pool_ids):
        sid = s["id"]
        row = snapshot[pid]
        status = row.get("status")
        lines = pool.task_lines(pid)
        out = lines.get("OUTPUT_FILE")
        ok = status == "SUCCESS" and out and Path(out).exists() and Path(out).stat().st_size > 0
        if not ok:
            failed += 1
            s["last_image_error"] = (row.get("error_message")
                                     or f"pool {pid} ended {status} with no output file")
            print(f"[{sid}] FAILED (pool {pid}): {s['last_image_error']}")
            save_doc(project_dir, doc)
            continue
        if kind == "first":
            s["first_frame_path"] = out
            s["first_frame_prompt_hash"] = s.get("keyframe_prompt_sha256")
        else:
            s["last_frame_path"] = out
            s["last_frame_prompt_hash"] = s.get("last_frame_prompt_sha256")
        s.pop("last_image_error", None)
        coins = int(lines.get("COINS") or 0)
        s["image_coins"] = int(s.get("image_coins") or 0) + coins
        coins_total += coins
        print(f"[{sid}] saved ({kind}, {coins} coins) -> {out}")
        save_doc(project_dir, doc)

    if failed:
        print(f"\n{failed}/{len(planned)} image task(s) failed. Successes kept; rerun "
              "this wave with --submit for the missing shots (no auto-resubmit).")
        return 1

    if doc.get("status") in ("shots",):
        doc["status"] = "keyframes"
    save_doc(project_dir, doc)
    print(f"\nWave {wave} complete — {len(planned)} image(s), {coins_total} RH coins.")
    if wave == "first":
        print("Review every first frame now (weak images are cheapest to re-roll here), then run")
        print("  python scripts/generate_keyframes.py --wave last   # only first_last_frame shots")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 4 keyframes (two waves)")
    p.add_argument("project_dir")
    p.add_argument("--wave", required=True, choices=("first", "last"))
    p.add_argument("--only", help="Comma-separated shot ids")
    p.add_argument("--force", action="store_true")
    p.add_argument("--submit", action="store_true")
    args = p.parse_args(argv or sys.argv[1:])
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), args.wave, only, args.force, args.submit)


if __name__ == "__main__":
    raise SystemExit(main())

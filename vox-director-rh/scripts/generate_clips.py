#!/usr/bin/env python3
"""Generate Vox MVP image-to-video clips through the RunningHub skill.

Default mode is a local dry-run. Use --submit only after explicit user approval.
The script waits for each submitted task and never resubmits because it is slow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from new_project import validate_doc

DEFAULT_ENDPOINT = "rhart-video-v3.1-pro/image-to-video"
ALLOWED_ENDPOINTS = {
    DEFAULT_ENDPOINT,
    "rhart-video-v3.1-fast/image-to-video",
}
RUNNINGHUB_SCRIPT = os.environ.get(
    "RUNNINGHUB_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "runninghub", "scripts", "runninghub.py"),
)
SOURCE_DURATION_S = "8"
RESOLUTION = "720p"

TASK_ID_RE = re.compile(r"Task ID:\s*([A-Za-z0-9_-]+)")
OUTPUT_RE = re.compile(r"OUTPUT_FILE:(.+)")
COST_RE = re.compile(r"COST:¥([0-9.]+)")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


def planned_shots(doc: dict, only: set[str] | None) -> list[dict]:
    shots = doc["shots"]
    if only:
        shots = [shot for shot in shots if shot.get("id") in only]
        missing = only - {shot.get("id") for shot in shots}
        if missing:
            raise SystemExit(f"Unknown shot ID(s): {sorted(missing)}")
    return shots


def existing_clip(shot: dict) -> Path | None:
    value = shot.get("clip_path")
    if not value:
        return None
    path = Path(value)
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        return path
    return None


def build_command(shot: dict, output: Path) -> list[str]:
    keyframe_path = Path(str(shot["keyframe_path"]))
    return [
        sys.executable,
        RUNNINGHUB_SCRIPT,
        "--endpoint",
        DEFAULT_ENDPOINT,
        "--prompt",
        shot["clip_prompt"],
        "--image",
        str(keyframe_path),
        "--param",
        "aspectRatio=16:9",
        "--param",
        f"duration={SOURCE_DURATION_S}",
        "--param",
        f"resolution={RESOLUTION}",
        "-o",
        str(output),
    ]


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

    endpoint = doc.get("video_endpoint") or DEFAULT_ENDPOINT
    if endpoint not in ALLOWED_ENDPOINTS:
        raise SystemExit(f"Unsupported video endpoint: {endpoint}")

    runninghub = Path(RUNNINGHUB_SCRIPT)
    if not runninghub.exists():
        raise SystemExit(f"RunningHub script not found: {runninghub}")

    clip_dir = project_dir / "clips"
    clip_dir.mkdir(exist_ok=True)
    shots = planned_shots(doc, only)
    costs: list[str] = []

    for index, shot in enumerate(shots):
        sid = shot["id"]
        if not shot.get("clip_prompt"):
            raise SystemExit(f"{sid} is missing clip_prompt; run generate_clip_prompts.py first")
        keyframe_path = Path(str(shot.get("keyframe_path", "")))
        if not keyframe_path.exists():
            raise SystemExit(f"{sid} keyframe file does not exist: {keyframe_path}")

        reused = existing_clip(shot)
        if reused and not force:
            print(f"[{sid}] Reusing existing clip file: {reused}")
            continue

        output = clip_dir / f"clip_{sid}.mp4"
        cmd = build_command(shot, output)

        if not submit:
            print(f"[{sid}] DRY-RUN: would submit one {SOURCE_DURATION_S}s {RESOLUTION} image-to-video task")
            print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
            continue

        print(f"[{sid}] Submitting image-to-video task ({index + 1}/{len(shots)}). Video can take several minutes; waiting for this exact task, no duplicate submission...")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        combined = "\n".join([proc.stdout or "", proc.stderr or ""])
        task_match = TASK_ID_RE.search(combined)
        if task_match:
            shot["video_task_id"] = task_match.group(1)

        output_match = OUTPUT_RE.search(combined)
        actual_path = Path(output_match.group(1).strip()) if output_match else None
        downloaded_ok = bool(actual_path and actual_path.exists() and actual_path.stat().st_size > 0)

        if proc.returncode != 0 and not downloaded_ok:
            shot["last_video_error"] = combined.strip()[-3000:]
            beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[{sid}] Video task failed or timed out. Stopped; it will not be resubmitted automatically.")
            if task_match:
                print(f"Task ID: {shot['video_task_id']}")
            print(combined.strip())
            return 1

        if not downloaded_ok:
            shot["last_video_error"] = "Task returned success but no non-empty video OUTPUT_FILE was found"
            beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(combined)
            raise SystemExit(f"[{sid}] No valid video output was resolved")

        shot["clip_url"] = ""  # URL is not required locally; RunningHub child downloaded the file.
        shot["clip_path"] = str(actual_path)
        shot["clip_source_duration_s"] = int(SOURCE_DURATION_S)
        shot.pop("last_video_error", None)
        cost_match = COST_RE.search(combined)
        if cost_match:
            shot["video_cost"] = cost_match.group(1)
            costs.append(f"{sid} ¥{cost_match.group(1)}")
        beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{sid}] Saved: {actual_path}")

    if submit:
        doc["status"] = "clips"
        beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if costs:
            print("Cost: " + ", ".join(costs))
        print("Clip stage complete. Review each source clip before audio/assembly.")
    else:
        print("\nDRY-RUN only: no task was submitted and no cost was incurred.")
        print("After explicit paid-generation approval, rerun with --submit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Vox MVP clips via RunningHub")
    parser.add_argument("project_dir")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s1,s2")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a clip file exists")
    parser.add_argument("--submit", action="store_true", help="Actually submit billable video tasks")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.force, args.submit)


if __name__ == "__main__":
    raise SystemExit(main())

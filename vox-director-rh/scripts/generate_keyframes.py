#!/usr/bin/env python3
"""Generate Vox MVP collage keyframes through the installed RunningHub skill.

Safety rules:
- Offline validation only unless --submit is provided.
- Submits one shot at a time and waits for that exact task.
- Never resubmits because a task is slow; the RunningHub client owns polling.
- Reuses existing non-empty keyframe files unless --force is provided.
- Stops at the first failure and records endpoint/task/error on the shot.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# This wrapper is run from Windows GBK consoles; force UTF-8 before printing costs.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

from new_project import validate_doc

DEFAULT_ENDPOINT = "rhart-image-n-g31-flash-lite/text-to-image"
ALLOWED_ENDPOINTS = {
    DEFAULT_ENDPOINT,
    "rhart-image-n-pro/text-to-image",
}
RUNNINGHUB_SCRIPT = os.environ.get(
    "RUNNINGHUB_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "runninghub", "scripts", "runninghub.py"),
)
TASK_ID_RE = re.compile(r"Task ID:\s*([A-Za-z0-9_-]+)")
OUTPUT_RE = re.compile(r"OUTPUT_FILE:(.+)")
COST_RE = re.compile(r"COST:¥([0-9.]+)")


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


def build_command(script: str, endpoint: str, shot: dict, output: Path) -> list[str]:
    return [
        sys.executable,
        script,
        "--endpoint",
        endpoint,
        "--prompt",
        shot["keyframe_prompt"],
        "--param",
        "aspectRatio=16:9",
        "-o",
        str(output),
    ]


def planned_shots(doc: dict, only: set[str] | None) -> list[dict]:
    shots = doc["shots"]
    if only:
        shots = [shot for shot in shots if shot.get("id") in only]
        missing = only - {shot.get("id") for shot in shots}
        if missing:
            raise SystemExit(f"Unknown shot ID(s): {sorted(missing)}")
    return shots


def existing_output(shot: dict) -> Path | None:
    value = shot.get("keyframe_path")
    if not value:
        return None
    path = Path(value)
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        return path
    return None


def run(project_dir: Path, only: set[str] | None, force: bool, submit: bool) -> int:
    doc = load_doc(project_dir)
    endpoint = doc.get("image_endpoint") or DEFAULT_ENDPOINT
    if endpoint not in ALLOWED_ENDPOINTS:
        raise SystemExit(f"Unsupported image endpoint: {endpoint}")
    if endpoint == DEFAULT_ENDPOINT and doc.get("image_resolution"):
        print("Note: Nano Banana 2 low-cost channel ignores resolution; no resolution parameter will be sent.")

    script = Path(RUNNINGHUB_SCRIPT)
    if not script.exists():
        raise SystemExit(f"RunningHub script not found: {script}")

    keyframe_dir = project_dir / "keyframes"
    keyframe_dir.mkdir(exist_ok=True)
    shots = planned_shots(doc, only)
    costs: list[str] = []

    for index, shot in enumerate(shots):
        sid = shot["id"]
        if not shot.get("keyframe_prompt"):
            raise SystemExit(f"{sid} is missing keyframe_prompt; run generate_keyframe_prompts.py first")

        reused = existing_output(shot)
        if reused and not force:
            print(f"[{sid}] Reusing existing keyframe file: {reused}")
            continue

        output = keyframe_dir / f"kf_{sid}.jpg"
        cmd = build_command(str(script), endpoint, shot, output)

        if not submit:
            print(f"[{sid}] DRY-RUN: would submit one keyframe task")
            print(" ".join(f'"{x}"' if " " in x else x for x in cmd))
            continue

        print(f"[{sid}] Submitting keyframe task ({index + 1}/{len(shots)}); waiting for this exact task, no duplicate submission...")
        child_env = os.environ.copy()
        # RunningHub prints the yen cost character; force UTF-8 so Windows GBK
        # consoles cannot turn a completed download into a wrapper-visible failure.
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
        combined = "\n".join([proc.stdout or "", proc.stderr or ""])

        task_match = TASK_ID_RE.search(combined)
        if task_match:
            shot["image_task_id"] = task_match.group(1)

        output_match = OUTPUT_RE.search(combined)
        actual_path = Path(output_match.group(1).strip()) if output_match else None
        downloaded_ok = bool(actual_path and actual_path.exists() and actual_path.stat().st_size > 0)

        if proc.returncode != 0 and not downloaded_ok:
            shot["last_error"] = combined.strip()[-2000:]
            save_doc(project_dir, doc)
            print(f"[{sid}] Task failed or timed out. Stopped; it will not be resubmitted automatically.")
            if task_match:
                print(f"Task ID: {shot['image_task_id']}")
            print(combined.strip())
            return 1

        if not downloaded_ok:
            shot["last_error"] = "Task reported success but no non-empty downloaded OUTPUT_FILE was found"
            save_doc(project_dir, doc)
            print(combined)
            raise SystemExit(f"[{sid}] No valid output file was resolved")

        if proc.returncode != 0:
            print(f"[{sid}] RunningHub child returned code {proc.returncode}, but the output file exists; treating as success without resubmitting.")

        shot["keyframe_path"] = str(actual_path)
        shot.pop("last_error", None)
        cost_match = COST_RE.search(combined)
        if cost_match:
            shot["image_cost"] = cost_match.group(1)
            costs.append(f"{sid} ¥{cost_match.group(1)}")
        save_doc(project_dir, doc)
        print(f"[{sid}] Saved: {actual_path}")

    if submit:
        doc["status"] = "keyframes"
        save_doc(project_dir, doc)
        if costs:
            print("花费: " + "，".join(costs))
        print("Keyframe stage complete. Review every image before entering the video stage.")
    else:
        print("\nDRY-RUN only: no task was submitted and no cost was incurred.")
        print("After explicit paid-generation approval, rerun with --submit.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Vox MVP keyframes via RunningHub")
    parser.add_argument("project_dir", help="Project directory containing beats.json")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s1,s2")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a local keyframe exists")
    parser.add_argument("--submit", action="store_true", help="Actually submit billable RunningHub tasks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.force, args.submit)


if __name__ == "__main__":
    raise SystemExit(main())

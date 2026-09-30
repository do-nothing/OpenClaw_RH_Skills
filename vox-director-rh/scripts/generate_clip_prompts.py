#!/usr/bin/env python3
"""Generate offline English image-to-video prompts for Vox MVP shots.

Does not access network and does not submit RunningHub tasks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from new_project import validate_doc

DEFAULT_VIDEO_ENDPOINT = "rhart-video-v3.1-pro/image-to-video"
SOURCE_DURATION_S = 8
RESOLUTION = "720p"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

CAMERA = {
    "push_in": (
        "one very slow, smooth, uniform push-in like a controlled Ken Burns move; "
        "the whole poster scales evenly without perspective distortion"
    ),
    "pull_out": (
        "one very slow, smooth, uniform pull-out that reveals more of the scene; "
        "the whole poster scales down evenly with no perspective change"
    ),
    "pan": (
        "one slow horizontal flat pan across the paper poster; translate sideways only, "
        "with no perspective change and no rotation"
    ),
    "tilt": (
        "one slow vertical flat tilt through the paper poster; translate vertically only, "
        "steady and flat, with no perspective change and no rotation"
    ),
    "parallax": (
        "the camera remains nearly locked while foreground, middle-ground and background "
        "paper layers drift at slightly different speeds in a gentle 2D parallax"
    ),
    "static": (
        "a locked-off static camera with no camera movement and no framing change"
    ),
}


def compose_clip_prompt(shot: dict) -> str:
    move = CAMERA[shot["camera_move"]]
    element_motion = str(shot.get("element_motion_en", "")).strip()
    title_rule = (
        "The exact Chinese headline and every printed mark must remain sharp, stable and unchanged; "
        "do not redraw, re-letter, warp or duplicate any text."
        if shot.get("title_on_image")
        else "Keep all graphic marks abstract and unreadable; do not introduce any letters or words."
    )
    return (
        "Animate this existing flat 2D hand-cut paper-collage poster into a subtle motion-graphic shot. "
        "Preserve the original composition, subject, colors, torn-paper edges, tape, halftone dots, newsprint texture and paper drop shadows exactly. "
        f"Camera: {move}. "
        f"Rigid paper element motion: {element_motion}. Elements may slide, sway, flutter, pivot or drift as flat cut paper, but must remain rigid and physically coherent. "
        f"{title_rule} "
        "The shot is one continuous 8-second take with no internal cuts, no scene changes, no new objects, no morphing, no melting, no 3D rotation and no photorealistic rendering. "
        "Use restrained, physically plausible motion and let the composition settle cleanly; the first 5 seconds will be used in the final edit."
    )


def update(project_dir: Path, force: bool, only: set[str] | None) -> tuple[int, int]:
    beats_path = project_dir / "beats.json"
    if not beats_path.exists():
        raise SystemExit(f"beats.json not found: {beats_path}")
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=True, project_dir=project_dir)
    if errors:
        print("Strict validation failed; clip prompts were not generated:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    generated = 0
    skipped = 0
    for shot in doc["shots"]:
        sid = shot["id"]
        if only and sid not in only:
            skipped += 1
            continue
        if shot.get("clip_prompt") and not force:
            skipped += 1
            continue
        if not shot.get("keyframe_path"):
            raise SystemExit(f"{sid} is missing keyframe_path; generate and approve keyframes first")
        keyframe_path = Path(str(shot["keyframe_path"]))
        if not keyframe_path.exists() or keyframe_path.stat().st_size == 0:
            raise SystemExit(f"{sid} keyframe file does not exist or is empty: {keyframe_path}")
        shot["clip_prompt"] = compose_clip_prompt(shot)
        shot["video_source_duration_s"] = SOURCE_DURATION_S
        generated += 1

    doc["video_endpoint"] = DEFAULT_VIDEO_ENDPOINT
    doc["video_resolution"] = RESOLUTION
    doc["video_source_duration_s"] = SOURCE_DURATION_S
    doc["video_generation_note"] = "Generate 8-second V3.1 Pro source clips at 720p; assembly trims/uses each shot's planned dur_s."
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return generated, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate offline image-to-video prompts")
    parser.add_argument("project_dir")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s1,s2")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    generated, skipped = update(Path(args.project_dir).resolve(), args.force, only)
    print(f"Clip prompts written: {Path(args.project_dir).resolve() / 'beats.json'}")
    print(f"Generated: {generated}; skipped: {skipped}")
    print(f"Video endpoint: {DEFAULT_VIDEO_ENDPOINT}; source duration: {SOURCE_DURATION_S}s; resolution: {RESOLUTION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

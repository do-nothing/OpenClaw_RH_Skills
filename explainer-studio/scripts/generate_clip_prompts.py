#!/usr/bin/env python3
"""Stage 5 (offline): assemble English video prompts.

first_frame shots      -> one continuous motion description
first_last_frame shots -> timeline-segmented prompt spanning the INTEGER submit
                          duration (0-a s / a-D s), matching the FL2VA workflow
Prompt timing uses submit_duration_s; the assembler uses used_duration_s.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from explainer_common import CJK_RE, load_doc, save_doc, sha256_text

MOVE_PHRASE = {
    "static": "locked-off static camera, no camera movement, stable ending",
    "push_in": "slow steady camera push-in (gentle dolly forward), stable ending",
    "pull_out": "slow steady camera pull-out (gentle dolly back), stable ending",
    "pan": "slow smooth lateral camera pan, stable ending",
    "tilt": "slow smooth vertical camera tilt, stable ending",
    "parallax": "subtle layered parallax drift between foreground and background, stable ending",
}

STYLE_MOTION = {
    "clean-diagram": "flat 2D vector infographic elements moving simply on screen",
    "paper-collage": "flat paper cut-out layers moving with rigid stop-motion-like motion",
    "swiss-infographic": "flat grid elements sliding and counting in precise Swiss-design motion",
    "warm-editorial": "soft flat illustrated shapes moving gently and warmly",
}


def compose(doc: dict, shot: dict) -> str:
    style_note = STYLE_MOTION[doc["visual_style"]]
    cam = MOVE_PHRASE.get(shot.get("camera_move", "push_in"), MOVE_PHRASE["push_in"])
    motion = shot.get("motion_en") or ""
    d = int(shot["submit_duration_s"])

    if shot["mode"] == "first_frame":
        base = (
            f"{style_note}. Scene action: {shot['scene_en']}. "
            f"{cam}."
        )
        if motion:
            base += f" Element motion: {motion}."
        base += (" Keep flat 2D throughout, no morphing into unrelated objects, "
                 "no new readable text, motion settles and holds at the end.")
        return base

    # first_last_frame: segmented timeline (integer seconds)
    a = max(1, round(d / 2))
    return (
        f"{style_note}; natural continuous transition from the first frame to the last frame. "
        f"0-{a}s: the scene starts as shown; {shot['scene_en']}. "
        f"{a}-{d}s: {shot['last_frame_change_en']}, arriving naturally at the final frame. "
        f"{cam}."
        + (f" Element motion along the way: {motion}. " if motion else " ")
        + "Same subject and scene identity in every segment; keep flat 2D; no new readable text."
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Assemble English video prompts (offline)")
    p.add_argument("project_dir")
    args = p.parse_args(argv or sys.argv[1:])
    project_dir = Path(args.project_dir).resolve()
    doc = load_doc(project_dir)

    errors = []
    for s in doc["shots"]:
        if not s.get("scene_en"):
            errors.append(f"{s['id']}: scene_en missing — run generate_keyframe_prompts.py")
            continue
        if CJK_RE.search(s["scene_en"]) or CJK_RE.search(s.get("motion_en") or ""):
            errors.append(f"{s['id']}: video prompt fields contain Chinese")
        s["clip_prompt"] = compose(doc, s)
        s["clip_prompt_sha256"] = sha256_text(s["clip_prompt"])
    if errors:
        for e in errors:
            print(f"- {e}")
        return 1

    save_doc(project_dir, doc)
    changed = [s["id"] for s in doc["shots"] if s.get("clip_path")]
    print(f"Composed video prompts for {len(doc['shots'])} shot(s).")
    if changed:
        print(f"已有视频的镜头 {changed}：提示词已更新，确认返工后用 "
              "generate_clips.py --force 重投（关键帧不重生成）")
    print("Next: python scripts/generate_clips.py   (dry-run, shows per-shot seconds/modes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

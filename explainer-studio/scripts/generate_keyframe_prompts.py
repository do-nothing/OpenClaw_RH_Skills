#!/usr/bin/env python3
"""Stage 4 (offline): assemble English keyframe prompts.

Reads authored English visual drafts from prompts.en.json:
  {"b03s1": {"scene_en": "...", "motion_en": "...",
             "last_frame_change_en": "..."}}
merges them into shots[], then composes:
  keyframe_prompt        — text-to-image prompt for the FIRST frame (image-gen-qwen)
  last_frame_prompt      — single-image EDIT instruction (image-edit-qwen), only
                           for first_last_frame shots
Chinese fields never enter a model prompt; the only Chinese allowed in the image
is the explicitly approved on-screen keyword/number text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from explainer_common import CJK_RE, load_doc, save_doc, sha256_text, shots_of

STYLE_PROFILES = {
    "clean-diagram": (
        "clean modern flat 2D vector infographic illustration, soft warm-white background, "
        "simple geometric shapes and clear iconic figures, restrained palette of deep navy, "
        "teal and one warm orange accent, generous negative space, crisp edges, soft minimal "
        "shadows, educational textbook clarity"
    ),
    "paper-collage": (
        "mixed-media hand-cut paper collage, flat 2D layered torn and scissor-cut paper pieces "
        "with rough deckled edges, real paper drop shadows, halftone print dots and newsprint "
        "texture, editorial zine look, separated foreground/middle/background layers"
    ),
    "swiss-infographic": (
        "Swiss International Style flat infographic, strict modular grid, strong geometric "
        "composition, Helvetica-like bold type shapes, white background, black plus a single "
        "highly saturated red accent, precise diagram hierarchy and calm negative space"
    ),
    "warm-editorial": (
        "warm friendly editorial digital illustration, flat 2D with rounded shapes and gentle "
        "soft shapes, muted warm paper tones (sand, clay, sage, dusty blue), approachable "
        "educational storybook mood, simple lighting, no photorealistic rendering"
    ),
}

DUTY_GUIDE = {
    "hook": "one surprising focal moment that creates curiosity, high contrast single focus",
    "subject": "clear portrait of the main subject with just enough context to recognize it",
    "definition": "a simple labeled concept diagram showing WHAT the thing is, uncluttered",
    "mechanism": "cause-and-effect diagram with arrows/flow showing HOW it works, step-ready composition",
    "compare": "two sides clearly juxtaposed (before/after, right/wrong, big/small) on one canvas",
    "evidence": "clean data-style visual: a big number, proportion bar or timeline, minimal decoration",
    "analogy": "the concrete analogy object acting out the abstract idea, consistent metaphor",
    "keyword": "one bold keyword/number as the hero element, strong typographic poster emphasis",
}

COMMON_NEG = (
    "Strictly flat 2D: NOT 3D, NOT CGI, NOT photorealistic, no glossy e-commerce rendering, "
    "no watermark."
)


def cjk_outside_allowed(s: str) -> bool:
    return bool(CJK_RE.search(s or ""))


def text_block(items: list[str]) -> str:
    if not items:
        return (
            "On-image text rule: render NO readable words, letters, numbers or labels anywhere "
            "(arrows and abstract marks are allowed)."
        )
    quoted = "; ".join(f"{t}" for t in items)
    return (
        f"On-image text rule: render ONLY these exact text elements, exactly as given: {quoted}. "
        "Keep them large, sharp and correct, minimal typography. Apart from these elements, "
        "render no other readable words, letters, numbers, labels, signs or garbled fake text."
    )


def first_prompt(doc: dict, beat: dict, shot: dict) -> str:
    parts = [
        f"{STYLE_PROFILES[doc['visual_style']]}.",
        f"Cognitive job of this frame: {DUTY_GUIDE[beat['visual_duty']]}.",
        f"Scene: {shot['scene_en']}",
    ]
    if shot.get("motion_en"):
        parts.append(f"Composition clue for later subtle motion (still image only): {shot['motion_en']}")
    parts.append(text_block(beat.get("on_screen_text") or []))
    if shot.get("avoid_en"):
        parts.append(f"Must avoid: {shot['avoid_en']}.")
    parts.append(COMMON_NEG)
    label = {
        "16:9": "16:9 horizontal", "9:16": "9:16 vertical", "1:1": "square",
        "4:3": "4:3 horizontal", "3:4": "3:4 vertical",
    }[doc["aspect"]]
    parts.append(f"{label} composition, one clear focal point.")
    return " ".join(parts)


def last_prompt(shot: dict) -> str:
    return (
        "Edit this image so it becomes the natural LAST frame of a short video starting from it. "
        "Keep EXACTLY the same subject(s), setting, composition, camera angle, framing, colors, "
        f"lighting and illustration style. Do not swap or redesign anything. Only change: "
        f"{shot['last_frame_change_en']}. Keep every on-screen text element identical; "
        "do not add new text or remove existing text."
    )


def run(project_dir: Path) -> int:
    doc = load_doc(project_dir)
    en_path = project_dir / "prompts.en.json"
    if not en_path.exists():
        raise SystemExit(f"{en_path} not found — run plan_shots.py first")
    english = json.loads(en_path.read_text(encoding="utf-8"))

    errors: list[str] = []
    by_id = {s["id"]: s for s in doc["shots"]}
    for sid, draft in english.items():
        shot = by_id.get(sid)
        if not shot:
            continue
        shot["scene_en"] = (draft.get("scene_en") or "").strip()
        shot["motion_en"] = (draft.get("motion_en") or "").strip()
        shot["last_frame_change_en"] = (draft.get("last_frame_change_en") or "").strip()
        shot["avoid_en"] = (draft.get("avoid_en") or "").strip()

    beats = {b["id"]: b for b in doc["beats"]}
    warns: list[str] = []
    for shot in doc["shots"]:
        sid = shot["id"]
        if not shot["scene_en"]:
            errors.append(f"{sid}: prompts.en.json 缺少 scene_en（中文视觉意图不能直接进提示词）")
            continue
        if cjk_outside_allowed(shot["scene_en"]) or cjk_outside_allowed(shot.get("motion_en")):
            errors.append(f"{sid}: scene_en/motion_en 含中文字符，进模型的只能是英文")
        if shot["mode"] == "first_last_frame" and not shot["last_frame_change_en"]:
            errors.append(f"{sid}: 首尾帧模式必须在 prompts.en.json 写 last_frame_change_en")
        beat = beats[shot["beat_id"]]
        if beat.get("avoid") and not shot.get("avoid_en"):
            warns.append(f"{sid}: script.md 写了「禁忌」但 prompts.en.json 没有 avoid_en，"
                         "该禁忌不会进入图片提示词")
        shot["keyframe_prompt"] = first_prompt(doc, beat, shot)
        if shot["mode"] == "first_last_frame":
            shot["last_frame_prompt"] = last_prompt(shot)
            shot["last_frame_prompt_sha256"] = sha256_text(shot["last_frame_prompt"])
        else:
            shot.pop("last_frame_prompt", None)
            shot["last_frame_prompt_sha256"] = None
        shot["keyframe_prompt_sha256"] = sha256_text(shot["keyframe_prompt"])

    if errors:
        print("Cannot assemble prompts:")
        for e in errors:
            print(f"- {e}")
        return 1

    save_doc(project_dir, doc)
    for wmsg in warns:
        print(f"WARNING: {wmsg}")
    stale = []
    for s in doc["shots"]:
        if s.get("first_frame_path") and s.get("image_pool_id"):
            stale.append(s["id"])
    print(f"Composed English keyframe prompts for {len(doc['shots'])} shot(s) "
          f"(style={doc['visual_style']}).")
    if stale:
        print(f"已有首帧的镜头 {stale}：视觉提示词已更新，确认视觉变化后用 "
              "generate_keyframes.py --force 重滚")
    print("Next: python scripts/generate_keyframes.py --wave first  (dry-run)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Assemble English keyframe prompts (offline)")
    p.add_argument("project_dir")
    args = p.parse_args(argv or sys.argv[1:])
    return run(Path(args.project_dir).resolve())


if __name__ == "__main__":
    raise SystemExit(main())

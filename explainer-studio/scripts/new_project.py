#!/usr/bin/env python3
"""Create an explainer-studio project scaffold (offline-only).

Writes out/<project>/script.md (the ONLY human-edited source) plus the working
folders. explainer.json is created later by sync_script.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from explainer_common import ASPECTS, STYLES

PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DIRS = ("audio", "keyframes", "clips", "qa", "_seg")


def beats_for_duration(duration: int) -> int:
    for upper, count in ((30, 4), (45, 5), (60, 7), (90, 9),
                         (120, 12), (180, 16), (240, 20)):
        if duration <= upper:
            return count
    return 24


def beat_template(idx: int, total: int) -> tuple[str, str, str, str, list[str]]:
    """Return (title, duty, narration, see, steps)."""
    if idx == 1:
        return ("钩子", "hook",
                "【请填写钩子旁白：前 3 秒抛出反常识、痛点或利益承诺，口语短句】",
                "【请填写：此刻观众需要看到的一个具体画面，只写对象和动作】", [])
    if idx == total:
        return ("收尾", "keyword",
                "【请填写收尾金句：观众看完应能复述的那一句话】",
                "【请填写：金句的纯视觉强化，一个清晰焦点】", [])
    if idx == 2:
        return ("定义", "definition",
                "【请填写：先用一句话给核心概念下定义】",
                "【请填写：概念是什么的具象图示】", [])
    if idx == 3:
        return ("小点一", "mechanism",
                "【请填写第一个小点的完整旁白】",
                "【请填写：因果或流程在画面上如何发生】",
                ["【步骤一】", "【步骤二】", "【步骤三】"])
    duty = "evidence" if idx % 2 == 0 else "compare"
    return (f"小点{idx - 2}", duty,
            f"【请填写第 {idx - 2} 个小点的完整旁白】",
            "【请填写：观众此刻要看到什么，只写对象和动作】", [])


def render_script(args: argparse.Namespace) -> str:
    total = beats_for_duration(args.duration)
    sample = args.sample_path or ""
    lines = [
        "---",
        f"project: {args.project}",
        f"topic: {args.topic}",
        "audience: 【请填写观众已有认知水平】",
        "core_takeaway: 【请填写这一个核心知识点/结论】",
        "tone: 口语、对话感、具体、不端着",
        f"target_duration_s: {args.duration}",
        f"aspect: {args.aspect}",
        f"visual_style: {args.style}",
        "voice:",
        f"  mode: {args.voice}",
        f"  sample_path: {sample}",
        "music:",
        f"  enabled: {'true' if args.music else 'false'}",
        "  prompt: 克制的纪录片配乐，纯器乐，无人声，不抢旁白",
        "captions: true",
        "chapter_cards: false",
        "---",
        "",
        f"# {args.topic}",
        "",
    ]
    for i in range(1, total + 1):
        title, duty, narration, see, steps = beat_template(i, total)
        lines += [f"## b{i:02d} {title}", "", narration, "",
                  f"- 视觉职责：{duty}",
                  f"- 看到：{see}"]
        if i == 1:
            lines.append("- 文字：【关键词】")
        if steps:
            lines.append("- 渐进：")
            for k, s in enumerate(steps, start=1):
                lines.append(f"  {k}. {s}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Create an explainer-studio project")
    p.add_argument("--project", required=True, help="English short name (dir name)")
    p.add_argument("--root", default="out", help="Root dir holding projects")
    p.add_argument("--topic", required=True, help="One-sentence knowledge point")
    p.add_argument("--aspect", default="16:9", choices=sorted(ASPECTS))
    p.add_argument("--duration", type=int, default=60,
                   help="Target seconds, 1-300 (only sizes the beat template)")
    p.add_argument("--style", default="clean-diagram", choices=list(STYLES))
    p.add_argument("--voice", default="tts", choices=("tts", "clone"))
    p.add_argument("--sample-path", default="", help="Reference voice sample for clone mode")
    music = p.add_mutually_exclusive_group()
    music.add_argument("--music", dest="music", action="store_true", default=True)
    music.add_argument("--no-music", dest="music", action="store_false")
    args = p.parse_args(argv or sys.argv[1:])

    if not PROJECT_RE.match(args.project):
        raise SystemExit("--project must be lowercase letters/digits/_- (max 40)")
    if not 1 <= args.duration <= 300:
        raise SystemExit("--duration must be 1-300")
    if args.voice == "clone" and not args.sample_path:
        raise SystemExit("--voice clone requires --sample-path")

    root = Path(args.root).resolve()
    project_dir = root / args.project
    if project_dir.exists():
        raise SystemExit(f"project already exists: {project_dir}")
    for d in (project_dir, *(project_dir / sub for sub in DIRS)):
        d.mkdir(parents=True, exist_ok=True)
    script = project_dir / "script.md"
    script.write_text(render_script(args), encoding="utf-8")

    print(f"Created project: {project_dir}")
    print(f"  template: {script} ({beats_for_duration(args.duration)} beats, "
          f"aspect {args.aspect}, style {args.style})")
    print("Next: rewrite script.md with the real narration and visual intent, then run")
    print(f"  python scripts/sync_script.py {project_dir} --strict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

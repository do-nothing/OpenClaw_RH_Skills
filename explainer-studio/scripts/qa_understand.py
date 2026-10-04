#!/usr/bin/env python3
"""Stage 7 (optional): media-understand QA.

Directly sends ORIGINAL files to media-understand (it auto-uploads large local
files; no proxy/transcode here). Preflight: <=2h duration, <=1GB size (above 1GB
host the file and pass a URL to media-understand yourself).

Default: per-shot quality questions with each shot's own spec (TEXT_OK /
TEXT_LEAK / DUTY_MATCH / CONTINUITY / VERDICT). --whole adds one whole-film
question about order, chapter chips and narration continuity.
Dry-run quotes; --submit runs. Missing DASHSCOPE_API_KEY skips cleanly.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from explainer_common import find_tool, load_doc

MAX_DURATION_S = 2 * 3600
MAX_SIZE_B = 1024 ** 3
MEDIA_SCRIPT = (Path(__file__).resolve().parent.parent.parent
                / "media-understand" / "scripts" / "media_understand.py")

DUTY_ZH = {
    "hook": "制造好奇/反常识的焦点瞬间", "subject": "让观众认出主体",
    "definition": "说明概念是什么", "mechanism": "展示因果或运作流程",
    "compare": "形成清晰对比", "evidence": "呈现数据/比例/时间线证据",
    "analogy": "用比喻解释抽象概念", "keyword": "强化收尾金句",
}


def shot_question(beat: dict, shot: dict, n_shots_in_beat: int) -> str:
    texts = "、".join(beat.get("on_screen_text") or []) or "无"
    fl = ("（这是首尾帧镜头，画面应从首帧状态自然过渡到尾帧状态："
          f"{shot.get('last_frame_change_en') or ''}）") if shot["mode"] == "first_last_frame" else ""
    split = (f"注意：该段落共 {n_shots_in_beat} 个镜头分工表达，本镜是第 {shot['ord']} 个，"
             "只负责下面给出的本镜画面；同段其他动作由别的镜头承担，"
             "不得因为其他镜头的动作没有出现在本镜而扣分。\n") if n_shots_in_beat > 1 else ""
    return (
        f"你在质检一支中文科普讲解片的单个镜头。{split}"
        "请检查并只回答以下标签行：\n"
        f"1) TEXT_OK / TEXT_LEAK：画面允许出现的文字只有【{texts}】；"
        f"若出现乱码假字、其他可读词句、整句旁白入画，标 TEXT_LEAK 并描述。"
        "允许文字中的某几项由同段其他镜头承载、本镜未出现，不算 LEAK。\n"
        f"2) DUTY_MATCH / DUTY_MISS：这一镜画面的认知任务是"
        f"【{DUTY_ZH.get(beat['visual_duty'], beat['visual_duty'])}】。"
        f"本镜应有的画面（英文设计稿）：{shot.get('scene_en') or beat['visual_see']}；"
        f"本镜元素运动：{shot.get('motion_en') or '轻微信息图运动'}。{fl}"
        "画面是否完成【本镜】这部分任务？\n"
        "3) CONTINUITY_OK / CONTINUITY_BAD：本镜内部主体、场景是否稳定一致，有无突变。\n"
        "4) DEFECT：有无黑场、严重畸变、水印、无关元素。\n"
        "5) VERDICT: PASS 或 FAIL（FAIL 必须给一句原因）。"
    )


def whole_question(doc: dict) -> str:
    beats = " / ".join(f"{b['id']}:{b['narration'][:14]}" for b in doc["beats"])
    chips = "、".join(f"{c['id']}={c['title']}" for c in (doc.get("chapters") or [])) or "无"
    return (
        "你在质检一支完整中文科普讲解片，请基于整片回答：\n"
        f"1) 镜头/段落数量与顺序是否为：{beats}\n"
        f"2) 逐字听旁白：有没有缺失、串行、被截断或两个段落叠在一起？\n"
        f"3) 左上角章节标签与顶部进度条（如有）：章节文字是否依次为【{chips}】，有无乱码？\n"
        "4) 有无死帧、黑场、字幕与旁白严重错位、画风突然跳变？\n"
        "5) 输出 `VERDICT: PASS/FAIL`，FAIL 时逐条列出位置与原因。"
    )


def preflight(path: Path, ffprobe: str) -> None:
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    size = path.stat().st_size
    if size > MAX_SIZE_B:
        raise SystemExit(f"{path.name} = {size/1024**3:.2f}GB > 1GB; media-understand "
                         "needs a public URL for files this big — host it and call the "
                         "media-understand script with the URL directly")
    p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    dur = float(p.stdout.strip())
    if dur > MAX_DURATION_S:
        raise SystemExit(f"{path.name} duration {dur:.0f}s > 2h model limit")
    print(f"preflight {path.name}: {dur:.1f}s, {size/1024**2:.1f}MB")
    return dur


def ask(path: Path, question: str, out: Path, fps: float = 1.0,
        channel: str = "auto") -> None:
    cmd = [sys.executable, str(MEDIA_SCRIPT), "ask", str(path), question,
           "--fps", f"{fps:g}", "--channel", channel, "--out", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"media-understand failed for {path.name}:\n{p.stdout}\n{p.stderr}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Optional media QA via media-understand")
    ap.add_argument("project_dir")
    ap.add_argument("--whole", action="store_true", help="also QA final.mp4 as one film")
    ap.add_argument("--only-whole", action="store_true", help="QA only final.mp4 as one film")
    ap.add_argument("--only", help="comma-separated shot ids to (re)run")
    ap.add_argument("--submit", action="store_true")
    args = ap.parse_args(argv or sys.argv[1:])
    project_dir = Path(args.project_dir).resolve()
    doc = load_doc(project_dir)
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None

    if not MEDIA_SCRIPT.exists():
        raise SystemExit(f"media-understand skill script missing: {MEDIA_SCRIPT}")
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("DASHSCOPE_API_KEY not set — skipping media QA (not blocking). "
              "Deterministic ffprobe/frame checks remain required.")
        return 0
    ffprobe = find_tool("ffprobe")
    qa_dir = project_dir / "qa"; qa_dir.mkdir(exist_ok=True)

    # tuple: (name, path, question, out, fps, channel); fps 0 = adapt below
    tasks: list[tuple[str, Path, str, Path, float, str]] = []
    beats = {b["id"]: b for b in doc["beats"]}
    shots_per_beat: dict[str, int] = {}
    for s in doc["shots"]:
        shots_per_beat[s["beat_id"]] = shots_per_beat.get(s["beat_id"], 0) + 1
    if not args.only_whole:
        for s in doc["shots"]:
            if only is not None and s["id"] not in only:
                continue
            clip = Path(str(s.get("clip_path") or ""))
            if clip.exists():
                tasks.append((s["id"], clip,
                              shot_question(beats[s["beat_id"]], s,
                                            shots_per_beat.get(s["beat_id"], 1)),
                              qa_dir / f"qa_{s['id']}.txt", 1.0, "auto"))
    final = project_dir / "final.mp4"
    if args.whole or args.only_whole:
        if not final.exists():
            raise SystemExit("final.mp4 missing — run assemble.py before --whole QA")
        tasks.append(("whole", final, whole_question(doc),
                      qa_dir / "qa_whole.txt", 0.0, "url"))

    if not tasks:
        print("Nothing to QA yet.")
        return 0
    for i, (name, path, _, _, fps, channel) in enumerate(tasks):
        dur = preflight(path, ffprobe)
        if fps == 0.0:
            # Server samples frames from the uploaded temp-storage copy;
            # keep frames <= ~120 to stay well under model limits.
            fps = min(1.0, max(0.2, 120.0 / dur))
            print(f"  whole-film adaptive fps={fps:g} (~{int(dur*fps)} frames), channel=url")
            tasks[i] = (name, path, tasks[i][2], tasks[i][3], fps, channel)
    print(f"\nDRY-RUN: {len(tasks)} media-understand call(s) (~¥0.01-0.05 per short clip).")
    for name, path, q, _, fps, channel in tasks:
        print(f"  {name:8s} {path.name} @ {fps:g}fps/{channel}")
    if not args.submit:
        print("\nRerun with --submit after approval.")
        return 0

    failures = []
    errors = []
    for name, path, q, out, fps, channel in tasks:
        print(f"asking about {name} ...", flush=True)
        try:
            ask(path, q, out, fps, channel)
        except SystemExit as exc:
            errors.append((name, str(exc)))
            print(f"  {name}: CALL ERROR — {exc}", flush=True)
            continue
        text = out.read_text(encoding="utf-8", errors="replace")
        # Accept either "VERDICT: PASS/FAIL" or a bare PASS/FAIL on the final line.
        verdict = [ln for ln in text.splitlines()
                   if "PASS" in ln.upper() or "FAIL" in ln.upper()]
        line = verdict[-1] if verdict else "(no verdict line)"
        print(f"  {name}: {line}", flush=True)
        if not verdict or "FAIL" in line.upper():
            failures.append(name)
    print(f"\nQA report(s) in {qa_dir}")
    if errors:
        print(f"CALL ERRORS: {[n for n, _ in errors]}")
    if failures:
        print(f"FAIL/UNKNOWN: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

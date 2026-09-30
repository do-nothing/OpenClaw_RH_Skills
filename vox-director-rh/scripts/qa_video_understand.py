#!/usr/bin/env python3
"""Optional multimodal QA for Vox MVP clips, via the media-understand SIBLING SKILL.

Instead of a paid RunningHub video-to-text workflow, this calls the generic
media-understand wrapper (Qwen3.8-Omni on Bailian; cost is token-based, roughly
a few fen per clip). One call per clip; the model answers labeled QA lines.

Trust boundary (from ground-truthed evaluation): headline OCR and speech
transcription are reliable; fine motion direction and music/SFX descriptions
must be verified by frame extraction / listening.
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

MEDIA_UNDERSTAND_SCRIPT = os.environ.get(
    "MEDIA_UNDERSTAND_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "media-understand",
                 "scripts", "media_understand.py"),
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


def build_question(shot: dict) -> str:
    expected_prop = str(shot.get("qa_prop") or "").strip()
    prop_line = (
        f"- Key prop that MUST be present and correct: {expected_prop}\n"
        "  Answer PROP_PRESENT yes/no and say what the object actually looks like.\n"
        if expected_prop
        else "- PROP_PRESENT: n/a (no specific prop to verify).\n"
    )
    headline = str(shot.get("headline") or "").strip()
    title_line = (
        f"- On-image Chinese title should read exactly: {headline}. "
        "Answer TITLE_OK yes/no and quote the title you actually see.\n"
        if shot.get("title_on_image") and headline
        else "- There should be no large on-image title; answer TITLE_OK n/a.\n"
    )
    return (
        "You are QA-ing an 8-second flat 2D hand-cut paper-collage animation for a "
        "Chinese educational short. Watch the WHOLE clip (visuals and sound), then "
        "answer ONLY with these labeled lines (English), each on its own line, be "
        "concise:\n"
        f"{title_line}"
        f"{prop_line}"
        "- TEXT_LEAK: Are there any readable prompt-like sentences, garbled fake "
        "characters, or extra letters/numbers rendered into the picture besides the "
        "intended title? Answer none/minor/bad.\n"
        "- STYLE_2D: Does it stay flat 2D paper collage with no 3D/CGI turn, no "
        "melting or morphing into other objects? Answer yes/no.\n"
        "- MOTION: Is the camera motion a single restrained continuous move with a "
        "stable ending? Answer yes/no.\n"
        "- VERDICT: overall pass or fail, and the single biggest problem if any.\n"
    )


def _extract(answer: str, label: str) -> str:
    m = re.search(rf"{label}\s*[:：]\s*(.+)", answer, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def run(project_dir: Path, only: set[str] | None, submit: bool, force: bool) -> int:
    beats = project_dir / "beats.json"
    if not beats.exists():
        raise SystemExit(f"beats.json not found: {beats}")
    doc = json.loads(beats.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=True, project_dir=project_dir)
    if errors:
        print("Strict validation failed; refusing QA:")
        for e in errors:
            print(f"- {e}")
        return 1
    mu = Path(MEDIA_UNDERSTAND_SCRIPT)
    if not mu.exists():
        raise SystemExit(
            f"media-understand script not found: {mu}\n"
            f"Clone/install the media-understand skill next to runninghub, or set "
            f"MEDIA_UNDERSTAND_SCRIPT. It also needs DASHSCOPE_API_KEY (see that "
            f"skill's SKILL.md).")

    qa_dir = project_dir / "qa"
    qa_dir.mkdir(exist_ok=True)
    shots = [s for s in doc["shots"] if not only or s["id"] in only]
    if only:
        missing = only - {s["id"] for s in shots}
        if missing:
            raise SystemExit(f"Unknown shot ID(s): {sorted(missing)}")

    for shot in shots:
        sid = shot["id"]
        clip = Path(str(shot.get("clip_path", "")))
        if not clip.exists():
            raise SystemExit(f"{sid}: clip not found: {clip}")
        out_txt = qa_dir / f"qa_{sid}.txt"
        if out_txt.exists() and not force and not submit:
            print(f"[{sid}] Reusing existing QA: {out_txt}")
            continue
        cmd = [
            sys.executable, str(mu), "ask", str(clip),
            build_question(shot), "--no-thinking", "--out", str(out_txt),
        ]
        if not submit:
            print(f"[{sid}] DRY-RUN: would run one media-understand QA call")
            print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
            continue

        print(f"[{sid}] Running media-understand QA (token cost, usually under a minute)...")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
        if proc.returncode != 0 or not out_txt.exists():
            shot["qa_error"] = (proc.stdout + proc.stderr).strip()[-3000:]
            beats.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[{sid}] QA failed. Stopped.")
            print(proc.stdout)
            print(proc.stderr)
            return 1

        answer = out_txt.read_text(encoding="utf-8").strip()
        shot["qa_result_path"] = str(out_txt)
        shot["qa_verdict"] = _extract(answer, "VERDICT")
        shot["qa_prop"] = shot.get("qa_prop")
        shot.pop("qa_error", None)
        beats.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{sid}] QA saved: {out_txt}")
        print(answer)
        print()

    if not submit:
        print("\nDRY-RUN only: no call made, no cost. Rerun with --submit.")
    else:
        print("QA complete. Verify any FAIL with frame extraction before regenerating.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Multimodal clip QA via media-understand")
    parser.add_argument("project_dir")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s2")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.submit, args.force)


if __name__ == "__main__":
    raise SystemExit(main())

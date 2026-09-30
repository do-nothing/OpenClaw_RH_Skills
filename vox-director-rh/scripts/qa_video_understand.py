#!/usr/bin/env python3
"""Optional Video-understand QA for Vox MVP clips.

Runs RunningHub rhart-text-g-25-pro/video-to-text over generated clips and asks
a multimodal model to verify props, on-screen text, 2D paper style and artifacts.
This is a SLOW task (upload + inference) and has a small cost, so it defaults to
dry-run and is opt-in. One task per shot; never resubmit a pending task.
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

QA_ENDPOINT = "rhart-text-g-25-pro/video-to-text"
RUNNINGHUB_SCRIPT = os.environ.get(
    "RUNNINGHUB_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "runninghub", "scripts", "runninghub.py"),
)
COST_RE = re.compile(r"COST:¥([0-9.]+)")
TASK_RE = re.compile(r"Task ID:\s*([A-Za-z0-9_-]+)")

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
        "Chinese educational short. Watch the WHOLE clip, then answer ONLY with these "
        "labeled lines (English), each on its own line, be concise:\n"
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
    if not Path(RUNNINGHUB_SCRIPT).exists():
        raise SystemExit(f"RunningHub script not found: {RUNNINGHUB_SCRIPT}")

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
        question = build_question(shot)
        cmd = [
            sys.executable, RUNNINGHUB_SCRIPT,
            "--endpoint", QA_ENDPOINT,
            "--prompt", question,
            "--video", str(clip),
        ]
        if not submit:
            print(f"[{sid}] DRY-RUN: would submit one video-understanding QA task")
            print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
            continue

        print(f"[{sid}] Submitting video-understanding QA; this is a slow task "
              "(upload + inference, can take several to ~20 minutes). Waiting, no resubmit...")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
        combined = "\n".join([proc.stdout or "", proc.stderr or ""]).strip()
        if proc.returncode != 0:
            shot["qa_error"] = combined[-3000:]
            beats.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            task = TASK_RE.search(combined)
            print(f"[{sid}] QA failed. Stopped; not resubmitted.")
            if task:
                print(f"Task ID: {task.group(1)}")
            print(combined)
            return 1

        # Keep only the labeled answer lines; drop progress/COST/task chatter.
        labels = ("TITLE_OK", "PROP_PRESENT", "TEXT_LEAK", "STYLE_2D", "MOTION", "VERDICT")
        answer = "\n".join(
            ln.strip() for ln in (proc.stdout or "").splitlines()
            if ln.strip().startswith(labels)
        ).strip()
        out_txt.write_text(answer + "\n", encoding="utf-8")
        shot["qa_result_path"] = str(out_txt)
        shot["qa_verdict"] = _extract(answer, "VERDICT")
        shot["qa_prop"] = shot.get("qa_prop")
        shot.pop("qa_error", None)
        cost = COST_RE.search(combined)
        if cost:
            shot["qa_cost"] = cost.group(1)
        beats.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{sid}] QA saved: {out_txt}")
        print(answer)

    if not submit:
        print("\nDRY-RUN only: no task submitted, no cost. Rerun with --submit.")
    return 0


def _extract(answer: str, label: str) -> str:
    m = re.search(rf"{label}\s*[:：]\s*(.+)", answer, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Video-understand QA via RunningHub")
    parser.add_argument("project_dir")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s2")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), only, args.submit, args.force)


if __name__ == "__main__":
    raise SystemExit(main())

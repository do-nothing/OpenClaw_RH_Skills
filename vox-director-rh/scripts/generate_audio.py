#!/usr/bin/env python3
"""Generate Vox MVP narration (per-shot TTS) and one instrumental BGM via RunningHub.

Default mode is a local dry-run. Use --submit only after explicit user approval.
Narration is generated as one file per shot so assembly can place it on each clip.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from new_project import validate_doc, beat_groups

TTS_ENDPOINT = "rhart-audio/text-to-audio/speech-2.8-turbo"
MUSIC_ENDPOINT = "rhart-audio/text-to-audio/music-2.5"
RUNNINGHUB_SCRIPT = os.environ.get(
    "RUNNINGHUB_SCRIPT",
    os.path.join(os.path.dirname(__file__), "..", "..", "runninghub", "scripts", "runninghub.py"),
)
# Knowledge-narration defaults. MiniMax speech-2.8 voice ids are free-form strings.
DEFAULT_VOICE_ID = "Wise_Woman"
DEFAULT_EMOTION = "neutral"
DEFAULT_SPEED = 1.05
# MiniMax music-2.5 requires lyrics; this tag requests a non-vocal instrumental bed.
INSTRUMENTAL_LYRICS = "[Instrumental]"
# Timing budget shared with assemble.py: low-cost V3.1 SKUs emit fixed 8s clips,
# and assemble keeps LEAD before + TAIL after the speech inside that clip.
SOURCE_CLIP_S = 8.0
ASM_LEAD_S = 0.20
ASM_TAIL_S = 0.45
MAX_VO_S = SOURCE_CLIP_S - ASM_LEAD_S - ASM_TAIL_S  # 7.35s of speech per shot

TASK_ID_RE = re.compile(r"Task ID:\s*([A-Za-z0-9_-]+)")
OUTPUT_RE = re.compile(r"OUTPUT_FILE:(.+)")
COST_RE = re.compile(r"COST:¥([0-9.]+)")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


def run_child(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
    )


def tts_command(shot: dict, voice_id: str, emotion: str, speed: float, output: Path) -> list[str]:
    return [
        sys.executable, RUNNINGHUB_SCRIPT,
        "--endpoint", TTS_ENDPOINT,
        # The RunningHub client maps --prompt onto the TTS endpoint's `text` field.
        "--prompt", shot["narration"],
        "--param", f"voice_id={voice_id}",
        "--param", f"emotion={emotion}",
        "--param", f"speed={speed}",
        "-o", str(output),
    ]


def music_command(doc: dict, output: Path) -> list[str]:
    prompt = (
        "Instrumental documentary background music only, NO vocals, NO lyrics, NO singing. "
        "Light but restrained, warm and curious, plucked strings (pipa/guitar-like) with soft hand percussion, "
        "steady gentle tempo around 90 BPM, clean and unobtrusive, suitable for Chinese educational narration. "
        f"Mood reference: {doc.get('music', {}).get('prompt', '')}"
    )
    return [
        sys.executable, RUNNINGHUB_SCRIPT,
        "--endpoint", MUSIC_ENDPOINT,
        "--prompt", prompt,
        "--param", f"lyrics={INSTRUMENTAL_LYRICS}",
        "--param", "bitrate=256000",
        "--param", "sampleRate=44100",
        "-o", str(output),
    ]


def find_ffprobe() -> str:
    found = shutil.which("ffprobe")
    if found:
        return found
    candidate = (
        Path(os.environ.get("LOCALAPPDATA", r"C:\\Users\\lj110\\AppData\\Local"))
        / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
          r"\ffmpeg-9.0.1-full_build\bin\ffprobe.exe"
    )
    if candidate.exists():
        return str(candidate)
    raise SystemExit("ffprobe not found on PATH or in the winget FFmpeg folder")


def probe_duration(ffprobe: str, path: Path) -> float:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"ffprobe failed for {path}: {proc.stderr}")
    return float(proc.stdout.strip())


def resolve_output(combined: str, fallback: Path) -> Path:
    match = OUTPUT_RE.search(combined)
    if match:
        return Path(match.group(1).strip())
    return fallback


def run(project_dir: Path, force: bool, submit: bool, voice_id: str, emotion: str, speed: float, only: set[str] | None = None) -> int:
    beats_path = project_dir / "beats.json"
    if not beats_path.exists():
        raise SystemExit(f"beats.json not found: {beats_path}")
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=True, project_dir=project_dir)
    if errors:
        print("Strict validation failed; refusing to generate audio:")
        for error in errors:
            print(f"- {error}")
        return 1
    if not Path(RUNNINGHUB_SCRIPT).exists():
        raise SystemExit(f"RunningHub script not found: {RUNNINGHUB_SCRIPT}")

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    ffprobe = find_ffprobe()
    jobs: list[tuple[str, list[str], Path, dict, str | None]] = []

    # One narration per BEAT, carried by the beat's anchor shot. A v2 detail
    # cut-in has no narration of its own (the beat VO plays across it).
    for group in beat_groups(doc):
        shot = group["anchor"]
        sid = shot["id"]
        if only and sid not in only:
            continue
        out = audio_dir / f"vo_{sid}.mp3"
        existing = shot.get("vo_path")
        if existing and Path(existing).exists() and Path(existing).stat().st_size > 0 and not force:
            print(f"[{sid}] Reusing existing narration: {existing}")
            continue
        jobs.append((sid, tts_command(shot, voice_id, emotion, speed, out), out, shot, "tts"))

    bgm_enabled = bool(doc.get("music", {}).get("enabled")) and not only
    bgm_out = audio_dir / "bgm.mp3"
    bgm_path = doc.get("music", {}).get("path")
    if bgm_enabled and not (bgm_path and Path(bgm_path).exists() and Path(bgm_path).stat().st_size > 0 and not force):
        jobs.append(("bgm", music_command(doc, bgm_out), bgm_out, doc.get("music", {}), "music"))
    elif not bgm_enabled:
        print("BGM disabled in beats.json; skipping music.")

    if not submit:
        for sid, cmd, _out, _store, _kind in jobs:
            print(f"[{sid}] DRY-RUN: would submit one audio task")
            print(" ".join(f'"{p}"' if " " in p else p for p in cmd))
        print("\nDRY-RUN only: no task was submitted and no cost was incurred.")
        print("After explicit approval, rerun with --submit.")
        return 0

    costs: list[str] = []
    for sid, cmd, out, store, kind in jobs:
        print(f"[{sid}] Submitting {kind} task; waiting for this exact task, no duplicate submission...")
        proc = run_child(cmd)
        combined = "\n".join([proc.stdout or "", proc.stderr or ""])
        task_match = TASK_ID_RE.search(combined)
        actual = resolve_output(combined, out)
        ok = proc.returncode == 0 and actual.exists() and actual.stat().st_size > 0
        if not ok:
            store[f"last_{kind}_error"] = combined.strip()[-3000:]
            beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[{sid}] Audio task failed. Stopped; it will not be resubmitted automatically.")
            if task_match:
                print(f"Task ID: {task_match.group(1)}")
            print(combined.strip())
            return 1
        if kind == "tts":
            store["vo_path"] = str(actual)
            store["voice_id"] = voice_id
            store.pop("last_tts_error", None)
            # Guard: speech must fit inside the fixed 8s source clip budget.
            vo_dur = probe_duration(ffprobe, actual)
            store["vo_duration_s"] = round(vo_dur, 3)
            if vo_dur > MAX_VO_S + 0.02:
                need_speed = speed * vo_dur / MAX_VO_S
                print(
                    f"[{sid}] narration {vo_dur:.2f}s exceeds the {MAX_VO_S:.2f}s budget "
                    f"(8s clip minus lead/tail). Regenerate JUST this shot faster:\n"
                    f"  python scripts/generate_audio.py {project_dir.name} "
                    f"--only {sid} --speed {need_speed:.2f} --force --submit\n"
                    f"Stopping; do not extend the shot beyond the 8s source clip."
                )
                beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return 1
            print(f"[{sid}] narration duration {vo_dur:.2f}s OK (<= {MAX_VO_S:.2f}s)")
        else:
            store["path"] = str(actual)
            store.pop("last_music_error", None)
        cost_match = COST_RE.search(combined)
        if cost_match:
            costs.append(f"{sid} ¥{cost_match.group(1)}")
        beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{sid}] Saved: {actual}")

    doc["status"] = "audio"
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if costs:
        print("Cost: " + ", ".join(costs))
    print("Audio stage complete. Review narration voice and confirm BGM has no vocals before assembly.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Vox MVP narration and BGM via RunningHub")
    parser.add_argument("project_dir")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--voice-id", default=DEFAULT_VOICE_ID)
    parser.add_argument("--emotion", default=DEFAULT_EMOTION,
                        choices=["happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"])
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED)
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s4")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), args.force, args.submit,
               args.voice_id, args.emotion, args.speed, only)


if __name__ == "__main__":
    raise SystemExit(main())

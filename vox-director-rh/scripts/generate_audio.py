#!/usr/bin/env python3
"""Generate Vox MVP narration (per-beat TTS) and one instrumental BGM via the pool.

Narration: pool type voice-clone-emo (IndexTTS2).
- voice.mode == "tts": no reference audio is sent; the workflow's built-in
  default voice speaks the text (verified usable).
- voice.mode == "clone": voice.sample_path is sent as the timbre reference.
There is no voice_id/emotion/speed control on this workflow.

BGM: pool type music-minimax with empty lyrics (pure instrumental).

Default mode is a local dry-run. --submit enqueues all narration + the BGM as ONE
pool batch and drives ticks until terminal; tasks are never auto-resubmitted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from new_project import validate_doc, beat_groups
import rh_pool_client as pool

TTS_TYPE = "voice-clone-emo"
MUSIC_TYPE = "music-minimax"

# Timing budget shared with assemble.py: H3 source clips are 8 s and assemble
# keeps LEAD before + TAIL after the speech inside that clip.
SOURCE_CLIP_S = 8.0
ASM_LEAD_S = 0.20
ASM_TAIL_S = 0.45
MAX_VO_S = SOURCE_CLIP_S - ASM_LEAD_S - ASM_TAIL_S  # 7.35s of speech per shot

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


def find_ffprobe() -> str:
    found = shutil.which("ffprobe")
    if found:
        return found
    winget = (
        Path(__import__("os").environ.get("LOCALAPPDATA", r"C:\Users\lj110\AppData\Local"))
        / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
          r"\ffmpeg-9.0.1-full_build\bin\ffprobe.exe"
    )
    if winget.exists():
        return str(winget)
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


def music_prompt(doc: dict) -> str:
    return (
        "Instrumental documentary background music only, NO vocals, NO lyrics, NO singing. "
        "Light but restrained, warm and curious, plucked strings (pipa/guitar-like) with soft "
        "hand percussion, steady gentle tempo around 90 BPM, clean and unobtrusive, suitable "
        "for Chinese educational narration. "
        f"Mood reference: {doc.get('music', {}).get('prompt', '')}"
    )


def run(project_dir: Path, force: bool, submit: bool, only: set[str] | None) -> int:
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
    pool.ensure_pool_script()

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    voice_mode = str(doc.get("voice", {}).get("mode") or "tts")
    sample_raw = doc.get("voice", {}).get("sample_path")
    sample_path: Path | None = None
    if voice_mode == "clone":
        sample_path = Path(str(sample_raw))
        if not sample_path.is_absolute():
            sample_path = project_dir / sample_path
        if not sample_path.exists():
            raise SystemExit(f"voice sample not found: {sample_path}")

    # (store, kind, job, output_path, shot_id) — one narration per BEAT anchor.
    planned: list[tuple[dict, str, dict, Path, str]] = []

    for group in beat_groups(doc):
        shot = group["anchor"]
        sid = shot["id"]
        if only and sid not in only:
            continue
        out = audio_dir / f"vo_{sid}"
        existing = shot.get("vo_path")
        if existing and Path(existing).exists() and Path(existing).stat().st_size > 0 and not force:
            print(f"[{sid}] Reusing existing narration: {existing}")
            continue
        params: dict = {"text": shot["narration"]}
        if voice_mode == "clone":
            params["referenceAudio"] = str(sample_path)
        planned.append((shot, "tts", {
            "type": TTS_TYPE, "params": params,
            "outputDir": str(audio_dir), "outputName": f"vo_{sid}",
        }, out, sid))

    bgm_enabled = bool(doc.get("music", {}).get("enabled")) and not only
    music_store = doc.get("music", {})
    bgm_out = audio_dir / "bgm"
    bgm_path = music_store.get("path")
    if bgm_enabled and not (bgm_path and Path(bgm_path).exists() and Path(bgm_path).stat().st_size > 0 and not force):
        planned.append((music_store, "music", {
            "type": MUSIC_TYPE, "params": {"prompt": music_prompt(doc)},
            "outputDir": str(audio_dir), "outputName": "bgm",
        }, bgm_out, "bgm"))
    elif not bgm_enabled:
        print("BGM disabled in beats.json; skipping music.")

    if not planned:
        print("Nothing to generate (all audio exists).")
        return 0

    jobs = [item[2] for item in planned]

    if not submit:
        print(f"DRY-RUN: would enqueue {len(jobs)} audio task(s) as one pool batch "
              f"(narration: {TTS_TYPE}, voice={voice_mode}; music: {MUSIC_TYPE}):")
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
        print("\nDRY-RUN only: no task was submitted and no cost was incurred.")
        print("After explicit approval, rerun with --submit.")
        return 0

    print(f"Enqueuing {len(jobs)} audio task(s) as one pool batch...")
    batch_id, pool_ids = pool.enqueue_batch(jobs)
    print(f"batch {batch_id}: pool ids {pool_ids}")
    for (store, kind, _j, _o, _sid), pid in zip(planned, pool_ids):
        store[f"{kind}_pool_id"] = pid
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")  # persist pool ids BEFORE ffprobe/wait
    snapshot = pool.wait_for(pool_ids)

    ffprobe = find_ffprobe()
    failed = 0
    over_budget: list[str] = []
    coins_total = 0

    for (store, kind, _job, _out, sid), pid in zip(planned, pool_ids):
        row = snapshot[pid]
        status = row.get("status")
        lines = pool.task_lines(pid)
        actual_str = lines.get("OUTPUT_FILE")
        actual = Path(actual_str) if actual_str else None
        ok = status == "SUCCESS" and actual and actual.exists() and actual.stat().st_size > 0
        if not ok:
            failed += 1
            store[f"last_{kind}_error"] = (row.get("error_message")
                                           or f"pool {pid} ended {status} with no output file")
            print(f"[{sid}] FAILED (pool {pid}): {store[f'last_{kind}_error']}")
            beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue

        coins = int(lines.get("COINS") or 0)
        coins_total += coins
        if kind == "tts":
            store["vo_path"] = str(actual)
            store["voice_mode"] = voice_mode
            store.pop("last_tts_error", None)
            vo_dur = probe_duration(ffprobe, actual)
            store["vo_duration_s"] = round(vo_dur, 3)
            print(f"[{sid}] Saved: {actual} ({vo_dur:.2f}s, {coins} coins)")
            if vo_dur > MAX_VO_S + 0.02:
                over_budget.append(
                    f"[{sid}] narration {vo_dur:.2f}s exceeds the {MAX_VO_S:.2f}s budget "
                    f"(8s clip minus lead/tail). SHORTEN the narration text in beats.json, "
                    f"then rerun: python scripts/generate_audio.py {project_dir.name} "
                    f"--only {sid} --force --submit"
                )
        else:
            store["path"] = str(actual)
            store.pop("last_music_error", None)
            print(f"[bgm] Saved: {actual} ({coins} coins)")
        beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if failed:
        print(f"\n{failed} audio task(s) failed. Rerun with --submit for the missing "
              f"items (existing files are reused, no auto-resubmit).")
        return 1
    if over_budget:
        print("\nNarration length guard tripped:")
        for line in over_budget:
            print("  " + line)
        print("Stopping; do not extend shots beyond the 8s source clip.")
        return 1

    doc["status"] = "audio"
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nAudio stage complete — {coins_total} RH coins.")
    print("Review the narration voice and confirm the BGM has no vocals before assembly.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Vox MVP narration and BGM via the RH task pool")
    parser.add_argument("project_dir")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--only", help="Comma-separated anchor shot IDs, e.g. s4")
    args = parser.parse_args(argv or sys.argv[1:])
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), args.force, args.submit, only)


if __name__ == "__main__":
    raise SystemExit(main())

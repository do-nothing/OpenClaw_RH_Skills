#!/usr/bin/env python3
"""Stage 3: plan shots from REAL voiceover durations and detected pauses.

Deterministic, offline, no cost:

  beat span S = beat window from the audio timeline:
    grouped mode (voice.group: auto): real block between neighboring beats in
    the normalized group segments (natural inter-beat pauses kept);
    beat mode: S = LEAD + vo_duration + TAIL (fixed 0.45s tail).
  n = round(S/8) clamped to [ceil(S/15), floor(S/4)]; progressive-step count
      takes priority when present
  ideal equal cuts snap to the nearest pause midpoint (longer sentence pauses
  preferred) inside +/-1.2s (fallback +/-2.0s); every shot must land 4-15s.
  No usable pause -> forced cut at the ideal point flagged forced_no_pause.

In grouped mode ALL shots are trimmed exactly to their used duration (the
audio timeline is master; no integer-second slack may accumulate).

Prints the approval table (gate 2) and writes shots[] into explainer.json.
Manual edits persist across replans by (beat_id, ord).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from explainer_common import (
    CARD_S, LEAD_S, SHOT_MAX_S, SHOT_MIN_S, SHOT_TARGET_S, SENTENCE_PAUSE_S,
    SNAP_WINDOW_FALLBACK_S, SNAP_WINDOW_S, TAIL_S, beat_timeline, is_grouped,
    load_doc, save_doc,
)

MOVES = ["push_in", "pan", "parallax", "tilt", "pull_out"]
MODES = ("first_frame", "first_last_frame")


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def shot_count(span: float, progressive: list[str]) -> int:
    lo = max(1, math.ceil(span / SHOT_MAX_S - 1e-9))
    hi = max(lo, math.floor(span / SHOT_MIN_S + 1e-9))
    base = round(span / SHOT_TARGET_S)
    if progressive:
        base = len(progressive)
    return int(clamp(base, lo, hi))


def choose_cut(ideal: float, pauses: list[dict], used: set[int],
               prev_boundary: float, span: float, remaining: int,
               lead: float = LEAD_S) -> tuple[float, str, float]:
    """Return (vo-relative cut, basis, pause_duration)."""
    candidates = []
    for i, p in enumerate(pauses):
        if i in used:
            continue
        mid = (p["start"] + p["end"]) / 2
        left = (lead + mid) - prev_boundary
        right = span - (lead + mid)
        if not (SHOT_MIN_S - 1e-9 <= left <= SHOT_MAX_S + 1e-9):
            continue
        if right < SHOT_MIN_S * (remaining + 1) - 1e-9:
            continue
        if right > SHOT_MAX_S * (remaining + 1) + 1e-9:
            continue
        dist = abs(mid - ideal)
        dur = min(p["duration"], 0.9)
        score = dist - dur * 1.5 + 2.0 * max(0.0, SENTENCE_PAUSE_S - p["duration"])
        candidates.append((score, dist, i, mid, p["duration"]))
    for window in (SNAP_WINDOW_S, SNAP_WINDOW_FALLBACK_S):
        near = [c for c in candidates if c[1] <= window]
        if near:
            near.sort(key=lambda c: c[0])
            _, _, i, mid, dur = near[0]
            used.add(i)
            basis = "sentence_pause" if dur >= SENTENCE_PAUSE_S else "short_pause"
            return mid, basis, dur
    return ideal, "forced_no_pause", 0.0


def plan_beat(beat: dict, n_override: int | None = None,
              span: float | None = None, lead: float = LEAD_S) -> tuple[list[dict], list[str]]:
    if span is None:
        span = LEAD_S + float(beat["vo_duration_s"]) + TAIL_S
    pauses = beat.get("pauses") or []
    n = shot_count(span, beat.get("progressive") or [])
    if n_override is not None:
        n = n_override
    warns: list[str] = []

    # vo-relative ideal cut points.
    cuts: list[tuple[float, str, float]] = []  # (vo-rel cut, basis, pause dur)
    used_pauses: set[int] = set()
    prev_beat_boundary = 0.0
    for k in range(1, n):
        ideal_beat = k * span / n
        ideal_vo = ideal_beat - lead
        cut, basis, dur = choose_cut(
            ideal_vo, pauses, used_pauses, prev_beat_boundary, span,
            n - 1 - k, lead)
        if basis == "forced_no_pause":
            warns.append(f"{beat['id']} 第 {k} 个切点附近无停顿（理想位置 {ideal_beat:.2f}s）"
                         "：硬切可能落在词上，建议在 script.md 该句加逗号后重做该 beat TTS")
        cuts.append((cut, basis, dur))
        prev_beat_boundary = lead + cut

    boundaries = [0.0] + [lead + c for c, _, _ in cuts]
    used_durs = [boundaries[i + 1] - boundaries[i] for i in range(n - 1)]
    last_used = span - boundaries[-1]
    used_durs.append(last_used)
    if last_used < SHOT_MIN_S - 1e-9:
        warns.append(f"{beat['id']} 末镜成片长度 {last_used:.2f}s < {SHOT_MIN_S:.0f}s："
                     f"用 --shots {beat['id']}:{max(1, n - 1)} 减少一镜")

    shots: list[dict] = []
    for ord_i, used in enumerate(used_durs, start=1):
        submit = int(clamp(math.ceil(used - 1e-9), SHOT_MIN_S, SHOT_MAX_S))
        if ord_i < n:
            cut_vo, basis, dur = cuts[ord_i - 1]
            cut_beat = lead + cut_vo
        else:
            cut_beat, basis, dur = (None, "single_shot" if n == 1 else "beat_last", 0.0)
        shots.append({
            "ord": ord_i,
            "used_duration_s": round(used, 3),
            "submit_duration_s": submit,
            "cut_beat_s": None if cut_beat is None else round(cut_beat, 3),
            "cut_basis": basis,
            "pause_duration_s": round(dur, 3),
        })
    return shots, warns


def default_size(duty: str, ord_i: int, n: int) -> str:
    if ord_i == 1 or ord_i == n:
        return "WIDE"
    return "CLOSE" if duty in ("evidence", "analogy") else "MEDIUM"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 3 shot planner")
    p.add_argument("project_dir")
    p.add_argument("--mode", action="append", default=[],
                   help="b03s1:first_last_frame (repeatable)")
    p.add_argument("--move", action="append", default=[],
                   help="b03s2:push_in (repeatable)")
    p.add_argument("--shots", action="append", default=[],
                   help="b09:2 override shot count for a beat (must still fit 4-15s)")
    args = p.parse_args(argv or sys.argv[1:])
    overrides_shots: dict[str, int] = {}
    for spec in args.shots:
        bid, _, val = spec.partition(":")
        try:
            n_val = int(val)
            if n_val < 1:
                raise ValueError
        except ValueError:
            raise SystemExit(f"bad --shots {spec}; expected e.g. b09:2")
        overrides_shots[bid.strip()] = n_val
    project_dir = Path(args.project_dir).resolve()
    doc = load_doc(project_dir)

    overrides_mode, overrides_move = {}, {}
    for spec in args.mode:
        sid, _, val = spec.partition(":")
        if val not in MODES:
            raise SystemExit(f"bad mode {spec}; one of {MODES}")
        overrides_mode[sid.strip()] = val
    for spec in args.move:
        sid, _, val = spec.partition(":")
        if val not in (*MOVES, "static"):
            raise SystemExit(f"bad move {spec}")
        overrides_move[sid.strip()] = val

    for b in doc["beats"]:
        if not b.get("vo_path") or b.get("vo_duration_s") is None:
            raise SystemExit(f"{b['id']} 还没有实测旁白，先运行 generate_audio.py --submit")

    # chapter map
    chapters = doc.get("chapters") or []
    def chapter_of(bid: str) -> str | None:
        cur = None
        for c in chapters:
            if bid >= c["from_beat"]:
                cur = c["id"]
            else:
                break
        return cur

    grouped = is_grouped(doc)
    tl = beat_timeline(doc) if grouped else None
    if grouped:
        print("Timeline source: grouped voice takes (audio-master, exact cuts)")
    else:
        print("Timeline source: per-beat TTS (lead 0.20 + vo + tail 0.45)")

    prev_manual = {(s["beat_id"], s["ord"]): s for s in doc.get("shots", [])}
    new_shots: list[dict] = []
    all_warns: list[str] = []
    t_cursor = 0.0
    move_idx = 0
    last_beat_id = doc["beats"][-1]["id"]

    known_beats = {b["id"] for b in doc["beats"]}
    for bid in overrides_shots:
        if bid not in known_beats:
            raise SystemExit(f"unknown beat id in --shots: {bid}")

    for b in doc["beats"]:
        if grouped:
            ent = tl["beats"][b["id"]]
            planned, warns = plan_beat(
                b, overrides_shots.get(b["id"]),
                span=ent["end"] - ent["start"], lead=ent["lead"])
        else:
            planned, warns = plan_beat(b, overrides_shots.get(b["id"]))
        all_warns += warns
        cid = chapter_of(b["id"])
        block_start = t_cursor
        for plan in planned:
            ord_i = plan["ord"]
            n = len(planned)
            sid = f"{b['id']}s{ord_i}"
            move = MOVES[move_idx % len(MOVES)]
            move_idx += 1
            if b["id"] == last_beat_id and ord_i == n:
                move = "static"
            rec = {
                "id": sid, "beat_id": b["id"], "ord": ord_i,
                "mode": "first_frame",
                "shot_size": default_size(b["visual_duty"], ord_i, n),
                "camera_move": move,
                "timeline_start_s": round(t_cursor, 3),
                "used_duration_s": plan["used_duration_s"],
                "submit_duration_s": plan["submit_duration_s"],
                "cut_at_s": (round(block_start + plan["cut_beat_s"], 3)
                             if plan["cut_beat_s"] is not None else None),
                "cut_basis": plan["cut_basis"],
                "pause_duration_s": plan["pause_duration_s"],
                "chapter_id": cid,
                "scene_en": "", "motion_en": "", "last_frame_change_en": "",
                "avoid_en": "",
            }
            old = prev_manual.get((b["id"], ord_i))
            if old:
                for k in ("mode", "shot_size", "camera_move",
                          "scene_en", "motion_en", "last_frame_change_en",
                          "avoid_en"):
                    if old.get(k):
                        rec[k] = old[k]
                structure_same = (
                    old.get("mode") == rec["mode"]
                    and abs(float(old.get("used_duration_s") or 0) - rec["used_duration_s"]) < 0.02
                    and int(old.get("submit_duration_s") or 0) == rec["submit_duration_s"]
                )
                if structure_same:
                    for k in ("first_frame_path", "last_frame_path", "image_pool_id",
                              "last_image_pool_id", "image_coins", "clip_path",
                              "clip_source_duration_s", "video_pool_id", "video_coins",
                              "keyframe_prompt", "keyframe_prompt_sha256",
                              "clip_prompt", "clip_prompt_sha256",
                              "last_image_error", "last_video_error"):
                        if k in old:
                            rec[k] = old[k]
                else:
                    # retimed / mode changed: first keyframe still reusable
                    if old.get("first_frame_path"):
                        rec["first_frame_path"] = old["first_frame_path"]
                        rec["image_pool_id"] = old.get("image_pool_id")
                        rec["keyframe_prompt"] = old.get("keyframe_prompt")
                        rec["keyframe_prompt_sha256"] = old.get("keyframe_prompt_sha256")
                    if rec["mode"] == "first_last_frame" and old.get("last_frame_path") \
                            and old.get("mode") == "first_last_frame":
                        rec["last_frame_path"] = old["last_frame_path"]
            if sid in overrides_mode:
                rec["mode"] = overrides_mode[sid]
            if sid in overrides_move:
                rec["camera_move"] = overrides_move[sid]
            # grouped: audio is master, every shot exact-trimmed; beat mode:
            # the last shot keeps its integer-second source (slack at tail)
            step = rec["used_duration_s"] if grouped or ord_i < n \
                else rec["submit_duration_s"]
            t_cursor += step
            new_shots.append(rec)

    if grouped:
        n_cards = sum(1 for g in doc.get("voice_groups") or [] if g.get("card"))
        expected = tl["total"] - n_cards * CARD_S
        if abs(t_cursor - expected) > 0.12:
            raise SystemExit(
                f"planned shot blocks total {t_cursor:.3f}s != audio timeline "
                f"{expected:.3f}s (excl. {n_cards} cards); refusing to write")

    # validate override target ids + adjacent move uniqueness (warning only)
    known = {s["id"] for s in new_shots}
    for sid in (*overrides_mode, *overrides_move):
        if sid not in known:
            raise SystemExit(f"unknown shot id: {sid}")
    for a, c in zip(new_shots, new_shots[1:]):
        if a["camera_move"] == c["camera_move"]:
            all_warns.append(f"相邻镜头 {a['id']}→{c['id']} 运镜相同（{a['camera_move']}），"
                             "可用 --move 调整")

    doc["shots"] = new_shots
    if doc.get("status") in ("draft", "audio"):
        doc["status"] = "shots"
    save_doc(project_dir, doc)

    # refresh prompts.en.json template without clobbering authored English
    en_path = project_dir / "prompts.en.json"
    en: dict = {}
    if en_path.exists():
        en = json.loads(en_path.read_text(encoding="utf-8"))
    changed = False
    for s in new_shots:
        if s["id"] not in en:
            en[s["id"]] = {"scene_en": "", "motion_en": "",
                           "last_frame_change_en": "", "avoid_en": ""}
            changed = True
    if changed:
        en_path.write_text(json.dumps(en, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    # approval table
    last_step = t_cursor - new_shots[-1]["timeline_start_s"]
    print(f"Planned {len(new_shots)} shot(s); block total "
          f"{new_shots[-1]['timeline_start_s'] + last_step:.2f}s "
          f"(excl. optional chapter cards)")
    cur_ch = None
    for s in new_shots:
        if s["chapter_id"] != cur_ch:
            cur_ch = s["chapter_id"]
            if cur_ch:
                title = next((c["title"] for c in chapters if c["id"] == cur_ch), "")
                print(f"\n── {cur_ch} {title} ──")
        cut = "" if s["cut_at_s"] is None else f" cut@{s['cut_at_s']:.2f}s({s['cut_basis']})"
        fl = "FL" if s["mode"] == "first_last_frame" else "FF"
        print(f"  {s['id']:7s} {s['timeline_start_s']:7.2f}s  use {s['used_duration_s']:5.2f}s "
              f"submit {s['submit_duration_s']:2d}s {fl} {s['shot_size']:6s} "
              f"{s['camera_move']:9s}{cut}")
    for w in all_warns:
        print(f"WARNING: {w}")
    print(f"\n英文画面稿模板：{en_path}（填写 scene_en / motion_en / "
          "last_frame_change_en / avoid_en 后运行 generate_keyframe_prompts.py）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

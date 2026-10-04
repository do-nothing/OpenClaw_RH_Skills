#!/usr/bin/env python3
"""Parse script.md into explainer.json (offline-only).

- Validates front matter and every beat (--strict also rejects placeholders).
- Snapshots runninghub workflowIds and the aspect parameter mapping.
- Hash-based cascade: changed narration resets that beat's audio/pauses/shots;
  changed visual fields invalidate its generated prompts (artifacts are kept
  until the user explicitly re-rolls with --force).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from explainer_common import (
    ASPECTS, PLACEHOLDER_RE, SCHEMA_VERSION, STYLES,
    doc_path, endpoint_snapshot, load_doc, parse_beats, parse_front_matter,
    save_doc, sha256_text, shots_of,
)

AUDIO_FIELDS = ("vo_path", "vo_duration_s", "tts_pool_id", "pauses_path",
                "pauses", "last_tts_error",
                # grouped-TTS fields
                "vo_group_id", "vo_seg_start_s", "vo_seg_end_s")
# Shot fields that survive a prompt-only (visual) invalidation.
SHOT_ARTIFACT_FIELDS = (
    "first_frame_path", "last_frame_path", "image_pool_id", "last_image_pool_id",
    "image_coins", "clip_path", "clip_source_duration_s", "video_pool_id",
    "video_coins", "last_image_error", "last_video_error",
)
PROMPT_FIELDS = ("keyframe_prompt", "keyframe_prompt_sha256",
                 "last_frame_prompt", "last_frame_prompt_sha256",
                 "clip_prompt", "clip_prompt_sha256",
                 "first_frame_prompt_hash", "last_frame_prompt_hash",
                 "clip_prompt_hash")


def visual_hash(b: dict) -> str:
    payload = json.dumps({
        "duty": b["visual_duty"], "see": b["visual_see"],
        "text": b["on_screen_text"], "steps": b["progressive"],
        "cont": b["continuity"], "avoid": b["avoid"],
    }, ensure_ascii=False, sort_keys=True)
    return sha256_text(payload)


def validate_front(fm: dict, n_beats: int) -> list[str]:
    errors: list[str] = []
    for key in ("project", "topic"):
        if not str(fm.get(key, "")).strip():
            errors.append(f"front matter 缺少 {key}")
    aspect = str(fm.get("aspect", "16:9"))
    if aspect not in ASPECTS:
        errors.append(f"aspect {aspect!r} 不支持（两端共同支持：{'/'.join(ASPECTS)}）")
    style = str(fm.get("visual_style", ""))
    if style not in STYLES:
        errors.append(f"visual_style {style!r} 不在：{'/'.join(STYLES)}")
    dur = fm.get("target_duration_s")
    # planning reference only (real length comes from measured narration);
    # 0 = unspecified. Content defines the length, not this field.
    if not isinstance(dur, (int, float)) or not 0 <= dur <= 300:
        errors.append("target_duration_s 必须是 0–300 的数字（0 = 不指定目标时长）")
    voice = fm.get("voice") or {}
    if voice.get("mode") not in ("tts", "clone"):
        errors.append("voice.mode 必须是 tts 或 clone")
    if voice.get("mode") == "clone" and not voice.get("sample_path"):
        errors.append("voice.mode=clone 时必须给 voice.sample_path")
    if voice.get("group", "auto") not in ("auto", "beat"):
        errors.append("voice.group 只能是 auto（默认，按章整组）或 beat（逐句）")
    chapters = fm.get("chapters") or []
    if chapters:
        if not 2 <= len(chapters) <= 4:
            errors.append(f"章节数建议 2–4（当前 {len(chapters)}）")
        ids, prev_from = [], None
        for c in chapters:
            cid = str(c.get("id", ""))
            title = str(c.get("title", ""))
            fb = str(c.get("from_beat", ""))
            ids.append(cid)
            if not cid or not title or not re.fullmatch(r"b\d{2}", fb):
                errors.append(f"章节项需含 id/title/from_beat：{c}")
                continue
            if len(title) > 8:
                errors.append(f"章节 {cid} 标题超过 8 字：{title}")
            if fb not in {f"b{i:02d}" for i in range(1, n_beats + 1)}:
                errors.append(f"章节 {cid} 的 from_beat {fb} 不存在")
            if prev_from is not None and fb <= prev_from:
                errors.append(f"章节 {cid} 的 from_beat 必须递增")
            prev_from = fb
        if len(set(ids)) != len(ids):
            errors.append("章节 id 重复")
    return errors


def placeholders(beats: list[dict]) -> list[str]:
    out = []
    for b in beats:
        for key in ("narration", "visual_see"):
            if PLACEHOLDER_RE.search(str(b.get(key, ""))):
                out.append(f"{b['id']} 的 {key} 仍是占位符")
        for t in b.get("on_screen_text", []):
            if PLACEHOLDER_RE.search(t):
                out.append(f"{b['id']} 的画面文字仍是占位符")
        for s in b.get("progressive", []):
            if PLACEHOLDER_RE.search(s):
                out.append(f"{b['id']} 的渐进步骤仍是占位符")
    return out


def recompute_status(doc: dict) -> str:
    beats = doc["beats"]
    if not beats or any(not b.get("vo_path") for b in beats):
        return "draft"
    # grouped mode is usable only when the group timeline is fully resolved;
    # a stale per-beat vo_path pointing at a group take is not a usable state
    if str(doc.get("voice", {}).get("group", "auto")) != "beat":
        groups = doc.get("voice_groups") or []
        if not groups or any(b.get("vo_seg_start_s") is None for b in beats):
            return "draft"
    shots = doc.get("shots", [])
    if not shots or any(not shots_of(doc, b["id"]) for b in beats):
        return "audio"
    if any(not s.get("first_frame_path") for s in shots):
        return "shots"
    if any(not s.get("clip_path") for s in shots):
        return "keyframes"
    return "clips"


def run(project_dir: Path, strict: bool) -> int:
    script_md = project_dir / "script.md"
    if not script_md.exists():
        raise SystemExit(f"script.md not found: {script_md} — run new_project.py first")
    text = script_md.read_text(encoding="utf-8-sig")
    fm, body = parse_front_matter(text)
    beats, beat_errors, warnings = parse_beats(body)
    errors = beat_errors + validate_front(fm, len(beats))
    if strict:
        errors += placeholders(beats)

    print(f"Parsed {len(beats)} beats from {script_md.name}")
    for b in beats:
        n_shots_hint = f"  渐进{len(b['progressive'])}步→预计多镜" if b.get("progressive") else ""
        print(f"  {b['id']} [{b['visual_duty']:10s}] ~{b['est_duration_s']:5.2f}s  "
              f"{b['narration'][:28]}{n_shots_hint}")
    chapters = fm.get("chapters") or []
    total_est = round(sum(b["est_duration_s"] for b in beats), 1)
    print(f"预估总时长（语速 0.24s/字，仅参考）：{total_est}s")
    if chapters and total_est < 90:
        warnings.append(f"预估 {total_est}s < 90s：章节通常用于长片，确认是否真的需要")
    if errors:
        print("\nValidation failed:")
        for e in errors:
            print(f"- {e}")
        if strict:
            return 1
        print("\n（非 --strict 模式：仅报告，不写 explainer.json 之外继续）")

    old: dict | None = None
    if doc_path(project_dir).exists():
        old = json.loads(doc_path(project_dir).read_text(encoding="utf-8"))
    old_beats = {b["id"]: b for b in (old or {}).get("beats", [])}
    old_shots = {}
    for s in (old or {}).get("shots", []):
        old_shots.setdefault(s["beat_id"], {})[s["ord"]] = s

    doc_beats: list[dict] = []
    doc_shots: list[dict] = []
    notes: list[str] = []
    old_aspect = (old or {}).get("aspect")
    for b in beats:
        nh = sha256_text(b["narration"])
        vh = visual_hash(b)
        prev = old_beats.get(b["id"])
        rec = {
            "id": b["id"], "title": b["title"], "narration": b["narration"],
            "visual_duty": b["visual_duty"], "visual_see": b["visual_see"],
            "on_screen_text": b["on_screen_text"], "progressive": b["progressive"],
            "continuity": b["continuity"], "avoid": b["avoid"],
            "est_duration_s": b["est_duration_s"],
            "narration_sha256": nh, "visual_sha256": vh,
        }
        narration_same = bool(prev and prev.get("narration_sha256") == nh)
        visual_same = bool(prev and prev.get("visual_sha256") == vh)
        if narration_same:
            for f in AUDIO_FIELDS:
                if f in prev:
                    rec[f] = prev[f]
        elif prev is not None:
            notes.append(f"{b['id']} 旁白已改：音频/停顿/镜头/关键帧/视频将级联重做")

        # carry shots by beat ordinal only when narration is unchanged
        if narration_same:
            for ord_s, shot in sorted(old_shots.get(b["id"], {}).items()):
                kept = {k: shot[k] for k in (
                    "id", "beat_id", "ord", "mode", "shot_size", "camera_move",
                    "timeline_start_s", "used_duration_s", "submit_duration_s",
                    "cut_at_s", "cut_basis", "pause_duration_s", "chapter_id",
                    "scene_en", "motion_en", "last_frame_change_en", "avoid_en",
                    *SHOT_ARTIFACT_FIELDS, *PROMPT_FIELDS,
                ) if k in shot}
                if not visual_same:
                    for f in PROMPT_FIELDS:
                        kept.pop(f, None)
                    notes.append(f"{b['id']} 视觉意图已改：{shot['id']} 提示词需重新生成"
                                 f"（已有图/片保留，确认后用 --force 重滚）")
                doc_shots.append(kept)
        doc_beats.append(rec)

    for bid in set(old_beats) - {b["id"] for b in beats}:
        notes.append(f"{bid} 已从讲稿删除，其生成记录不再引用（磁盘文件保留）")

    doc = {
        "schema_version": SCHEMA_VERSION,
        "project": fm["project"],
        "topic": fm["topic"],
        "audience": fm.get("audience"),
        "core_takeaway": fm.get("core_takeaway"),
        "tone": fm.get("tone"),
        "aspect": fm.get("aspect", "16:9"),
        "target_duration_s": fm.get("target_duration_s"),
        "visual_style": fm.get("visual_style"),
        "voice": fm.get("voice", {"mode": "tts"}),
        "music": fm.get("music", {"enabled": False}),
        "captions": fm.get("captions", True),
        "chapter_cards": bool(fm.get("chapter_cards", False)),
        "chapters": chapters,
        "script_sha256": sha256_text(text),
        "aspect_map": ASPECTS[fm.get("aspect", "16:9")],
        "endpoints": endpoint_snapshot(),
        "beats": doc_beats,
        "shots": doc_shots,
    }
    if old and "music" in old:
        # keep resolved BGM path/pool id unless music got disabled
        if doc["music"].get("enabled"):
            for k in ("path", "pool_id", "music_pool_id"):
                if old["music"].get(k):
                    doc["music"][k] = old["music"][k]

    # A group take is one acoustic unit: an edit to one beat invalidates its
    # whole group, but unaffected groups are kept (group ids stay positional as
    # long as the beat list and chapter structure are unchanged).
    old_groups = (old or {}).get("voice_groups") or []
    old_voice_group = (old or {}).get("voice", {}).get("group", "auto")
    new_voice_group = doc["voice"].get("group", "auto")
    old_beat_ids = [b["id"] for b in (old or {}).get("beats", [])]
    new_beat_map = {r["id"]: r for r in doc_beats}
    new_beat_ids = list(new_beat_map)
    any_narration_changed = any(
        not old_beats.get(bid)
        or old_beats[bid].get("narration_sha256") != rec["narration_sha256"]
        for bid, rec in new_beat_map.items())
    structure_same = (old_beat_ids == new_beat_ids
                      and (old or {}).get("chapters") == chapters)
    if old_groups and not any_narration_changed and structure_same \
            and old_voice_group == new_voice_group:
        # nothing audio-relevant changed
        doc["voice_groups"] = old_groups
    elif old_groups:
        if structure_same and old_voice_group == new_voice_group:
            kept: list[dict] = []
            dropped_gids: set[str] = set()
            for g in old_groups:
                if all(old_beats.get(bid, {}).get("narration_sha256")
                       == new_beat_map[bid]["narration_sha256"]
                       for bid in g["beats"]):
                    kept.append(g)
                else:
                    dropped_gids.add(g["id"])
            if dropped_gids:
                notes.append(
                    f"音频组 {sorted(dropped_gids)} 内旁白改动，整组需重配；"
                    "其余组保留（重跑 generate_audio.py 后需重新规划镜头）")
                for rec in doc_beats:
                    if rec.get("vo_group_id") in dropped_gids:
                        for k in ("vo_group_id", "vo_seg_start_s", "vo_seg_end_s"):
                            rec.pop(k, None)
            doc["voice_groups"] = kept
        else:
            notes.append("beat/章节结构或 voice.group 变化：整组旁白时间轴全部失效，"
                         "重跑 generate_audio.py --submit 后需重新规划镜头")
            for rec in doc_beats:
                for k in ("vo_group_id", "vo_seg_start_s", "vo_seg_end_s"):
                    rec.pop(k, None)
    if old_aspect and old_aspect != doc["aspect"] and old:
        notes.append(f"画幅 {old_aspect} → {doc['aspect']}：已有关键帧/视频需重滚")

    doc["status"] = recompute_status(doc)
    save_doc(project_dir, doc)

    for n in notes:
        print(f"CASCADE: {n}")
    for wmsg in warnings:
        print(f"WARNING: {wmsg}")
    print(f"\nWrote {doc_path(project_dir)} (status={doc['status']})")
    if errors and strict:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Parse script.md into explainer.json")
    p.add_argument("project_dir")
    p.add_argument("--strict", action="store_true",
                   help="Reject placeholders and any validation error")
    args = p.parse_args(argv or sys.argv[1:])
    return run(Path(args.project_dir).resolve(), args.strict)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stage 2: narration (voice-clone-emo) + one BGM (music-yue2).

Narration modes (voice.group in script.md front matter):
- auto (default): beats are synthesized in GROUPS (one take per chapter, split
  at ~60s estimated speech). One task renders a whole group -> natural cross-
  sentence prosody and inter-beat pauses; after download the take is aligned
  to beat boundaries (audio_align, local/free) and normalized into seg files
  that become the master timeline for plan_shots/assemble.
- beat: legacy one-task-per-beat synthesis; timeline rebuilt from fixed lead
  0.20 + vo + tail 0.45. Kept for rerolling one beat after script edits.

clone mode sends one shared voice sample for every job. BGM: style only, no
lyrics -> prebuilt fake lyrics + RoFormer; save node 56 (accompaniment).

Default is a local dry-run (quote). --submit enqueues ONE pool batch and only
waits for that batch; nothing is ever auto-resubmitted. Alignment failure
stops the stage (keeps the raw take) instead of spending money on fallback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from explainer_common import (
    PLACEHOLDER_RE, detect_pauses,
    find_tool, load_doc, probe_duration, save_doc, shots_of,
)
import audio_align
import rh_pool_client as pool

TTS_TYPE = "voice-clone-emo"
MUSIC_TYPE = "music-yue2"
MUSIC_ACCOMPANIMENT_NODE = "56"
END_PUNCT = ("。", "！", "？", "!?", "”", "’", "…")


def music_style(doc: dict) -> str:
    return (
        "instrumental documentary background music, no vocals, no singing, "
        "light but restrained, warm and curious, clean unobtrusive mix that stays "
        "under spoken narration, suitable for Chinese educational explainer video. "
        f"Mood reference: {doc.get('music', {}).get('prompt', '')}"
    )


def plan_groups(doc: dict) -> list[list[dict]]:
    """Groups are defined purely by content: one group per chapter
    (split at chapters.from_beat). No chapters -> the whole piece is one
    take. Duration never splits a group — if a take is ever too long for
    the TTS service or too expensive to reroll, that is a script decision
    (split the chapter), not an engineering heuristic."""
    chapter_starts = {c["from_beat"] for c in (doc.get("chapters") or [])}
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for b in doc["beats"]:
        if cur and b["id"] in chapter_starts:
            groups.append(cur)
            cur = []
        cur.append(b)
    if cur:
        groups.append(cur)
    return groups


def group_text(beats: list[dict]) -> str:
    parts: list[str] = []
    for b in beats:
        t = b["narration"].strip()
        if parts and not parts[-1].endswith(END_PUNCT):
            parts[-1] += "。"
        parts.append(t)
    return "".join(parts)


def run(project_dir: Path, force: bool, submit: bool, only: set[str] | None) -> int:
    doc = load_doc(project_dir)
    beats = doc["beats"]
    if only:
        missing = only - {b["id"] for b in beats}
        if missing:
            raise SystemExit(f"Unknown beat id(s): {sorted(missing)}")
    for b in beats:
        if PLACEHOLDER_RE.search(b["narration"]):
            raise SystemExit(f"{b['id']} narration still contains placeholders; "
                             "finish script.md and run sync_script.py --strict")
    pool.ensure_pool_script()

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    voice_mode = str(doc.get("voice", {}).get("mode") or "tts")
    group_mode = str(doc.get("voice", {}).get("group", "auto"))
    sample_path: Path | None = None
    if voice_mode == "clone":
        sample_path = Path(str(doc["voice"].get("sample_path")))
        if not sample_path.is_absolute():
            sample_path = project_dir / sample_path
        if not sample_path.exists():
            raise SystemExit(f"voice sample not found: {sample_path}")

    # (store, kind, job, key) tuples. For grouped TTS jobs `store` is a payload
    # dict; for legacy/music jobs it is the beat/doc store that receives fields.
    planned: list[tuple[object, str, dict, str]] = []
    grouped = group_mode != "beat"

    selected_groups: list[tuple[str, list[dict], bool]] = []
    group_payloads: list[dict] = []
    if grouped:
        groups = plan_groups(doc)
        old_groups = {g["id"]: g for g in (doc.get("voice_groups") or [])}
        chapter_starts = {c["from_beat"] for c in (doc.get("chapters") or [])}
        for idx, gbeats in enumerate(groups, start=1):
            gid = f"g{idx:02d}"
            card = bool(doc.get("chapter_cards")) and gbeats[0]["id"] in chapter_starts
            old = old_groups.get(gid)
            same_comp = bool(old and old.get("beats") == [b["id"] for b in gbeats])
            raw_ok = bool(same_comp and old.get("raw_path")
                          and Path(str(old["raw_path"])).exists()
                          and Path(str(old["raw_path"])).stat().st_size > 0)
            wants_tts = force or (only is not None and any(
                b["id"] in only for b in gbeats))
            if wants_tts:
                selected_groups.append((gid, gbeats, card))
                text = group_text(gbeats)
                params: dict = {"text": text}
                if voice_mode == "clone":
                    params["referenceAudio"] = str(sample_path)
                payload = {"gid": gid, "beats": [b["id"] for b in gbeats],
                           "card": card, "text": text, "pool_id": None}
                group_payloads.append(payload)
                planned.append((payload, "tts", {
                    "type": TTS_TYPE, "params": params,
                    "outputDir": str(audio_dir), "outputName": f"vo_{gid}",
                }, gid))
                if only:
                    extra = sorted({b["id"] for b in gbeats} - only)
                    if extra:
                        print(f"NOTE: --only 命中组 {gid}，整组重配："
                              f"{[b['id'] for b in gbeats]}（含 {extra}）")
                continue
            # reuse raw; free local seg rebuild when card toggle / seg missing
            seg_ok = bool(raw_ok and old.get("seg_path")
                          and Path(str(old["seg_path"])).exists()
                          and bool(old.get("card")) == card)
            if seg_ok:
                print(f"[{gid}] Reusing existing group narration: {old['raw_path']}")
            elif raw_ok:
                print(f"[{gid}] Raw take reused; rebuilding normalized seg "
                      f"(card={card})")
                selected_groups.append((gid, gbeats, card))
            else:
                # no usable raw: must synthesize, but --submit wasn't targeting it
                selected_groups.append((gid, gbeats, card))
                text = group_text(gbeats)
                params = {"text": text}
                if voice_mode == "clone":
                    params["referenceAudio"] = str(sample_path)
                payload = {"gid": gid, "beats": [b["id"] for b in gbeats],
                           "card": card, "text": text, "pool_id": None}
                group_payloads.append(payload)
                planned.append((payload, "tts", {
                    "type": TTS_TYPE, "params": params,
                    "outputDir": str(audio_dir), "outputName": f"vo_{gid}",
                }, gid))
    else:
        for b in beats:
            if only and b["id"] not in only:
                continue
            existing = b.get("vo_path")
            if existing and Path(existing).exists() and Path(existing).stat().st_size > 0 and not force:
                print(f"[{b['id']}] Reusing existing narration: {existing}")
                continue
            params = {"text": b["narration"]}
            if voice_mode == "clone":
                params["referenceAudio"] = str(sample_path)
            planned.append((b, "tts", {
                "type": TTS_TYPE, "params": params,
                "outputDir": str(audio_dir), "outputName": f"vo_{b['id']}",
            }, b["id"]))

    music_store = doc.get("music", {})
    bgm_enabled = bool(music_store.get("enabled")) and not only
    if bgm_enabled:
        bgm_path = music_store.get("path")
        if bgm_path and Path(bgm_path).exists() and Path(bgm_path).stat().st_size > 0 and not force:
            print(f"[bgm] Reusing existing BGM: {bgm_path}")
        else:
            planned.append((music_store, "music", {
                "type": MUSIC_TYPE,
                "params": {"style": music_style(doc),
                           "maxDuration": min(360, int(doc.get("target_duration_s") or 60) + 15)},
                "outputDir": str(audio_dir), "outputName": "bgm",
            }, "bgm"))
    elif not only:
        print("BGM disabled; skipping music.")

    if not planned:
        if grouped and selected_groups:
            return _finalize_groups(project_dir, doc, selected_groups, {}, {})
        print("Nothing to generate (all audio exists).")
        return 0

    jobs = [item[2] for item in planned]
    if not submit:
        print(f"DRY-RUN: would enqueue {len(jobs)} audio task(s) as one pool batch "
              f"(narration {TTS_TYPE} voice={voice_mode} group={group_mode}; "
              f"music={MUSIC_TYPE if bgm_enabled else 'off'}):")
        if grouped:
            for payload in group_payloads:
                print(f"\n[{payload['gid']}] beats={payload['beats']} "
                      f"card={payload['card']} {len(payload['text'])} 字")
                print(f"  {payload['text']}")
        print("\n" + json.dumps(
            [{"type": j["type"],
              "params": {**j["params"], "text": j["params"]["text"][:60] + "…"}}
             for j in jobs],
            ensure_ascii=False, indent=2))
        print("\nDRY-RUN only: no cost incurred. Rerun with --submit after approval.")
        return 0

    print(f"Enqueuing {len(jobs)} audio task(s) as one batch...")
    batch_id, pool_ids = pool.enqueue_batch(jobs)
    print(f"batch {batch_id}: pool ids {pool_ids}")
    for (store, kind, _j, _key), pid in zip(planned, pool_ids):
        if kind == "tts" and grouped:
            store["pool_id"] = pid
        else:
            store[f"{kind}_pool_id"] = pid
    save_doc(project_dir, doc)

    snapshot = pool.wait_for(pool_ids)
    ffprobe = find_tool("ffprobe")
    ffmpeg = find_tool("ffmpeg")
    failed = 0
    coins_total = 0
    group_raws: dict[str, Path] = {}

    for (store, kind, _job, key), pid in zip(planned, pool_ids):
        row = snapshot[pid]
        status = row.get("status")
        lines = pool.task_lines(pid)
        actual_str = lines.get("OUTPUT_FILE")
        if kind == "music":
            actual_str = next(
                (str(dl.get("path")) for dl in (row.get("downloads_json") or [])
                 if str(dl.get("nodeId")) == MUSIC_ACCOMPANIMENT_NODE and dl.get("ok")),
                actual_str)
        actual = Path(actual_str) if actual_str else None
        ok = status == "SUCCESS" and actual and actual.exists() and actual.stat().st_size > 0
        if not ok:
            failed += 1
            err = (row.get("error_message")
                   or f"pool {pid} ended {status} with no output file")
            if isinstance(store, dict) and grouped:
                store["last_tts_error"] = err
            else:
                store[f"last_{kind}_error"] = err
            print(f"[{key}] FAILED (pool {pid}): {err}")
            save_doc(project_dir, doc)
            continue

        coins = int(lines.get("COINS") or 0)
        coins_total += coins
        if kind == "tts" and grouped:
            store["raw_path"] = str(actual)
            store["tts_coins"] = coins
            group_raws[key] = actual
            print(f"[{key}] group take downloaded, {coins} coins -> {actual.name}")
        elif kind == "tts":
            store["vo_path"] = str(actual)
            store["tts_pool_id"] = pid
            store.pop("last_tts_error", None)
            vo_dur = probe_duration(ffprobe, actual)
            store["vo_duration_s"] = round(vo_dur, 3)
            pauses = detect_pauses(ffmpeg, actual)
            ppath = audio_dir / f"pauses_{key}.json"
            ppath.write_text(json.dumps(pauses, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            store["pauses_path"] = str(ppath)
            store["pauses"] = pauses
            span = 0.20 + vo_dur + 0.45
            print(f"[{key}] {vo_dur:.2f}s (span {span:.2f}s), "
                  f"{len(pauses)} pause(s), {coins} coins -> {actual.name}")
        else:
            store["path"] = str(actual)
            store.pop("last_music_error", None)
            print(f"[bgm] saved ({coins} coins) -> {actual.name}")
        save_doc(project_dir, doc)

    if failed:
        print(f"\n{failed} audio task(s) failed. Successes kept; rerun --submit for "
              "missing items (existing files reused, no auto-resubmit).")
        return 1

    if grouped:
        payload_by_gid = {p["gid"]: p for p in group_payloads}
        rc = _finalize_groups(project_dir, doc, selected_groups, group_raws,
                              payload_by_gid)
        if rc:
            return rc

    if doc.get("shots") and all(shots_of(doc, b["id"]) for b in beats):
        pass  # keep later stage
    else:
        doc["status"] = "audio"
    save_doc(project_dir, doc)
    print(f"\nAudio stage complete — {coins_total} RH coins. "
          "Next: python scripts/plan_shots.py")
    return 0


def _finalize_groups(project_dir: Path, doc: dict,
                     selected_groups: list[tuple[str, list[dict], bool]],
                     group_raws: dict[str, Path],
                     payload_by_gid: dict[str, dict] | None = None) -> int:
    """Align takes to beats; write normalized seg files + per-beat timeline fields.

    Freshly downloaded takes come from group_raws; free rebuilds reuse the
    stored raw path (chapter-card toggle / missing seg file).
    """
    payload_by_gid = payload_by_gid or {}
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    audio_dir = project_dir / "audio"
    old_groups = {g["id"]: g for g in (doc.get("voice_groups") or [])}
    new_records: dict[str, dict] = {}
    beat_map = {b["id"]: b for b in doc["beats"]}
    align_failed = False

    for gid, gbeats, card in selected_groups:
        raw = group_raws.get(gid)
        old = old_groups.get(gid)
        if raw is None and old and old.get("raw_path"):
            raw = Path(str(old["raw_path"]))
        if raw is None or not raw.exists():
            raise SystemExit(f"{gid}: no TTS output and no reusable raw take")
        seg = audio_dir / f"seg_{gid}.m4a"

        align = audio_align.align_beats(
            ffmpeg, ffprobe, raw, [b["narration"] for b in gbeats])
        if align.get("__align_failed__"):
            align_failed = True
            print(f"[{gid}] 对齐失败（原始整组音频已保留：{raw.name}）：")
            for r in align["reasons"]:
                print(f"  - {r}")
            continue
        intervals = align["intervals"]
        norm = audio_align.build_segment(
            ffmpeg, ffprobe, raw, seg, intervals, card)
        per_beat_pauses = audio_align.beat_pauses(align, intervals)

        rec: dict = {
            "id": gid,
            "beats": [b["id"] for b in gbeats],
            "raw_path": str(raw),
            "seg_path": str(seg),
            "raw_duration_s": align["raw_duration_s"],
            "seg_duration_s": norm["seg_duration_s"],
            "card": card,
            "align_method": align["method"],
        }
        # billing/history: fresh payload wins, else keep old record values
        payload = payload_by_gid.get(gid, {})
        if payload.get("pool_id") is not None:
            rec["tts_pool_id"] = payload["pool_id"]
        if payload.get("tts_coins") is not None:
            rec["tts_coins"] = payload["tts_coins"]
        if old:
            for k in ("tts_pool_id", "tts_coins", "pool_id"):
                if rec.get(k) is None and old.get(k) is not None:
                    rec[k] = old[k]
        new_records[gid] = rec

        for b, iv, vo_seg, pauses in zip(
                gbeats, intervals, norm["vo_seg"], per_beat_pauses):
            recd = beat_map[b["id"]]
            recd["vo_path"] = str(raw)
            recd["vo_group_id"] = gid
            recd["vo_seg_start_s"] = vo_seg["start"]
            recd["vo_seg_end_s"] = vo_seg["end"]
            recd["vo_duration_s"] = round(iv["end"] - iv["start"], 3)
            recd["pauses"] = pauses
            ppath = audio_dir / f"pauses_{b['id']}.json"
            ppath.write_text(
                json.dumps(pauses, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            recd["pauses_path"] = str(ppath)
            recd.pop("last_tts_error", None)
        print(f"[{gid}] aligned {len(gbeats)} beats ({align['method']}), "
              f"seg {norm['seg_duration_s']:.2f}s card={card} -> {seg.name}")
        save_doc(project_dir, doc)

    if align_failed:
        print("\n对齐失败：原始音频已保留，但未写时间轴。可：")
        print("  1) 检查跨 beat 处是否缺少句末停顿，改稿后重跑该组；")
        print("  2) 在 script.md 设 voice.group: beat 退回逐 beat 合成。")
        return 1

    final_groups: list[dict] = []
    for idx, gbeats in enumerate(plan_groups(doc), start=1):
        gid = f"g{idx:02d}"
        if gid in new_records:
            final_groups.append(new_records[gid])
        elif gid in old_groups:
            final_groups.append(old_groups[gid])
        else:
            raise SystemExit(f"internal error: no record for group {gid}")
    doc["voice_groups"] = final_groups
    if not (doc.get("shots") and all(shots_of(doc, b["id"]) for b in doc["beats"])):
        doc["status"] = "audio"
    save_doc(project_dir, doc)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stage 2 narration + BGM via RH pool")
    p.add_argument("project_dir")
    p.add_argument("--only", help="Comma-separated beat ids, e.g. b03 (whole group)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--submit", action="store_true")
    args = p.parse_args(argv or sys.argv[1:])
    only = {x.strip() for x in args.only.split(",") if x.strip()} if args.only else None
    return run(Path(args.project_dir).resolve(), args.force, args.submit, only)


if __name__ == "__main__":
    raise SystemExit(main())

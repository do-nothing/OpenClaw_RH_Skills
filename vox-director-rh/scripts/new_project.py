#!/usr/bin/env python3
"""Create and validate a local Vox Director project (offline-only).

Never calls RunningHub or any network API. Creates project folders and a draft
beats.json.

Schema v2 ("openclaw-vox-mvp-2") adds the narrative layer on top of v1 while
keeping a FLAT shots array (each item is still one keyframe + one 8s source
clip, so the generator scripts barely change):

  beat = one narration line + one caption. It groups 1-2 visual shots via
  beat_id. The first shot is the "anchor" (WIDE, carries narration + headline),
  the optional second is a "detail" cut-in (CLOSE/DETAIL, no headline, no
  narration). Speech plays continuously across the beat; the visual cuts
  mid-sentence (the upstream "wide + detail" rhythm win). Detail shots are
  optional and cost extra, so the default template stays 4 beats / 4 shots.

Old v1 projects (schema openclaw-vox-mvp-1, every shot carries its own
narration) still validate and build: each shot is treated as its own beat.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = "openclaw-vox-mvp-2"
V1_SCHEMA_VERSION = "openclaw-vox-mvp-1"

# Visual themes. Descriptions live in generate_keyframe_prompts.py THEMES; keep
# these keys in sync. Ported/adapted from the upstream theme library.
ALLOWED_THEMES = {
    "newsprint-editorial",
    "swiss-modern",
    "chinese-ink",
    "american-retro",
    "punk-zine",
    "soviet-constructivist",
    "wpa-propaganda",
    "70s-groovy",
    "atomic-age",
    "gilded-deco",
}
# Flat-safe camera vocabulary (uniform translate/scale never warps the art).
ALLOWED_MOVES = {"static", "push_in", "pull_out", "pan", "tilt", "parallax"}
ALLOWED_SIZES = {"WIDE", "MEDIUM", "CLOSE", "DETAIL"}
ALLOWED_ARCS = {
    "hook_payoff", "how_it_works", "timeline", "myth_buster",
    "pas", "bab", "man_in_hole", "listicle",
}
ALLOWED_HOOKS = {
    "direct_question", "surprising_stat", "mistake_callout", "pain_point",
    "secret_reveal", "outcome_tease", "pattern_interrupt",
}
ALLOWED_ENDINGS = {"hard_cut", "quick_cta", "loop_close"}
ALLOWED_STATUS = {"draft", "keyframes", "clips", "audio", "assembled", "verified"}
REQUIRED_DIRS = ("keyframes", "clips", "audio", "_seg")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PLACEHOLDER_RE = re.compile(r"【请填写|TODO|待填写|REPLACE_WITH", re.IGNORECASE)
CJK_RE = re.compile(r"[一-鿿]")


# --------------------------------------------------------------------------- #
# v2 draft template
# --------------------------------------------------------------------------- #
def _visual_fields(camera: str, scene_cn: str, scene_en: str, motion_cn: str,
                   palette_note: str, palette_en: str) -> dict:
    return {
        "scene": scene_cn,
        "scene_en": scene_en,
        "camera_move": camera,
        "element_motion": motion_cn,
        "element_motion_en": "[REPLACE_WITH_ENGLISH_RIGID_PAPER_MOTION]",
        "palette_note": palette_note,
        "palette_en": palette_en,
    }


def _anchor_shot(idx: int, beat_id: str, size: str, dur: float, camera: str,
                 topic: str, *, hook: bool, hook_type: str | None,
                 role_cn: str, scene_en: str) -> dict:
    shot = {
        "id": f"s{idx}",
        "beat_id": beat_id,
        "beat_role": "anchor",
        "shot_size": size,
        "dur_s": dur,
        "hook": hook,
        "title_on_image": True,
        "headline": "【请填写短标题】",
        "narration": f"【请填写{role_cn}旁白（推荐 12–22 字）：围绕“{topic}”】",
        **_visual_fields(
            camera,
            f"围绕“{topic}”制作分层纸片拼贴：主体、相关道具、报纸碎片和几何纸碎。",
            scene_en,
            "前景主体缓慢运动，纸浪和报纸碎片轻轻飘动，半调网点微弱脉动",
            "米白纸张、炭黑轮廓、深红强调色",
            "[REPLACE_WITH_ENGLISH_PALETTE]",
        ),
    }
    if hook:
        shot["hook_type"] = hook_type or "direct_question"
    return shot


def _detail_shot(anchor_idx: int, beat_id: str, camera: str, topic: str) -> dict:
    return {
        "id": f"s{anchor_idx}b",
        "beat_id": beat_id,
        "beat_role": "detail",
        "shot_size": "CLOSE",
        "dur_s": 2.2,
        "title_on_image": False,
        # Detail cut-in: NO headline and NO narration — the beat narration
        # continues across this shot; it is a visual punch only.
        **_visual_fields(
            camera,
            f"用纸片特写放大“{topic}”最关键的一个道具、数字或动作，填满画面。",
            "[REPLACE_WITH_ENGLISH_TIGHT_CLOSEUP_DETAIL_NO_TEXT]",
            "关键纸片道具轻微弹入或被推近，碎屑短促散开后归位",
            "延续本 beat 的纸张底色，仅用一个高饱和强调色",
            "[REPLACE_WITH_ENGLISH_PALETTE]",
        ),
    }


# Per-arc narrative stages (Chinese role hints shown in the draft narration).
# Authored for the long 12-beat case; evenly sampled for shorter films.
ARC_STAGES = {
    "hook_payoff": ["钩子", "背景", "展开", "展开", "推进", "推进", "转折", "推进", "高潮", "收束", "金句", "落点"],
    "how_it_works": ["钩子", "它是什么", "总览", "步骤一", "步骤一细节", "步骤二", "步骤二细节", "步骤三", "常见误解", "关键好处", "金句", "行动点"],
    "timeline": ["钩子", "起源", "早期", "早期", "发展", "发展", "转折点", "扩散", "成熟", "现状", "启示", "落点"],
    "myth_buster": ["先抛事实", "钩子", "常见错觉", "错觉来源", "拆穿一", "拆穿二", "真正原理", "证据", "证据细节", "该信什么", "金句", "落点"],
    "pas": ["痛点钩子", "痛点场景", "放大后果", "后果加剧", "转机", "解法亮相", "如何起效", "证明", "证明细节", "额外好处", "行动号召", "紧迫感"],
    "bab": ["现状钩子", "之前多糟", "糟糕细节", "代价", "转机", "之后多好", "好处", "好处细节", "如何桥接", "证明", "行动号召", "落点"],
    "man_in_hole": ["本来挺好", "日常", "意外掉落", "困境加深", "谷底", "挣扎", "转机", "开始爬升", "关键努力", "突破", "比以前更好", "金句"],
    "listicle": ["承诺钩子", "第 N 项", "第 N 项", "第 N 项", "第 N 项", "第 N 项", "第 N 项", "第 N 项", "第 N 项", "第 N 项", "最关键一项", "回顾"],
}

# Camera rhythm per arc for the long case; sampled for shorter films.
# Adjacent beats never repeat; the final payoff beat is static.
ARC_MOVES = {
    "hook_payoff": ["push_in", "pan", "parallax", "pan", "push_in", "tilt", "pull_out", "parallax", "push_in", "tilt", "static", "pull_out"],
    "how_it_works": ["push_in", "pan", "tilt", "pan", "push_in", "pan", "parallax", "push_in", "tilt", "parallax", "static", "pull_out"],
    "timeline": ["push_in", "pan", "pan", "pan", "pan", "tilt", "push_in", "pan", "parallax", "tilt", "pull_out", "static"],
    "myth_buster": ["push_in", "tilt", "pan", "push_in", "parallax", "tilt", "push_in", "pan", "parallax", "tilt", "static", "pull_out"],
    "pas": ["push_in", "static", "pan", "tilt", "push_in", "parallax", "pan", "push_in", "parallax", "tilt", "static", "push_in"],
    "bab": ["tilt", "push_in", "pan", "tilt", "push_in", "pull_out", "pan", "parallax", "push_in", "tilt", "static", "pull_out"],
    "man_in_hole": ["push_in", "pan", "tilt", "push_in", "static", "pan", "pull_out", "tilt", "parallax", "push_in", "pull_out", "static"],
    "listicle": ["push_in", "pan", "pan", "pan", "pan", "pan", "pan", "pan", "pan", "tilt", "parallax", "static"],
}

# Framing sizes: open wide, tighten through the middle/payoff, resolve at end.
SIZE_FLOW = ["WIDE", "MEDIUM", "MEDIUM", "CLOSE", "CLOSE", "MEDIUM", "CLOSE", "CLOSE", "MEDIUM", "CLOSE", "CLOSE", "WIDE"]

_HOOK_SCENE_EN = "[REPLACE_WITH_ENGLISH_HOOK_SCENE_AS_LAYERED_PAPER_CUTOUTS]"
_DEFAULT_SCENE_EN = "[REPLACE_WITH_ENGLISH_LAYERED_PAPER_COLLAGE_SCENE_NO_READABLE_LABELS]"
_DETAIL_CAM = {"push_in": "pan", "pull_out": "pan", "pan": "push_in",
               "tilt": "push_in", "parallax": "push_in", "static": "push_in"}


def _sample(seq: list[str], n: int) -> list[str]:
    """Evenly sample n items, always keeping the first and last."""
    if n >= len(seq):
        return list(seq)
    if n == 1:
        return [seq[0]]
    idx = [round(i * (len(seq) - 1) / (n - 1)) for i in range(n)]
    return [seq[j] for j in idx]


_MOVE_POOL = ["push_in", "pan", "parallax", "tilt", "pull_out"]


def _moves_for(arc: str, n: int) -> list[str]:
    """n camera moves sampled from the arc rhythm, then repaired so adjacent
    beats never repeat and the final payoff beat is always static."""
    moves = _sample(ARC_MOVES[arc], n)
    moves[-1] = "static"
    for i in range(1, n):
        if moves[i] != moves[i - 1]:
            continue
        if i == n - 1:
            # Keep the final static; repair the beat just before it.
            prev2 = moves[i - 2] if i - 2 >= 0 else None
            moves[i - 1] = next(t for t in _MOVE_POOL if t != "static" and t != prev2)
        else:
            nxt = moves[i + 1] if i + 1 < n else None
            moves[i] = next(t for t in _MOVE_POOL if t != moves[i - 1] and t != nxt)
    return moves


def beats_for_duration(duration: int) -> int:
    """Longer films use MORE beats, not longer single sentences (each line must
    still fit the 8s source / 7.35s speech budget)."""
    for upper, count in ((22, 4), (32, 6), (42, 8), (52, 10)):
        if duration <= upper:
            return count
    return 12


def make_template(topic: str, project: str, theme: str, duration: int,
                  voice_mode: str, sample_path: str | None, music: bool,
                  arc: str, ending: str, detail_beats: set[str]) -> dict:
    """Create a deliberate draft. Placeholders must be replaced before paying."""
    n_beats = beats_for_duration(duration)
    stages = _sample(ARC_STAGES[arc], n_beats)
    moves = _moves_for(arc, n_beats)
    sizes = _sample(SIZE_FLOW, n_beats)
    stages[0] = "钩子"
    beat_dur = round(duration / n_beats, 1)

    shots: list[dict] = []
    for i in range(n_beats):
        beat_id = f"b{i + 1}"
        stage = stages[i]
        is_hook = i == 0
        role_cn = "钩子" if is_hook else stage
        scene_en = _HOOK_SCENE_EN if is_hook else _DEFAULT_SCENE_EN
        shots.append(_anchor_shot(
            i + 1, beat_id, sizes[i], beat_dur, moves[i], topic,
            hook=is_hook, hook_type="direct_question" if is_hook else None,
            role_cn=role_cn, scene_en=scene_en,
        ))
        if beat_id in detail_beats:
            next_move = moves[i + 1] if i + 1 < n_beats else None
            detail_cam = next(t for t in _MOVE_POOL
                              if t != moves[i] and t != next_move)
            shots.append(_detail_shot(i + 1, beat_id, detail_cam, topic))

    return {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "topic": topic,
        "language": "zh-CN",
        "aspect": "16:9",
        "target_duration_s": duration,
        "theme": theme,
        "arc": arc,
        "ending": ending,
        "status": "draft",
        "image_endpoint": None,
        "video_endpoint": None,
        "voice": {
            "mode": voice_mode,
            "sample_path": sample_path,
            "language": "zh-CN",
        },
        "music": {
            "enabled": music,
            "prompt": "克制的纪录片配乐，纯器乐，无人声，不压过人声" if music else "",
        },
        "captions": True,
        "watermark": "",
        "no_duplicate_submit": True,
        "shots": shots,
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _groups(shots: list[dict]) -> list[tuple[str, list[tuple[int, dict]]]]:
    """Group flat shots by beat_id, preserving first-seen order."""
    order: list[str] = []
    buckets: dict[str, list[tuple[int, dict]]] = {}
    for i, shot in enumerate(shots):
        bid = str(shot.get("beat_id", ""))
        if bid not in buckets:
            buckets[bid] = []
            order.append(bid)
        buckets[bid].append((i, shot))
    return [(bid, buckets[bid]) for bid in order]


def validate_doc_v2(doc: dict, strict: bool, project_dir: Path | None) -> list[str]:
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    project = str(doc.get("project", ""))
    require(bool(PROJECT_RE.fullmatch(project)), "project 必须是 1–40 位小写英文、数字、下划线或连字符")
    require(bool(str(doc.get("topic", "")).strip()), "topic 不能为空")
    require(doc.get("language") == "zh-CN", "目前仅支持 language=zh-CN")
    require(doc.get("aspect") == "16:9", "第一梯队仅支持 aspect=16:9（竖屏后续再加）")
    require(doc.get("theme") in ALLOWED_THEMES, f"theme 必须是 {sorted(ALLOWED_THEMES)} 之一")
    require(doc.get("arc") in ALLOWED_ARCS, f"arc 必须是 {sorted(ALLOWED_ARCS)} 之一（见 references/narrative.md）")
    ending = doc.get("ending", "hard_cut")
    require(ending in ALLOWED_ENDINGS, f"ending 必须是 {sorted(ALLOWED_ENDINGS)} 之一")
    require(doc.get("status") in ALLOWED_STATUS, f"status 必须是 {sorted(ALLOWED_STATUS)} 之一")
    require(doc.get("no_duplicate_submit") is True, "no_duplicate_submit 必须为 true")
    require(doc.get("captions") is True, "目前要求 captions=true")

    duration = doc.get("target_duration_s")
    require(isinstance(duration, (int, float)) and 10 <= float(duration) <= 75,
            "target_duration_s 必须在 10–75 秒之间（仅规划用；最终时长由旁白实际长度决定，长片靠更多 beat）")

    voice = doc.get("voice")
    require(isinstance(voice, dict), "voice 必须是对象")
    if isinstance(voice, dict):
        require(voice.get("mode") in {"tts", "clone"}, "voice.mode 必须是 tts 或 clone")
        require(voice.get("language") == "zh-CN", "voice.language 必须是 zh-CN")
        if voice.get("mode") == "clone":
            sample = voice.get("sample_path")
            require(bool(sample), "voice.mode=clone 时必须提供 sample_path")
            if sample and project_dir:
                p = Path(str(sample))
                if not p.is_absolute():
                    p = project_dir / p
                if not p.exists():
                    errors.append(f"语音克隆样本不存在: {sample}")

    music = doc.get("music")
    require(isinstance(music, dict), "music 必须是对象")
    if isinstance(music, dict):
        require(isinstance(music.get("enabled"), bool), "music.enabled 必须是布尔值")
        if music.get("enabled"):
            require(bool(str(music.get("prompt", "")).strip()), "music.enabled=true 时必须有 music.prompt")

    shots = doc.get("shots")
    require(isinstance(shots, list) and 1 <= len(shots) <= 24, "shots 必须是 1–24 个视觉镜头")
    if not (isinstance(shots, list) and 1 <= len(shots) <= 24):
        return errors

    groups = _groups(shots)
    beat_ids = [bid for bid, _ in groups]
    expected = [f"b{i}" for i in range(1, len(groups) + 1)]
    require(beat_ids == expected, f"beat_id 必须连续为 {expected}，实际 {beat_ids}")

    seen_ids: set[str] = set()
    previous_move: str | None = None
    total_planned = 0.0

    for gi, (bid, members) in enumerate(groups, start=1):
        roles = [s.get("beat_role") for _, s in members]
        require(roles[0] == "anchor", f"{bid}: 第一个镜头必须是 anchor")
        require(all(r in {"anchor", "detail"} for r in roles), f"{bid}: beat_role 只能是 anchor/detail")
        require(roles.count("anchor") == 1, f"{bid}: 每个 beat 只能有一个 anchor")
        require(len(members) <= 2, f"{bid}: 一个 beat 最多 2 个镜头（anchor + 可选 detail）")
        if len(members) == 2 and roles[1] != "detail":
            errors.append(f"{bid}: 第二个镜头必须是 detail")

        anchor = members[0][1]
        # ---- anchor (carries narration + optional headline) ----
        ap = f"{bid}.anchor({anchor.get('id')})"
        require(anchor.get("id") not in seen_ids, f"{ap}: shot id 重复")
        seen_ids.add(str(anchor.get("id")))
        require(anchor.get("shot_size", "WIDE") in ALLOWED_SIZES, f"{ap}.shot_size 非法")
        adur = anchor.get("dur_s")
        require(isinstance(adur, (int, float)) and 3.0 <= float(adur) <= 6.5,
                f"{ap}.dur_s 必须在 3.0–6.5 秒")
        if isinstance(adur, (int, float)):
            total_planned += float(adur)
        require(isinstance(anchor.get("hook"), bool), f"{ap}.hook 必须是布尔值")
        if gi == 1:
            require(anchor.get("hook") is True, "b1 的 anchor 必须 hook=true")
            require(anchor.get("hook_type") in ALLOWED_HOOKS,
                    f"b1 的 hook_type 必须是 {sorted(ALLOWED_HOOKS)} 之一")
        require(isinstance(anchor.get("title_on_image"), bool), f"{ap}.title_on_image 必须是布尔值")
        if anchor.get("camera_move") not in ALLOWED_MOVES:
            errors.append(f"{ap}.camera_move 非法：{sorted(ALLOWED_MOVES)}")
        if previous_move is not None and anchor.get("camera_move") == previous_move:
            errors.append(f"{ap}.camera_move 与上一镜头重复（相邻镜头运镜必须不同）")
        previous_move = anchor.get("camera_move")

        narration = str(anchor.get("narration", "")).strip()
        require(bool(narration), f"{ap}.narration 不能为空（旁白归 beat 的 anchor）")
        if strict and narration:
            require(4 <= len(narration) <= 45,
                    f"{ap}.narration 推荐 12–22 字、硬上限 45；最终以 generate_audio 的 7.35s 时长校验为准")
            if PLACEHOLDER_RE.search(narration):
                errors.append(f"{ap}.narration 仍含占位符")
        headline = str(anchor.get("headline", "")).strip()
        if anchor.get("title_on_image"):
            require(bool(headline), f"{ap}: 标题镜头必须填 headline")
            require(len(headline) <= 20, f"{ap}.headline 建议 ≤20 字")
        if strict and PLACEHOLDER_RE.search(headline):
            errors.append(f"{ap}.headline 仍含占位符")
        _check_english(anchor, ap, strict, errors, require)

        # ---- optional detail (no narration, no headline) ----
        if len(members) == 2:
            di, detail = members[1]
            dp = f"{bid}.detail({detail.get('id')})"
            require(detail.get("id") not in seen_ids, f"{dp}: shot id 重复")
            seen_ids.add(str(detail.get("id")))
            require(detail.get("shot_size") in {"CLOSE", "DETAIL"},
                    f"{dp}.shot_size 必须是 CLOSE 或 DETAIL")
            require(detail.get("title_on_image") is False, f"{dp}.title_on_image 必须为 false")
            require(not str(detail.get("headline", "")).strip(), f"{dp} 不能带 headline")
            require(not str(detail.get("narration", "")).strip(),
                    f"{dp} 不能带 narration（beat 旁白由 anchor 承担，连续铺到本镜）")
            ddur = detail.get("dur_s")
            require(isinstance(ddur, (int, float)) and 1.2 <= float(ddur) <= 4.0,
                    f"{dp}.dur_s 必须在 1.2–4.0 秒")
            if isinstance(ddur, (int, float)):
                total_planned += float(ddur)
            if detail.get("camera_move") not in ALLOWED_MOVES:
                errors.append(f"{dp}.camera_move 非法")
            if detail.get("camera_move") == anchor.get("camera_move"):
                errors.append(f"{dp}.camera_move 与 anchor 重复")
            previous_move = detail.get("camera_move")
            _check_english(detail, dp, strict, errors, require)

    return errors


def _check_english(shot: dict, prefix: str, strict: bool, errors: list[str], require) -> None:
    for key in ("scene", "element_motion", "palette_note"):
        require(bool(str(shot.get(key, "")).strip()), f"{prefix}.{key} 不能为空")
    if not strict:
        return
    bounds = {"scene_en": (20, 700), "element_motion_en": (10, 400), "palette_en": (5, 200)}
    for key, (lo, hi) in bounds.items():
        value = str(shot.get(key, "")).strip()
        require(lo <= len(value) <= hi, f"{prefix}.{key} 长度应在 {lo}–{hi}")
        if PLACEHOLDER_RE.search(value):
            errors.append(f"{prefix}.{key} 仍含占位符")
        if CJK_RE.search(value):
            errors.append(f"{prefix}.{key} 必须用英文（中文只允许出现在 headline）")
    scene = str(shot.get("scene", "")).strip()
    motion = str(shot.get("element_motion", "")).strip()
    require(10 <= len(scene) <= 500, f"{prefix}.scene 长度应在 10–500")
    require(5 <= len(motion) <= 300, f"{prefix}.element_motion 长度应在 5–300")


def validate_doc_v1(doc: dict, strict: bool, project_dir: Path | None) -> list[str]:
    """Legacy 4-shot schema (openclaw-vox-mvp-1): every shot is its own beat."""
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    v1_themes = {"newsprint-editorial", "swiss-modern", "chinese-ink"}
    v1_moves = {"static", "push_in", "pan", "parallax"}
    project = str(doc.get("project", ""))
    require(bool(PROJECT_RE.fullmatch(project)), "project 必须是 1–40 位小写英文、数字、下划线或连字符")
    require(bool(str(doc.get("topic", "")).strip()), "topic 不能为空")
    require(doc.get("language") == "zh-CN", "MVP 仅支持 language=zh-CN")
    require(doc.get("aspect") == "16:9", "MVP 仅支持 aspect=16:9")
    require(doc.get("theme") in v1_themes, f"v1 theme 必须是 {sorted(v1_themes)} 之一")
    require(doc.get("status") in ALLOWED_STATUS, f"status 必须是 {sorted(ALLOWED_STATUS)} 之一")
    require(doc.get("no_duplicate_submit") is True, "no_duplicate_submit 必须为 true")
    require(doc.get("captions") is True, "MVP 第一版要求 captions=true")
    duration = doc.get("target_duration_s")
    require(isinstance(duration, (int, float)) and 15 <= float(duration) <= 20, "target_duration_s 必须在 15–20 秒")

    voice = doc.get("voice")
    require(isinstance(voice, dict), "voice 必须是对象")
    if isinstance(voice, dict) and voice.get("mode") == "clone":
        sample = voice.get("sample_path")
        require(bool(sample), "voice.mode=clone 时必须提供 sample_path")
        if sample and project_dir:
            p = Path(str(sample))
            if not p.is_absolute():
                p = project_dir / p
            if not p.exists():
                errors.append(f"语音克隆样本不存在: {sample}")
    music = doc.get("music")
    require(isinstance(music, dict), "music 必须是对象")
    if isinstance(music, dict) and music.get("enabled"):
        require(bool(str(music.get("prompt", "")).strip()), "music.enabled=true 时必须有 music.prompt")

    shots = doc.get("shots")
    require(isinstance(shots, list) and len(shots) == 4, "v1 必须恰好 4 个 shots")
    if not (isinstance(shots, list) and len(shots) == 4):
        return errors
    total = 0.0
    previous_move = None
    for index, shot in enumerate(shots, start=1):
        prefix = f"shots[{index}]"
        require(isinstance(shot, dict), f"{prefix} 必须是对象")
        if not isinstance(shot, dict):
            continue
        require(shot.get("id") == f"s{index}", f"{prefix}.id 必须是 s{index}")
        dur = shot.get("dur_s")
        require(isinstance(dur, (int, float)) and 3.5 <= float(dur) <= 5, f"{prefix}.dur_s 必须在 3.5–5 秒")
        if isinstance(dur, (int, float)):
            total += float(dur)
        require(isinstance(shot.get("hook"), bool), f"{prefix}.hook 必须是布尔值")
        if index == 1:
            require(shot.get("hook") is True, "s1.hook 必须为 true")
        require(isinstance(shot.get("title_on_image"), bool), f"{prefix}.title_on_image 必须是布尔值")
        require(shot.get("camera_move") in v1_moves, f"{prefix}.camera_move 非法")
        if previous_move is not None and shot.get("camera_move") == previous_move:
            errors.append(f"{prefix}.camera_move 不得与相邻镜头重复")
        previous_move = shot.get("camera_move")
        for key in ("narration", "scene", "element_motion", "palette_note"):
            value = str(shot.get(key, "")).strip()
            require(bool(value), f"{prefix}.{key} 不能为空")
            if strict and PLACEHOLDER_RE.search(value):
                errors.append(f"{prefix}.{key} 仍含占位符")
        headline = str(shot.get("headline", "")).strip()
        if shot.get("title_on_image"):
            require(bool(headline), f"{prefix} 标题镜头必须填 headline")
            require(len(headline) <= 20, f"{prefix}.headline 建议 ≤20 字")
        if strict:
            if PLACEHOLDER_RE.search(headline):
                errors.append(f"{prefix}.headline 仍含占位符")
            narration = str(shot.get("narration", "")).strip()
            require(4 <= len(narration) <= 45, f"{prefix}.narration 推荐 12–22 字、硬上限 45")
            for ek, lo, hi in (("scene_en", 20, 700), ("element_motion_en", 10, 400), ("palette_en", 5, 200)):
                ev = str(shot.get(ek, "")).strip()
                require(lo <= len(ev) <= hi, f"{prefix}.{ek} 长度应在 {lo}–{hi}")
                if PLACEHOLDER_RE.search(ev) or CJK_RE.search(ev):
                    errors.append(f"{prefix}.{ek} 必须是已填写的英文")
    if isinstance(duration, (int, float)):
        require(abs(total - float(duration)) <= 2.0, f"镜头总时长 {total:.1f}s 与目标 {duration}s 相差不能超过 2 秒")
    return errors


def validate_doc(doc: dict, strict: bool = False, project_dir: Path | None = None) -> list[str]:
    version = doc.get("schema_version")
    if version == V1_SCHEMA_VERSION:
        return validate_doc_v1(doc, strict, project_dir)
    if version == SCHEMA_VERSION:
        return validate_doc_v2(doc, strict, project_dir)
    return [f"schema_version 不受支持: {version}（支持 {V1_SCHEMA_VERSION} / {SCHEMA_VERSION}）"]


def beat_groups(doc: dict) -> list[dict]:
    """Normalized beat view shared by the audio and assembly stages.

    Returns one dict per beat in order:
      {"beat_id": str, "anchor": shot, "details": [shot, ...]}
    v2 groups flat shots by beat_id (anchor first + optional detail).
    v1 has no beat_id, so every shot is its own single-shot beat.
    """
    shots = doc.get("shots", [])
    if doc.get("schema_version") == V1_SCHEMA_VERSION:
        return [{"beat_id": str(s.get("id")), "anchor": s, "details": []} for s in shots]
    groups: list[dict] = []
    for bid, members in _groups(shots):
        anchor = members[0][1]
        details = [s for _, s in members[1:]]
        groups.append({"beat_id": bid, "anchor": anchor, "details": details})
    return groups


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def create_project(args: argparse.Namespace) -> Path:
    root = Path(args.root).resolve()
    project_dir = root / args.project
    beats_path = project_dir / "beats.json"
    if beats_path.exists() and not args.force:
        raise SystemExit(f"项目已存在: {beats_path}\n如需覆盖用 --force；不会删除已生成素材。")

    project_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_DIRS:
        (project_dir / name).mkdir(exist_ok=True)

    detail_beats = set()
    if args.detail:
        for item in args.detail.split(","):
            item = item.strip()
            if not re.fullmatch(r"b(?:[1-9]|1[0-2])", item):
                raise SystemExit("--detail 形如 b2,b10（在这些 beat 后追加 detail 特写镜头）")
            detail_beats.add(item)

    doc = make_template(
        topic=args.topic, project=args.project, theme=args.theme, duration=args.duration,
        voice_mode=args.voice, sample_path=args.sample_path, music=args.music,
        arc=args.arc, ending=args.ending, detail_beats=detail_beats,
    )
    errors = validate_doc(doc, strict=False, project_dir=project_dir)
    if errors:
        raise SystemExit("草稿结构校验失败:\n- " + "\n- ".join(errors))
    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return project_dir


def validate_existing(project_dir: Path, strict: bool) -> None:
    beats_path = project_dir / "beats.json"
    if not beats_path.exists():
        raise SystemExit(f"找不到 beats.json: {beats_path}")
    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=strict, project_dir=project_dir)
    if errors:
        print(f"{'严格' if strict else '基础'}校验失败:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"{'严格' if strict else '基础结构'}校验通过: {beats_path}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or validate a local Vox Director project")
    parser.add_argument("project_dir", nargs="?", help="Existing project directory for --validate-only")
    parser.add_argument("--project")
    parser.add_argument("--root", default="out")
    parser.add_argument("--topic")
    parser.add_argument("--theme", default="newsprint-editorial", choices=sorted(ALLOWED_THEMES))
    parser.add_argument("--arc", default="hook_payoff", choices=sorted(ALLOWED_ARCS),
                        help="叙事弧线，见 references/narrative.md")
    parser.add_argument("--ending", default="hard_cut", choices=sorted(ALLOWED_ENDINGS))
    parser.add_argument("--duration", type=int, default=18,
                        help="目标成片秒数 10–75；约 ≤22→4 beat、≤32→6、≤42→8、≤52→10、更长→12")
    parser.add_argument("--voice", choices=["tts", "clone"], default="tts")
    parser.add_argument("--sample-path")
    parser.add_argument("--music", action="store_true")
    parser.add_argument("--detail", help="逗号分隔，给这些 beat 追加 detail 特写，如 b2,b3（会增加生成费用）")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.validate_only:
        if not args.project_dir:
            raise SystemExit("--validate-only 需要 project_dir")
        validate_existing(Path(args.project_dir).resolve(), strict=args.strict)
        return 0

    if not args.project:
        raise SystemExit("创建项目必须提供 --project")
    if not args.topic:
        raise SystemExit("创建项目必须提供 --topic")
    if args.voice == "clone" and not args.sample_path:
        raise SystemExit("--voice clone 时必须提供 --sample-path")
    if not PROJECT_RE.fullmatch(args.project):
        raise SystemExit("--project 必须是 1–40 位小写英文、数字、下划线或连字符，且以英文/数字开头")

    project_dir = create_project(args)
    print(f"已创建项目: {project_dir}")
    print(f"草稿文件: {project_dir / 'beats.json'}")
    print("下一步：替换占位符并通过严格校验后，才能进入付费生成阶段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

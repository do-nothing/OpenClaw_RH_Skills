#!/usr/bin/env python3
"""Shared helpers for explainer-studio stage scripts.

- script.md parser (YAML-subset front matter + ## bXX beats)
- explainer.json load/save, hashing and cascade invalidation
- aspect mapping and runninghub endpoint snapshot resolution
- ffmpeg/ffprobe discovery, duration probing, silence detection

Stdlib-only. Never calls a network API itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "openclaw-explainer-1"

LEAD_S = 0.20
TAIL_S = 0.45
SHOT_MIN_S = 4.0
SHOT_MAX_S = 15.0
SHOT_TARGET_S = 8.0
EST_SEC_PER_UNIT = 0.24
# chapter cards (silent block before a chapter's first beat)
CARD_S = 1.4
CHAPTER_LEAD_S = 0.9

# silencedetect
SILENCE_NOISE_DB = "-35dB"
SILENCE_MIN_D = 0.25
SENTENCE_PAUSE_S = 0.45
EDGE_TRIM_S = 0.10
SNAP_WINDOW_S = 1.2
SNAP_WINDOW_FALLBACK_S = 2.0

DUTIES = ("hook", "subject", "definition", "mechanism", "compare",
          "evidence", "analogy", "keyword")
STYLES = ("clean-diagram", "paper-collage", "swiss-infographic", "warm-editorial")
ASPECTS = {
    "16:9": {"image": "16:9 (Widescreen)", "video": 5, "width": 1280, "height": 720},
    "9:16": {"image": "9:16 (Portrait Widescreen)", "video": 4, "width": 720, "height": 1280},
    "1:1":  {"image": "1:1 (Square)", "video": 1, "width": 720, "height": 720},
    "4:3":  {"image": "4:3 (Standard)", "video": 3, "width": 960, "height": 720},
    "3:4":  {"image": "3:4 (Portrait Standard)", "video": 2, "width": 720, "height": 960},
}

ENDPOINT_KEYS = {
    "tts": "voice-clone-emo",
    "music": "music-yue2",
    "image": "image-gen-qwen",
    "image_edit": "image-edit-qwen",
    "video_first_frame": "i2v-minimax-h3-first-frame",
    "video_first_last_frame": "i2v-minimax-h3-first-last-frame",
}
MUSIC_ACCOMPANIMENT_NODE = "56"

# Chinese visual-field labels accepted in script.md beat bodies.
FIELD_DUTY = "视觉职责"
FIELD_SEE = "看到"
FIELD_TEXT = "文字"
FIELD_STEPS = "渐进"
FIELD_CONT = "连贯"
FIELD_AVOID = "禁忌"
KNOWN_FIELDS = (FIELD_DUTY, FIELD_SEE, FIELD_TEXT, FIELD_STEPS, FIELD_CONT, FIELD_AVOID)
CAMERA_WORDS = ("特写", "俯拍", "仰拍", "推镜", "拉镜", "慢镜头", "景深", "海报风",
                "航拍", "广角", "长焦", "运镜", "机位")
PLACEHOLDER_RE = re.compile(r"【请填写|TODO|待填写|REPLACE_WITH", re.IGNORECASE)
CJK_RE = re.compile(r"[一-鿿]")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass


# --------------------------------------------------------------------------- #
# paths / tools
# --------------------------------------------------------------------------- #
def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def runninghub_task_types() -> Path:
    p = Path(os.environ.get("RUNNINGHUB_TASK_TYPES", "")) if os.environ.get("RUNNINGHUB_TASK_TYPES") else None
    if p and p.exists():
        return p
    return skill_root().parent / "runninghub" / "config" / "task-types.json"


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    winget = (
        Path(os.environ.get("LOCALAPPDATA", r"C:\Users\lj110\AppData\Local"))
        / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / r"ffmpeg-9.0.1-full_build\bin" / f"{name}.exe"
    )
    if winget.exists():
        return str(winget)
    raise SystemExit(f"{name} not found on PATH or at {winget}")


def probe_duration(ffprobe: str, path: Path) -> float:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"ffprobe failed for {path}: {proc.stderr}")
    return float(proc.stdout.strip())


def detect_pauses(ffmpeg: str, audio: Path) -> list[dict]:
    """silencedetect pauses relative to the single voiceover file.

    Returns [{start,end,duration}], dropping edge silence inside EDGE_TRIM_S.
    """
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(audio),
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}:d={SILENCE_MIN_D}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # ffmpeg prints silencedetect lines on stderr.
    starts: list[float] = []
    pauses: list[dict] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?\d+\.?\d*)", line)
        if m:
            starts.append(float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*(-?\d+\.?\d*)\s*\|\s*silence_duration:\s*(\d+\.?\d*)", line)
        if m and starts:
            start = starts.pop(0)
            pauses.append({"start": round(start, 3), "end": round(float(m.group(1)), 3),
                           "duration": round(float(m.group(2)), 3)})
    return [p for p in pauses if p["start"] >= EDGE_TRIM_S]


# --------------------------------------------------------------------------- #
# front matter (small YAML subset)
# --------------------------------------------------------------------------- #
def _scalar(raw: str):
    v = raw.strip()
    if v in ("", "~", "null"):
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if (len(v) >= 2) and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _flow_map(raw: str) -> dict:
    body = raw.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    out: dict = {}
    for part in body.split(","):
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        out[k.strip()] = _scalar(v)
    return out


def parse_front_matter(text: str) -> tuple[dict, str]:
    text = text.lstrip("﻿")  # tolerate a UTF-8 BOM (PowerShell 5 adds one)
    if not text.startswith("---"):
        raise ValueError("script.md must start with a --- front matter block")
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("front matter is not closed with ---")
    fm: dict = {}
    i = 1
    while i < end:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", line)
        if not m:
            raise ValueError(f"bad front matter line: {line!r}")
        key, raw = m.group(1), m.group(2)
        if raw.strip():
            fm[key] = _scalar(raw)
            i += 1
            continue
        # block: nested mapping or list until dedent
        block: list[str] = []
        i += 1
        while i < end and (lines[i].startswith("  ") or not lines[i].strip()):
            block.append(lines[i])
            i += 1
        stripped = [b for b in block if b.strip()]
        if stripped and stripped[0].lstrip().startswith("-"):
            items = []
            for b in stripped:
                body = b.lstrip()[1:].strip()
                items.append(_flow_map(body) if body.startswith("{") else _scalar(body))
            fm[key] = items
        else:
            nested: dict = {}
            for b in stripped:
                bm = re.match(r"^([A-Za-z_][\w]*):\s*(.*)$", b.strip())
                if bm:
                    nested[bm.group(1)] = _scalar(bm.group(2))
            fm[key] = nested
    return fm, "\n".join(lines[end + 1:])


# --------------------------------------------------------------------------- #
# beat parsing
# --------------------------------------------------------------------------- #
def _split_text_items(raw: str) -> list[str]:
    parts = re.split(r"[/、，,]", raw)
    return [p.strip() for p in parts if p.strip()]


def count_units(text: str) -> int:
    """CJK chars + latin words + standalone numbers."""
    n = len(CJK_RE.findall(text))
    stripped = CJK_RE.sub(" ", text)
    n += len([t for t in re.split(r"[^\w'.%-]+", stripped) if t])
    return n


def parse_beats(body: str) -> tuple[list[dict], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    # Split at level-2 headings; content before the first one (e.g. an H1 title) is ignored.
    chunks: list[tuple[str, list[str]]] = []
    cur_head: str | None = None
    cur_lines: list[str] = []
    for line in body.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            if cur_head is not None:
                chunks.append((cur_head, cur_lines))
            cur_head, cur_lines = h.group(1), []
        elif re.match(r"^#\s+", line):
            continue
        elif cur_head is not None:
            cur_lines.append(line)
    if cur_head is not None:
        chunks.append((cur_head, cur_lines))

    beats: list[dict] = []
    for idx, (head, lines) in enumerate(chunks, start=1):
        hm = re.match(r"^(b\d{2})(?:\s+(.*))?$", head)
        if not hm:
            errors.append(f"beat 标题必须形如 b01：{head!r}")
            continue
        bid, btitle = hm.group(1), (hm.group(2) or "").strip()
        expected = f"b{idx:02d}"
        if bid != expected:
            errors.append(f"beat 编号必须连续：第 {idx} 个是 {bid}，应为 {expected}")

        # Narration = first paragraph: consecutive non-empty non-list lines.
        para: list[str] = []
        j = 0
        while j < len(lines) and not lines[j].strip():
            j += 1
        while j < len(lines):
            ln = lines[j]
            if not ln.strip():
                break
            if ln.lstrip().startswith(("-", "*")) or re.match(r"^\s*\d+[.、)]", ln):
                break
            para.append(ln.strip())
            j += 1
        narration = "".join(para).strip()
        if not narration:
            errors.append(f"{bid} 缺少旁白正文（标题后第一段纯文本）")

        fields: dict[str, object] = {}
        steps: list[str] = []
        while j < len(lines):
            ln = lines[j]
            bm = re.match(r"^\s*[-*]\s*([^:：]+)[:：]\s*(.*)$", ln)
            if bm:
                label = bm.group(1).strip()
                value = bm.group(2).strip()
                if label not in KNOWN_FIELDS:
                    errors.append(f"{bid} 未识别的视觉字段：{label}（允许：{'/'.join(KNOWN_FIELDS)}）")
                elif label == FIELD_STEPS:
                    if value:
                        steps.append(value)
                    # consume following indented numbered items
                    k = j + 1
                    while k < len(lines):
                        nxt = lines[k]
                        sm = re.match(r"^\s+(\d+)[.、)]\s*(.+)$", nxt)
                        if sm:
                            steps.append(sm.group(2).strip())
                            j = k
                            k += 1
                            continue
                        if not nxt.strip():
                            k += 1
                            continue
                        break
                    fields[label] = steps
                else:
                    fields[label] = value
            elif ln.strip():
                # loose numbered line outside a 渐进 block
                if re.match(r"^\s*\d+[.、)]", ln):
                    errors.append(f"{bid} 有序步骤必须写在「{FIELD_STEPS}」字段下")
                else:
                    warnings.append(f"{bid} 忽略无法解析的行：{ln.strip()[:40]}")
            j += 1

        duty = str(fields.get(FIELD_DUTY, "")).strip()
        see = str(fields.get(FIELD_SEE, "")).strip()
        if not duty:
            errors.append(f"{bid} 缺少必填字段「{FIELD_DUTY}」")
        elif duty not in DUTIES:
            errors.append(f"{bid} 视觉职责 {duty!r} 不在枚举内：{'/'.join(DUTIES)}")
        if not see:
            errors.append(f"{bid} 缺少必填字段「{FIELD_SEE}」")
        else:
            hit = [w for w in CAMERA_WORDS if w in see]
            if hit:
                warnings.append(f"{bid}「看到」里出现拍摄词汇 {hit}；景别/运镜留到阶段 3")
        if idx == 1 and duty and duty != "hook":
            errors.append("第一个 beat 的视觉职责必须是 hook")
        if idx == len(chunks) and duty and duty != "keyword":
            warnings.append(f"收尾 beat {bid} 职责建议为 keyword（当前 {duty}）")

        texts = _split_text_items(str(fields.get(FIELD_TEXT, "")))
        if len(texts) > 3:
            errors.append(f"{bid} 画面文字最多 3 项（当前 {len(texts)} 项）")
        for t in texts:
            if len(t) > 8:
                errors.append(f"{bid} 画面文字每项建议 ≤8 字：{t!r}（{len(t)} 字）")
        if steps:
            if not 2 <= len(steps) <= 3:
                errors.append(f"{bid} 渐进步骤必须 2–3 个（当前 {len(steps)}），超过 3 个请拆 beat")

        beats.append({
            "id": bid, "title": btitle, "narration": narration,
            "visual_duty": duty, "visual_see": see,
            "on_screen_text": texts,
            "progressive": steps,
            "continuity": str(fields.get(FIELD_CONT, "") or "").strip(),
            "avoid": str(fields.get(FIELD_AVOID, "") or "").strip(),
            "est_duration_s": round(count_units(narration) * EST_SEC_PER_UNIT, 2),
        })
    if not beats:
        errors.append("没有找到任何 ## bXX beat")
    return beats, errors, warnings


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# endpoint snapshot
# --------------------------------------------------------------------------- #
def endpoint_snapshot() -> dict:
    path = runninghub_task_types()
    if not path.exists():
        raise SystemExit(f"task-types.json not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {t["typeId"]: t for t in data["types"]}
    snap: dict = {}
    for key, type_id in ENDPOINT_KEYS.items():
        if type_id not in by_id:
            raise SystemExit(f"pool type {type_id} missing in {path}")
        entry = {"type": type_id, "workflowId": by_id[type_id]["workflowId"]}
        if key == "music":
            entry["accompanimentNodeId"] = MUSIC_ACCOMPANIMENT_NODE
        snap[key] = entry
    return snap


# --------------------------------------------------------------------------- #
# doc state
# --------------------------------------------------------------------------- #
def doc_path(project_dir: Path) -> Path:
    return project_dir / "explainer.json"


def load_doc(project_dir: Path) -> dict:
    p = doc_path(project_dir)
    if not p.exists():
        raise SystemExit(f"explainer.json not found: {p} — run sync_script.py first")
    return json.loads(p.read_text(encoding="utf-8"))


def save_doc(project_dir: Path, doc: dict) -> None:
    doc_path(project_dir).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shots_of(doc: dict, beat_id: str) -> list[dict]:
    return [s for s in doc.get("shots", []) if s["beat_id"] == beat_id]


# --------------------------------------------------------------------------- #
# grouped-TTS timeline (audio is the master timeline)
# --------------------------------------------------------------------------- #
def is_grouped(doc: dict) -> bool:
    """Grouped narration mode: voice_groups[] normalized segments exist and
    the project does not explicitly opt out with voice.group: beat."""
    if str(doc.get("voice", {}).get("group", "auto")) == "beat":
        return False
    groups = doc.get("voice_groups") or []
    return bool(groups) and all(
        b.get("vo_seg_start_s") is not None and b.get("vo_group_id")
        for b in doc["beats"])


def beat_timeline(doc: dict) -> dict:
    """Compute global timeline from normalized group segments.

    Returns {"total", "beats": {bid: {start, end, lead, vo_start, vo_end,
    vo_duration, group_id}}, "groups": [{id, start, duration, card}]}.
    Grouped mode only; raises if data is missing/inconsistent.
    """
    groups = doc.get("voice_groups") or []
    beat_map = {b["id"]: b for b in doc["beats"]}
    seen: list[str] = []
    t = 0.0
    entries: dict[str, dict] = {}
    group_out: list[dict] = []
    for g in groups:
        bids = list(g["beats"])
        if not bids:
            raise SystemExit(f"voice group {g.get('id')} has no beats")
        seen += bids
        gstart = t
        card = bool(g.get("card"))
        content_off = CARD_S if card else 0.0
        for i, bid in enumerate(bids):
            b = beat_map.get(bid)
            if b is None:
                raise SystemExit(f"voice group {g['id']} references missing beat {bid}")
            s = float(b["vo_seg_start_s"])
            e = float(b["vo_seg_end_s"])
            if i == 0:
                block_start = gstart + content_off
            else:
                block_start = gstart + s - LEAD_S
            if i + 1 < len(bids):
                nxt = float(beat_map[bids[i + 1]]["vo_seg_start_s"])
                block_end = gstart + nxt - LEAD_S
            else:
                block_end = gstart + float(g["seg_duration_s"])
            entries[bid] = {
                "start": round(block_start, 3),
                "end": round(block_end, 3),
                "lead": round(s - (block_start - gstart), 3),
                "vo_start": round(gstart + s, 3),
                "vo_end": round(gstart + e, 3),
                "vo_duration": round(e - s, 3),
                "group_id": g["id"],
            }
        gd = float(g["seg_duration_s"])
        group_out.append({"id": g["id"], "start": round(gstart, 3),
                          "duration": gd, "card": card})
        t += gd
    if seen != [b["id"] for b in doc["beats"]]:
        raise SystemExit(
            "voice_groups do not cover the beat list exactly "
            f"(groups={seen}, beats={[b['id'] for b in doc['beats']]})")
    return {"total": round(t, 3), "beats": entries, "groups": group_out}


def find_shot(doc: dict, shot_id: str) -> dict | None:
    for s in doc.get("shots", []):
        if s["id"] == shot_id:
            return s
    return None

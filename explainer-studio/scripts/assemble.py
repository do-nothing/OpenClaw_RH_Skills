#!/usr/bin/env python3
"""Stage 6: local ffmpeg/Pillow assembly.

Timeline truth:
- grouped narration (voice.group: auto, default): normalized group voice
  segments ARE the master timeline; every shot is exact-trimmed to its used
  duration; chapter cards sit on silence baked into the group segment.
- legacy per-beat narration: blocks are built from lead 0.20 + real vo + tail
  0.45; non-last shots trim exactly, the beat's last shot keeps its full
  integer-second source (slack lands at the beat tail).

Layers: clips concat -> sequential one-line Pillow captions (punctuation-split
phrases timed by speech weight, one line at a time, per-beat transparent qtrle
tracks overlaid in the final pass) -> voice/BGM mix -> chapter chip + top
progress overlay -> final.mp4.
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

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from explainer_common import (
    CARD_S, CHAPTER_LEAD_S, LEAD_S, beat_timeline, is_grouped, load_doc,
)

FPS = 24
VO_BOOST = 1.35
BGM_BASE = 0.45
BGM_DUCK = 0.20
BGM_FLAT = 0.22
SS = 2
FONT_RATIO = 0.048
WIDTH_RATIO = 0.90          # hard ceiling: no single caption may exceed this
CAP_TARGET_RATIO = 0.52     # preferred: split a clause further when wider
BOTTOM_RATIO = 0.075
OUTLINE_RATIO = 0.08
CAP_MIN_S = 0.75            # shortest time one caption line stays on screen
CAP_BREAK_AFTER = frozenset("，。！？、；：,;:.!?")
SENT_END = frozenset("。！？.!?")   # hard boundaries anti-fragment never crosses
CAP_MERGE_WEIGHT = 5.0      # clauses this short (speech weight) absorb the next
_WORD_RE = re.compile(r"[A-Za-z0-9]+|\s+|[^\sA-Za-z0-9]")
_PROBE = ImageDraw.Draw(Image.new("RGB", (8, 8)))
CHIP_COLORS = ("0xF26B38", "0x2A9D8F", "0xE9C46A", "0x457B9D")
FONT_SRC = r"C:\Windows\Fonts\simhei.ttf"

WINGET_BIN = Path(
    os.environ.get("LOCALAPPDATA", r"C:\Users\lj110\AppData\Local")
) / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin"


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    cand = WINGET_BIN / f"{name}.exe"
    if cand.exists():
        return str(cand)
    raise SystemExit(f"{name} not found on PATH or at {cand}")


def probe_duration(ffprobe: str, path: Path) -> float:
    p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit(f"ffprobe failed for {path}: {p.stderr}")
    return float(p.stdout.strip())


def _font(size: int):
    return ImageFont.truetype(FONT_SRC, size)


def _tw(text, font) -> float:
    return _PROBE.textlength(text, font=font)


def split_captions(text: str, font, max_w: float, target_w: float) -> list[str]:
    """Split one beat narration into SHORT sequential one-line caption pieces.

    Pipeline:
    1. Forced cut after every break punctuation. Sentence-final marks
       (。！？.!?) are HARD boundaries; the rest (，、；：) are soft.
    2. Anti-fragment: a soft-ending clause whose speech weight <=
       CAP_MERGE_WEIGHT greedily absorbs following clauses (boundary
       punctuation stays inside the merged line) until it grows past the
       threshold, reaches a hard boundary, or would exceed target_w.
    3. Width fallback: still-too-wide lines split at balanced token
       boundaries (CJK per character, latin words/numbers atomic).
    4. Trailing break punctuation is stripped from every final piece
       (internal punctuation is kept).
    """
    text = " ".join(str(text).split())

    # 1) forced punctuation cuts
    clauses: list[list] = []
    cur = ""
    for ch in text:
        cur += ch
        if ch in CAP_BREAK_AFTER:
            clauses.append([cur, ch in SENT_END])
            cur = ""
    if cur:
        clauses.append([cur, False])

    # 2) anti-fragment merge (forward-only, never across hard boundaries)
    merged: list[list] = []
    for clause, is_hard in clauses:
        if (merged and not merged[-1][1]
                and piece_weight(merged[-1][0]) <= CAP_MERGE_WEIGHT
                and _tw(merged[-1][0] + clause, font) <= target_w):
            merged[-1][0] += clause
            merged[-1][1] = is_hard
        else:
            merged.append([clause, is_hard])

    # 3) width fallback + 4) strip trailing break punctuation
    _strip = "".join(CAP_BREAK_AFTER)
    pieces: list[str] = []
    for clause, _ in merged:
        if _tw(clause, font) <= target_w:
            lines = [clause]
        else:
            lines = []
            line = ""
            for tok in _WORD_RE.findall(clause):
                if _tw(line + tok, font) <= target_w or not line:
                    line += tok
                    continue
                lines.append(line)
                line = tok
                # single token (long latin word) wider than hard ceiling:
                # break it character by character
                while _tw(line, font) > max_w and len(line) > 1:
                    cut = 1
                    while cut < len(line) and _tw(line[:cut + 1], font) <= max_w:
                        cut += 1
                    lines.append(line[:cut])
                    line = line[cut:]
            lines.append(line)
        for ln in lines:
            ln = ln.rstrip(_strip)
            if ln:
                pieces.append(ln)
    return pieces


def piece_weight(piece: str) -> float:
    """Speech-length proxy: one CJK char ~= 1, latin/digit ~= 0.55, no punct."""
    return sum(1.0 for ch in piece if "一" <= ch <= "鿿") + \
        sum(0.55 for ch in piece if ch.isascii() and ch.isalnum())


def allocate_piece_frames(weights: list[float], avail_f: int,
                          fps: int, min_s: float = CAP_MIN_S) -> list[int]:
    """Distribute an integer number of frames over pieces by speech weight.

    Cumulative boundaries land on weighted positions; each piece gets at least
    one frame, and >= min_s frames when the window allows it.
    """
    n = len(weights)
    min_f = max(1, round(min_s * fps))
    if n == 1 or n * min_f > avail_f:
        # window too tight for the min rule: proportional split, min 1 frame
        total = sum(weights) or 1.0
        raw = [avail_f * w / total for w in weights]
        frames = [max(1, int(round(x))) for x in raw]
        # largest-remainder correction so the sum is exact
        diff = avail_f - sum(frames)
        order = sorted(range(n), key=lambda i: raw[i] - int(raw[i]),
                       reverse=(diff > 0))
        k = 0
        while diff != 0 and order:
            i = order[k % n]
            if diff > 0:
                frames[i] += 1; diff -= 1
            elif frames[i] > 1:
                frames[i] -= 1; diff += 1
            k += 1
        return frames

    total = sum(weights) or 1.0
    bounds = [int(round(avail_f * sum(weights[:i + 1]) / total))
              for i in range(n)]
    frames: list[int] = []
    prev = 0
    for i, end in enumerate(bounds):
        start = prev
        if i < n - 1 and end - start < min_f:
            end = min(avail_f - (n - 1 - i) * min_f, start + min_f)
        if i < n - 1 and end <= start:
            end = start + 1
        frames.append(max(1, end - start))
        prev = end
    frames[-1] = avail_f - sum(frames[:-1])
    return frames


def render_caption_line(text: str, path: Path, w: int, h: int):
    """Render ONE caption line centered near the bottom (transparent bg)."""
    cw, ch = w * SS, h * SS
    size = int(h * FONT_RATIO) * SS
    font = _font(size)
    margin = int(h * BOTTOM_RATIO) * SS
    ow = max(2, round(size * OUTLINE_RATIO))
    wd = _tw(text, font)
    ascent, descent = font.getmetrics()
    x = round((cw - wd) / 2)
    y = ch - margin - ascent - descent
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.text((x + 2 * SS, y + 3 * SS), text, font=font, fill=(0, 0, 0, 175),
            stroke_width=ow, stroke_fill=(0, 0, 0, 175))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4 * SS)))
    d = ImageDraw.Draw(canvas)
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255),
           stroke_width=ow, stroke_fill=(26, 20, 16, 235))
    canvas.resize((w, h), Image.LANCZOS).save(path)


def render_beat_caption_track(ffmpeg: str, bid: str, pieces: list[str],
                              piece_frames: list[int], lead_f: int,
                              tail_f: int, w: int, h: int,
                              seg_dir: Path, project_dir: Path) -> Path:
    """One transparent qtrle clip covering a beat block:

    transparent lead | line 1..k shown sequentially | transparent tail.
    Frame counts are integers, so k clips overlay with exact frame timing.
    """
    pngs: list[Path] = []
    for i, text in enumerate(pieces):
        p = seg_dir / f"cap_{bid}_{i:02d}.png"
        render_caption_line(text, p, w, h)
        pngs.append(p)

    # Gap frames come from a transparent PNG, NOT a lavfi color source:
    # color=c=black@0.0 frames lose their alpha on the way through qtrle and
    # come out opaque black (pieces via PNG keep theirs).
    blank = seg_dir / "cap_blank.png"
    if not blank.exists():
        Image.new("RGBA", (w, h), (0, 0, 0, 0)).save(blank)

    inputs = ["-loop", "1", "-i", str(blank)]
    for p in pngs:
        inputs += ["-loop", "1", "-i", str(p)]

    # EVERY pad fed to the concat filter must be trim-bounded: -loop image
    # inputs are infinite, and concat waits for each pad's EOF before moving
    # on (an untrimmed pad deadlocks the whole graph).
    if lead_f > 0:
        flt = [f"[0:v]format=rgba,fps={FPS},split=2[g0r][g1r]",
               f"[g0r]trim=0:{lead_f / FPS:.6f},setpts=PTS-STARTPTS[g0]"]
        tail_src = "[g1r]"
        seq = ["[g0]"]
    else:
        flt = [f"[0:v]format=rgba,fps={FPS},setpts=PTS-STARTPTS[g1r]"]
        tail_src = "[g1r]"
        seq = []
    for j, nf in enumerate(piece_frames):
        flt.append(f"[{j + 1}:v]format=rgba,fps={FPS},"
                   f"trim=0:{nf / FPS:.6f},setpts=PTS-STARTPTS[p{j}]")
        seq.append(f"[p{j}]")
    if tail_f > 0:
        flt.append(f"{tail_src}trim=0:{tail_f / FPS:.6f},"
                   f"setpts=PTS-STARTPTS[g1]")
        seq.append("[g1]")
    flt.append("".join(seq)
               + f"concat=n={len(seq)}:v=1:a=0,format=rgba[v]")

    mov = seg_dir / f"caption_{bid}.mov"
    run([ffmpeg, "-y", *inputs, "-filter_complex", ";".join(flt),
         "-map", "[v]", "-c:v", "qtrle", "-pix_fmt", "rgba",
         "-an", str(mov)], project_dir)
    return mov


def render_chip(title: str, idx: int, total_ch: int, path: Path):
    font = _font(30)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    label = f"{idx}/{total_ch}  {title}"
    tw = probe.textlength(label, font=font)
    pw, ph = int(tw + 48), 64
    img = Image.new("RGBA", (pw * SS, ph * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, pw * SS - 1, ph * SS - 1], radius=int(16 * SS),
                        fill=(18, 24, 38, 205))
    d.text((24 * SS, int(13 * SS)), label, font=_font(30 * SS), fill=(255, 255, 255, 255))
    img.resize((pw, ph), Image.LANCZOS).save(path)


def render_card(title: str, idx: int, total_ch: int, path: Path, w: int, h: int):
    img = Image.new("RGB", (w, h), (20, 33, 61))
    d = ImageDraw.Draw(img)
    f_small = _font(int(h * 0.045))
    f_big = _font(int(h * 0.09))
    for txt, font, y in ((f"第 {idx} 章 / {total_ch}", f_small, h * 0.40),
                         (title, f_big, h * 0.50)):
        tw = d.textlength(txt, font=font)
        d.text(((w - tw) / 2, y), txt, font=font, fill=(255, 255, 255))
    bar = int(h * 0.012)
    d.rectangle([w * 0.42, h * 0.36, w * 0.58, h * 0.36 + bar], fill=(242, 107, 56))
    img.save(path)


def run(cmd: list[str], cwd: Path):
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stdout); print(p.stderr)
        raise SystemExit(f"ffmpeg failed ({p.returncode}): {' '.join(cmd[:6])} ...")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 6 local assembly")
    ap.add_argument("project_dir")
    args = ap.parse_args(argv or sys.argv[1:])
    project_dir = Path(args.project_dir).resolve()
    doc = load_doc(project_dir)
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    w = int(doc["aspect_map"]["width"]); h = int(doc["aspect_map"]["height"])
    seg_dir = project_dir / "_seg"; seg_dir.mkdir(exist_ok=True)

    beats = {b["id"]: b for b in doc["beats"]}
    shots_by_beat: dict[str, list[dict]] = {}
    for s in doc["shots"]:
        shots_by_beat.setdefault(s["beat_id"], []).append(s)
    for bid in beats:
        shots_by_beat.setdefault(bid, [])
        if not shots_by_beat[bid]:
            raise SystemExit(f"{bid} has no planned shots — run plan_shots.py")
        shots_by_beat[bid].sort(key=lambda s: s["ord"])

    chapters = doc.get("chapters") or []
    first_of_chapter = {c["from_beat"]: c for c in chapters}
    grouped = is_grouped(doc)
    tl = beat_timeline(doc) if grouped else None

    # ---- build ordered visual blocks + beat starts (cards shift timeline) ----
    blocks: list[dict] = []   # {kind: shot/card, ...}
    beat_starts: dict[str, float] = {}
    beat_leads: dict[str, float] = {}
    cursor = 0.0
    for b in doc["beats"]:
        if doc.get("chapter_cards") and b["id"] in first_of_chapter:
            blocks.append({"kind": "card", "chapter": first_of_chapter[b["id"]]})
            cursor += CARD_S
            beat_leads[b["id"]] = CHAPTER_LEAD_S
        else:
            beat_leads[b["id"]] = LEAD_S
        beat_starts[b["id"]] = cursor
        sh = shots_by_beat[b["id"]]
        for i, s in enumerate(sh):
            if grouped:
                # audio is master: all shots exact-trimmed
                dur = float(s["used_duration_s"])
            else:
                dur = float(s["used_duration_s"]) if i < len(sh) - 1 \
                    else float(s["submit_duration_s"])
            blocks.append({"kind": "shot", "shot": s, "dur": dur, "beat": b})
            cursor += dur
    total = cursor

    if grouped:
        if abs(total - tl["total"]) > 0.12:
            raise SystemExit(
                f"visual blocks {total:.3f}s != voice timeline {tl['total']:.3f}s; "
                "rerun plan_shots.py")
        for bid, ent in tl["beats"].items():
            if abs(beat_starts[bid] - ent["start"]) > 0.08:
                raise SystemExit(
                    f"{bid} block start {beat_starts[bid]:.3f} != audio timeline "
                    f"{ent['start']:.3f}; rerun plan_shots.py")
            if abs(beat_leads[bid] - ent["lead"]) > 0.08:
                raise SystemExit(
                    f"{bid} lead {beat_leads[bid]:.3f} != audio timeline "
                    f"{ent['lead']:.3f}")
        print("Voice: grouped takes (concatenated normalized segments)")
    else:
        print("Voice: per-beat TTS (adelay placement)")

    # chapter ranges in global time
    ch_ranges: list[dict] = []
    for c in chapters:
        start = beat_starts[c["from_beat"]] - (CARD_S if doc.get("chapter_cards") else 0)
        start = max(0.0, start)
        ch_ranges.append({"id": c["id"], "title": c["title"], "start": start, "end": total})
    for i, c in enumerate(ch_ranges):
        if i + 1 < len(ch_ranges):
            c["end"] = ch_ranges[i + 1]["start"]

    print("Timeline:")
    for b in doc["beats"]:
        sh = shots_by_beat[b["id"]]
        if grouped:
            span = sum(float(s["used_duration_s"]) for s in sh)
        else:
            span = (sum(float(s["used_duration_s"]) for s in sh[:-1])
                    + float(sh[-1]["submit_duration_s"]))
        print(f"  {b['id']}: start={beat_starts[b['id']]:.2f}s lead={beat_leads[b['id']]:.2f}s "
              f"block={span:.2f}s shots={len(sh)}")
    print(f"Total: {total:.2f}s")

    # ---- render captions + segments ----
    seg_paths: list[Path] = []
    for blk in blocks:
        if blk["kind"] == "card":
            c = blk["chapter"]
            idx = next(i for i, x in enumerate(chapters, 1) if x["id"] == c["id"])
            png = seg_dir / f"card_{c['id']}.png"
            mov = seg_dir / f"card_{c['id']}.mp4"
            render_card(c["title"], idx, len(chapters), png, w, h)
            run([ffmpeg, "-y", "-loop", "1", "-i", str(png), "-t", f"{CARD_S:.3f}",
                 "-r", str(FPS), "-an",
                 "-vf", f"scale={w}:{h},fps={FPS},setsar=1,format=yuv420p",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-pix_fmt", "yuv420p", str(mov)], project_dir)
            seg_paths.append(mov)
            continue
        s, b = blk["shot"], blk["beat"]
        seg = seg_dir / f"seg_{s['id']}.mp4"
        clip = Path(str(s["clip_path"]))
        if not clip.exists():
            raise SystemExit(f"missing clip {s['id']}: {clip}")
        if grouped:
            clip_dur = probe_duration(ffprobe, clip)
            if blk["dur"] > clip_dur + 0.05:
                raise SystemExit(
                    f"{s['id']} needs {blk['dur']:.2f}s but its clip is only "
                    f"{clip_dur:.2f}s; rerun plan_shots.py / regenerate this clip")
        # captions are overlaid later as ONE timed track (sequential one-liners)
        fc = (f"[0:v]trim=duration={blk['dur']:.3f},setpts=PTS-STARTPTS,"
              f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},"
              f"fps={FPS},setsar=1,format=yuv420p[v]")
        run([ffmpeg, "-y", "-i", str(clip), "-an",
             "-filter_complex", fc, "-map", "[v]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", str(seg)], project_dir)
        seg_paths.append(seg)

    concat_list = seg_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in seg_paths),
                           encoding="utf-8")
    video_caps = seg_dir / "video_caps.mp4"
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(video_caps)], project_dir)

    # ---- voice + BGM ----
    inputs: list[str] = []
    fc: list[str] = []
    duck_windows: list[str] = []
    if grouped:
        # one normalized segment per voice group, already on the master timeline
        seg_files: list[Path] = []
        for g in doc["voice_groups"]:
            sp = Path(str(g["seg_path"]))
            if not sp.exists():
                raise SystemExit(f"missing voice segment {g['id']}: {sp}")
            seg_files.append(sp)
            inputs += ["-i", str(sp)]
        n = len(seg_files)
        voice_labels = []
        for i, sp in enumerate(seg_files):
            lab = f"v{i}"
            fc.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"volume={VO_BOOST}[{lab}]")
            voice_labels.append(f"[{lab}]")
        fc.append("".join(voice_labels)
                  + f"concat=n={n}:v=0:a=1[voice]")
        for bid, ent in tl["beats"].items():
            duck_windows.append(
                f"between(t,{max(0.0, ent['vo_start'] - 0.12):.3f},"
                f"{min(total, ent['vo_end'] + 0.20):.3f})")
    else:
        vo_specs = []
        for b in doc["beats"]:
            vo = Path(str(b["vo_path"]))
            if not vo.exists():
                raise SystemExit(f"missing narration {b['id']}: {vo}")
            vo_specs.append((b, vo))
            inputs += ["-i", str(vo)]
        n = len(vo_specs)
        voice_labels = []
        for i, (b, vo) in enumerate(vo_specs):
            vo_start = beat_starts[b["id"]] + beat_leads[b["id"]]
            vo_dur = probe_duration(ffprobe, vo)
            delay = int(round(vo_start * 1000))
            fc.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"adelay={delay}|{delay},volume={VO_BOOST}[v{i}]")
            voice_labels.append(f"[v{i}]")
            duck_windows.append(
                f"between(t,{max(0.0, vo_start - 0.12):.3f},"
                f"{min(total, vo_start + vo_dur + 0.20):.3f})")
        fc.append("".join(voice_labels)
                  + f"amix=inputs={n}:normalize=0:duration=longest[voice]")

    bgm_path = Path(str(doc.get("music", {}).get("path") or ""))
    has_bgm = bgm_path.exists()
    if doc.get("music", {}).get("enabled") and not has_bgm:
        print("WARNING: music enabled but no BGM file; mixing voice only")
    if has_bgm:
        inputs += ["-stream_loop", "-1", "-i", str(bgm_path)]

    if has_bgm:
        if doc.get("music", {}).get("duck", True) is False:
            # Flat bed: no swell in the gaps between narration segments.
            fc.append(
                f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"atrim=0:{total:.3f},asetpts=N/SR/TB,volume={BGM_FLAT}[ducked]")
        else:
            fc.append(
                f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"atrim=0:{total:.3f},asetpts=N/SR/TB,volume={BGM_BASE},"
                f"volume={BGM_DUCK}:enable='{'+'.join(duck_windows)}'[ducked]")
        fc.append("[ducked][voice]amix=inputs=2:normalize=0:duration=longest,"
                  f"apad=whole_dur={total:.3f},atrim=0:{total:.3f},"
                  "aresample=48000,asetpts=N/SR/TB[aout]")
    else:
        fc.append(f"[voice]apad=whole_dur={total:.3f},atrim=0:{total:.3f},"
                  "aresample=48000,asetpts=N/SR/TB[aout]")
    mix = seg_dir / "mix.m4a"
    run([ffmpeg, "-y", *inputs, "-filter_complex", ";".join(fc),
         "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", str(mix)], project_dir)

    video_with_audio = seg_dir / "video_full.mp4"
    run([ffmpeg, "-y", "-i", str(video_caps), "-i", str(mix),
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         str(video_with_audio)], project_dir)

    # ---- sequential one-line caption tracks (one transparent mov / beat) ----
    for stale in seg_dir.glob("cap_*.png"):
        stale.unlink()
    for stale in seg_dir.glob("caption_*.mov"):
        stale.unlink()
    cap_font = _font(int(h * FONT_RATIO))
    cap_max_w = int(w * WIDTH_RATIO)
    cap_target_w = int(w * CAP_TARGET_RATIO)
    bid_order = [b["id"] for b in doc["beats"]]
    caption_movs: list[tuple[Path, float]] = []
    for i, b in enumerate(doc["beats"]):
        bid = b["id"]
        block_start = beat_starts[bid]
        block_end = beat_starts[bid_order[i + 1]] if i + 1 < len(bid_order) \
            else total
        if grouped:
            ent = tl["beats"][bid]
            vo_start, vo_end = float(ent["vo_start"]), float(ent["vo_end"])
        else:
            vo_start = block_start + beat_leads[bid]
            vo_end = min(block_end, vo_start + float(b["vo_duration_s"]))
        pieces = split_captions(b["narration"], cap_font,
                                cap_max_w, cap_target_w)
        over = [p for p in pieces if _tw(p, cap_font) > cap_max_w]
        if over:
            raise SystemExit(f"{bid}: caption wider than frame: {over}")
        bs_f, be_f = round(block_start * FPS), round(block_end * FPS)
        vs_f, ve_f = round(vo_start * FPS), round(vo_end * FPS)
        lead_f = max(0, vs_f - bs_f)
        avail = max(1, ve_f - vs_f)
        pf = allocate_piece_frames([piece_weight(p) for p in pieces],
                                   avail, FPS)
        tail_f = max(0, be_f - bs_f - lead_f - sum(pf))
        mov = render_beat_caption_track(
            ffmpeg, bid, pieces, pf, lead_f, tail_f, w, h,
            seg_dir, project_dir)
        caption_movs.append((mov, block_start))
        print(f"  {bid} captions: {len(pieces)} one-line piece(s)")

    def caption_chain(base_label: str, first_input_idx: int):
        """ffmpeg overlay chain for all beat caption movs.

        Returns (last_label_bare, extra_cli_inputs, filter_lines).
        """
        extra: list[str] = []
        lines: list[str] = []
        prev = base_label  # bare pad name, e.g. "0:v"
        last = base_label
        for j, (_m, start) in enumerate(caption_movs):
            idx = first_input_idx + j
            inl, outl = f"cs{j}", f"cap{j}"
            lines.append(f"[{idx}:v]setpts=PTS+{start:.3f}/TB[{inl}]")
            lines.append(
                f"[{prev}][{inl}]overlay=x=0:y=0:eof_action=pass:"
                f"repeatlast=0:format=auto[{outl}]")
            extra += ["-i", str(caption_movs[j][0])]
            prev = outl
            last = outl
        return last, extra, lines

    # ---- chapter chips + progress bar (final pass, re-encode video) ----
    if chapters:
        chip_inputs: list[str] = []
        chip_movs: list[tuple[Path, float, float]] = []
        for i, c in enumerate(ch_ranges, start=1):
            png = seg_dir / f"chip_{c['id']}.png"
            mov = seg_dir / f"chip_{c['id']}.mov"
            render_chip(c["title"], i, len(ch_ranges), png)
            # chip starts with the chapter's first BEAT content (after any card),
            # not with the full-screen chapter card
            chip_start = beat_starts[chapters[i - 1]["from_beat"]]
            dur = max(0.8, min(c["end"], chip_start + 12.0) - chip_start)
            fade_out_start = max(0.1, dur - 0.35)
            run([ffmpeg, "-y", "-loop", "1", "-i", str(png),
                 "-vf", f"fade=t=in:st=0:d=0.25:alpha=1,"
                        f"fade=t=out:st={fade_out_start:.2f}:d=0.35:alpha=1,"
                        f"format=yuva420p,fps={FPS}",
                 "-t", f"{dur:.3f}", "-c:v", "qtrle", "-an", str(mov)], project_dir)
            chip_movs.append((mov, chip_start, dur))
            chip_inputs += ["-i", str(mov)]

        bar_h = max(6, round(h * 0.01))
        cap_base_idx = 1 + len(ch_ranges) + len(chip_movs)
        cap_last, cap_inputs, cap_lines = caption_chain("0:v", cap_base_idx)
        filters = cap_lines + [
            f"[{cap_last}]drawbox=x=0:y=0:w=iw:h={bar_h}:"
            "color=black@0.25:t=fill[base]"]
        labels = ["base"]
        # Chapter fill segments. drawbox w/x are evaluated once at init in
        # ffmpeg 9 (t=NaN), so a time-varying drawbox width renders static;
        # instead slide a static per-chapter color strip in via overlay x,
        # which IS re-evaluated per frame.
        bounds = [round(ch_ranges[i]["start"] / total * w)
                  for i in range(len(ch_ranges))] + [w]
        seg_inputs: list[str] = []
        for i, c in enumerate(ch_ranges):
            color = CHIP_COLORS[i % len(CHIP_COLORS)]
            rgb = tuple(int(color[j:j + 2], 16) for j in (2, 4, 6))
            x0, x1 = bounds[i], bounds[i + 1]
            sw = max(1, x1 - x0 + 1)  # +1px overlap hides hairline seams
            seg_png = seg_dir / f"barseg_{c['id']}.png"
            Image.new("RGBA", (sw, bar_h), rgb + (242,)).save(seg_png)
            in_idx = 1 + len(seg_inputs) // 2
            seg_inputs += ["-i", str(seg_png)]
            prev = labels[-1]
            lab = f"bar{i}"
            x_expr = (f"{x0 - sw}+min({sw},max(0,"
                      f"(t-{c['start']:.5f})*{w:.5f}/{total:.5f}))")
            filters.append(
                f"[{prev}][{in_idx}:v]overlay=x='{x_expr}':y=0:"
                f"enable='gte(t,{c['start']:.5f})'[{lab}]")
            labels.append(lab)
        for j, (_m, start, dur) in enumerate(chip_movs):
            prev = labels[-1]
            lab = f"chip{j}"
            in_idx = len(ch_ranges) + 1 + j
            # overlay aligns secondary PTS to the MAIN timeline, so shift the
            # short chip clip to its chapter start; otherwise chapters >1 show
            # the EOF-repeated faded-out last frame for their whole window.
            filters.append(f"[{in_idx}:v]setpts=PTS+{start:.3f}/TB[ch{j}]")
            filters.append(
                f"[{prev}][ch{j}]overlay=36:{bar_h + 12}:"
                f"enable='between(t,{start:.3f},{start + dur:.3f})'[{lab}]")
            labels.append(lab)
        filters[-1] = filters[-1].replace(f"[{labels[-1]}]", "[vout]")
        run([ffmpeg, "-y", "-i", str(video_with_audio), *seg_inputs,
             *chip_inputs, *cap_inputs,
             "-filter_complex", ";".join(filters),
             "-map", "[vout]", "-map", "0:a:0",
             "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-movflags", "+faststart", str(project_dir / "final.mp4")], project_dir)
    else:
        # per-segment frame rounding in the concat-copy video can drift a few
        # frames past the audio master; hard-trim both streams to total
        cap_last, cap_inputs, cap_lines = caption_chain("0:v", 1)
        cap_lines[-1] = cap_lines[-1].replace(f"[{cap_last}]", "[vout]")
        run([ffmpeg, "-y", "-i", str(video_with_audio), *cap_inputs,
             "-filter_complex", ";".join(cap_lines),
             "-map", "[vout]", "-map", "0:a:0",
             "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium",
             "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-movflags", "+faststart", str(project_dir / "final.mp4")], project_dir)

    doc["status"] = "assembled"
    from explainer_common import save_doc
    save_doc(project_dir, doc)
    print(f"\nFinal: {project_dir / 'final.mp4'} ({total:.2f}s, {w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

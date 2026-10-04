#!/usr/bin/env python3
"""Stage 6: local ffmpeg/Pillow assembly.

Timeline truth:
- grouped narration (voice.group: auto, default): normalized group voice
  segments ARE the master timeline; every shot is exact-trimmed to its used
  duration; chapter cards sit on silence baked into the group segment.
- legacy per-beat narration: blocks are built from lead 0.20 + real vo + tail
  0.45; non-last shots trim exactly, the beat's last shot keeps its full
  integer-second source (slack lands at the beat tail).

Layers: clips -> verbatim Pillow captions (one per beat) -> concat -> voice/BGM
mix -> chapter chip + top progress overlay (final pass) -> final.mp4.
"""

from __future__ import annotations

import argparse
import json
import os
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
FONT_RATIO = 0.045
WIDTH_RATIO = 0.90
LINE_HEIGHT = 1.15
BOTTOM_RATIO = 0.06
OUTLINE_RATIO = 0.08
BREAK_AFTER = "，、；：,;:"
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


def wrap_cjk(text, font, max_w):
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    text = " ".join(str(text).split())
    if probe.textlength(text, font=font) <= max_w:
        return [text]
    phrases, cur = [], ""
    for ch in text:
        cur += ch
        if ch in BREAK_AFTER:
            phrases.append(cur); cur = ""
    if cur:
        phrases.append(cur)
    lines, line = [], ""
    for ph in phrases:
        if probe.textlength(ph, font=font) > max_w:
            if line:
                lines.append(line); line = ""
            for ch in ph:
                if line and probe.textlength(line, font=font) + probe.textlength(ch, font=font) > max_w:
                    lines.append(line); line = ch
                else:
                    line += ch
            continue
        if line and probe.textlength(line + ph, font=font) > max_w:
            lines.append(line); line = ph
        else:
            line += ph
    if line:
        lines.append(line)
    return lines


def render_caption(text, path: Path, w: int, h: int):
    cw, ch = w * SS, h * SS
    size = int(h * FONT_RATIO) * SS
    font = _font(size)
    max_w = int(w * WIDTH_RATIO) * SS
    lines = wrap_cjk(text, font, max_w)
    ascent, descent = font.getmetrics()
    lh = int(size * LINE_HEIGHT)
    margin = int(h * BOTTOM_RATIO) * SS
    ow = max(2, round(size * OUTLINE_RATIO))
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    widths = [probe.textlength(ln, font=font) for ln in lines]
    block_h = ascent + descent + lh * (len(lines) - 1)
    y0 = ch - margin - block_h
    pos = [(round((cw - wd) / 2), y0 + i * lh) for i, wd in enumerate(widths)]
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for (x, y), ln in zip(pos, lines):
        sd.text((x + 2 * SS, y + 3 * SS), ln, font=font, fill=(0, 0, 0, 175),
                stroke_width=ow, stroke_fill=(0, 0, 0, 175))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4 * SS)))
    d = ImageDraw.Draw(canvas)
    for (x, y), ln in zip(pos, lines):
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=ow, stroke_fill=(26, 20, 16, 235))
    canvas.resize((w, h), Image.LANCZOS).save(path)
    return len(lines)


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
        cap = seg_dir / f"cap_{b['id']}.png"
        if not cap.exists():
            n = render_caption(b["narration"], cap, w, h)
            print(f"  {b['id']} caption {n} line(s)")
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
        fc = (f"[0:v]trim=duration={blk['dur']:.3f},setpts=PTS-STARTPTS,"
              f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},"
              f"fps={FPS},setsar=1,format=yuv420p[bg];"
              f"[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]")
        run([ffmpeg, "-y", "-i", str(clip), "-i", str(cap), "-an",
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
        filters = [
            f"[0:v]drawbox=x=0:y=0:w=iw:h={bar_h}:color=black@0.25:t=fill[base]"]
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
             *chip_inputs, "-filter_complex", ";".join(filters),
             "-map", "[vout]", "-map", "0:a:0",
             "-t", f"{total:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-movflags", "+faststart", str(project_dir / "final.mp4")], project_dir)
    else:
        # per-segment frame rounding in the concat-copy video can drift a few
        # frames past the audio master; hard-trim both streams to total
        run([ffmpeg, "-y", "-i", str(video_with_audio),
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

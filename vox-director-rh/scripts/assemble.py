#!/usr/bin/env python3
"""Assemble the Vox MVP final video locally with ffmpeg.

Single source of truth for timing: each shot's length is derived from its actual
narration file duration (lead-in + narration + tail), NOT from beats.json dur_s.
That one computed length drives video trim, narration offset and BGM ducking, so
audio and picture can never drift apart.

Pipeline (all local, no API cost):
1. ffprobe each narration; shot_dur = LEAD + vo_dur + TAIL (clamped to <=8s, the
   fixed source-clip length). Trim/normalize each source clip, burn the verbatim
   Chinese narration as a wrapped subtitle.
2. Concat the segments into a video-only track.
3. Place each narration at its shot start + LEAD; duck one trimmed BGM bed under
   it with deterministic time-window volume envelopes (no sidechaincompress).
4. Mux into final.mp4.
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

from new_project import beat_groups

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

WINGET_BIN = Path(
    os.environ.get("LOCALAPPDATA", r"C:\Users\lj110\AppData\Local")
) / r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin"
FONT_SRC = r"C:\Windows\Fonts\simhei.ttf"
WIDTH, HEIGHT, FPS = 1280, 720, 24
SOURCE_CLIP_S = 8.0          # H3 clips are requested with durationSeconds=8
LEAD_S = 0.20                # silence/visual lead before each narration starts
TAIL_S = 0.45                # tail after each narration ends (last shot too)
VO_BOOST = 1.35
BGM_BASE = 0.45
BGM_DUCK = 0.20
# Caption look mirrors upstream Vox Director (text_overlay.py 'white' style):
# small white glyphs + dark keyline + Gaussian soft shadow, NO background band.
# Rendered with Pillow as a full-frame transparent PNG then overlaid: drawtext's
# built-in font line gap made two CJK lines look like a blank row, whereas Pillow
# places each line at an explicit pixel line height. Supersampled for crisp strokes.
CAPTION_SS = 2
CAPTION_FONT_RATIO = 0.045   # font size = short edge * 0.045 (32px @720p)
CAPTION_WIDTH_RATIO = 0.90   # wrap only past 90% of frame width (CJK is edge-aligned)
CAPTION_LINE_HEIGHT = 1.15   # CJK block glyphs need less than the Latin 1.30
CAPTION_BOTTOM_RATIO = 0.06  # bottom margin = 6% of height
CAPTION_OUTLINE_RATIO = 0.08
BREAK_AFTER = "，、；：,;:、"


def wrap_cjk(text: str, font, max_w: float) -> list[str]:
    """Wrap by real pixel measurement. Prefer breaking right after punctuation;
    only hard-split a single phrase that itself exceeds the width."""
    text = " ".join(str(text).split())
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def tw(s: str) -> float:
        return probe.textlength(s, font=font)

    if tw(text) <= max_w:
        return [text]

    phrases: list[str] = []
    cur = ""
    for ch in text:
        cur += ch
        if ch in BREAK_AFTER:
            phrases.append(cur)
            cur = ""
    if cur:
        phrases.append(cur)

    lines: list[str] = []
    line = ""
    for phrase in phrases:
        if tw(phrase) > max_w:
            if line:
                lines.append(line)
                line = ""
            for ch in phrase:
                if line and tw(line) + tw(ch) > max_w:
                    lines.append(line)
                    line = ch
                else:
                    line += ch
            continue
        if line and tw(line) + tw(phrase) > max_w:
            lines.append(line)
            line = phrase
        else:
            line += phrase
    if line:
        lines.append(line)
    return lines


def render_caption_png(text: str, out_path: Path) -> list[str]:
    """Render the verbatim narration as a full-frame transparent caption PNG.
    White fill + dark keyline + Gaussian soft shadow, no band. Returns lines."""
    ss = CAPTION_SS
    cw, ch = WIDTH * ss, HEIGHT * ss
    size = int(HEIGHT * CAPTION_FONT_RATIO) * ss
    font = ImageFont.truetype(FONT_SRC, size)
    max_w = int(WIDTH * CAPTION_WIDTH_RATIO) * ss
    lines = wrap_cjk(text, font, max_w)

    ascent, descent = font.getmetrics()
    cell = ascent + descent
    lh = int(size * CAPTION_LINE_HEIGHT)
    margin = int(HEIGHT * CAPTION_BOTTOM_RATIO) * ss
    outline_w = max(2, round(size * CAPTION_OUTLINE_RATIO))
    sx, sy = 2 * ss, 3 * ss

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    widths = [probe.textlength(ln, font=font) for ln in lines]
    block_h = cell + lh * (len(lines) - 1)
    y0 = ch - margin - block_h
    pos = [(round((cw - wd) / 2), y0 + i * lh) for i, wd in enumerate(widths)]

    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for (x, y), ln in zip(pos, lines):
        sd.text((x + sx, y + sy), ln, font=font, fill=(0, 0, 0, 175),
                stroke_width=outline_w, stroke_fill=(0, 0, 0, 175))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(4 * ss)))

    d = ImageDraw.Draw(canvas)
    for (x, y), ln in zip(pos, lines):
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=outline_w, stroke_fill=(26, 20, 16, 235))

    canvas.resize((WIDTH, HEIGHT), Image.LANCZOS).save(out_path)
    return lines


def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidate = WINGET_BIN / f"{name}.exe"
    if candidate.exists():
        return str(candidate)
    raise SystemExit(f"{name} not found on PATH or at {candidate}")


def probe_duration(ffprobe: str, path: Path) -> float:
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"ffprobe failed for {path}: {proc.stderr}")
    return float(proc.stdout.strip())


def resolve_project_path(project_dir: Path, value: str) -> Path:
    """Resolve a beats.json media path: absolute as-is, else relative to project."""
    p = Path(str(value))
    return p if p.is_absolute() else (project_dir / p)


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(f'"{c}"' if " " in c else c for c in cmd[:6]), "...")
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(f"ffmpeg failed ({proc.returncode})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble Vox MVP final.mp4")
    parser.add_argument("project_dir")
    args = parser.parse_args(argv or sys.argv[1:])
    project_dir = Path(args.project_dir).resolve()
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")

    doc = json.loads((project_dir / "beats.json").read_text(encoding="utf-8"))
    groups = beat_groups(doc)
    seg_dir = project_dir / "_seg"
    seg_dir.mkdir(exist_ok=True)

    # --- Single source of truth: beat timing from the anchor narration length.
    # One beat = one VO line + one caption spanning 1-2 visual shots. The anchor
    # (WIDE) carries the VO; the optional detail cut-in plays the tail of the same
    # narration mid-sentence. v1 projects have one shot per beat, so this reduces
    # exactly to the previous per-shot path.
    MIN_ANCHOR_S = LEAD_S + 0.60
    beats: list[dict] = []      # one per narration line (audio unit)
    visuals: list[dict] = []    # one per rendered segment (anchor + details)
    total = 0.0
    for group in groups:
        bid = group["beat_id"]
        anchor = group["anchor"]
        details = group["details"]
        vo = resolve_project_path(project_dir, str(anchor["vo_path"]))
        if not vo.exists():
            raise SystemExit(f"missing narration for beat {bid} (anchor {anchor.get('id')}): {vo}")
        vo_dur = probe_duration(ffprobe, vo)
        span = LEAD_S + vo_dur + TAIL_S

        # Detail shots absorb their planned dur_s; the anchor takes the rest so a
        # little speech keeps playing across the cut. Each clip is an 8s source.
        detail_durs = [float(d.get("dur_s", 2.2)) for d in details]
        detail_total = sum(detail_durs)
        anchor_dur = span - detail_total
        if anchor_dur < MIN_ANCHOR_S:
            # Short narration: shrink details to keep a usable anchor length.
            scale = max(0.0, (span - MIN_ANCHOR_S) / detail_total) if detail_total else 0.0
            detail_durs = [max(0.8, d * scale) for d in detail_durs]
            detail_total = sum(detail_durs)
            anchor_dur = span - detail_total

        members = [(anchor, anchor_dur, "anchor")] + list(zip(details, detail_durs, ["detail"] * len(details)))
        beat_visuals = []
        for shot, seg_dur, role in members:
            source_dur = float(shot.get("clip_source_duration_s")
                               or shot.get("video_source_duration_s")
                               or SOURCE_CLIP_S)
            if seg_dur > source_dur + 0.05:
                raise SystemExit(
                    f"{bid}/{role} {shot.get('id')}: segment {seg_dur:.2f}s exceeds the {source_dur:.0f}s source clip."
                )
            clip = resolve_project_path(project_dir, str(shot["clip_path"]))
            if not clip.exists():
                raise SystemExit(f"missing clip for {shot.get('id')}: {clip}")
            rec = {"beat_id": bid, "sid": shot["id"], "role": role,
                   "shot": shot, "clip": clip, "dur": seg_dur}
            beat_visuals.append(rec)
            visuals.append(rec)

        beats.append({"beat_id": bid, "sid": anchor["id"], "anchor": anchor,
                      "vo": vo, "vo_dur": vo_dur, "start": total,
                      "span": span, "visuals": beat_visuals})
        total += anchor_dur + detail_total

    print("Beat timing (from real anchor narration):")
    for b in beats:
        cuts = " + ".join(f"{v['sid']}({v['dur']:.2f}s)" for v in b["visuals"])
        print(f"  {b['beat_id']}: start={b['start']:.2f}s vo={b['vo_dur']:.2f}s "
              f"span={b['span']:.2f}s  [{cuts}]")
    print(f"Total: {total:.2f}s")

    # 1) Render one caption PNG per BEAT (verbatim narration), encode every visual
    #    segment trimmed to its own duration with that caption overlaid.
    seg_paths: list[Path] = []
    for b in beats:
        cap_png = seg_dir / f"cap_{b['beat_id']}.png"
        cap_lines = render_caption_png(str(b["anchor"]["narration"]), cap_png)
        print(f"  {b['beat_id']} caption lines: {len(cap_lines)} -> {cap_png.name}")
        for v in b["visuals"]:
            sid = v["sid"]
            seg = seg_dir / f"seg_{sid}.mp4"
            fc = (
                f"[0:v]trim=duration={v['dur']:.3f},setpts=PTS-STARTPTS,"
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={FPS},setsar=1,format=yuv420p[bg];"
                f"[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
            )
            run([
                ffmpeg, "-y", "-i", str(v["clip"]), "-i", str(cap_png),
                "-an", "-filter_complex", fc, "-map", "[v]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", str(seg),
            ], project_dir)
            v["seg"] = seg
            seg_paths.append(seg)

    # 2) Concat.
    concat_list = seg_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in seg_paths), encoding="utf-8"
    )
    video_only = seg_dir / "video_only.mp4"
    run([
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(video_only),
    ], project_dir)

    # 3) Narration placement (one VO per beat, one LEAD) + deterministic BGM ducking.
    inputs: list[str] = []
    for b in beats:
        inputs += ["-i", str(b["vo"])]
    bgm = resolve_project_path(project_dir, str(doc["music"]["path"]))
    if not bgm.exists():
        raise SystemExit(f"missing BGM: {bgm} (reuse one by placing audio/bgm.mp3 "
                         f"and setting music.path)")
    # Loop the BGM input so a shorter bed (e.g. 23s) fills the whole timeline.
    inputs += ["-stream_loop", "-1", "-i", str(bgm)]

    fc: list[str] = []
    voice_labels: list[str] = []
    duck_windows: list[str] = []
    for i, b in enumerate(beats):
        vo_start = b["start"] + LEAD_S  # narration begins once per beat
        delay_ms = int(round(vo_start * 1000))
        fc.append(
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},volume={VO_BOOST}[v{i}]"
        )
        voice_labels.append(f"[v{i}]")
        duck_windows.append(
            f"between(t,{max(0.0, vo_start - 0.12):.3f},"
            f"{min(total, vo_start + b['vo_dur'] + 0.20):.3f})"
        )
    n = len(beats)
    fc.append("".join(voice_labels)
              + f"amix=inputs={n}:normalize=0:duration=longest[voice]")
    duck_expr = "+".join(duck_windows)
    fc.append(
        f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,"
        f"atrim=0:{total:.3f},asetpts=N/SR/TB,volume={BGM_BASE},"
        f"volume={BGM_DUCK}:enable='{duck_expr}'[ducked]"
    )
    fc.append(
        "[ducked][voice]amix=inputs=2:normalize=0:duration=longest,"
        f"apad=whole_dur={total:.3f},atrim=0:{total:.3f},"
        "aresample=48000,asetpts=N/SR/TB[aout]"
    )

    mix = seg_dir / "mix.m4a"
    run([
        ffmpeg, "-y", *inputs,
        "-filter_complex", ";".join(fc),
        "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", str(mix),
    ], project_dir)

    # 4) Mux. Video and audio share the same total by construction.
    final = project_dir / "final.mp4"
    run([
        ffmpeg, "-y", "-i", str(video_only), "-i", str(mix),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(final),
    ], project_dir)

    print(f"\nFinal: {final} ({total:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

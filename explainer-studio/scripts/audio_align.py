#!/usr/bin/env python3
"""Align beat texts inside one group TTS audio, then normalize it.

Free, local, deterministic. A group is one TTS render of several beat
narrations spoken in one take (natural prosody, natural inter-beat pauses).
After download we must recover where every beat lives inside the take:

  align_beats()  - silence structure + character-count priors snap expected
                   beat boundaries to real inter-sentence silences; strict
                   confidence validation, returns a __align_failed__ dict with
                   reasons on failure (caller stops; no automatic paid retry).
  build_segment()- normalize the raw take into a timeline segment:
                   head trimmed/padded to exactly LEAD (or CHAPTER_LEAD after
                   a chapter-card silence block), tail trimmed/padded to
                   TAIL; optional CARD_S of silence prepended for chapter
                   cards. Concatenating normalized segments back-to-back
                   yields the master voice timeline.

Audio coordinates:
  raw   - inside the downloaded TTS take
  seg   - inside the normalized segment (what assemble concatenates)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from explainer_common import (
    CARD_S, CHAPTER_LEAD_S, EDGE_TRIM_S, LEAD_S, SILENCE_MIN_D,
    SILENCE_NOISE_DB, TAIL_S, count_units, probe_duration,
)

# Plausible per-character speech rate (s/unit) for a matched beat.
RATE_MIN = 0.10
RATE_MAX = 0.50
MIN_BEAT_SPEECH_S = 1.0
# DP boundary selection weights (see align_beats)
W_RATE = 1.0          # per-beat rate vs group mean rate (normalized)
W_PRIOR = 0.25        # position prior: (dist/2s)^2
W_PAUSE = 1.2         # reward per second of pause (up to 1.0s)
# Position-prior units: punctuation carries expected silence, so
# pause-heavy beats (e.g. dramatic delivery) get proportionally more weight.
WEAK_PAUSE_MARKS = "，、,;；："
STRONG_PAUSE_MARKS = "。！？.!?…"
WEAK_PAUSE_UNITS = 1.5
STRONG_PAUSE_UNITS = 3.0


def _prior_units(text: str) -> float:
    return (count_units(text)
            + WEAK_PAUSE_UNITS * sum(text.count(c) for c in WEAK_PAUSE_MARKS)
            + STRONG_PAUSE_UNITS * sum(text.count(c) for c in STRONG_PAUSE_MARKS))


def _parse_silences(ffmpeg: str, audio: Path, dur: float) -> list[dict]:
    """All silencedetect intervals, including head/tail edges, clamped to file."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(audio),
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}:d={SILENCE_MIN_D}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts: list[float] = []
    out: list[dict] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?\d+\.?\d*)", line)
        if m:
            starts.append(max(0.0, float(m.group(1))))
            continue
        m = re.search(r"silence_end:\s*(-?\d+\.?\d*)\s*\|\s*silence_duration:\s*(\d+\.?\d*)", line)
        if m and starts:
            end = min(dur, max(0.0, float(m.group(1))))
            start = starts.pop(0)
            if end > start:
                out.append({"start": round(start, 3), "end": round(end, 3),
                            "duration": round(end - start, 3)})
    for s in starts:  # silence running to EOF without a printed end
        if dur > s:
            out.append({"start": round(s, 3), "end": round(dur, 3),
                        "duration": round(dur - s, 3)})
    out.sort(key=lambda p: p["start"])
    return out


def _fail(reasons: list[str]) -> dict:
    return {"__align_failed__": True, "reasons": reasons}


def align_beats(ffmpeg: str, ffprobe: str, audio: Path,
                texts: list[str]) -> dict:
    """Return {"intervals":[{"start","end"}...], "silences":[...], ...} or a
    {"__align_failed__": True, "reasons": [...]} refusal."""
    dur = probe_duration(ffprobe, audio)
    silences = _parse_silences(ffmpeg, audio, dur)

    head = next((p for p in silences if p["start"] <= 0.05), None)
    tail = next((p for p in silences if p["end"] >= dur - 0.05), None)
    internal = [p for p in silences
                if p is not head and p is not tail
                and p["start"] >= EDGE_TRIM_S and p["end"] <= dur - EDGE_TRIM_S]

    speech0 = head["end"] if head else 0.0
    speech_last_end = tail["start"] if tail else dur
    if speech_last_end - speech0 < MIN_BEAT_SPEECH_S:
        return _fail([f"整组有声区域仅 {speech_last_end - speech0:.2f}s，TTS 输出异常"])

    chars = [max(1, count_units(t)) for t in texts]
    prior_weights = [max(1.0, _prior_units(t)) for t in texts]
    total_prior = sum(prior_weights)
    outer = max(0.1, speech_last_end - speech0)

    # Single-beat group: no boundaries to find.
    if len(texts) == 1:
        return {"intervals": [{"start": round(speech0, 3),
                               "end": round(speech_last_end, 3)}],
                "silences": internal, "raw_duration_s": round(dur, 3),
                "method": "single"}

    # Pick one internal pause per boundary via a global DP.  Greedy snapping to
    # the character-proportional expectation breaks when one beat is spoken
    # noticeably slower/faster than the mean (its expected boundary can sit
    # >1.5s off next to an in-beat pause).  The DP scores whole paths:
    # per-beat rate consistency vs the group mean rate, a soft position prior,
    # and a reward for longer (inter-sentence) pauses.
    mu = outer / sum(chars)
    m = len(texts)
    # dp[i] = (cost, prev_pause_idx) after the current boundary picks pause i;
    # key -1 is the virtual starting point at speech0.
    dp: dict[int, tuple[float, int | None]] = {-1: (0.0, None)}
    back: list[dict[int, tuple[float, int | None]]] = []

    def rate_ok(speech_s: float, n_chars: int) -> bool:
        rate = speech_s / n_chars
        return (speech_s >= MIN_BEAT_SPEECH_S
                and RATE_MIN <= rate <= RATE_MAX)

    for k in range(1, m):
        cum_units = sum(prior_weights[:k])
        expected = speech0 + outer * cum_units / total_prior
        nxt: dict[int, tuple[float, int | None]] = {}
        for prev_i, (base, _) in dp.items():
            prev_end = speech0 if prev_i == -1 else internal[prev_i]["end"]
            for i, p in enumerate(internal):
                if i <= prev_i or p["start"] <= prev_end + 1e-6:
                    continue
                speech_s = p["start"] - prev_end
                if not rate_ok(speech_s, chars[k - 1]):
                    continue
                rate = speech_s / chars[k - 1]
                mid = (p["start"] + p["end"]) / 2
                cost = (base
                        + W_RATE * ((rate - mu) / mu) ** 2
                        + W_PRIOR * ((mid - expected) / 2.0) ** 2
                        - W_PAUSE * min(p["duration"], 1.0))
                if i not in nxt or cost < nxt[i][0]:
                    nxt[i] = (cost, prev_i)
        if not nxt:
            return _fail([
                f"边界 {k}（「{texts[k][:12]}…」之前）: 找不到满足语速约束的停顿"
                f"（期望位置 {expected:.2f}s，可能被一口气念过）"])
        back.append(nxt)
        dp = nxt

    # close the final beat
    best = None
    for i, (base, _) in dp.items():
        speech_s = speech_last_end - internal[i]["end"]
        if not rate_ok(speech_s, chars[-1]):
            continue
        rate = speech_s / chars[-1]
        cost = base + W_RATE * ((rate - mu) / mu) ** 2
        if best is None or cost < best[0]:
            best = (cost, i)
    if best is None:
        return _fail(["末句语速校验失败：没有任何边界组合能让所有 beat 落在合理语速区间"])

    chosen: list[int] = []
    cur = best[1]
    for nxt_map in reversed(back):
        chosen.append(cur)
        cur = nxt_map[cur][1]
    chosen.reverse()
    boundaries = [internal[i] for i in chosen]

    intervals: list[dict] = []
    cur_start = speech0
    for p in boundaries:
        intervals.append({"start": round(cur_start, 3), "end": round(p["start"], 3)})
        cur_start = p["end"]
    intervals.append({"start": round(cur_start, 3),
                      "end": round(speech_last_end, 3)})

    reasons: list[str] = []
    for iv, text, n_chars in zip(intervals, texts, chars):
        speech = iv["end"] - iv["start"]
        if speech < MIN_BEAT_SPEECH_S:
            reasons.append(f"「{text[:12]}…」匹配语音段仅 {speech:.2f}s")
        rate = speech / n_chars
        if not RATE_MIN <= rate <= RATE_MAX:
            reasons.append(
                f"「{text[:12]}…」语速 {rate:.3f}s/字 超出合理区间 "
                f"[{RATE_MIN}, {RATE_MAX}]（疑似边界误匹配）")
    if reasons:
        return _fail(reasons)
    return {"intervals": intervals, "silences": internal,
            "raw_duration_s": round(dur, 3), "method": "silence"}


def beat_pauses(align: dict, intervals: list[dict]) -> list[list[dict]]:
    """Split the group's internal silences into beat-relative pause lists."""
    out: list[list[dict]] = []
    for iv in intervals:
        lst = []
        for p in align["silences"]:
            mid = (p["start"] + p["end"]) / 2
            if iv["start"] - 0.02 <= mid < iv["end"] - 0.02:
                start = round(p["start"] - iv["start"], 3)
                end = round(p["end"] - iv["start"], 3)
                if start >= EDGE_TRIM_S:
                    lst.append({"start": start, "end": end,
                                "duration": round(end - start, 3)})
        out.append(lst)
    return out


def build_segment(ffmpeg: str, ffprobe: str, raw: Path, out: Path,
                  intervals: list[dict], card: bool) -> dict:
    """Render the normalized timeline segment.

    Returns {"seg_duration_s", "vo_seg": [{"start","end"} in seg coords]}.
    """
    dur = probe_duration(ffprobe, raw)
    head = intervals[0]["start"]
    tail_end = intervals[-1]["end"]
    lead = CHAPTER_LEAD_S if card else LEAD_S
    card_off = CARD_S if card else 0.0

    t0 = max(0.0, head - lead)
    hpad = max(0.0, lead - head)
    t1 = tail_end + TAIL_S
    src_end = min(t1, dur)
    tail_pad = max(0.0, t1 - dur)
    if src_end <= t0:
        raise SystemExit(f"alignment produced empty segment body for {raw.name}")
    body_final = hpad + (src_end - t0) + tail_pad
    hp_ms = int(round(hpad * 1000))

    body = (f"[0:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"atrim={t0:.3f}:{src_end:.3f},asetpts=N/SR/TB,"
            f"adelay={hp_ms}|{hp_ms},"
            f"apad=whole_dur={body_final:.3f},atrim=0:{body_final:.3f},"
            f"asetpts=N/SR/TB")
    fc: list[str] = []
    if card:
        fc.append(f"anullsrc=r=48000:cl=stereo:d={CARD_S:.3f}[card]")
        fc.append(body + "[body]")
        fc.append("[card][body]concat=n=2:v=0:a=1[aout]")
    else:
        fc.append(body + "[aout]")

    p = subprocess.run(
        [ffmpeg, "-y", "-i", str(raw), "-filter_complex", ";".join(fc),
         "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print(p.stdout); print(p.stderr)
        raise SystemExit(f"segment normalization failed: {raw.name}")

    seg_dur = probe_duration(ffprobe, out)
    expected = card_off + body_final
    if abs(seg_dur - expected) > 0.08:
        raise SystemExit(
            f"normalized segment {out.name} duration {seg_dur:.3f} != "
            f"expected {expected:.3f}")

    vo_seg = [{
        "start": round(card_off + lead + (iv["start"] - head), 3),
        "end": round(card_off + lead + (iv["end"] - head), 3),
    } for iv in intervals]
    return {"seg_duration_s": round(seg_dur, 3), "vo_seg": vo_seg}

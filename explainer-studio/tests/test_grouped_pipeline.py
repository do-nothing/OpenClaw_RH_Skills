#!/usr/bin/env python3
"""Offline, zero-cost tests for the chapter-grouped TTS pipeline.

No network, no RH coins: "speech" is a ffmpeg sine tone and pauses are
anullsrc silence, with ground-truth boundaries known by construction.

Run:  python explainer-studio/tests/test_grouped_pipeline.py
      (requires ffmpeg/ffprobe on PATH; audio tests skip otherwise)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audio_align  # noqa: E402
import assemble  # noqa: E402
import generate_audio  # noqa: E402
import plan_shots  # noqa: E402
from explainer_common import CARD_S, LEAD_S, is_grouped, beat_timeline  # noqa: E402
from sync_script import validate_front  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
HAS_FFMPEG = bool(FFMPEG and FFPROBE)

# Ground truth of the synthesized take (seconds):
#   head .30 | tone 2.40 | pause .62 | tone 1.68 | IN-BEAT pause 1.00 |
#   tone 1.68 | pause .70 | tone 3.12 | tail .35
# The in-beat 1.00s pause is deliberately LONGER than the 0.62s inter-beat
# pause: a longest-pause/greedy picker misreads it as a beat boundary.
TRUE = {
    "speech0": 0.30,
    "b1": (0.30, 2.70),
    "b2": (3.32, 7.68),   # 1.68 + 1.00 internal + 1.68
    "b3": (8.38, 11.50),
    "dur": 11.85,
}
TEXTS = [
    "甲乙丙丁戊己庚辛壬癸",                       # 10 units -> 0.24 s/unit
    "子丑寅卯辰巳午未申酉戌亥甲乙丙丁戊己",          # 18 units -> 4.36/18
    "金木水火土天王太上老君日月星",                 # 13 units -> 3.12/13
]


def synth_take(out: Path) -> None:
    """Render the take as concatenated 16k mono wav parts."""
    parts = [
        ("s", 0.30, 0), ("t", 2.40, 440), ("s", 0.62, 0),
        ("t", 1.68, 520), ("s", 1.00, 0), ("t", 1.68, 520),
        ("s", 0.70, 0), ("t", 3.12, 600), ("s", 0.35, 0),
    ]
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        listed = []
        for i, (kind, dur, freq) in enumerate(parts):
            p = tdp / f"p{i:02d}.wav"
            src = (f"anullsrc=r=16000:cl=mono" if kind == "s"
                   else f"sine=frequency={freq}:sample_rate=16000")
            subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i", src,
                            "-t", f"{dur:.3f}", "-c:a", "pcm_s16le", str(p)],
                           capture_output=True, check=True)
            listed.append(p)
        listfile = tdp / "list.txt"
        listfile.write_text("".join(f"file '{p.as_posix()}'\n" for p in listed),
                            encoding="utf-8")
        subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listfile), "-c", "copy", str(out)],
                       capture_output=True, check=True)


class PlanGroupsTest(unittest.TestCase):
    def _doc(self, beats, chapters=None):
        return {"beats": [{"id": f"b{i:02d}", "est_duration_s": 99.0}
                          for i in range(1, beats + 1)],
                "chapters": chapters or []}

    def test_chapters_define_groups(self):
        doc = self._doc(6, [{"id": "c1", "title": "一", "from_beat": "b01"},
                            {"id": "c2", "title": "二", "from_beat": "b04"}])
        groups = generate_audio.plan_groups(doc)
        self.assertEqual([[b["id"] for b in g] for g in groups],
                         [["b01", "b02", "b03"], ["b04", "b05", "b06"]])

    def test_no_chapters_one_group_regardless_of_estimate(self):
        # est_duration_s 99s each would have blown any old seconds cap.
        groups = generate_audio.plan_groups(self._doc(6))
        self.assertEqual([b["id"] for b in groups[0]],
                         ["b01", "b02", "b03", "b04", "b05", "b06"])


class ValidateFrontTest(unittest.TestCase):
    BASE = {"project": "t", "topic": "x", "aspect": "16:9",
            "visual_style": "clean-diagram", "voice": {"mode": "tts"}}

    def _err(self, dur):
        fm = dict(self.BASE, target_duration_s=dur)
        return [e for e in validate_front(fm, 7) if "target_duration" in e]

    def test_duration_window(self):
        for good in (0, 90, 300):
            self.assertEqual(self._err(good), [])
        for bad in (-1, 301, "90"):
            self.assertTrue(self._err(bad))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not on PATH")
class AudioAlignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raw = Path(cls.tmp.name) / "take.wav"
        synth_take(cls.raw)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_boundaries_recover_ground_truth(self):
        r = audio_align.align_beats(FFMPEG, FFPROBE, self.raw, TEXTS)
        self.assertNotIn("__align_failed__", r, r.get("reasons"))
        self.assertEqual(r["method"], "silence")
        self.assertEqual(len(r["intervals"]), 3)
        for iv, (lo, hi) in zip(r["intervals"],
                                (TRUE["b1"], TRUE["b2"], TRUE["b3"])):
            self.assertAlmostEqual(iv["start"], lo, delta=0.12)
            self.assertAlmostEqual(iv["end"], hi, delta=0.12)

    def test_single_beat_group(self):
        r = audio_align.align_beats(FFMPEG, FFPROBE, self.raw, TEXTS[:1])
        self.assertEqual(r["method"], "single")
        self.assertAlmostEqual(r["intervals"][0]["start"],
                               TRUE["speech0"], delta=0.05)

    def test_rate_mismatch_refuses_not_guesses(self):
        r = audio_align.align_beats(FFMPEG, FFPROBE, self.raw,
                                    ["字" * 100] * 3)
        self.assertTrue(r.get("__align_failed__"))
        self.assertTrue(r["reasons"])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not on PATH")
class BuildSegmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "take.wav"
        synth_take(self.raw)
        r = audio_align.align_beats(FFMPEG, FFPROBE, self.raw, TEXTS)
        self.assertNotIn("__align_failed__", r, r.get("reasons"))
        self.intervals = r["intervals"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalized_durations_and_offsets(self):
        from explainer_common import CHAPTER_LEAD_S, probe_duration
        for card in (False, True):
            # card groups keep the raw 0.30 head and pad to a 0.90 lead
            # (body +0.7 vs non-card), plus 1.4s card silence in front.
            extra = CARD_S if card else 0.0
            extra += (CHAPTER_LEAD_S - LEAD_S) if card else 0.0
            expected = TRUE["dur"] + extra
            out = Path(self.tmp.name) / f"seg_{card}.m4a"
            info = audio_align.build_segment(
                FFMPEG, FFPROBE, self.raw, out, self.intervals, card)
            self.assertAlmostEqual(probe_duration(FFPROBE, out),
                                   expected, delta=0.08)
            self.assertAlmostEqual(info["seg_duration_s"], expected,
                                   delta=0.08)
            # first vo starts after card silence + fixed lead
            want_start = (CARD_S if card else 0.0) + (
                CHAPTER_LEAD_S if card else LEAD_S)
            self.assertAlmostEqual(info["vo_seg"][0]["start"],
                                   want_start, delta=0.05)


class TimelineTest(unittest.TestCase):
    def _doc(self):
        # g01: card, seg 5.0 (card 1.4, lead .9, b01 1s, b02 .8s, tail .45...);
        # g02: plain, seg 4.0
        return {
            "voice": {"group": "auto"},
            "beats": [
                {"id": "b01", "vo_group_id": "g01",
                 "vo_seg_start_s": 2.3, "vo_seg_end_s": 3.3},
                {"id": "b02", "vo_group_id": "g01",
                 "vo_seg_start_s": 3.8, "vo_seg_end_s": 4.6},
                {"id": "b03", "vo_group_id": "g02",
                 "vo_seg_start_s": 0.2, "vo_seg_end_s": 3.55},
            ],
            "voice_groups": [
                {"id": "g01", "beats": ["b01", "b02"],
                 "seg_duration_s": 5.0, "card": True},
                {"id": "g02", "beats": ["b03"],
                 "seg_duration_s": 4.0, "card": False},
            ],
        }

    def test_grouped_gating(self):
        self.assertTrue(is_grouped(self._doc()))
        old = {"voice": {}, "beats": [{"id": "b01", "vo_path": "x"}]}
        self.assertFalse(is_grouped(old))
        beat_mode = self._doc()
        beat_mode["voice"]["group"] = "beat"
        self.assertFalse(is_grouped(beat_mode))

    def test_windows(self):
        tl = beat_timeline(self._doc())
        self.assertAlmostEqual(tl["total"], 9.0, delta=1e-6)
        b = tl["beats"]
        self.assertAlmostEqual(b["b01"]["start"], CARD_S, delta=1e-6)
        self.assertAlmostEqual(b["b01"]["lead"], 0.9, delta=1e-6)
        # middle beat: gstart(0) + vo_seg_start(3.8) - lead(.2)
        self.assertAlmostEqual(b["b02"]["start"], 3.6, delta=1e-6)
        self.assertAlmostEqual(b["b03"]["start"], 5.0, delta=1e-6)
        self.assertAlmostEqual(b["b03"]["end"], 9.0, delta=1e-6)


class ClipReuseTest(unittest.TestCase):
    """plan_shots.clip_reusable: re-cut an existing source clip (grouped only)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        clip = Path(self._td.name) / "c.mp4"
        clip.write_bytes(b"x")
        self.clip = str(clip)

    def tearDown(self):
        self._td.cleanup()

    def old(self, **kw):
        d = {"mode": "first_frame", "clip_path": self.clip,
             "clip_source_duration_s": 8.0}
        d.update(kw)
        return d

    def rec(self, used=7.5, mode="first_frame"):
        return {"mode": mode, "used_duration_s": used}

    def test_shorter_window_grouped(self):
        self.assertTrue(plan_shots.clip_reusable(self.old(), self.rec(), True))

    def test_margin_boundary(self):
        # matches assemble.py probe: used may exceed source by <= 0.05
        self.assertTrue(plan_shots.clip_reusable(
            self.old(), self.rec(used=8.05), True))
        self.assertFalse(plan_shots.clip_reusable(
            self.old(), self.rec(used=8.06), True))

    def test_beat_mode_never_reuses(self):
        self.assertFalse(plan_shots.clip_reusable(self.old(), self.rec(), False))

    def test_mode_change_blocks(self):
        self.assertFalse(plan_shots.clip_reusable(
            self.old(), self.rec(mode="first_last_frame"), True))

    def test_missing_file_or_metadata(self):
        self.assertFalse(plan_shots.clip_reusable(
            self.old(clip_path=str(Path(self._td.name) / "nope.mp4")),
            self.rec(), True))
        self.assertFalse(plan_shots.clip_reusable(
            {"mode": "first_frame", "clip_source_duration_s": 8.0},
            self.rec(), True))
        self.assertFalse(plan_shots.clip_reusable(
            self.old(clip_source_duration_s=None), self.rec(), True))


class CaptionSplitTest(unittest.TestCase):
    """Sequential one-line captions: punctuation split + timed frame budget."""

    FONT = assemble.FONT_SRC if Path(assemble.FONT_SRC).exists() else None
    W, H = 1280, 720

    def setUp(self):
        if not self.FONT:
            self.skipTest("simhei.ttf unavailable")
        self.font = assemble._font(int(self.H * assemble.FONT_RATIO))
        self.max_w = int(self.W * assemble.WIDTH_RATIO)
        self.target_w = int(self.W * assemble.CAP_TARGET_RATIO)

    def split(self, text):
        return assemble.split_captions(text, self.font,
                                       self.max_w, self.target_w)

    BRK = "".join(assemble.CAP_BREAK_AFTER)

    def _strip_brk(self, s):
        return s.translate(str.maketrans("", "", self.BRK))

    def test_punctuation_split_strips_trailing(self):
        t = "明天就要交报告了，你却在擦桌子、给耳机线打结、反复刷同一个购物软件。"
        p = self.split(t)
        self.assertGreater(len(p), 3)
        for piece in p:
            self.assertNotIn(piece[-1], assemble.CAP_BREAK_AFTER)
            self.assertLessEqual(assemble._tw(piece, self.font), self.max_w)
        # first clause is long, no merge; its trailing comma is gone
        self.assertEqual(p[0], "明天就要交报告了")
        # no characters are lost: punctuation-free concat equals punct-free
        # source
        self.assertEqual("".join(self._strip_brk(x) for x in p),
                         self._strip_brk(t))

    def test_double_sentence_end_punct_stripped(self):
        p = self.split("真的吗？！他走了。")
        self.assertEqual(p, ["真的吗", "他走了"])

    def test_anti_fragment_merges_short_lead(self):
        # w<=5 soft lead absorbs the next clause; internal comma is kept
        p = self.split("第一招，别想着写完报告，只告诉自己。")
        self.assertEqual(p, ["第一招，别想着写完报告", "只告诉自己"])

    def test_anti_fragment_never_crosses_sentence_end(self):
        # the short clause ends a sentence (hard boundary): it stays alone
        p = self.split("写五分钟。五分钟后你可以停。")
        self.assertEqual(p, ["写五分钟", "五分钟后你可以停"])
        # a short emphatic sentence ending is intentionally left standalone
        p2 = self.split("我要说的就两个字，足够近。")
        self.assertEqual(p2, ["我要说的就两个字", "足够近"])

    def test_anti_fragment_blocked_by_width(self):
        # 注意 (w=2) would merge, but the combined line exceeds target_w
        t = "注意，活跃的竟然是认出陌生人的那片区域啊。"
        p = self.split(t)
        self.assertEqual(len(p), 2)
        self.assertEqual(p[0], "注意")

    def test_long_clause_split_keeps_latin_word_atomic(self):
        t = "那为什么 deadline 前你又突然能专注了？因为那一刻，"
        # force a secondary split with a narrow target; hard ceiling stays wide
        p = assemble.split_captions(t, self.font, self.max_w, 400)
        self.assertGreaterEqual(len(p), 3)
        self.assertEqual("".join(self._strip_brk(x) for x in p),
                         self._strip_brk(t))
        self.assertIn("deadline", " ".join(p))
        for piece in p:
            self.assertLessEqual(assemble._tw(piece, self.font), 401)

    def test_real_widths_fit_one_line(self):
        # at the production target width the real b09 sentence stays one line
        t = "那为什么 deadline 前你又突然能专注了？"
        p = self.split(t)
        self.assertEqual(len(p), 1)
        self.assertLessEqual(assemble._tw(p[0], self.font), self.max_w)

    def test_every_real_beat_fits_one_line(self):
        doc_p = (Path(__file__).resolve().parents[1]
                 / "out" / "grouped_test" / "explainer.json")
        if not doc_p.exists():
            self.skipTest("grouped_test project not present")
        doc = json.loads(doc_p.read_text(encoding="utf-8"))
        total_pieces = 0
        for b in doc["beats"]:
            pieces = self.split(b["narration"])
            total_pieces += len(pieces)
            for piece in pieces:
                self.assertLessEqual(
                    assemble._tw(piece, self.font), self.max_w,
                    f"{b['id']} caption too wide: {piece}")
        self.assertGreater(total_pieces, len(doc["beats"]))

    def test_frame_budget_sums_exactly(self):
        for avail, n in ((240, 3), (348, 7), (10, 4), (96, 5)):
            weights = [1.0 + 0.3 * i for i in range(n)]
            frames = assemble.allocate_piece_frames(weights, avail, 24)
            self.assertEqual(len(frames), n)
            self.assertEqual(sum(frames), avail)
            self.assertTrue(all(f >= 1 for f in frames))

    def test_frame_budget_min_duration_when_window_allows(self):
        # 7 pieces over ~14.5s: each piece can afford the 0.75s minimum
        weights = [3.0, 6.0, 3.0, 8.0, 8.0, 3.0, 11.0]
        frames = assemble.allocate_piece_frames(weights, 348, 24)
        self.assertEqual(sum(frames), 348)
        self.assertTrue(all(f >= round(0.75 * 24) for f in frames))


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from caption_equivalence import CaptionError, compare_files
from caption_equivalence.cli import main
from caption_equivalence.core import Cue, _sweep


def stamp(milliseconds, comma=True):
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{',' if comma else '.'}{ms:03}"


def srt(cues):
    return "\n\n".join(
        f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}"
        for index, (start, end, text) in enumerate(cues, 1)
    ) + ("\n" if cues else "")


def vtt(cues):
    return "WEBVTT\n\n" + "\n\n".join(
        f"{stamp(start, False)} --> {stamp(end, False)}\n{text}" for start, end, text in cues
    )


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def pair(self, old, new, **options):
        return compare_files(
            self.write("before.srt", srt(old)), self.write("after.vtt", vtt(new)), **options
        )

    def test_cross_format_same_text(self):
        result = self.pair([(0, 1000, "Hello")], [(0, 1000, "Hello")])
        self.assertEqual(result["status"], "equivalent")
        self.assertEqual(result["different_ms"], 0)

    def test_adjacent_split_is_equivalent(self):
        result = self.pair([(0, 1000, "Hold")], [(0, 400, "Hold"), (400, 1000, "Hold")])
        self.assertEqual(result["status"], "equivalent")
        self.assertEqual(result["reference"]["cues"], 1)
        self.assertEqual(result["candidate"]["cues"], 2)

    def test_missing_tail(self):
        result = self.pair([(0, 1000, "Hello")], [(0, 700, "Hello")])
        self.assertEqual(result["different_ms"], 300)
        self.assertEqual(result["findings"][0]["kind"], "missing")

    def test_extra_text(self):
        result = self.pair([(0, 1000, "Hello")], [(0, 1000, "Hello"), (500, 800, "Extra")])
        self.assertEqual(result["different_ms"], 300)
        self.assertEqual(result["findings"][0]["kind"], "added")

    def test_replaced_text(self):
        result = self.pair([(0, 1000, "Hello")], [(0, 1000, "Goodbye")])
        finding = result["findings"][0]
        self.assertEqual(finding["kind"], "changed")
        self.assertEqual(finding["missing_cue_count"], 1)
        self.assertEqual(finding["added_cue_count"], 1)
        self.assertEqual(result["different_ms"], 1000)

    def test_exact_offset_and_explicit_budget(self):
        result = self.pair([(0, 100, "A")], [(10, 110, "A")])
        self.assertEqual(result["different_ms"], 20)
        self.assertEqual(result["status"], "different")
        accepted = self.pair([(0, 100, "A")], [(10, 110, "A")], max_different_ms=20)
        self.assertEqual(accepted["status"], "within_budget")
        self.assertEqual(accepted["different_ms"], 20)

    def test_duplicate_overlap_is_not_deduplicated(self):
        result = self.pair([(0, 100, "A"), (50, 100, "A")], [(0, 100, "A")])
        self.assertEqual(result["different_ms"], 50)
        self.assertEqual(result["findings"][0]["missing_cue_count"], 1)

    def test_reflow_wrappers_and_entities(self):
        result = self.pair(
            [(0, 100, "<b><i>Hello</i></b>\nworld &amp; friends")],
            [(0, 100, "Hello world &#38; friends")],
        )
        self.assertEqual(result["status"], "equivalent")

    def test_encoded_tags_are_literal_text(self):
        result = self.pair([(0, 100, "&lt;i&gt;text&lt;/i&gt;")], [(0, 100, "<i>text</i>")])
        self.assertEqual(result["status"], "different")

    def test_unicode_case_and_normalization_remain_significant(self):
        for old, new in [("Hello", "hello"), ("é", "e\u0301"), ("東京", "京都")]:
            self.assertEqual(self.pair([(0, 100, old)], [(0, 100, new)])["different_ms"], 100)

    def test_whitespace_only_difference_is_accepted(self):
        self.assertEqual(
            self.pair([(0, 100, "a\t b")], [(0, 100, "a\u00a0b")])["status"], "equivalent"
        )

    def test_cue_file_order_does_not_change_multiset(self):
        rows = [(0, 100, "A"), (10, 50, "B")]
        self.assertEqual(self.pair(rows, list(reversed(rows)))["status"], "equivalent")

    def test_end_is_exclusive_without_false_overlap(self):
        result = self.pair(
            [(0, 50, "A"), (50, 100, "B")], [(0, 50, "A"), (50, 100, "B")], max_active=1
        )
        self.assertEqual(result["status"], "equivalent")

    def test_large_duration_does_not_iterate_per_millisecond(self):
        duration = 999999 * 3600 * 1000
        self.assertEqual(
            self.pair([(0, duration, "A")], [(0, duration, "A")])["status"], "equivalent"
        )

    def test_empty_conversion_is_detected(self):
        result = self.pair([(0, 100, "A")], [])
        self.assertEqual(result["different_ms"], 100)
        self.assertEqual(result["candidate"]["cues"], 0)

    def test_empty_reference_requires_explicit_option(self):
        with self.assertRaisesRegex(CaptionError, "empty_reference"):
            self.pair([], [])
        self.assertEqual(self.pair([], [], allow_empty_reference=True)["status"], "equivalent")

    def test_added_from_explicit_empty_reference(self):
        self.assertEqual(
            self.pair([], [(0, 100, "A")], allow_empty_reference=True)["different_ms"], 100
        )

    def test_findings_bound_does_not_limit_detection(self):
        old = [(i * 20, i * 20 + 10, "A") for i in range(20)]
        result = self.pair(old, [], max_findings=1)
        self.assertEqual(result["different_ms"], 200)
        self.assertEqual(result["different_intervals"], 20)
        self.assertEqual(len(result["findings"]), 1)
        self.assertTrue(result["findings_truncated"])

    def test_per_interval_line_evidence_is_bounded(self):
        result = self.pair([(0, 100, "A")] * 20, [])
        self.assertEqual(result["findings"][0]["missing_cue_count"], 20)
        self.assertEqual(len(result["findings"][0]["reference_lines"]), 8)
        self.assertTrue(result["findings"][0]["reference_lines_truncated"])

    def test_vtt_cue_ids_notes_and_short_timestamps(self):
        old = self.write("a.srt", srt([(0, 1000, "A")]))
        new = self.write(
            "b.vtt",
            "WEBVTT\n\nNOTE private internal note\nignored\n\nmy-id\n00:00.000 --> 00:01.000\nA\n",
        )
        result = compare_files(old, new)
        self.assertEqual(result["status"], "equivalent")
        self.assertEqual(result["candidate"]["ignored_notes"], 1)
        self.assertNotIn("private", json.dumps(result))

    def test_utf8_bom_and_crlf(self):
        old = self.write("a.srt", srt([(0, 100, "中文")]))
        new = self.root / "b.vtt"
        new.write_bytes(b"\xef\xbb\xbf" + vtt([(0, 100, "中文")]).replace("\n", "\r\n").encode())
        self.assertEqual(compare_files(old, new)["status"], "equivalent")

    def test_format_override(self):
        old = self.write("a.data", srt([(0, 100, "A")]))
        with self.assertRaisesRegex(CaptionError, "unsupported_format"):
            compare_files(old, old)
        self.assertEqual(
            compare_files(old, old, reference_format="srt", candidate_format="srt")["status"],
            "equivalent",
        )

    def test_unsupported_features_fail_closed(self):
        variants = [
            "WEBVTT\n\nSTYLE\n::cue {color:red}\n",
            "WEBVTT\n\nREGION\nid:x\n",
            "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00.000,MPEGTS:0\n\n",
            "WEBVTT\n\n00:00.000 --> 00:01.000 position:50%\nA\n",
        ]
        old = self.write("old.srt", srt([(0, 1000, "A")]))
        for content in variants:
            with self.subTest(content=content[:40]), self.assertRaises(CaptionError):
                compare_files(old, self.write("bad.vtt", content))

    def test_markup_and_reference_errors_are_content_free(self):
        for payload in [
            "<v Person>secret</v>",
            "<00:00.050>secret",
            "<b>secret",
            "<i>secret</b>",
            "<I>secret</I>",
            "<b class=x>secret</b>",
            "&unknown;",
            "AT&T",
            "&#0;",
            "&#xD800;",
            "&#999999999999;",
            "&notarealentity;",
            "&#" + "1" * 80 + ";",
            r"{\an8}secret",
            "secret --> other",
            "<secret",
            "<b></b>",
        ]:
            with self.subTest(payload=payload[:30]), self.assertRaises(CaptionError) as caught:
                self.pair([(0, 100, "A")], [(0, 100, payload)])
            self.assertNotIn("secret", str(caught.exception))

    def test_invalid_timestamps_and_duration(self):
        for timing in [
            "00:00:00,000 --> 00:00:00,000",
            "00:00:01,000 --> 00:00:00,000",
            "00:60:00,000 --> 01:00:01,000",
            "00:00:60,000 --> 01:00:01,000",
            "00:00:00.000 --> 00:00:01.000",
            "0:00:00,000 --> 00:00:01,000",
        ]:
            path = self.write("bad.srt", f"1\n{timing}\nA\n")
            with self.subTest(timing=timing), self.assertRaises(CaptionError):
                compare_files(path, path)

    def test_missing_headers_indices_timing_and_payload(self):
        for name, content in [
            ("bad.vtt", "no header\n"),
            ("bad.srt", "not-an-index\n"),
            ("bad.srt", "0\n00:00:00,000 --> 00:00:01,000\nA\n"),
            ("bad.srt", "1\n"),
            ("bad.srt", "1\n00:00:00,000 --> 00:00:01,000\n"),
        ]:
            path = self.write(name, content)
            with self.subTest(content=content), self.assertRaises(CaptionError):
                compare_files(path, path)

    def test_size_encoding_and_control_errors(self):
        good = self.write("good.srt", srt([(0, 100, "A")]))
        for raw, code in [(b"\xff", "not_utf8"), (b"\x00", "control_character")]:
            bad = self.root / "bad.srt"
            bad.write_bytes(raw)
            with self.assertRaisesRegex(CaptionError, code):
                compare_files(good, bad)
        with self.assertRaisesRegex(CaptionError, "size_limit"):
            compare_files(good, good, max_bytes=10)

    def test_missing_file_and_directory(self):
        good = self.write("good.srt", srt([(0, 100, "A")]))
        for path in [self.root / "absent.srt", self.root]:
            with self.assertRaises(CaptionError):
                compare_files(good, path, candidate_format="srt")

    def test_cue_and_concurrency_limits(self):
        rows = [(0, 100, str(i)) for i in range(5)]
        with self.assertRaisesRegex(CaptionError, "cue_limit"):
            self.pair(rows, rows, max_cues=4)
        with self.assertRaisesRegex(CaptionError, "active_cue_limit"):
            self.pair(rows, rows, max_active=4)

    def test_bad_limits(self):
        for options in [
            dict(max_bytes=0),
            dict(max_cues=0),
            dict(max_active=-1),
            dict(max_findings=-1),
            dict(max_different_ms=-1),
            dict(max_bytes=True),
        ]:
            with (
                self.subTest(options=options),
                self.assertRaisesRegex(CaptionError, "invalid_limits"),
            ):
                self.pair([], [], **options)

    def test_no_transcript_or_paths_in_receipt(self):
        result = self.pair([(0, 100, "PRIVATE-SOURCE")], [(0, 100, "PRIVATE-CANDIDATE")])
        receipt = json.dumps(result)
        self.assertNotIn("PRIVATE", receipt)
        self.assertNotIn(str(self.root), receipt)

    def test_cli_exit_codes_and_unchanged_inputs(self):
        old = self.write("old.srt", srt([(0, 100, "PRIVATE")]))
        new = self.write("new.vtt", vtt([]))
        before = [hashlib.sha256(p.read_bytes()).digest() for p in (old, new)]
        for candidate, flags, code in [
            (old, [], 0),
            (new, [], 1),
            (new, ["--max-different-ms", "100"], 0),
            (self.root / "absent.vtt", [], 2),
        ]:
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "caption_equivalence",
                    str(old),
                    str(candidate),
                    "--json",
                    *flags,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(run.returncode, code, run.stderr)
            self.assertIn("status", json.loads(run.stdout))
            self.assertNotIn("PRIVATE", run.stdout + run.stderr)
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).digest() for p in (old, new)])

    def test_text_cli_with_findings_and_truncation(self):
        old = self.write("old.srt", srt([(0, 100, "A"), (200, 300, "A")]))
        new = self.write("new.vtt", vtt([]))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(old), str(new), "--max-findings", "1"]), 1)
        self.assertIn("omitted", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main([str(old), "absent.vtt"]), 2)
        self.assertIn("ERROR", out.getvalue())

    def test_random_timeline_oracle_and_symmetry(self):
        rng = random.Random(2048)
        for iteration in range(200):
            tracks = []
            for _ in range(2):
                cues = []
                for index in range(rng.randrange(9)):
                    begin = rng.randrange(50)
                    cues.append(
                        Cue(begin, begin + rng.randrange(1, 15), rng.choice("ABC"), index + 1)
                    )
                tracks.append(tuple(cues))
            # Independent exhaustive oracle over integer milliseconds; unlike
            # the implementation, it builds full active text multisets each tick.
            expected = sum(
                Counter(c.text for c in tracks[0] if c.start <= t < c.end)
                != Counter(c.text for c in tracks[1] if c.start <= t < c.end)
                for t in range(65)
            )
            with self.subTest(iteration=iteration):
                actual = _sweep(*tracks, max_findings=5, max_active=10)
                reverse = _sweep(tracks[1], tracks[0], max_findings=5, max_active=10)
                self.assertEqual(actual["different_ms"], expected)
                self.assertEqual(reverse["different_ms"], expected)

    def test_random_same_text_partition_invariance(self):
        rng = random.Random(4096)
        for _ in range(100):
            points = sorted({0, 100, *[rng.randrange(1, 100) for _ in range(12)]})
            pieces = tuple(
                Cue(a, b, "Same", i + 1)
                for i, (a, b) in enumerate(zip(points, points[1:], strict=False))
            )
            result = _sweep((Cue(0, 100, "Same", 1),), pieces, max_findings=1, max_active=1)
            self.assertEqual(result["different_ms"], 0)


if __name__ == "__main__":
    unittest.main()

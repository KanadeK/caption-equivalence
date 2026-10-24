"""Strict subset parsing and an exact millisecond event sweep."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from html.entities import html5
from pathlib import Path
from typing import Any

from . import __version__

MAX_BYTES = 16 * 1024 * 1024
SRT_TIME = re.compile(r"[0-9]{2,6}:[0-9]{2}:[0-9]{2},[0-9]{3}")
VTT_TIME = re.compile(r"(?:[0-9]{2,6}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3}")
TIMING = re.compile(r"(\S+)[ \t]+-->[ \t]+(\S+)")
ENTITY = re.compile(r"&(?:#[xX][0-9a-fA-F]+|#[0-9]+|[A-Za-z][A-Za-z0-9]+);")
TEXT_RUN = re.compile(r"[^<&]+")


class CaptionError(ValueError):
    """Stable diagnostics never include transcript lines or input paths."""

    def __init__(self, code: str, side: str = "options", line: int | None = None):
        self.code, self.side, self.line = code, side, line
        super().__init__(f"{side}: {code}" + (f" at line {line}" if line is not None else ""))


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    text: str
    line: int


@dataclass(frozen=True)
class Track:
    cues: tuple[Cue, ...]
    sha256: str
    format: str
    ignored_notes: int

    def summary(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "format": self.format,
            "cues": len(self.cues),
            "first_ms": min((cue.start for cue in self.cues), default=None),
            "last_ms": max((cue.end for cue in self.cues), default=None),
            "ignored_notes": self.ignored_notes,
        }


def _timestamp(value: str, format: str, side: str, line: int) -> int:
    if not (SRT_TIME if format == "srt" else VTT_TIME).fullmatch(value):
        raise CaptionError("invalid_timestamp", side, line)
    parts = value.replace(",", ".").split(":")
    hours = int(parts[0]) if len(parts) == 3 else 0
    minutes = int(parts[-2])
    seconds, milliseconds = (int(part) for part in parts[-1].split("."))
    if minutes >= 60 or seconds >= 60:
        raise CaptionError("timestamp_out_of_range", side, line)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def _plain(raw: str, side: str, line: int) -> str:
    """Remove only explicitly supported wrappers; reject timed/unknown markup."""
    if "-->" in raw or "{\\" in raw:
        raise CaptionError("unsupported_payload_syntax", side, line)
    result: list[str] = []
    stack: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "<":
            end = raw.find(">", index + 1)
            token = raw[index : end + 1] if end >= 0 else ""
            if not re.fullmatch(r"</?[biu]>", token):
                raise CaptionError("unsupported_markup", side, line)
            if token.startswith("</"):
                if not stack or stack.pop() != token[2]:
                    raise CaptionError("unbalanced_markup", side, line)
            else:
                stack.append(token[1])
            index = end + 1
        elif char == "&":
            match = ENTITY.match(raw, index)
            if match is None or len(match[0]) > 64:
                raise CaptionError("unsupported_character_reference", side, line)
            entity = match[0][1:-1]
            if entity.startswith("#"):
                number = int(entity[2:], 16) if entity[1:2].lower() == "x" else int(entity[1:])
                if number == 0 or number > 0x10FFFF or 0xD800 <= number <= 0xDFFF:
                    raise CaptionError("unsupported_character_reference", side, line)
            elif entity + ";" not in html5:
                raise CaptionError("unsupported_character_reference", side, line)
            decoded = html.unescape(match[0])
            if decoded == match[0] or any(
                (unicodedata.category(c) == "Cc" and c not in "\n\r\t")
                or unicodedata.category(c) == "Cs"
                for c in decoded
            ):
                raise CaptionError("unsupported_character_reference", side, line)
            result.append(decoded)
            index = match.end()
        else:
            run = TEXT_RUN.match(raw, index)
            result.append(run[0])
            index = run.end()
    if stack:
        raise CaptionError("unbalanced_markup", side, line)
    text = " ".join("".join(result).split())
    if not text:
        raise CaptionError("empty_cue_text", side, line)
    return text


def _blocks(lines: list[str], start: int):
    block: list[tuple[int, str]] = []
    for index in range(start, len(lines)):
        if not lines[index].strip():
            if block:
                yield block
                block = []
        else:
            block.append((index + 1, lines[index]))
    if block:
        yield block


def _load(path: Path, side: str, format: str | None, max_bytes: int, max_cues: int) -> Track:
    format = format or path.suffix.lstrip(".").casefold()
    if format not in {"srt", "vtt"}:
        raise CaptionError("unsupported_format", side)
    try:
        if not path.is_file():
            raise CaptionError("not_regular_file", side)
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except CaptionError:
        raise
    except (OSError, ValueError):
        raise CaptionError("cannot_read", side) from None
    if len(data) > max_bytes:
        raise CaptionError("size_limit", side)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise CaptionError("not_utf8", side) from None
    if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in text):
        raise CaptionError("control_character", side)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = 0
    if format == "vtt":
        if not re.fullmatch(r"WEBVTT(?:[ \t].*)?", lines[0]) or "-->" in lines[0]:
            raise CaptionError("missing_webvtt_header", side, 1)
        if len(lines) > 1 and lines[1].strip():
            raise CaptionError("unsupported_header_metadata", side, 2)
        start = 1
    cues: list[Cue] = []
    ignored_notes = 0
    for block in _blocks(lines, start):
        number, first = block[0]
        if format == "vtt":
            if first == "NOTE" or first.startswith(("NOTE ", "NOTE\t")):
                ignored_notes += 1
                continue
            if first in {"STYLE", "REGION"}:
                raise CaptionError("unsupported_style_or_region", side, number)
            timing_index = 0 if "-->" in first else 1
        else:
            if not re.fullmatch(r"[0-9]{1,10}", first) or int(first) == 0:
                raise CaptionError("invalid_srt_index", side, number)
            timing_index = 1
        if len(block) <= timing_index:
            raise CaptionError("missing_timing", side, number)
        timing_line, timing_text = block[timing_index]
        timing = TIMING.fullmatch(timing_text)
        if timing is None:
            raise CaptionError("invalid_timing_or_settings", side, timing_line)
        begin = _timestamp(timing[1], format, side, timing_line)
        end = _timestamp(timing[2], format, side, timing_line)
        if end <= begin:
            raise CaptionError("nonpositive_duration", side, timing_line)
        if len(block) == timing_index + 1:
            raise CaptionError("missing_cue_text", side, timing_line)
        payload = "\n".join(value for _, value in block[timing_index + 1 :])
        normalized = _plain(payload, side, block[timing_index + 1][0])
        cues.append(Cue(begin, end, normalized, timing_line))
        if len(cues) > max_cues:
            raise CaptionError("cue_limit", side, timing_line)
    return Track(tuple(cues), hashlib.sha256(data).hexdigest(), format, ignored_notes)


def _sweep(
    reference: tuple[Cue, ...], candidate: tuple[Cue, ...], max_findings: int, max_active: int
) -> dict[str, Any]:
    events: dict[int, list[tuple[int, int, int, Cue]]] = defaultdict(list)
    for side, cues in enumerate((reference, candidate)):
        for index, cue in enumerate(cues):
            events[cue.start].append((side, index, 1, cue))
            events[cue.end].append((side, index, -1, cue))
    times = sorted(events)
    active: list[dict[int, Cue]] = [{}, {}]
    balance: dict[str, int] = {}
    missing = added = different_ms = intervals = 0
    findings = []
    for position, time in enumerate(times[:-1]):
        for side, index, change, cue in events[time]:
            if change == 1:
                active[side][index] = cue
            else:
                active[side].pop(index)
            old = balance.get(cue.text, 0)
            missing -= max(old, 0)
            added -= max(-old, 0)
            new = old + (change if side == 0 else -change)
            if new:
                balance[cue.text] = new
            else:
                balance.pop(cue.text, None)
            missing += max(new, 0)
            added += max(-new, 0)
        for side, entries in enumerate(active):
            if len(entries) > max_active:
                raise CaptionError("active_cue_limit", "reference" if side == 0 else "candidate")
        if missing or added:
            duration = times[position + 1] - time
            different_ms += duration
            intervals += 1
            if len(findings) < max_findings:
                old_lines = sorted(
                    cue.line for cue in active[0].values() if balance.get(cue.text, 0) > 0
                )
                new_lines = sorted(
                    cue.line for cue in active[1].values() if balance.get(cue.text, 0) < 0
                )
                findings.append(
                    {
                        "start_ms": time,
                        "end_ms": times[position + 1],
                        "kind": "changed"
                        if missing and added
                        else "missing"
                        if missing
                        else "added",
                        "missing_cue_count": missing,
                        "added_cue_count": added,
                        "reference_lines": old_lines[:8],
                        "candidate_lines": new_lines[:8],
                        "reference_lines_truncated": len(old_lines) > 8,
                        "candidate_lines_truncated": len(new_lines) > 8,
                    }
                )
    return {
        "different_ms": different_ms,
        "different_intervals": intervals,
        "findings": findings,
        "findings_truncated": intervals > len(findings),
    }


def compare_files(
    reference: str | Path,
    candidate: str | Path,
    *,
    reference_format: str | None = None,
    candidate_format: str | None = None,
    max_different_ms: int = 0,
    max_findings: int = 50,
    max_bytes: int = MAX_BYTES,
    max_cues: int = 50_000,
    max_active: int = 256,
    allow_empty_reference: bool = False,
) -> dict[str, Any]:
    """Compare exact normalized active text multisets on [start, end) intervals."""
    if any(
        type(n) is not int or n < minimum
        for n, minimum in [
            (max_different_ms, 0),
            (max_findings, 0),
            (max_bytes, 1),
            (max_cues, 1),
            (max_active, 1),
        ]
    ):
        raise CaptionError("invalid_limits")
    old = _load(Path(reference), "reference", reference_format, max_bytes, max_cues)
    new = _load(Path(candidate), "candidate", candidate_format, max_bytes, max_cues)
    if not old.cues and not allow_empty_reference:
        raise CaptionError("empty_reference", "reference")
    result = _sweep(old.cues, new.cues, max_findings, max_active)
    status = (
        "equivalent"
        if result["different_ms"] == 0
        else "within_budget"
        if result["different_ms"] <= max_different_ms
        else "different"
    )
    return {
        "schema_version": 1,
        "tool_version": __version__,
        "status": status,
        "reference": old.summary(),
        "candidate": new.summary(),
        "budget_ms": max_different_ms,
        **result,
    }

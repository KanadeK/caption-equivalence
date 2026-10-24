# caption-equivalence

Check that an SRT/WebVTT conversion preserves normalized caption text **over time**.
The CLI compares active text multisets on exact millisecond intervals, reports
missing, added or changed text, and accepts adjacent splitting of the same text.

[简体中文](README.zh-CN.md) · Python 3.11+ · MIT · No runtime dependencies

For example, one cue showing `Hold` from 0–2 seconds is equivalent to two `Hold`
cues covering 0–1 and 1–2 seconds. A missing 1–2 second segment is a 1,000 ms
regression. A cue-number or line diff cannot express this acceptance contract.

## Install

```sh
git clone https://github.com/KanadeK/caption-equivalence.git
cd caption-equivalence
python -m venv .venv
```

Activate with `source .venv/bin/activate` (Linux/macOS) or
`.\.venv\Scripts\Activate.ps1` (PowerShell), then:

```sh
python -m pip install .
caption-equivalence --version
```

## Run a complete acceptance workflow

```sh
caption-equivalence examples/reference.srt examples/resegmented.vtt --json
# Exit 0, equivalent: different cue counts, same text on every interval.
caption-equivalence examples/reference.srt examples/missing-tail.vtt --json
# Exit 1, different: 1,000 ms of reference text is missing.
caption-equivalence examples/reference.srt examples/empty.vtt --json
# Exit 1: an empty conversion loses all 3,000 ms of reference coverage.
```

These are original synthetic caption fixtures, not dialogue from copyrighted media.
Input files are never changed. Text/JSON reports omit transcript text, cue IDs,
comments, filenames and input paths. They contain file SHA-256 values, counts,
interval times and bounded timing-line references. Reports still expose timing
metadata; file hashes are not a guarantee of anonymity.

## What equivalence means

Each cue is active on `[start, end)`; its end is exclusive. At every boundary in
either track, the tool compares a **multiset of normalized cue strings**. Duplicate
overlapping captions count multiple times. Source file order and cue numbers/IDs
are not part of this text contract.

Normalization decodes supported, semicolon-terminated HTML character references,
removes balanced lowercase `<b>`, `<i>` and `<u>` wrappers without attributes,
and collapses all Unicode whitespace into single spaces. Text case, punctuation
and Unicode normalization differences remain significant. Encoded tags such as
`&lt;i&gt;` remain literal text; they are not interpreted again as markup.

Changing line wrapping or splitting one cue into adjacent cues with identical
normalized text is accepted. Splitting `Hello world` into successive `Hello` and
`world` cues is a timing/text change and is rejected. Combining simultaneous
separate cues into one concatenated cue is also outside this conservative contract.
It is not word alignment, semantic similarity or a pixel comparison of rendered
subtitles. Formatting and position fidelity are not evaluated.

`different_ms` is the duration of the union of intervals with unequal text
multisets; it is not multiplied by the number of missing cues. Findings classify
an interval as `missing`, `added` or `changed` and give unmatched cue counts.
`different_intervals` counts atomic boundary intervals, so harmless extra cue
boundaries can change that count during an already-different span.

## Explicit policies

```sh
# Accept up to 20 ms of total disagreement, but retain the true duration/details.
caption-equivalence before.srt after.vtt --max-different-ms 20 --json
# Hide details while still checking and counting every interval.
caption-equivalence before.srt after.vtt --max-findings 0 --json
```

Zero disagreement produces `equivalent`; nonzero disagreement within an explicit
budget produces `within_budget`. Both exit 0, but the statuses are distinct.
There is no automatic timing alignment or rounding tolerance. An empty reference
is an error unless `--allow-empty-reference` is explicitly given. An empty valid
candidate remains comparable and fails against a nonempty reference.

| Exit | Meaning |
| --- | --- |
| 0 | Equivalent, or within an explicitly requested disagreement budget |
| 1 | Text/timing disagreement exceeds the budget |
| 2 | Invalid, unsupported, unreadable or resource-limited input |

## Supported subset and limits

- UTF-8 SRT and WebVTT, with optional UTF-8 BOM; LF, CRLF and CR are accepted.
  Extensions select the parser; override with `--reference-format srt|vtt` and
  `--candidate-format srt|vtt` for differently named files.
- SRT needs a positive numeric index, `HH:MM:SS,mmm` timings and nonempty text.
  Indices need not be sequential. WebVTT needs a `WEBVTT` header, an optional
  cue identifier, and `HH:MM:SS.mmm` or `MM:SS.mmm` timings. Hours use 2–6 digits;
  minutes/seconds must be below 60 and durations positive.
- WebVTT NOTE blocks and header descriptions are ignored and notes are counted.
  STYLE/REGION blocks, timing settings, timestamp-map header metadata, voice/ruby/
  class/language spans, inline karaoke timestamps, ASS overrides, unknown tags,
  unbalanced wrappers, ambiguous raw ampersands and invalid references are rejected.
  Rejection fails the gate; it never silently claims unsupported fidelity.
- Default per-file limits: 16 MiB (`--max-bytes`), 50,000 cues (`--max-cues`),
  256 simultaneously active cues (`--max-active`). Default report limit is 50
  intervals (`--max-findings`), with at most 8 timing-line references per side
  per finding. All detection/counting continues when details are truncated.

The sweep uses cue boundaries, not a millisecond-by-millisecond loop; long quiet
or constant-caption spans are cheap. Files/cues/events are held in memory within
the input limits. These are application limits, not an OS-level hostile-file sandbox.

## When to use another tool

Use [SubtitleEdit](https://github.com/SubtitleEdit/subtitleedit) or
[pysubs2](https://github.com/tkarabela/pysubs2) to edit, convert or retime captions.
[subtool](https://github.com/maxgfr/subtool) provides broader subtitle workflows,
and [DuoSubs](https://github.com/CK-Explorer/DuoSubs) aligns bilingual subtitles by
meaning. This project performs a narrow, deterministic CI check after conversion,
without a GUI, model downloads, audio analysis or runtime network requests.
It follows a documented subset rather than claiming full
[WebVTT](https://www.w3.org/TR/webvtt1/) renderer conformance.

## Development and cleanup

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests, lint, coverage, build and isolated
wheel installation. The suite includes an independent exhaustive timeline oracle
and randomized partition invariance checks. CI covers Linux, Windows and macOS
and never creates commits. [Private security reporting](SECURITY.md) is available.

Uninstall with `python -m pip uninstall caption-equivalence`. Deactivate and remove
the dedicated virtual environment to clean up. There are no persistent caches,
background jobs, downloaded models or user-data directories.

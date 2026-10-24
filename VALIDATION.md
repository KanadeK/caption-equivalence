# Validation for 0.1.0

Executed locally on Windows / Python 3.13.16, 2026-10-24:

- 35 unittest cases passed; combined statement/branch coverage was 97%.
- The suite includes 200 seeded random timeline comparisons against an independent
  exhaustive per-millisecond Counter oracle, also checking swap symmetry, plus
  100 random partitions proving same-text adjacent splitting remains equivalent.
- Deterministic cases cover missing/extra/changed text, duplicate overlaps, exact
  boundaries and budgets, reflow/basic wrappers/entities, empty conversions,
  bounded reports, malformed timestamps/markup and unsupported WebVTT features.
- Ruff lint and format checks passed; source distribution and wheel built.
- A fresh virtual environment outside the checkout installed the wheel, ran the
  equivalent/missing-tail/empty-candidate fixtures with actual expected durations
  0/1000/3000 ms and exit codes 0/1/1, and uninstalled it successfully.
- An independent manual interoperability probe used separately installed MIT
  pysubs2 1.9.0 to convert two original synthetic SRT cues to WebVTT. The conversion
  was equivalent. Moving both cues by 20 ms produced exactly 80 ms of disagreement
  (two 20 ms edges for each of two disjoint cues), as expected.
- No third-party runtime dependencies are present. Manual review checked parsing,
  supported-feature rejection, half-open intervals, multiplicity, content-free
  diagnostics, resource limits and license/provenance.

Review replaced per-character text accumulation with contiguous runs to avoid
unnecessary large lists for long cue payloads. Unknown entities and unsupported
timed markup are rejected rather than silently normalized into a claimed pass.
No audio, renderer layout or translation-quality correctness is claimed. The
repository's Actions page records the authoritative cross-platform CI outcomes.

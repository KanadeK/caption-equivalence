import argparse
import json

from . import __version__
from .core import MAX_BYTES, CaptionError, compare_files


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gate normalized SRT/WebVTT text over time.")
    parser.add_argument("reference")
    parser.add_argument("candidate")
    parser.add_argument("--reference-format", choices=["srt", "vtt"])
    parser.add_argument("--candidate-format", choices=["srt", "vtt"])
    parser.add_argument("--max-different-ms", type=int, default=0)
    parser.add_argument("--max-findings", type=int, default=50)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--max-cues", type=int, default=50_000)
    parser.add_argument("--max-active", type=int, default=256)
    parser.add_argument("--allow-empty-reference", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        result = compare_files(
            args.reference,
            args.candidate,
            reference_format=args.reference_format,
            candidate_format=args.candidate_format,
            max_different_ms=args.max_different_ms,
            max_findings=args.max_findings,
            max_bytes=args.max_bytes,
            max_cues=args.max_cues,
            max_active=args.max_active,
            allow_empty_reference=args.allow_empty_reference,
        )
    except CaptionError as exc:
        result = {
            "schema_version": 1,
            "status": "error",
            "error": {"code": exc.code, "side": exc.side, "line": exc.line},
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    elif result["status"] == "error":
        error = result["error"]
        print(f"ERROR {error['side']}: {error['code']} (line {error['line']})")
    else:
        print(
            f"{result['status'].upper()}: {result['different_ms']} differing ms across "
            f"{result['different_intervals']} boundary interval(s); budget {result['budget_ms']} ms"
        )
        for finding in result["findings"]:
            print(f"  {finding['start_ms']}..{finding['end_ms']} ms: {finding['kind']}")
        if result["findings_truncated"]:
            print("  More intervals omitted; duration and counts remain complete.")
    return 2 if result["status"] == "error" else int(result["status"] == "different")

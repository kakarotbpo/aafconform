"""Command-line entry point."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import __version__
from .inspect_aaf import DumpOptions, dump_json, dump_text


def _cmd_inspect(args: argparse.Namespace) -> int:
    kinds = tuple(args.kind) if args.kind else ("CompositionMob", "MasterMob", "SourceMob")
    opts = DumpOptions(extras=not args.no_extras, mob_filter=args.mob, kinds=kinds)
    text = dump_json(args.aaf, opts) if args.json else dump_text(args.aaf, opts)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


def _pin(value: str) -> int:
    m = re.fullmatch(r"[Aa]?(\d+)", value.strip())
    if not m or int(m.group(1)) < 1:
        raise argparse.ArgumentTypeError("use an audio track like A1")
    return int(m.group(1)) - 1


def _cmd_conform(args: argparse.Namespace) -> int:
    from . import report
    from .aafread import ReadError
    from .aafwrite import WriteError
    from .api import default_output
    from .conform import ConformError, conform
    from .match import MatchError

    output = Path(args.output) if args.output else Path(default_output(args.cut))
    try:
        r = conform(
            args.reference,
            args.cut,
            output,
            pin=args.pin,
            reference_seq=args.reference_seq,
            cut_seq=args.cut_seq,
            force=args.force,
        )
    except (ConformError, ReadError, WriteError, MatchError) as e:
        sys.stderr.write(f"aafconform: {e}\n")
        return 1
    out = sys.stdout
    out.write(f"Reference: {r.reference_name}\n")
    out.write(f"Cut:       {r.cut_name}\n")
    out.write(f"Wrote:     {output}  (sequence '{r.output_name}')\n\n")
    out.write(report.text(r.plan, r.reference, r.cut, r.tc_start, r.fps, r.drop))
    all_rows = report.rows(r.plan, r.reference, r.tc_start, r.fps, r.drop)
    if args.csv:
        report.write_csv(args.csv, all_rows)
    if args.json:
        summary = {
            "reference": r.reference_name,
            "cut": r.cut_name,
            "output": str(output),
            "sequence": r.output_name,
            "flagged": len(r.plan.flagged),
        }
        report.write_json(args.json, all_rows, summary)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aafconform",
        description="Rebuild an Avid cut against the proper multigroup from a reference sequence.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="dump the structure of an AAF (read-only)")
    p.add_argument("aaf", help="AAF file to inspect")
    p.add_argument("--json", action="store_true", help="full property tree as JSON")
    p.add_argument("--mob", help="only mobs whose name or MobID contains this text")
    p.add_argument(
        "--kind",
        action="append",
        choices=["CompositionMob", "MasterMob", "SourceMob"],
        help="only this mob class (repeatable)",
    )
    p.add_argument("--no-extras", action="store_true", help="hide unmodelled properties")
    p.add_argument("-o", "--output", help="write to file instead of stdout")
    p.set_defaults(func=_cmd_inspect)

    p = sub.add_parser(
        "conform",
        help="write a new AAF: the cut's edits on the reference's track layout",
    )
    p.add_argument("reference", help="master layout AAF (correct multigroup mapping)")
    p.add_argument("cut", help="cut AAF to fix (never modified)")
    p.add_argument("-o", "--output", help="new AAF to write (default: '<cut> CONFORMED.aaf')")
    p.add_argument(
        "--pin",
        type=_pin,
        help="cut audio track whose edit points new tracks follow (default: the mix track)",
    )
    p.add_argument("--reference-seq", help="reference sequence name, if it has several")
    p.add_argument("--cut-seq", help="cut sequence name, if it has several")
    p.add_argument("--csv", help="also write the event report as CSV")
    p.add_argument("--json", help="also write the event report as JSON")
    p.add_argument("--force", action="store_true", help="replace the output if it exists")
    p.set_defaults(func=_cmd_conform)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

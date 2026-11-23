"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

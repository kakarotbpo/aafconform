"""Start the aafconform desktop app.

aafconform-app              open the window
aafconform-app --self-test  conform two built-in test files, no window
aafconform-app --serve      serve the interface to a browser (development)
"""

from __future__ import annotations

import argparse
import sys


def self_test() -> int:
    """Prove a packaged build works end to end: no window, no samples needed."""
    import tempfile
    from pathlib import Path

    from .. import api
    from ..synthetic import build_avid_group
    from .window import UI

    # The interface files must have made it into the build.
    missing = [
        p
        for p in (
            UI,
            UI.parent / "app.js",
            UI.parent / "app.css",
            UI.parent / "fonts" / "SpaceGrotesk.woff2",
        )
        if not p.is_file()
    ]
    if missing:
        print("self-test FAILED: missing", *missing)
        return 1

    with tempfile.TemporaryDirectory() as d:
        ref, cut = Path(d) / "layout.aaf", Path(d) / "pull.aaf"
        build_avid_group(str(ref), str(cut))
        result = api.conform(ref, cut, Path(d) / "out.aaf", csv_path=Path(d) / "r.csv")
        ok = (
            result["totals"]["built"] > 0
            and result["totals"]["corrected"] > 0
            and Path(result["output"]).exists()
            and Path(result["csv"]).exists()
        )
    print("self-test", "passed" if ok else "FAILED", result["totals"])
    if ok and sys.platform == "win32":
        # Load the window's .NET runtime (pythonnet) the way opening the
        # window does, without showing one.
        try:
            import webview.platforms.winforms  # noqa: F401
        except Exception as e:
            print("self-test FAILED: window runtime did not load:", type(e).__name__, e)
            return 1
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aafconform-app")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8765, help=argparse.SUPPRESS)
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--log", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.log:  # a windowed exe has no console: write output to a file
        sys.stdout = sys.stderr = open(args.log, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    if args.self_test:
        return self_test()
    if args.serve:
        from .devserver import serve

        serve(args.port)
        return 0
    from .window import run

    run(debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())

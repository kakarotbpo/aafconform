"""PyInstaller entry point for the desktop app (a plain script, so no relative imports)."""

import sys

from aafconform.app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

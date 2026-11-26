"""What the app window can ask Python to do.

Every method returns {"ok": True, "data": ...} or {"ok": False, "error": "..."}
so the interface never has to parse a Python traceback. Nothing here needs a
window, so it is tested directly; the window only adds file dialogs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import __version__, api


def _ok(data=None) -> dict:
    return {"ok": True, "data": data}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message}


def _call(fn, *args, **kwargs) -> dict:
    try:
        return _ok(fn(*args, **kwargs))
    except api.ApiError as e:
        return _fail(str(e))
    except Exception as e:  # never let an unexpected error kill the window
        return _fail(f"Unexpected error: {type(e).__name__}: {e}")


def _pin(value) -> int | None:
    """'A3' or 3 (1-based) from the interface, to a 0-based track index."""
    if value in (None, "", "auto"):
        return None
    text = str(value).strip().upper().lstrip("A")
    return int(text) - 1 if text.isdigit() and int(text) > 0 else None


class Bridge:
    """Methods exposed to the interface's JavaScript as window.pywebview.api."""

    def __init__(self) -> None:
        self._window = None  # set by the app when running in a real window

    def attach(self, window) -> None:
        self._window = window

    # -- files ---------------------------------------------------------------

    def version(self) -> dict:
        return _ok(__version__)

    def describe(self, path: str) -> dict:
        return _call(api.describe, path)

    def default_output(self, cut: str) -> dict:
        return _call(api.default_output, cut)

    def output_exists(self, path: str) -> dict:
        return _ok(bool(path) and Path(path).exists())

    # -- conform -------------------------------------------------------------

    def preview(self, reference: str, cut: str, pin=None) -> dict:
        return _call(api.preview, reference, cut, pin=_pin(pin))

    def conform(
        self,
        reference: str,
        cut: str,
        output: str,
        pin=None,
        csv: bool = True,
        json: bool = False,
        replace: bool = False,
    ) -> dict:
        out = Path(output)
        if out.suffix.lower() != ".aaf":  # "EP101 v1.2" is a name, not a .2 file
            out = out.with_name(out.name + ".aaf")
        stem = out.with_suffix("")
        return _call(
            api.conform,
            reference,
            cut,
            out,
            pin=_pin(pin),
            force=bool(replace),
            csv_path=f"{stem} report.csv" if csv else None,
            json_path=f"{stem} report.json" if json else None,
        )

    # -- desktop -------------------------------------------------------------

    def choose_file(self, title: str = "Choose an AAF") -> dict:
        """Open dialog. Returns the chosen path, or None if cancelled."""
        if self._window is None:
            return _fail("File dialogs need the desktop app")
        import webview

        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("AAF files (*.aaf)", "All files (*.*)")
        )
        return _ok(result[0] if result else None)

    def choose_output(self, suggested: str) -> dict:
        """Save dialog for the new AAF."""
        if self._window is None:
            return _fail("File dialogs need the desktop app")
        import webview

        p = Path(suggested) if suggested else Path.home() / "conformed.aaf"
        result = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(p.parent),
            save_filename=p.name,
            file_types=("AAF files (*.aaf)",),
        )
        if not result:
            return _ok(None)
        chosen = result if isinstance(result, str) else result[0]
        if not chosen.lower().endswith(".aaf"):
            chosen += ".aaf"
        return _ok(chosen)

    def reveal(self, path: str) -> dict:
        """Show a file in Explorer (or Finder / the file manager)."""
        p = Path(path)
        if not p.exists():
            return _fail(f"not found: {p}")
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(p)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p.parent)])
        except OSError as e:
            return _fail(f"Could not open the folder: {e}")
        return _ok()

    def open_file(self, path: str) -> dict:
        """Open a file (the CSV report) in its default app."""
        p = Path(path)
        if not p.exists():
            return _fail(f"not found: {p}")
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # noqa: S606 - opening the user's own report
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except OSError as e:
            return _fail(f"Could not open the file: {e}")
        return _ok()

"""The desktop window: the HTML interface in a native window via pywebview."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from functools import partial
from pathlib import Path

from .bridge import Bridge

UI = Path(__file__).resolve().parent / "ui" / "index.html"


def _windows_setup() -> str | None:
    """Windows-only window fixes. Returns the folder for the browser's profile.

    - The interface is always dark, but pywebview colours the title bar from
      the Windows app theme, so a light setting gave a white bar over it.
    - Left to itself, pywebview gives the browser a new temporary profile on
      every launch (slower start, and a folder left behind in %TEMP% each
      time). A fixed folder is reused instead; private mode still keeps no
      cookies or site data.
    """
    if sys.platform != "win32":
        return None
    from webview.platforms import winforms

    winforms.BrowserView.BrowserForm.is_dark_theme = lambda self: True
    base = os.environ.get("LOCALAPPDATA")
    return str(Path(base) / "aafconform" / "webview") if base else None


BACKGROUND = "#0e0e10"  # --bg in ui/app.css
# Wait for the page's fonts and its first paint, so the page replaces the
# "Starting" text in one go.
PAINTED_JS = (
    "document.fonts.ready.then(() => new Promise("
    "r => requestAnimationFrame(() => requestAnimationFrame(() => r(true)))))"
)


def _add_starting_label(form):
    """Windows: "Starting aafconform..." over the window until the page shows.

    The window appears as soon as the .NET runtime is up, but WebView2 takes
    a second or so more to show the page (several on the very first launch),
    and an empty window reads as a launch that failed. A label is added on
    top of the browser area before the window is shown.
    """
    from System.Drawing import ColorTranslator, ContentAlignment, Font
    from System.Windows.Forms import DockStyle, Label

    label = Label()
    label.Text = "Starting aafconform\u2026"
    label.Dock = DockStyle.Fill
    label.TextAlign = ContentAlignment.MiddleCenter
    label.BackColor = ColorTranslator.FromHtml(BACKGROUND)
    label.ForeColor = ColorTranslator.FromHtml("#9b9893")  # --muted
    label.Font = Font("Segoe UI", 10.5)
    form.Controls.Add(label)
    label.BringToFront()
    return label


def _remove_starting_label(form, label) -> None:
    from System import Action

    def remove() -> None:
        form.Controls.Remove(label)
        label.Dispose()

    form.Invoke(Action(remove))


def run(debug: bool = False, started: float | None = None, launch_test: bool = False) -> None:
    """Open the window. `launch_test` closes it again once it is ready to use."""
    t0 = time.perf_counter() if started is None else started

    def mark(what: str) -> None:
        print(f"{time.perf_counter() - t0:5.2f}s {what}", flush=True)

    import webview
    from webview.dom import DOMEventHandler

    storage = _windows_setup()
    bridge = Bridge()
    window = webview.create_window(
        "aafconform",
        url=str(UI),
        js_api=bridge,
        width=1280,
        height=900,
        min_size=(960, 680),
        maximized=True,  # the check and report screens need the room
        background_color=BACKGROUND,
        text_select=True,
    )
    bridge.attach(window)

    def on_drop(zone: str, event: dict) -> None:
        # pywebview adds the dropped file's real path; the page can't see it.
        files = (event.get("dataTransfer") or {}).get("files") or []
        path = files[0].get("pywebviewFullPath") if files else None
        print(f"drop on {zone}: {len(files)} file(s), path {path!r}", flush=True)
        args = json.dumps([zone, path] if path else [zone])
        call = "dropped" if path else "dropFailed"
        window.evaluate_js(f"window.app && app.{call}(...{args})")

    def on_loaded() -> None:
        mark("page loaded")
        try:
            for zone in ("reference", "cut"):
                element = window.dom.get_element(f"#drop-{zone}")
                if element is None:
                    print(f"drop zone {zone}: element not found", flush=True)
                    continue
                # Not `element.events.drop +=`: pywebview only lists on* handlers two
                # prototypes up, which misses `ondrop` on a <section>, so that raised
                # AttributeError in this thread and drops silently did nothing.
                element.on("drop", DOMEventHandler(partial(on_drop, zone), True, True))
                print(f"drop zone {zone}: ready", flush=True)
            painted = threading.Event()  # promises only resolve through a callback
            window.evaluate_js(PAINTED_JS, lambda _: painted.set())
            painted.wait(5)
        finally:  # never leave the label over the app
            if starting:
                _remove_starting_label(window.native, starting.pop())
        mark("ready")
        if launch_test:
            window.destroy()

    starting = []  # the "Starting" label, on Windows
    if sys.platform == "win32":
        # before_show runs on the window's thread, before it first appears.
        window.events.before_show += lambda: starting.append(_add_starting_label(window.native))
    window.events.shown += lambda: mark("window shown")
    window.events.loaded += on_loaded
    mark("opening the window")
    # Served over pywebview's local http server: browsers refuse fonts over file://.
    webview.start(debug=debug, http_server=True, storage_path=storage)

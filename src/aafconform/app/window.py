"""The desktop window: the HTML interface in a native window via pywebview."""

from __future__ import annotations

import json
import os
import sys
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


def run(debug: bool = False) -> None:
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
        background_color="#0e0e10",
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

    window.events.loaded += on_loaded
    # Served over pywebview's local http server: browsers refuse fonts over file://.
    webview.start(debug=debug, http_server=True, storage_path=storage)

"""The desktop window: the HTML interface in a native window via pywebview."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path

from .bridge import Bridge

UI = Path(__file__).resolve().parent / "ui" / "index.html"


def run(debug: bool = False) -> None:
    import webview
    from webview.dom import DOMEventHandler

    bridge = Bridge()
    window = webview.create_window(
        "aafconform",
        url=str(UI),
        js_api=bridge,
        width=1280,
        height=900,
        min_size=(960, 680),
        background_color="#0e0e10",
        text_select=True,
    )
    bridge.attach(window)

    def on_drop(zone: str, event: dict) -> None:
        # pywebview adds the dropped file's real path; the page can't see it.
        files = (event.get("dataTransfer") or {}).get("files") or []
        path = files[0].get("pywebviewFullPath") if files else None
        if path:
            window.evaluate_js(f"window.app && app.dropped({json.dumps(zone)}, {json.dumps(path)})")

    def on_loaded() -> None:
        for zone in ("reference", "cut"):
            element = window.dom.get_element(f"#drop-{zone}")
            if element is not None:
                element.events.drop += DOMEventHandler(partial(on_drop, zone), True, True)

    window.events.loaded += on_loaded
    # Served over pywebview's local http server: browsers refuse fonts over file://.
    webview.start(debug=debug, http_server=True)

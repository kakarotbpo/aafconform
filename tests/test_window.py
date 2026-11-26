"""The real desktop window, run offscreen on pywebview's Qt backend.

The Windows app uses WebView2, but the DOM event wiring between the page and
Python is pywebview's shared code, and it is where drops once silently broke:
the handler was never attached, and the only sign was an error in a thread of
a windowed app with no console. A drop is replayed here with the file path
pywebview gets from WebView2 on Windows; the file must load.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("webview")
pytest.importorskip("qtpy")
pytest.importorskip("PyQt6.QtWebEngineWidgets")

DRIVER = r"""
import json, sys, threading, time
import webview
from webview.dom import _dnd_state
from aafconform.app import window as appwin

path, name = sys.argv[1], sys.argv[2]

def until(w, js, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if w.evaluate_js(js):
            return True
        time.sleep(0.2)
    return False

def drive():
    try:
        while not webview.windows:
            time.sleep(0.1)
        w = webview.windows[0]
        w.events.loaded.wait(60)
        if not until(w, "Object.keys(window.pywebview._eventHandlers || {}).length >= 2"):
            print("RESULT no drop handlers", flush=True)
            return
        _dnd_state["paths"].append((name, path))  # what WebView2 hands pywebview
        w.evaluate_js('''(() => {
          const dt = new DataTransfer();
          dt.items.add(new File(["x"], %s));
          const el = document.querySelector("#drop-reference");
          for (const t of ["dragenter", "dragover", "drop"])
            el.dispatchEvent(new DragEvent(t, {dataTransfer: dt, bubbles: true, cancelable: true}));
        })()''' % json.dumps(name))
        until(w, "!!app.state.files.reference || !!app.state.errors.reference", 30)
        print("RESULT", w.evaluate_js(
            "JSON.stringify([app.state.files.reference && app.state.files.reference.path,"
            " app.state.errors.reference])"), flush=True)
    finally:
        for w in list(webview.windows):
            w.destroy()

threading.Thread(target=drive, daemon=True).start()
appwin.run()
"""


def test_dropping_a_file_on_the_window_loads_it(tmp_path):
    from aafconform.synthetic import build_avid_group

    ref = tmp_path / "EP101 MASTER.aaf"
    build_avid_group(str(ref), str(tmp_path / "pull.aaf"))
    script = tmp_path / "drive.py"
    script.write_text(DRIVER)
    env = {
        **os.environ,
        "PYWEBVIEW_GUI": "qt",
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox",
    }
    run = subprocess.run(
        [sys.executable, str(script), str(ref), ref.name],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = run.stdout + run.stderr
    assert "drop zone reference: ready" in out, out
    result = [line for line in run.stdout.splitlines() if line.startswith("RESULT ")]
    assert result, out
    assert json.loads(result[-1].removeprefix("RESULT ")) == [str(ref), ""], out

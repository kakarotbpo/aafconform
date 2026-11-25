"""The desktop app's Python side: the bridge, the dev server and the UI in a browser."""

import json
import threading
import urllib.request

import pytest

from aafconform import synthetic
from aafconform.app.__main__ import main as app_main
from aafconform.app.bridge import Bridge, _pin
from aafconform.app.devserver import make_server


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    d = tmp_path_factory.mktemp("app")
    ref, cut = d / "layout.aaf", d / "pull.aaf"
    synthetic.build_avid_group(str(ref), str(cut))
    return ref, cut


def test_pin_parsing():
    assert [_pin(v) for v in (None, "", "auto", "A1", "a3", 2, "A0", "x")] == [
        None,
        None,
        None,
        0,
        2,
        1,
        None,
        None,
    ]


def test_bridge_flow(pair, tmp_path):
    ref, cut = pair
    b = Bridge()
    assert b.describe(str(ref))["data"]["sequence"]["name"] == "MASTER LAYOUT"
    p = b.preview(str(ref), str(cut), "auto")
    assert p["ok"] and p["data"]["totals"]["built"] == 10
    out = tmp_path / "x" / "new.aaf"
    out.parent.mkdir()
    r = b.conform(str(ref), str(cut), str(out), "A1", True, False, False)
    assert r["ok"], r
    assert out.exists() and (tmp_path / "x" / "new report.csv").exists()
    assert r["data"]["csv"].endswith("new report.csv")
    assert b.output_exists(str(out))["data"] is True
    again = b.conform(str(ref), str(cut), str(out))
    assert not again["ok"] and "already exists" in again["error"]
    assert b.conform(str(ref), str(cut), str(out), replace=True)["ok"]


def test_bridge_errors_are_messages(tmp_path):
    b = Bridge()
    r = b.describe(str(tmp_path / "nope.aaf"))
    assert r == {"ok": False, "error": r["error"]} and "not found" in r["error"]
    assert not b.choose_file()["ok"]  # no window in tests
    assert not b.reveal(str(tmp_path / "nope.aaf"))["ok"]


def test_self_test_passes(capsys):
    assert app_main(["--self-test"]) == 0
    assert "self-test passed" in capsys.readouterr().out


@pytest.fixture
def server():
    srv = make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_devserver_serves_ui_and_api(server, pair):
    html = urllib.request.urlopen(server + "/").read().decode()
    assert "AAFCONFORM_DEV" in html and "app.js" in html
    assert urllib.request.urlopen(server + "/fonts/SpaceGrotesk.woff2").status == 200
    req = urllib.request.Request(
        server + "/api/describe",
        data=json.dumps({"args": [str(pair[0])]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert json.loads(urllib.request.urlopen(req).read())["ok"] is True
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(server + "/../pyproject.toml")


def test_ui_end_to_end_in_a_browser(server, pair, tmp_path):
    """Load both files, check the plan, conform, read the report. No JS errors."""
    sync_api = pytest.importorskip("playwright.sync_api")
    ref, cut = pair
    errors = []
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser not installed here
            pytest.skip(f"no Chromium for Playwright: {e}")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(server + "/")
        page.evaluate(f"app.load('reference', {str(ref)!r})")
        page.wait_for_function("app.state.files.reference !== null")
        page.evaluate(f"app.load('cut', {str(cut)!r})")
        page.wait_for_selector("#screen-check:not([hidden]) .plan")
        plan = page.inner_text("#screen-check")
        assert "Track plan" in plan and "A3–A4" in plan and "Built on A1 MIX L" in plan
        assert "1 event will be left as it is" in plan
        out = tmp_path / "ui.aaf"
        page.fill("#out", str(out))
        page.click("#conform")
        page.wait_for_selector("#screen-report:not([hidden]) .tiles")
        report = page.inner_text("#screen-report")
        assert "Conformed sequence written and checked" in report
        assert "Group clip conflict" in report
        page.click("button[data-filter='attn']")
        assert "clip 'ISO_2'" in page.inner_text(".events")
        browser.close()
    assert out.exists()
    assert errors == []

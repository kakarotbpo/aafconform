"""The front-end API: plain JSON-safe data and editor-friendly errors."""

import hashlib
import json

import pytest

from aafconform import api, synthetic


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("api")
    ref, cut = d / "layout.aaf", d / "cut.aaf"
    synthetic.build_avid_group(str(ref), str(cut))
    return ref, cut


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_describe_cut(files):
    _, cut = files
    d = api.describe(cut)
    json.dumps(d)
    seq = d["sequence"]
    assert d["sequences"] == ["CUT.Exported.01"]
    assert (seq["fps"], seq["start"], seq["frames"]) == (25, "10:00:00:00", 240)
    assert [t["label"] for t in seq["picture"]] == ["V1"]
    assert [(t["label"], t["name"], t["empty"]) for t in seq["sound"]] == [
        ("A1", "MIX L", False),
        ("A2", "MIX R", False),
        ("A3", "", False),
        ("A4", "", True),
    ]
    assert seq["sound"][0]["effects"] == ["Audio Pan"]
    assert seq["groups"] == ["SCENE_1.Grp.01"]


def test_preview_writes_nothing(files):
    ref, cut = files
    before = sorted(p.name for p in cut.parent.iterdir())
    r = api.preview(ref, cut)
    json.dumps(r)
    assert sorted(p.name for p in cut.parent.iterdir()) == before
    assert r["output"] is None and r["sequence"] is None
    assert r["pin"] == "A1 'MIX L'"
    assert [(t["label"], t["mode"]) for t in r["tracks"]] == [
        ("V1", "repair"),
        ("A1", "repair"),
        ("A2", "repair"),
        ("A3", "build"),
        ("A4", "build"),
        ("A5", "extra"),
    ]
    assert r["dropped"] == ["A4"]
    assert r["totals"] == {
        "kept": 4,
        "built": 10,
        "corrected": 4,
        "other": 2,
        "flagged": 1,
        "effects": 2,  # Resize on V1, Audio Gain on MIX L (pan is track-level)
    }
    assert {e["status"] for e in r["events"]} >= {"kept", "built", "corrected", "flagged"}


def test_conform_default_output_and_reports(files, tmp_path):
    ref, cut = files
    before = _sha(ref), _sha(cut)
    out = tmp_path / "out.aaf"
    r = api.conform(ref, cut, out, csv_path=tmp_path / "r.csv", json_path=tmp_path / "r.json")
    assert (_sha(ref), _sha(cut)) == before
    assert r["output"] == str(out) and r["sequence"] == "out"
    assert out.exists() and (tmp_path / "r.csv").exists()
    assert json.loads((tmp_path / "r.json").read_text())["flagged"] == 1
    assert api.default_output(cut).endswith("cut CONFORMED.aaf")


def test_errors_are_messages(files, tmp_path):
    ref, cut = files
    with pytest.raises(api.ApiError, match="not found"):
        api.preview(tmp_path / "missing.aaf", cut)
    junk = tmp_path / "junk.aaf"
    junk.write_bytes(b"not an aaf")
    with pytest.raises(api.ApiError, match="could not read"):
        api.describe(junk)
    taken = tmp_path / "taken.aaf"
    taken.write_bytes(b"x")
    with pytest.raises(api.ApiError, match="already exists"):
        api.conform(ref, cut, taken)
    assert taken.read_bytes() == b"x"


def test_inspect_is_json(files):
    _, cut = files
    d = api.inspect(cut)
    json.dumps(d)
    assert d

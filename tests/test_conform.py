"""End-to-end conform tests: synthetic Avid-style files, plus real samples."""

import hashlib
import json
from pathlib import Path

import aaf2
import pytest

from aafconform import aafread, synthetic
from aafconform.cli import main
from aafconform.conform import ConformError, conform
from aafconform.model import Kind, Mode, Status

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
MASTER = SAMPLES / "CONFORM EXAMPLE MASTER LAYOUT.aaf"
NEEDS_FIXING = SAMPLES / "CONFORM EXAMPLE EDIT THAT NEEDS FIXING.aaf"
EDGE = SAMPLES / "CONFORM EXAMPLE EDIT THAT NEEDS FIXING - EDGE CASES.aaf"
RESULT = SAMPLES / "CONFORM EXAMPLE EDIT RESULT.aaf"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def group_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("group")
    ref, cut = d / "ref.aaf", d / "cut.aaf"
    synthetic.build_avid_group(str(ref), str(cut))
    return ref, cut


@pytest.fixture(scope="module")
def conformed(group_files, tmp_path_factory):
    ref, cut = group_files
    before = (_sha(ref), _sha(cut))
    out = tmp_path_factory.mktemp("out") / "EP101 v3 FIXED.aaf"
    result = conform(ref, cut, out)
    assert (_sha(ref), _sha(cut)) == before, "inputs must never be modified"
    return result, out


def _written(path: Path):
    with aaf2.open(str(path), "r") as f:
        comp = aafread.pick_sequence(f)
        return comp.name, aafread.read_cut(comp), [s.slot_id for s in comp.slots]


def test_plan_on_synthetic_group(conformed):
    result, _ = conformed
    p = result.plan
    assert [(t.name, t.mode) for t in p.tracks] == [
        ("MIX L", Mode.REPAIR),
        ("MIX R", Mode.REPAIR),
        ("ISO 1", Mode.BUILD),
        ("ISO 2", Mode.BUILD),
        ("", Mode.EXTRA),
    ]
    assert [i.status for i in p.tracks[0].items] == [
        Status.KEPT,
        Status.KEPT,
        Status.TRANSITION,
        Status.CORRECTED,
        Status.CORRECTED,
        Status.KEPT_OTHER,
        Status.FLAGGED,
        Status.FILLER,
    ]
    assert [i.status for i in p.tracks[1].items] == [
        Status.KEPT,
        Status.CORRECTED,
        Status.FILLER,
    ]
    assert p.dropped == (3,)


def test_written_tracks_and_events(conformed):
    _, out = conformed
    name, cut, slot_ids = _written(out)
    assert name == "EP101 v3 FIXED"  # named after the file: it's what Avid's bin shows
    assert slot_ids == list(range(1, len(slot_ids) + 1))
    assert [t.name for t in cut.tracks] == ["MIX L", "MIX R", "ISO 1", "ISO 2", ""]
    assert all(t.length == 240 for t in cut.tracks)

    mix = cut.tracks[0].items
    # kept, kept under its gain, dissolve, corrected x2, ADR, flagged ISO_2, filler
    assert [i.kind for i in mix] == [
        Kind.GROUP,
        Kind.GROUP,
        Kind.TRANSITION,
        Kind.GROUP,
        Kind.GROUP,
        Kind.OTHER,
        Kind.OTHER,
        Kind.FILLER,
    ]
    assert mix[1].effects == ("Audio Gain",)
    assert [i.selected for i in mix if i.kind is Kind.GROUP] == [2, 2, 2, 2]
    assert [i.src_start for i in mix if i.kind is Kind.GROUP] == [100, 200, 300, 400]
    assert mix[6].label == "clip 'ISO_2'"

    iso1 = cut.tracks[2].items
    assert [(i.kind, i.record_start, i.length) for i in iso1] == [
        (Kind.GROUP, 0, 50),
        (Kind.GROUP, 50, 40),
        (Kind.TRANSITION, 80, 10),
        (Kind.GROUP, 80, 60),
        (Kind.GROUP, 140, 30),
        (Kind.FILLER, 170, 30),
        (Kind.GROUP, 200, 20),
        (Kind.FILLER, 220, 20),
    ]
    assert {i.selected for i in iso1 if i.kind is Kind.GROUP} == {4}
    assert all(i.effects == () for i in iso1), "gain must not be copied to built tracks"
    assert cut.tracks[4].items[0].label == "clip 'MUSIC'"

    # Track-level pan stays on the mix tracks and is not copied to built ones.
    assert [t.effects for t in cut.tracks] == [("Audio Pan",), ("Audio Pan",), (), (), ()]
    mix_r = cut.tracks[1].items
    assert [(i.kind, i.selected, i.src_start) for i in mix_r[:2]] == [
        (Kind.GROUP, 3, 100),
        (Kind.GROUP, 3, 200),
    ]


def test_picture_master_clip_corrected_with_effect_kept(conformed):
    result, out = conformed
    v1 = result.plan.picture[0]
    assert [i.status for i in v1.items] == [Status.KEPT, Status.CORRECTED, Status.FILLER]
    # CAM frames 200-240 sit at group 200 and 700; only 200 is in sync.
    assert (v1.items[1].src_start, v1.items[1].channel) == (200, 1)
    assert "in sync" in v1.items[1].note
    _, cut, _ = _written(out)
    got = cut.picture[0].items
    assert [(i.kind, i.record_start, i.length) for i in got] == [
        (Kind.GROUP, 0, 50),
        (Kind.GROUP, 50, 40),
        (Kind.FILLER, 90, 150),
    ]
    assert got[1].effects == ("PaintResize_v2",)
    assert got[1].src_start == 200
    with aaf2.open(str(out), "r") as f:
        v = aafread.picture_slots(aafread.pick_sequence(f))[0].segment.components[1]
        assert v.operation.name == "PaintResize_v2"
        sel = v.segments[0].components[0]
        assert aafread.cls(sel) == "Selector"
        spatial = sel["Selected"].value
        assert spatial.operation.name == "SpatialAdapter" and spatial.length == 40
        clip = aafread.selector_clip(spatial)
        assert (clip.slot_id, clip.start, clip.length) == (1, 200, 40)


def test_built_selectors_carry_layout_alternates(conformed):
    _, out = conformed
    with aaf2.open(str(out), "r") as f:
        comp = aafread.pick_sequence(f)
        iso2 = aafread.sound_slots(comp)[3]
        sel = iso2.segment.components[0]
        assert sel["Selected"].value.slot_id == 5
        assert [a.slot_id for a in sel["Alternates"].value] == [2, 4]
        attrs = aafread.attributes(sel, "ComponentAttributeList")
        assert attrs == {"_AAF_SELECTED": 2}


def test_output_must_be_new(group_files, tmp_path):
    ref, cut = group_files
    with pytest.raises(ConformError):
        conform(ref, cut, cut)
    existing = tmp_path / "x.aaf"
    existing.write_bytes(b"keep me")
    with pytest.raises(ConformError):
        conform(ref, cut, existing)
    assert existing.read_bytes() == b"keep me"
    assert not (tmp_path / "x.aaf.partial").exists()


def test_cli_conform_writes_reports(group_files, tmp_path, capsys):
    ref, cut = group_files
    out, csv_path, json_path = tmp_path / "o.aaf", tmp_path / "r.csv", tmp_path / "r.json"
    args = [str(ref), str(cut), "-o", str(out), "--csv", str(csv_path), "--json", str(json_path)]
    assert main(["conform", *args]) == 0
    text = capsys.readouterr().out
    assert "Needs attention (1)" in text and "clip 'ISO_2'" in text
    assert csv_path.read_text().startswith("track,name,mode,status")
    data = json.loads(json_path.read_text())
    assert data["flagged"] == 1 and data["events"]
    assert main(["conform", *args]) == 1, "refuses to overwrite without --force"


# --- real Media Composer exports (git-ignored; skipped when absent) -----------

needs_samples = pytest.mark.skipif(
    not all(p.exists() for p in (MASTER, NEEDS_FIXING, RESULT, EDGE)),
    reason="real sample AAFs not present in samples/",
)


def _layout(path: Path, name: str | None = None):
    """Per track: name and per-event (length, selected, start, alternates, attrs)."""
    with aaf2.open(str(path), "r") as f:
        comp = aafread.pick_sequence(f, name)
        out = []
        for slot in comp.slots:
            events = []
            seg, _ = aafread.track_sequence(slot)
            for _, c, _ in aafread.components(seg) if aafread.cls(seg) == "Sequence" else []:
                inner, _, _ = aafread.unwrap(c)
                if aafread.cls(inner) == "Selector":
                    sel = aafread.unwrap(inner["Selected"].value)[0]
                    events.append(
                        (
                            c.length,
                            sel.slot_id,
                            sel.start,
                            tuple(a.slot_id for a in inner["Alternates"].value or []),
                            tuple(sorted(aafread.attributes(inner, "ComponentAttributeList"))),
                        )
                    )
                else:
                    events.append((c.length, aafread.cls(c)))
            out.append((slot.slot_id, slot.name, slot.media_kind, tuple(events)))
        return out


@needs_samples
def test_real_conform_matches_avids_own_fix(tmp_path):
    out = tmp_path / "out.aaf"
    before = _sha(NEEDS_FIXING), _sha(MASTER)
    r = conform(MASTER, NEEDS_FIXING, out)
    assert (_sha(NEEDS_FIXING), _sha(MASTER)) == before
    assert _layout(out, r.output_name) == _layout(RESULT)


# What the wrong source looks like in the report (clip names come from the
# private sample files and are deliberately not written here).
EDGE2 = {
    "NOT MULTI": "was clip '",
    "WRONG MULTI": "was group clip '",
}


@needs_samples
@pytest.mark.parametrize("variant", sorted(EDGE2))
def test_real_same_audio_from_the_wrong_source_is_corrected(variant, tmp_path):
    """The middle event sounds identical but is not from the layout's multigroup:
    a master clip cut in directly, or a different group clip."""
    cut = SAMPLES / f"CONFORM EXAMPLE EDIT THAT NEEDS FIXING EDGE CASES 2 - {variant}.aaf"
    if not cut.exists():
        pytest.skip(f"{cut.name} not present")
    before = _sha(cut)
    out = tmp_path / "out.aaf"
    r = conform(MASTER, cut, out)
    assert _sha(cut) == before
    assert not r.plan.flagged
    for t in r.plan.tracks[:2]:
        assert [i.status for i in t.items] == [Status.KEPT, Status.CORRECTED, Status.KEPT]
        assert t.items[1].note.startswith(EDGE2[variant])
    # Event for event the same as Avid's own fix. NOT MULTI also keeps the
    # track-level pan on the mix tracks, which _layout looks through.
    assert _layout(out, r.output_name) == _layout(RESULT)


@needs_samples
def test_real_video_master_clip_under_effect_is_corrected(tmp_path):
    cut = (
        SAMPLES
        / "CONFORM EXAMPLE EDIT THAT NEEDS FIXING EDGE CASES 3 - VIDEO NO MULTI AND EFFECT.aaf"
    )
    if not cut.exists():
        pytest.skip(f"{cut.name} not present")
    before = _sha(cut)
    out = tmp_path / "out.aaf"
    r = conform(MASTER, cut, out)
    assert _sha(cut) == before
    assert not r.plan.flagged
    v1 = r.plan.picture[0]
    assert [i.status for i in v1.items] == [Status.KEPT, Status.CORRECTED, Status.KEPT]
    # The camera clip repeats inside the group (1181, 3495, 5809): sync picks 1181.
    assert v1.items[1].src_start == 1181
    written = _written(out)[1].picture[0].items
    assert [i.effects for i in written] == [(), ("PaintResize_v2",), ("PaintResize_v2",)]
    assert [(i.kind, i.src_start) for i in written] == [
        (Kind.GROUP, 277),
        (Kind.GROUP, 1181),
        (Kind.GROUP, 1634),
    ]


@needs_samples
def test_real_edge_cases(tmp_path):
    out = tmp_path / "out.aaf"
    r = conform(MASTER, EDGE, out)
    p = r.plan
    assert not p.flagged
    # The layout's eight tracks in its order, then the cut's two music tracks.
    # Names are read from the private sample, not written here.
    with aaf2.open(str(MASTER), "r") as f:
        layout = [s.name for s in aafread.sound_slots(aafread.pick_sequence(f))]
    assert len(layout) == 8
    assert [t.name for t in p.tracks] == [*layout, "", ""]
    assert p.dropped == (2, 3, 4, 5, 6, 7)
    mix_l = p.tracks[0]
    assert [i.status for i in mix_l.items] == [
        Status.KEPT,
        Status.KEPT,
        Status.TRANSITION,
        Status.KEPT,
        Status.KEPT_OTHER,
    ]
    # Iso tracks follow MIX L's audio edits (not V1's), dissolve included.
    for t in p.tracks[2:8]:
        assert [(i.status, i.record_start, i.length, i.src_start) for i in t.items] == [
            (Status.BUILT, 0, 101, 277),
            (Status.BUILT, 101, 192, 1181),
            (Status.TRANSITION, 281, 12, None),
            (Status.BUILT, 281, 130, 1628),
            (Status.FILLER, 411, 90, None),
        ]
    layout = _layout(out, r.output_name)
    # V1 untouched: its edit points differ from the audio (split edits).
    assert [e[0] for e in layout[1][3]] == [80, 207, 124, 90]

"""Unit tests for the pure matching logic, on hand-built plain data."""

import pytest

from aafconform import match
from aafconform.model import (
    Cut,
    CutItem,
    CutTrack,
    GroupChannelRange,
    Kind,
    Mapping,
    Material,
    Mode,
    Reference,
    RefSegment,
    RefTrack,
    Status,
)
from aafconform.report import timecode

G, H = "group-G", "group-H"
MIX, ISO = Mapping(2, (4,)), Mapping(4, (2,))


def seg(key, group, src, length, mapping, rec=0):
    return RefSegment(key, rec, length, group, src, mapping)


def ranges(group, offset=0):
    """Group channels 2 and 4 play files 'mix' and 'iso' from position `offset`."""
    return (
        GroupChannelRange(group, 2, 0, 1000, Material("mix", 1, offset)),
        GroupChannelRange(group, 4, 0, 1000, Material("iso", 1, offset)),
    )


def reference(segments_mix=None, segments_iso=None, channel_ranges=None):
    return Reference(
        (
            RefTrack(0, "MIX", tuple(segments_mix or [seg(0, G, 0, 1000, MIX)])),
            RefTrack(1, "ISO", tuple(segments_iso or [seg(1, G, 0, 1000, ISO)])),
        ),
        channel_ranges if channel_ranges is not None else ranges(G),
        {G: "SCENE_1"},
    )


def grp(index, rec, length, src, selected=2, group=G, **kw):
    mat = Material("mix" if selected == 2 else "iso", 1, src)
    return CutItem(index, Kind.GROUP, rec, length, "group clip", group, src, selected, mat, **kw)


def other(index, rec, length, material=None, label="clip 'ADR'", **kw):
    return CutItem(index, Kind.OTHER, rec, length, label, material=material, **kw)


def filler(index, rec, length):
    return CutItem(index, Kind.FILLER, rec, length)


def dissolve(index, rec, length=10):
    return CutItem(index, Kind.TRANSITION, rec, length, cutpoint=length // 2)


def track(index, items, name="", length=None):
    length = length if length is not None else max(i.record_start + i.length for i in items)
    return CutTrack(index, name, tuple(items), length)


# --- lookup -----------------------------------------------------------------


def test_lookup_covered_by_one_segment():
    t = RefTrack(0, "MIX", (seg(0, G, 0, 100, MIX),))
    s, note = match.lookup(t, G, 10, 50)
    assert s.key == 0 and note == ""


def test_lookup_covered_by_two_segments_with_same_mapping():
    t = RefTrack(0, "MIX", (seg(0, G, 0, 100, MIX), seg(1, G, 100, 100, MIX, rec=100)))
    s, note = match.lookup(t, G, 80, 50)
    assert s is not None and note == ""


def test_lookup_refuses_mapping_change_inside_event():
    t = RefTrack(0, "MIX", (seg(0, G, 0, 100, MIX), seg(1, G, 100, 100, ISO, rec=100)))
    s, note = match.lookup(t, G, 80, 50)
    assert s is None and "changes inside" in note


def test_lookup_outside_range_uses_the_only_mapping_with_a_note():
    t = RefTrack(0, "MIX", (seg(0, G, 0, 100, MIX),))
    s, note = match.lookup(t, G, 150, 20)
    assert s.key == 0 and "outside" in note


def test_lookup_outside_range_with_several_mappings_is_refused():
    t = RefTrack(0, "MIX", (seg(0, G, 0, 100, MIX), seg(1, G, 200, 100, ISO, rec=100)))
    s, note = match.lookup(t, G, 150, 20)
    assert s is None and "several mappings" in note


def test_lookup_group_not_on_track():
    t = RefTrack(0, "MIX", (seg(0, G, 0, 100, MIX),))
    s, note = match.lookup(t, H, 0, 10)
    assert s is None and "not on reference track" in note


# --- repair (the cut already has the track) ----------------------------------


def test_correct_events_are_kept_untouched():
    cut = Cut((track(0, [grp(0, 0, 50, 100), grp(1, 50, 40, 200, effects=("Audio Gain",))]),))
    p = match.plan(reference(), cut)
    mix = p.tracks[0]
    assert mix.mode is Mode.REPAIR
    assert [i.status for i in mix.items] == [Status.KEPT, Status.KEPT]


def test_wrong_channel_of_the_right_group_is_corrected():
    cut = Cut((track(0, [grp(0, 0, 50, 100), grp(1, 50, 30, 400, selected=4)]),))
    mix = match.plan(reference(), cut).tracks[0]
    assert mix.items[1].status is Status.CORRECTED
    assert mix.items[1].channel == 2 and mix.items[1].src_start == 400


def test_master_clip_used_directly_is_corrected_by_material():
    direct = other(1, 50, 60, Material("mix", 1, 300), label="clip 'MIX'")
    cut = Cut((track(0, [grp(0, 0, 50, 100), direct]),))
    item = match.plan(reference(), cut).tracks[0].items[1]
    assert item.status is Status.CORRECTED
    assert (item.group, item.src_start, item.channel) == (G, 300, 2)


def test_material_from_another_channel_is_flagged_not_swapped():
    wrong = other(1, 50, 20, Material("iso", 1, 500), label="clip 'ISO'")
    cut = Cut((track(0, [grp(0, 0, 50, 100), wrong]),))
    item = match.plan(reference(), cut).tracks[0].items[1]
    assert item.status is Status.FLAGGED
    assert "channel 4" in item.note


def test_unrelated_material_is_kept_as_other():
    adr = other(1, 50, 30, Material("adr", 1, 0))
    cut = Cut((track(0, [grp(0, 0, 50, 100), adr]),))
    assert match.plan(reference(), cut).tracks[0].items[1].status is Status.KEPT_OTHER


def test_same_material_via_another_multigroup_is_corrected():
    # Same channel, same audio clip, but through a group the layout doesn't use.
    foreign = grp(1, 50, 30, 100, group=H)
    cut = Cut((track(0, [grp(0, 0, 50, 100), foreign]),))
    item = match.plan(reference(), cut).tracks[0].items[1]
    assert item.status is Status.CORRECTED
    assert (item.group, item.src_start) == (G, 100)


def test_unknown_multigroup_with_unknown_material_is_flagged():
    foreign = CutItem(1, Kind.GROUP, 50, 30, "group clip", H, 100, 2, Material("other", 1, 0))
    cut = Cut((track(0, [grp(0, 0, 50, 100), foreign]),))
    item = match.plan(reference(), cut).tracks[0].items[1]
    assert item.status is Status.FLAGGED
    assert "not in the reference" in item.note


def test_speed_change_is_flagged_and_left_alone():
    cut = Cut((track(0, [grp(0, 0, 50, 100), grp(1, 50, 30, 200, timing_change=True)]),))
    p = match.plan(reference(), cut)
    assert p.tracks[0].items[1].status is Status.FLAGGED
    built = p.tracks[1].items[1]
    assert built.status is Status.FLAGGED and "filler" in built.note


# --- build (the cut lacks the track) ------------------------------------------


def test_built_track_follows_pin_edits_including_dissolve():
    items = [grp(0, 0, 50, 100), grp(1, 50, 40, 200), dissolve(2, 80), grp(3, 80, 60, 300)]
    cut = Cut((track(0, items),))
    iso = match.plan(reference(), cut).tracks[1]
    assert iso.mode is Mode.BUILD
    got = [(i.status, i.record_start, i.length, i.src_start, i.channel) for i in iso.items]
    assert got == [
        (Status.BUILT, 0, 50, 100, 4),
        (Status.BUILT, 50, 40, 200, 4),
        (Status.TRANSITION, 80, 10, None, None),
        (Status.BUILT, 80, 60, 300, 4),
    ]


def test_built_track_gets_filler_under_non_group_material():
    cut = Cut((track(0, [grp(0, 0, 50, 100), other(1, 50, 30, Material("adr", 1, 0))]),))
    iso = match.plan(reference(), cut).tracks[1]
    assert [i.status for i in iso.items] == [Status.BUILT, Status.FILLER]


def test_dissolve_between_two_gaps_is_dropped_keeping_length():
    adr1 = other(1, 50, 40, Material("adr", 1, 0))
    adr2 = other(3, 80, 60, Material("adr", 1, 100))
    cut = Cut((track(0, [grp(0, 0, 50, 100), adr1, dissolve(2, 80), adr2]),))
    iso = match.plan(reference(), cut).tracks[1]
    assert Status.TRANSITION not in [i.status for i in iso.items]
    total = sum(i.length for i in iso.items if i.status is not Status.TRANSITION)
    assert total == 140


def test_material_in_two_groups_is_ambiguous():
    ref = Reference(
        (
            RefTrack(0, "MIX", (seg(0, G, 0, 1000, MIX), seg(1, H, 0, 1000, MIX, rec=1000))),
            RefTrack(1, "ISO", (seg(2, G, 0, 1000, ISO), seg(3, H, 0, 1000, ISO, rec=1000))),
        ),
        (*ranges(G), *ranges(H, offset=50)),
    )
    direct = other(1, 50, 20, Material("mix", 1, 300), label="clip 'MIX'")
    cut = Cut((track(0, [grp(0, 0, 50, 100), direct]),))
    p = match.plan(ref, cut)
    assert p.tracks[0].items[1].status is Status.FLAGGED
    assert "2 places in the reference" in p.tracks[0].items[1].note


# --- pairing, extras, pin -------------------------------------------------------


def test_tracks_pair_by_channel_not_position():
    # The wrong template has the iso on A1 and the mix on A2.
    a1 = track(0, [grp(0, 0, 50, 100, selected=4)])
    a2 = track(1, [grp(0, 0, 50, 100, selected=2)])
    p = match.plan(reference(), Cut((a1, a2)))
    assert (p.tracks[0].name, p.tracks[0].cut_track) == ("MIX", 1)
    assert (p.tracks[1].name, p.tracks[1].cut_track) == ("ISO", 0)
    assert all(t.mode is Mode.REPAIR for t in p.tracks)


def test_extra_tracks_kept_after_layout_and_empty_tracks_dropped():
    mix = track(0, [grp(0, 0, 50, 100)])
    empty = track(1, [filler(0, 0, 50)])
    music = track(2, [other(0, 0, 50, Material("music", 1, 0), label="clip 'MUSIC'")])
    p = match.plan(reference(), Cut((mix, empty, music)))
    assert [t.mode for t in p.tracks] == [Mode.REPAIR, Mode.BUILD, Mode.EXTRA]
    assert p.tracks[2].cut_track == 2
    assert p.dropped == (1,)


def test_pin_override_and_bad_pin():
    mix = track(0, [grp(0, 0, 50, 100)])
    alt = track(1, [grp(0, 0, 20, 100), grp(1, 20, 30, 120)])
    p = match.plan(reference(), Cut((mix, alt)), pin=1)
    assert p.pin == 1
    with pytest.raises(match.MatchError):
        match.plan(reference(), Cut((mix,)), pin=5)


def test_reference_without_groups_is_an_error():
    ref = Reference((RefTrack(0, "MIX", ()),))
    with pytest.raises(match.MatchError):
        match.plan(ref, Cut((track(0, [grp(0, 0, 50, 100)]),)))


# --- timecode -----------------------------------------------------------------


@pytest.mark.parametrize(
    "frame,fps,drop,want",
    [
        (90000, 25, False, "01:00:00:00"),
        (90000 + 411, 25, False, "01:00:16:11"),
        (1800, 30, True, "00:01:00;02"),
        (17982, 30, True, "00:10:00;00"),
    ],
)
def test_timecode(frame, fps, drop, want):
    assert timecode(frame, fps, drop) == want


# --- picture and sync ----------------------------------------------------------

CAM = Mapping(1, ())


def picture_reference(positions=(0, 500)):
    """Group G whose picture channel 1 plays file 'cam' from 0 at each position."""
    ranges_ = tuple(
        GroupChannelRange(G, 1, p, 500, Material("cam", 1, 0)) for p in positions
    ) + ranges(G)
    return Reference(
        (
            RefTrack(0, "MIX", (seg(0, G, 0, 1000, MIX),)),
            RefTrack(1, "ISO", (seg(1, G, 0, 1000, ISO),)),
        ),
        ranges_,
        {G: "SCENE_1"},
        picture=(RefTrack(0, "", (seg(2, G, 0, 1000, CAM),)),),
    )


def pic(index, rec, length, material=None, selected=None, group=None, src=None, **kw):
    kind = Kind.GROUP if group else Kind.OTHER
    label = "group clip" if group else "clip 'CAM'"
    return CutItem(index, kind, rec, length, label, group, src, selected, material, **kw)


def test_picture_material_in_two_places_resolved_by_audio_sync():
    cut = Cut(
        (track(0, [grp(0, 0, 50, 100), grp(1, 50, 40, 200)]),),
        picture=(
            CutTrack(
                0,
                "",
                (
                    pic(0, 0, 50, Material("cam", 1, 100), 1, G, 100),
                    pic(1, 50, 40, Material("cam", 1, 200), effects=("Resize",)),
                ),
                90,
                kind="picture",
            ),
        ),
    )
    v1 = match.plan(picture_reference(), cut).picture[0]
    assert [i.status for i in v1.items] == [Status.KEPT, Status.CORRECTED]
    assert v1.items[1].src_start == 200  # 700 is the other copy, out of sync


def test_picture_material_in_two_places_without_sync_is_flagged():
    # Mix is in the group but the picture event sits under ADR: nothing in
    # sync anchors it, so it must not be guessed.
    mix = track(0, [grp(0, 0, 50, 100), other(1, 50, 40, Material("adr", 1, 0))])
    v1 = CutTrack(
        0,
        "",
        (
            pic(0, 0, 50, Material("cam", 1, 100), 1, G, 100),
            pic(1, 50, 40, Material("cam", 1, 200)),
        ),
        90,
        kind="picture",
    )
    item = match.plan(picture_reference(), Cut((mix,), (v1,))).picture[0].items[1]
    assert item.status is Status.FLAGGED
    assert "2 places" in item.note


def test_picture_out_of_sync_with_audio_is_flagged():
    # Audio at 50-90 is the group at 600 (offset 550): neither 200 nor 700 fits.
    mix = track(0, [grp(0, 0, 50, 100), grp(1, 50, 40, 600)])
    v1 = CutTrack(0, "", (pic(0, 50, 40, Material("cam", 1, 200)),), 90, kind="picture")
    v1 = CutTrack(
        0, "", (CutItem(0, Kind.FILLER, 0, 50), replace_rec(v1.items[0], 50)), 90, kind="picture"
    )
    item = match.plan(picture_reference(), Cut((mix,), (v1,))).picture[0].items[1]
    assert item.status is Status.FLAGGED


def replace_rec(item, rec):
    from dataclasses import replace

    return replace(item, record_start=rec)


def test_picture_keeps_the_editors_camera_angle():
    # A multigroup picture event on another camera (channel 6) is editorial.
    mix = track(0, [grp(0, 0, 50, 100)])
    v1 = CutTrack(0, "", (pic(0, 0, 50, Material("cam2", 1, 100), 6, G, 100),), 50, kind="picture")
    item = match.plan(picture_reference(), Cut((mix,), (v1,))).picture[0].items[0]
    assert item.status is Status.KEPT and item.channel == 6


def test_picture_left_alone_when_reference_has_no_picture():
    v1 = CutTrack(0, "", (pic(0, 0, 50, Material("cam", 1, 100)),), 50, kind="picture")
    p = match.plan(reference(), Cut((track(0, [grp(0, 0, 50, 100)]),), (v1,)))
    assert p.picture == ()
    assert any("no picture track" in w for w in p.warnings)

"""Build small synthetic AAFs with pyaaf2 for tests.

These approximate an Avid export (tape -> file -> master mob chains, a
selector-based group clip, a sequence with a dissolve) closely enough to
exercise the inspector. They are NOT a substitute for real Media Composer
exports, which are the ground truth for the conform design.
"""

from __future__ import annotations

import aaf2

RATE = 25
TC_START = 10 * 60 * 60 * RATE  # 10:00:00:00


def _tape(f, name: str, kind: str, length: int):
    tape = f.create.SourceMob()
    tape.name = name
    tape.descriptor = f.create.TapeDescriptor()
    tape.create_tape_slots(name, RATE, RATE, media_kind=kind, length=length)
    # create_tape_slots puts the timecode at 0; real tapes start at a TC offset
    for slot in tape.slots:
        if slot.media_kind == "Timecode":
            slot.segment.start = TC_START
    f.content.mobs.append(tape)
    return tape


def _master(f, name: str, kind: str, channels: int, length: int):
    """Tape mob -> file mob -> master mob, `channels` slots of `kind`."""
    tape = _tape(f, name, kind, length)
    file_mob = f.create.SourceMob()
    file_mob.name = name
    file_mob.descriptor = f.create.PCMDescriptor() if kind == "sound" else f.create.CDCIDescriptor()
    if kind == "sound":
        d = file_mob.descriptor
        d["SampleRate"].value = 48000
        d["AudioSamplingRate"].value = 48000
        d["Channels"].value = 1
        d["QuantizationBits"].value = 24
        d["BlockAlign"].value = 3
        d["AverageBPS"].value = 144000
        d["Length"].value = length
    else:
        d = file_mob.descriptor
        d["ComponentWidth"].value = 8
        d["HorizontalSubsampling"].value = 2
        d["StoredWidth"].value = 1920
        d["StoredHeight"].value = 1080
        d["FrameLayout"].value = "FullFrame"
        d["ImageAspectRatio"].value = "16/9"
        d["VideoLineMap"].value = [42, 0]
        d["SampleRate"].value = RATE
        d["Length"].value = length
    master = f.create.MasterMob(name)
    f.content.mobs.append(file_mob)
    f.content.mobs.append(master)
    for ch in range(1, channels + 1):
        fslot = file_mob.create_timeline_slot(RATE, slot_id=ch)
        fslot.segment = tape.create_source_clip(slot_id=1, start=0, length=length)
        fslot.segment.media_kind = kind
        mslot = master.create_timeline_slot(RATE, slot_id=ch)
        mslot.segment = file_mob.create_source_clip(slot_id=ch, start=0, length=length)
        mslot.segment.media_kind = kind
    return master


VIDEO_DISSOLVE_AUID = "0c3bea40-fc05-11d2-8a29-0050040ef7d2"  # kAAFEffectVideoDissolve


def _video_dissolve(f):
    opdef = f.create.OperationDef(VIDEO_DISSOLVE_AUID, "Video Dissolve", "")
    opdef.media_kind = "picture"
    opdef.number_inputs = 2
    f.dictionary.register_def(opdef)
    return opdef


def _clip(f, mob, slot_id: int, start: int, length: int, kind: str):
    clip = mob.create_source_clip(slot_id=slot_id, start=start, length=length)
    clip.media_kind = kind
    return clip


def build_reference(path: str, length: int = 500, audio_channels: int = 4) -> None:
    """A group clip (Selector over two cameras) plus N audio channels, cut into a sequence."""
    with aaf2.open(path, "w") as f:
        cam_a = _master(f, "A001C001", "picture", 1, length)
        cam_b = _master(f, "B001C001", "picture", 1, length)
        audio = _master(f, "SOUND_001", "sound", audio_channels, length)

        group = f.create.CompositionMob("MULTIGROUP_01")
        group.usage = "Usage_TopLevel"
        f.content.mobs.append(group)
        vslot = group.create_timeline_slot(RATE, slot_id=1)
        vslot["SlotName"].value = "V1"
        sel = f.create.Selector(media_kind="picture", length=length)
        sel["Selected"].value = _clip(f, cam_a, 1, 0, length, "picture")
        sel["Alternates"].value = [_clip(f, cam_b, 1, 0, length, "picture")]
        vslot.segment = sel
        for ch in range(1, audio_channels + 1):
            aslot = group.create_timeline_slot(RATE, slot_id=1 + ch)
            aslot["SlotName"].value = f"A{ch}"
            aslot.segment = _clip(f, audio, ch, 0, length, "sound")

        seq = f.create.CompositionMob("REFERENCE_SEQ")
        seq.usage = "Usage_TopLevel"
        f.content.mobs.append(seq)
        tc_slot = seq.create_timeline_slot(RATE, slot_id=1)
        tc_slot.segment = f.create.Timecode(RATE, length=length)
        tc_slot.segment.start = TC_START
        v = seq.create_timeline_slot(RATE, slot_id=2)
        vseq = f.create.Sequence(media_kind="picture")
        vseq.components.append(_clip(f, group, 1, 0, length, "picture"))
        vseq.length = length
        v.segment = vseq
        for ch in range(1, audio_channels + 1):
            a = seq.create_timeline_slot(RATE, slot_id=2 + ch)
            aseq = f.create.Sequence(media_kind="sound")
            aseq.components.append(_clip(f, group, 1 + ch, 0, length, "sound"))
            aseq.length = length
            a.segment = aseq


def build_cut(path: str) -> None:
    """Pulled cameras on V1 with a dissolve, single audio channel on A1."""
    length = 500
    with aaf2.open(path, "w") as f:
        cam_a = _master(f, "A001C001", "picture", 1, length)
        cam_b = _master(f, "B001C001", "picture", 1, length)
        audio = _master(f, "SOUND_001", "sound", 1, length)

        seq = f.create.CompositionMob("CUT_SEQ")
        seq.usage = "Usage_TopLevel"
        f.content.mobs.append(seq)
        v = seq.create_timeline_slot(RATE, slot_id=1)
        vseq = f.create.Sequence(media_kind="picture")
        vseq.components.append(_clip(f, cam_a, 1, 100, 50, "picture"))
        trans = f.create.Transition(media_kind="picture", length=10)
        trans["CutPoint"].value = 5
        # pyaaf2 quirk: f.create.X stores X on a shared factory before the call's
        # arguments are evaluated, so never nest f.create calls in arguments.
        dissolve = _video_dissolve(f)
        trans["OperationGroup"].value = f.create.OperationGroup(
            dissolve, length=10, media_kind="picture"
        )
        vseq.components.append(trans)
        vseq.components.append(_clip(f, cam_b, 1, 200, 40, "picture"))
        vseq.components.append(f.create.Filler(media_kind="picture", length=10))
        vseq.length = 50 + 40 - 10 + 10  # transitions overlap their neighbours
        v.segment = vseq
        a = seq.create_timeline_slot(RATE, slot_id=2)
        aseq = f.create.Sequence(media_kind="sound")
        aseq.components.append(_clip(f, audio, 1, 100, 80, "sound"))
        aseq.components.append(f.create.Filler(media_kind="sound", length=10))
        aseq.length = 90
        a.segment = aseq


# --- Avid-style multigroup, modelled on real Media Composer 25.12 exports ----
#
# Media Composer exports a multigroup as an unnamed inner CompositionMob whose
# slots are the group's channels, plus a bin mob flagged _MLT_GRP. Sequence
# tracks hold Selectors whose clips all point into the inner composition: the
# selected clip is the channel that track plays, the alternates are the others.

GROUP_LEN = 1000
AUDIO_GAIN_AUID = "9d2ea894-0968-11d3-8a38-0050040ef7d2"
AUDIO_DISSOLVE_AUID = "0c3bea41-fc05-11d2-8a29-0050040ef7d2"
AUDIO_PAN_AUID = "9d2ea893-0968-11d3-8a38-0050040ef7d2"
CHANNELS = {2: "MIX_L", 3: "MIX_R", 4: "ISO_1", 5: "ISO_2"}
LAYOUT = [  # reference tracks: name, selected channel, alternates
    ("MIX L", 2, (4, 5)),
    ("MIX R", 3, ()),
    ("ISO 1", 4, (2, 5)),
    ("ISO 2", 5, (2, 4)),
]


def _ids(names):
    from aaf2.mobid import MobID

    return {n: (MobID.new(), MobID.new(), MobID.new()) for n in names}


def _sound_master(f, name, ids, length=GROUP_LEN):
    """Tape -> file (PCM) -> master, one channel, with fixed MobIDs."""
    tape_id, file_id, master_id = ids[name]
    tape = f.create.SourceMob()
    tape.name = name
    tape.mob_id = tape_id
    tape.descriptor = f.create.TapeDescriptor()
    tape.create_tape_slots(name, RATE, RATE, media_kind="sound", length=length)
    f.content.mobs.append(tape)
    file_mob = f.create.SourceMob()
    file_mob.name = name
    file_mob.mob_id = file_id
    d = f.create.PCMDescriptor()
    file_mob.descriptor = d
    d["SampleRate"].value = 48000
    d["AudioSamplingRate"].value = 48000
    d["Channels"].value = 1
    d["QuantizationBits"].value = 24
    d["BlockAlign"].value = 3
    d["AverageBPS"].value = 144000
    d["Length"].value = length
    f.content.mobs.append(file_mob)
    fslot = file_mob.create_timeline_slot(RATE, slot_id=1)
    fslot.segment = _clip(f, tape, 1, 0, length, "sound")
    master = f.create.MasterMob(name)
    master.mob_id = master_id
    f.content.mobs.append(master)
    mslot = master.create_timeline_slot(RATE, slot_id=1)
    mslot.segment = _clip(f, file_mob, 1, 0, length, "sound")
    return master


CAM_LEN = GROUP_LEN // 2


def _picture_master(f, name, ids, length=CAM_LEN):
    """Tape -> file (CDCI) -> master, picture, with fixed MobIDs."""
    tape_id, file_id, master_id = ids[name]
    tape = f.create.SourceMob()
    tape.name = name
    tape.mob_id = tape_id
    tape.descriptor = f.create.TapeDescriptor()
    tape.create_tape_slots(name, RATE, RATE, media_kind="picture", length=length)
    f.content.mobs.append(tape)
    file_mob = f.create.SourceMob()
    file_mob.name = name
    file_mob.mob_id = file_id
    d = f.create.CDCIDescriptor()
    file_mob.descriptor = d
    d["ComponentWidth"].value = 8
    d["HorizontalSubsampling"].value = 2
    d["StoredWidth"].value = 1920
    d["StoredHeight"].value = 1080
    d["FrameLayout"].value = "FullFrame"
    d["ImageAspectRatio"].value = "16/9"
    d["VideoLineMap"].value = [42, 0]
    d["SampleRate"].value = RATE
    d["Length"].value = length
    f.content.mobs.append(file_mob)
    fslot = file_mob.create_timeline_slot(RATE, slot_id=1)
    fslot.segment = _clip(f, tape, 1, 0, length, "picture")
    master = f.create.MasterMob(name)
    master.mob_id = master_id
    f.content.mobs.append(master)
    mslot = master.create_timeline_slot(RATE, slot_id=1)
    mslot.segment = _clip(f, file_mob, 1, 0, length, "picture")
    return master


def _spatial(f, op, clip, length):
    """Avid's per-clip framing wrapper: SpatialAdapter -> Sequence -> clip."""
    seq = f.create.Sequence(media_kind="picture")
    seq.components.append(clip)
    seq.length = length
    og = f.create.OperationGroup(op, length=length, media_kind="picture")
    og.segments.append(seq)
    return og


def _picture_selector(f, op, inner, start, length):
    sel = f.create.Selector(media_kind="picture", length=length)
    clip = _clip(f, inner, 1, start, length, "picture")
    sel["Selected"].value = _spatial(f, op, clip, length)
    _attr(f, sel, "ComponentAttributeList", "_AAF_SELECTED", 0)
    return sel


def _attr(f, obj, key, name, value):
    tv = f.create.TaggedValue(name, value)
    obj[key].append(tv)


def _group_selector(f, inner, selected, alternates, start, length):
    sel = f.create.Selector(media_kind="sound", length=length)
    sel["Selected"].value = _clip(f, inner, selected, start, length, "sound")
    sel["Alternates"].value = [_clip(f, inner, a, start, length, "sound") for a in alternates]
    order = sorted([selected, *alternates])
    _attr(f, sel, "ComponentAttributeList", "_AAF_SELECTED", order.index(selected))
    return sel


def _library(f, ids, group_id, grp_id):
    """Masters, the inner group composition and the _MLT_GRP bin mob.

    The group's picture (slot 1) is the CAM clip cut in twice from its start,
    like the camera clip in the real samples: the same frames sit at two group
    positions, so matching picture by material alone is ambiguous.
    """
    masters = {n: _sound_master(f, n, ids) for n in ids if n != "CAM"}
    masters["CAM"] = _picture_master(f, "CAM", ids)
    inner = f.create.CompositionMob("")
    inner.mob_id = group_id
    f.content.mobs.append(inner)
    v = inner.create_timeline_slot(RATE, slot_id=1)
    vseq = f.create.Sequence(media_kind="picture")
    vseq.components.append(_clip(f, masters["CAM"], 1, 0, CAM_LEN, "picture"))
    vseq.components.append(_clip(f, masters["CAM"], 1, 0, CAM_LEN, "picture"))
    vseq.length = GROUP_LEN
    v.segment = vseq
    for slot_id, name in CHANNELS.items():
        s = inner.create_timeline_slot(RATE, slot_id=slot_id)
        seq = f.create.Sequence(media_kind="sound")
        seq.components.append(_clip(f, masters[name], 1, 0, GROUP_LEN, "sound"))
        seq.length = GROUP_LEN
        s.segment = seq
    grp = f.create.CompositionMob("SCENE_1.Grp.01")
    grp.mob_id = grp_id
    grp.usage = "Usage_LowerLevel"
    _attr(f, grp, "MobAttributeList", "_MLT_GRP", 1)
    f.content.mobs.append(grp)
    s = grp.create_timeline_slot(RATE, slot_id=2)
    s.segment = _group_selector(f, inner, 2, (4, 5), 0, GROUP_LEN)
    return masters, inner


def _sequence(f, name, length):
    seq = f.create.CompositionMob(name)
    seq.usage = "Usage_TopLevel"
    f.content.mobs.append(seq)
    tc = seq.create_timeline_slot(RATE, slot_id=1)
    tc.segment = f.create.Timecode(RATE, length=length)
    tc.segment.start = TC_START
    return seq


def _sound_track(f, seq, slot_id, name, components, length, track_effect=None):
    """A sound track; `track_effect` wraps the whole track as Avid does for
    track-level effects such as Audio Pan."""
    slot = seq.create_timeline_slot(RATE, slot_id=slot_id)
    slot["SlotName"].value = name
    slot["PhysicalTrackNumber"].value = slot_id - 1
    s = f.create.Sequence(media_kind="sound")
    for c in components:
        s.components.append(c)
    s.length = length
    if track_effect is not None:
        wrapper = f.create.OperationGroup(track_effect, length=length, media_kind="sound")
        wrapper.segments.append(s)
        slot.segment = wrapper
    else:
        slot.segment = s
    return slot


SPATIAL_AUID = "3a9a7d4f-5b52-4bd4-9cd2-7c3c4f0f5a01"
RESIZE_AUID = "3a9a7d4f-5b52-4bd4-9cd2-7c3c4f0f5a02"


def _picture_track(f, seq, components, length):
    """V1, created before the audio tracks so it sits first, as in Avid."""
    slot = seq.create_timeline_slot(RATE, slot_id=9)
    slot["PhysicalTrackNumber"].value = 1
    s = f.create.Sequence(media_kind="picture")
    for c in components:
        s.components.append(c)
    s.length = length
    slot.segment = s
    return slot


def _opdef(f, auid, name, inputs, kind="sound"):
    op = f.create.OperationDef(auid, name, "")
    op.media_kind = kind
    op.number_inputs = inputs
    f.dictionary.register_def(op)
    return op


def build_avid_group(reference_path: str, cut_path: str) -> None:
    """A master layout and a cut on the wrong template, sharing one multigroup.

    Cut A1 'MIX L' (record frames):
      0-50     group, MIX L channel           -> kept
      50-90    group, MIX L, with Audio Gain  -> kept (gain stays)
      80-90    audio dissolve, cut point 5
      80-140   MIX_L master clip used directly -> corrected to the group
      140-170  group, but ISO_1 channel       -> corrected to MIX L channel
      170-200  ADR clip, not in the group      -> kept as other material
      200-220  ISO_2 master clip used directly -> flagged (wrong channel)
      220-240  filler
    Cut A2 'MIX R': group MIX R, then the MIX_R master clip used directly
    (corrected), then filler.
    A1 and A2 are wrapped in a track-level Audio Pan, as Media Composer
    exports them when pan is set on the track: kept, but not copied to the
    built tracks.
    Cut A3: music. Cut A4: empty.
    Cut V1:
      0-50     group picture                         -> kept
      50-90    Resize over the CAM master clip used directly, frames 200-240
               -> corrected to the group at 200 (not 700: the audio at 50-90
               is the group at 200, so only 200 is in sync); Resize stays
      90-240   filler
    """
    from aaf2.mobid import MobID

    ids = _ids([*CHANNELS.values(), "ADR", "MUSIC", "CAM"])
    group_id, grp_id = MobID.new(), MobID.new()

    with aaf2.open(reference_path, "w") as f:
        _, inner = _library(f, ids, group_id, grp_id)
        spatial = _opdef(f, SPATIAL_AUID, "SpatialAdapter", 1, "picture")
        seq = _sequence(f, "MASTER LAYOUT", GROUP_LEN)
        _picture_track(f, seq, [_picture_selector(f, spatial, inner, 0, GROUP_LEN)], GROUP_LEN)
        for n, (name, sel, alts) in enumerate(LAYOUT):
            comp = _group_selector(f, inner, sel, alts, 0, GROUP_LEN)
            _sound_track(f, seq, 2 + n, name, [comp], GROUP_LEN)

    with aaf2.open(cut_path, "w") as f:
        masters, inner = _library(f, ids, group_id, grp_id)
        gain = _opdef(f, AUDIO_GAIN_AUID, "Audio Gain", 1)
        dissolve = _opdef(f, AUDIO_DISSOLVE_AUID, "Audio Dissolve", 2)
        pan = _opdef(f, AUDIO_PAN_AUID, "Audio Pan", 1)
        spatial = _opdef(f, SPATIAL_AUID, "SpatialAdapter", 1, "picture")
        resize = _opdef(f, RESIZE_AUID, "PaintResize_v2", 1, "picture")
        length = 240
        seq = _sequence(f, "CUT.Exported.01", length)

        cam_clip = _clip(f, masters["CAM"], 1, 200, 40, "picture")
        direct = _spatial(f, spatial, cam_clip, 40)
        resized = f.create.OperationGroup(resize, length=40, media_kind="picture")
        rseq = f.create.Sequence(media_kind="picture")
        rseq.components.append(direct)
        rseq.length = 40
        resized.segments.append(rseq)
        v1 = [
            _picture_selector(f, spatial, inner, 100, 50),
            resized,
            f.create.Filler(media_kind="picture", length=150),
        ]
        _picture_track(f, seq, v1, length)

        a1 = [_group_selector(f, inner, 2, (4, 5), 100, 50)]
        wrapped = f.create.OperationGroup(gain, length=40, media_kind="sound")
        inner_sel = _group_selector(f, inner, 2, (4, 5), 200, 40)
        wrapped.segments.append(inner_sel)
        a1.append(wrapped)
        trans = f.create.Transition(media_kind="sound", length=10)
        trans["CutPoint"].value = 5
        og = f.create.OperationGroup(dissolve, length=10, media_kind="sound")
        trans["OperationGroup"].value = og
        a1.append(trans)
        a1.append(_clip(f, masters["MIX_L"], 1, 300, 60, "sound"))
        a1.append(_group_selector(f, inner, 4, (2, 5), 400, 30))
        a1.append(_clip(f, masters["ADR"], 1, 10, 30, "sound"))
        a1.append(_clip(f, masters["ISO_2"], 1, 500, 20, "sound"))
        a1.append(f.create.Filler(media_kind="sound", length=20))
        _sound_track(f, seq, 2, "MIX L", a1, length, track_effect=pan)

        a2 = [
            _group_selector(f, inner, 3, (), 100, 50),
            _clip(f, masters["MIX_R"], 1, 200, 40, "sound"),
            f.create.Filler(media_kind="sound", length=150),
        ]
        _sound_track(f, seq, 3, "MIX R", a2, length, track_effect=pan)
        _sound_track(f, seq, 4, "", [_clip(f, masters["MUSIC"], 1, 0, length, "sound")], length)
        _sound_track(f, seq, 5, "", [f.create.Filler(media_kind="sound", length=length)], length)

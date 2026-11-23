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

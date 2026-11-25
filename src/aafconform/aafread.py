"""Read Avid AAF sequences into the plain model used by the matcher."""

from __future__ import annotations

from fractions import Fraction

from .model import (
    Cut,
    CutItem,
    CutTrack,
    GroupChannelRange,
    Kind,
    Mapping,
    Material,
    Reference,
    RefSegment,
    RefTrack,
)

# Source mobs that stand for physical media rather than essence files.
_PHYSICAL_DESCRIPTORS = {"TapeDescriptor", "ImportDescriptor", "FilmDescriptor"}
_MAX_DEPTH = 40


class ReadError(Exception):
    pass


def cls(obj) -> str:
    return obj.classdef.class_name


def attributes(obj, key: str) -> dict:
    """Avid attribute list (MobAttributeList, ComponentAttributeList) as a dict."""
    if key not in obj.keys():
        return {}
    return {t.name: t.value for t in obj[key].value}


def pick_sequence(f, name: str | None = None):
    """The top-level sequence to work on: the only one, or the one named."""
    tops = list(f.content.toplevel())
    if name is not None:
        tops = [m for m in tops if m.name == name]
        if not tops:
            raise ReadError(f"no top-level sequence named '{name}'")
    if not tops:
        raise ReadError("no top-level sequence in this AAF")
    if len(tops) > 1:
        names = ", ".join(repr(m.name) for m in tops)
        raise ReadError(f"several top-level sequences ({names}); choose one by name")
    return tops[0]


# Avid wraps every picture clip in a SpatialAdapter (its framing/reformat
# settings). It is part of the clip, not an effect the editor added.
CLIP_WRAPPERS = {"SpatialAdapter"}


def sound_slots(comp) -> list:
    return [s for s in comp.slots if s.media_kind == "Sound"]


def picture_slots(comp) -> list:
    return [s for s in comp.slots if s.media_kind == "Picture"]


def edit_rate(comp) -> Fraction:
    rates = {Fraction(s.edit_rate) for s in comp.slots if s.media_kind in ("Sound", "Picture")}
    if len(rates) != 1:
        raise ReadError(f"sequence '{comp.name}' has mixed edit rates {sorted(rates)}")
    return rates.pop()


def timecode_start(comp) -> tuple[int, int, bool]:
    """(start frame, fps, drop) of the sequence's timecode track."""
    for s in comp.slots:
        seg = s.segment
        if cls(seg) == "Sequence" and len(seg.components) == 1:
            seg = seg.components[0]
        if cls(seg) == "Timecode":
            return seg.start, seg.fps, bool(seg.drop)
    return 0, 25, False


def components(seq):
    """Yield (index, component, record_start) with Avid's transition overlap."""
    pos = 0
    for i, c in enumerate(seq.components):
        if cls(c) == "Transition":
            pos -= c.length
            yield i, c, pos
            continue
        yield i, c, pos
        pos += c.length


def unwrap(comp):
    """Strip effect wrappers. Returns (inner, effect names, timing_change)."""
    effects = []
    timing = False
    while True:
        kind = cls(comp)
        if kind == "OperationGroup":
            op = comp.operation
            name = op.name if op is not None else "unknown effect"
            if name not in CLIP_WRAPPERS:
                effects.append(name)
            if op is not None and "IsTimeWarp" in op.keys() and op["IsTimeWarp"].value:
                timing = True
            inputs = list(comp.segments)
            if len(inputs) != 1:
                return comp, tuple(effects), True
            if inputs[0].length != comp.length:
                timing = True
            comp = inputs[0]
        elif kind == "Sequence" and len(comp.components) == 1:
            comp = comp.components[0]
        else:
            return comp, tuple(effects), timing


def track_sequence(slot):
    """A slot's segment under any track-level effects. Returns (segment, effects).

    Avid wraps a whole track in an effect (for example Audio Pan) when it is
    applied to the track rather than a clip. Only wrappers that keep timing are
    looked through.
    """
    seg = slot.segment
    effects = []
    while cls(seg) == "OperationGroup":
        op = seg.operation
        inputs = list(seg.segments)
        if len(inputs) != 1 or inputs[0].length != seg.length:
            break
        if op is not None and "IsTimeWarp" in op.keys() and op["IsTimeWarp"].value:
            break
        effects.append(op.name if op is not None else "unknown effect")
        seg = inputs[0]
    return seg, tuple(effects)


def _clip_target(clip):
    """The mob a SourceClip points at, or None at the end of a chain."""
    mob_id = clip.mob_id
    if mob_id is None or mob_id.int == 0:
        return None
    return clip.root.content.mobs.get(mob_id, None)


def selector_clip(node):
    """The SourceClip inside a Selector choice, looking through SpatialAdapter."""
    for _ in range(_MAX_DEPTH):
        kind = cls(node)
        if kind == "SourceClip":
            return node
        if kind == "OperationGroup" and len(node.segments) == 1:
            node = node.segments[0]
        elif kind == "Sequence" and len(node.components) == 1:
            node = node.components[0]
        else:
            return None
    return None


def selector_info(sel):
    """(group, src_start, mapping) for a Selector into a group, else None."""
    selected = sel["Selected"].value
    alternates = list(sel["Alternates"].value or []) if "Alternates" in sel.keys() else []
    clips = [selector_clip(c) for c in (selected, *alternates)]
    if any(c is None for c in clips):
        return None
    selected, alternates = clips[0], clips[1:]
    targets = {str(c.mob_id) for c in clips}
    starts = {c.start for c in clips}
    if len(targets) != 1 or len(starts) != 1:
        return None
    mob = _clip_target(selected)
    if mob is None or cls(mob) != "CompositionMob":
        return None
    mapping = Mapping(selected.slot_id, tuple(c.slot_id for c in alternates))
    return str(selected.mob_id), selected.start, mapping


def segment_at(seg, pos):
    """Descend a segment to the SourceClip playing at `pos`: (clip, offset)."""
    for _ in range(_MAX_DEPTH):
        kind = cls(seg)
        if kind == "Sequence":
            hit = None
            for _, c, start in components(seg):
                if cls(c) != "Transition" and start <= pos < start + c.length:
                    hit = (c, pos - start)
            if hit is None:
                return None, 0
            seg, pos = hit
        elif kind == "Selector":
            seg = seg["Selected"].value
        elif kind == "OperationGroup":
            inputs = list(seg.segments)
            if not inputs or inputs[0].length != seg.length:
                return None, 0
            seg = inputs[0]
        elif kind == "NestedScope":
            seg = list(seg["Slots"].value)[-1]
        elif kind == "SourceClip":
            return seg, pos
        else:
            return None, 0
    return None, 0


def resolve_material(clip, offset: int = 0, rate: Fraction | None = None) -> Material | None:
    """Follow a SourceClip down to the essence file mob it plays."""
    for _ in range(_MAX_DEPTH):
        mob = _clip_target(clip)
        if mob is None:
            return None
        try:
            slot = mob.slot_at(clip.slot_id)
        except IndexError:
            return None
        # StartTime is in the edit units of the slot containing the clip.
        pos = clip.start + offset
        slot_rate = Fraction(slot.edit_rate)
        if rate is not None and rate != slot_rate:
            pos = int(Fraction(pos) * slot_rate / rate)
        if cls(mob) == "SourceMob":
            desc = mob.descriptor
            if desc is not None and cls(desc) not in _PHYSICAL_DESCRIPTORS:
                return Material(str(mob.mob_id), slot.slot_id, pos)
        clip, offset = segment_at(slot.segment, pos)
        if clip is None:
            return None
        rate = slot_rate
    return None


def _group_label(group: str, names: dict[str, str]) -> str:
    name = names.get(group)
    return f"group clip '{name}'" if name else f"group clip {group[-8:]}"


def _item(index, comp, start, rate, names) -> CutItem:
    kind = cls(comp)
    if kind == "Transition":
        return CutItem(
            index, Kind.TRANSITION, start, comp.length, label="dissolve", cutpoint=comp.cutpoint
        )
    if kind == "Filler":
        return CutItem(index, Kind.FILLER, start, comp.length)
    inner, effects, timing = unwrap(comp)
    if cls(inner) == "Selector":
        info = selector_info(inner)
        if info is not None:
            group, src, mapping = info
            mat = resolve_material(selector_clip(inner["Selected"].value), 0, rate)
            return CutItem(
                index,
                Kind.GROUP,
                start,
                comp.length,
                label=_group_label(group, names),
                group=group,
                src_start=src,
                selected=mapping.selected,
                material=mat,
                effects=effects,
                timing_change=timing,
            )
        inner = inner["Selected"].value
    if cls(inner) == "SourceClip":
        mob = _clip_target(inner)
        name = mob.name if mob is not None else "end of chain"
        return CutItem(
            index,
            Kind.OTHER,
            start,
            comp.length,
            label=f"clip '{name}'",
            material=resolve_material(inner, 0, rate),
            effects=effects,
            timing_change=timing,
        )
    return CutItem(
        index,
        Kind.OTHER,
        start,
        comp.length,
        label=cls(inner),
        effects=effects,
        timing_change=timing,
    )


def _slot_items(slot, rate, names) -> tuple[tuple[CutItem, ...], tuple[str, ...]]:
    seg, effects = track_sequence(slot)
    if cls(seg) != "Sequence":
        return (_item(0, seg, 0, rate, names),), effects
    items = tuple(_item(i, c, start, rate, names) for i, c, start in components(seg))
    return items, effects


def read_cut(comp) -> Cut:
    rate = edit_rate(comp)
    names = group_names(comp.root)
    out = {}
    for kind, slots in (("sound", sound_slots(comp)), ("picture", picture_slots(comp))):
        tracks = []
        for n, slot in enumerate(slots):
            items, effects = _slot_items(slot, rate, names)
            tracks.append(
                CutTrack(n, slot.name or "", items, slot.segment.length, effects, kind=kind)
            )
        out[kind] = tuple(tracks)
    return Cut(out["sound"], picture=out["picture"])


def group_names(f) -> dict[str, str]:
    """Inner group composition MobID -> the group clip's bin name.

    Multigroups (_MLT_GRP) take precedence over plain group clips that share
    the same inner composition.
    """
    names: dict[str, str] = {}
    mobs = [m for m in f.content.mobs if cls(m) == "CompositionMob"]
    mobs.sort(key=lambda m: not attributes(m, "MobAttributeList").get("_MLT_GRP"))
    for mob in mobs:
        for slot in mob.slots:
            seg = slot.segment
            if cls(seg) == "Selector":
                info = selector_info(seg)
                if info and mob.name:
                    names.setdefault(info[0], mob.name)
    return names


def _channel_ranges(f, groups, channels, rate) -> list[GroupChannelRange]:
    out = []
    for group in groups:
        mob = next((m for m in f.content.mobs if str(m.mob_id) == group), None)
        if mob is None:
            continue
        for slot in mob.slots:
            if slot.slot_id not in channels.get(group, ()):
                continue
            seg = slot.segment
            items = components(seg) if cls(seg) == "Sequence" else [(0, seg, 0)]
            for _, c, start in items:
                if cls(c) in ("Transition", "Filler"):
                    continue
                clip, off = segment_at(c, 0)
                if clip is None:
                    continue
                mat = resolve_material(clip, off, Fraction(slot.edit_rate))
                if mat is not None:
                    out.append(GroupChannelRange(group, slot.slot_id, start, c.length, mat))
    return out


def read_reference(f, comp) -> tuple[Reference, dict[int, object]]:
    """The layout plus a key -> Selector map for the writer to copy from."""
    rate = edit_rate(comp)
    selectors: dict[int, object] = {}
    channels: dict[str, set[int]] = {}
    sound = _ref_tracks(sound_slots(comp), selectors, channels)
    picture = _ref_tracks(picture_slots(comp), selectors, channels)
    groups = {s.group for t in (*sound, *picture) for s in t.segments}
    ranges = _channel_ranges(f, groups, channels, rate)
    names = group_names(f)
    return Reference(sound, tuple(ranges), names, picture=picture), selectors


def _ref_tracks(slots, selectors, channels) -> tuple[RefTrack, ...]:
    tracks = []
    for n, slot in enumerate(slots):
        segs = []
        seg, _ = track_sequence(slot)
        items = components(seg) if cls(seg) == "Sequence" else [(0, seg, 0)]
        for _, c, start in items:
            if cls(c) in ("Transition", "Filler"):
                continue
            inner, _, timing = unwrap(c)
            if timing or cls(inner) != "Selector":
                continue
            info = selector_info(inner)
            if info is None:
                continue
            group, src, mapping = info
            key = len(selectors)
            selectors[key] = inner
            segs.append(RefSegment(key, start, c.length, group, src, mapping))
            channels.setdefault(group, set()).update((mapping.selected, *mapping.alternates))
        tracks.append(RefTrack(n, slot.name or "", tuple(segs)))
    return tuple(tracks)

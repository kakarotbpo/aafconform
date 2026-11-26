"""Apply a Plan to a copy of the cut AAF, opened read-write.

Everything Media Composer wrote is kept as it was, except the top-level
sequence: it gets a new MobID and name (so it can't collide with the original
cut on import), and its audio tracks are replaced by the planned ones.
"""

from __future__ import annotations

from aaf2.mobid import MobID

from .aafread import (
    CLIP_WRAPPERS,
    cls,
    picture_slots,
    selector_info,
    sound_slots,
    track_sequence,
)
from .model import Mode, OutTrack, Plan, Status


class WriteError(Exception):
    pass


_TIMED = {"Selector", "OperationGroup", "Sequence", "SourceClip"}


def _selector(f, ref_sel, src_start: int, length: int):
    """A copy of the reference Selector, retimed to this event.

    Picture Selectors hold SpatialAdapter -> Sequence -> SourceClip chains, so
    every timed object inside is retimed, not only the direct clips.
    """
    sel = ref_sel.copy(root=f)
    for obj, _ in sel.walk_references():
        kind = cls(obj)
        if kind not in _TIMED:
            continue
        if kind == "Sequence" and len(obj.components) != 1:
            raise WriteError("unexpected multi-clip sequence inside a reference group clip")
        obj.length = length
        if kind == "SourceClip":
            obj.start = src_start
    return sel


def _ensure_mob(f, ref_f, mob_id, seen: set) -> None:
    """Copy a mob and everything it references from the reference, if missing."""
    key = str(mob_id)
    if mob_id.int == 0 or key in seen or f.content.mobs.get(mob_id) is not None:
        return
    seen.add(key)
    src = ref_f.content.mobs.get(mob_id)
    if src is None:
        raise WriteError(f"mob {key} is in neither the cut nor the reference")
    f.content.mobs.append(src.copy(root=f))
    for obj, _ in src.walk_references():
        if cls(obj) == "SourceClip" and obj.mob_id is not None:
            _ensure_mob(f, ref_f, obj.mob_id, seen)


def _ensure_groups(f, ref_f, groups: set[str]) -> None:
    """Make sure each group composition and its multigroup mob are in `f`."""
    seen: set = set()
    by_id = {str(m.mob_id): m for m in ref_f.content.mobs}
    for g in sorted(groups):
        if g not in by_id:
            raise WriteError(f"group {g} not found in the reference")
        _ensure_mob(f, ref_f, by_id[g].mob_id, seen)
        # The bin's multigroup clip that wraps this group composition.
        for m in ref_f.content.mobs:
            if cls(m) != "CompositionMob":
                continue
            for slot in m.slots:
                seg = slot.segment
                if cls(seg) == "Selector" and (selector_info(seg) or (None,))[0] == g:
                    _ensure_mob(f, ref_f, m.mob_id, seen)
                    break


def _replace_inner(seq, index: int, new) -> None:
    """Swap the clip or Selector inside a component, keeping effect wrappers."""
    holder = seq["Components"]
    pos = index
    node = holder[pos]
    while True:
        kind = cls(node)
        if kind == "OperationGroup" and node.operation is not None:
            if node.operation.name in CLIP_WRAPPERS:
                break  # the clip's own framing: replaced along with the clip
        if kind == "OperationGroup" and len(node.segments) == 1:
            holder, pos = node["InputSegments"], 0
        elif kind == "Sequence" and len(node.components) == 1:
            holder, pos = node["Components"], 0
        else:
            break
        node = holder[pos]
    holder.pop(pos)
    holder.insert(pos, new)


def _built_slot(f, pin_slot, track: OutTrack, ref_selectors):
    """A copy of the pin slot with new events. Track-level effects (pan) are
    not carried over: they belong to the pin's own track."""
    pin_seq, _ = track_sequence(pin_slot)
    if cls(pin_seq) != "Sequence":
        raise WriteError("the pin track is not a sequence")
    pin_components = list(pin_seq.components)
    slot = pin_slot.copy()
    seq = pin_seq.copy()
    seq.components.clear()
    for item in track.items:
        if item.status is Status.BUILT:
            seq.components.append(
                _selector(f, ref_selectors[item.ref_key], item.src_start, item.length)
            )
        elif item.status is Status.TRANSITION:
            seq.components.append(pin_components[item.cut_index].copy())
        else:  # FILLER, FLAGGED
            filler = f.create.Filler("sound", item.length)
            seq.components.append(filler)
    seq.length = track.length
    slot.segment = seq
    return slot


def _repaired_slot(f, cut_slot, track: OutTrack, ref_selectors):
    slot = cut_slot.copy()
    for item in track.items:
        if item.status is Status.CORRECTED:
            new = _selector(f, ref_selectors[item.ref_key], item.src_start, item.length)
            _replace_inner(track_sequence(slot)[0], item.cut_index, new)
    return slot


def write(f, comp, plan: Plan, ref_f, ref_selectors, name: str) -> object:
    """Rebuild `comp` in file `f` (opened 'rw'): audio tracks per the plan, picture
    events corrected in place, as a new sequence called `name`. Returns it."""
    groups = {
        i.group
        for t in (*plan.tracks, *plan.picture)
        for i in t.items
        if i.status in (Status.BUILT, Status.CORRECTED)
    }
    _ensure_groups(f, ref_f, groups)

    # Picture: repaired in place, only where an event needs correcting.
    repaired_picture = {}
    for t in plan.picture:
        if any(i.status is Status.CORRECTED for i in t.items):
            src = picture_slots(comp)[t.cut_track]
            repaired_picture[src.slot_id] = _repaired_slot(f, src, t, ref_selectors)

    old_sound = sound_slots(comp)
    pin_slot = old_sound[plan.pin]
    new_sound = []
    for t in plan.tracks:
        if t.mode is Mode.BUILD:
            slot = _built_slot(f, pin_slot, t, ref_selectors)
            old_id = None
        elif t.mode is Mode.REPAIR:
            slot = _repaired_slot(f, old_sound[t.cut_track], t, ref_selectors)
            old_id = old_sound[t.cut_track].slot_id
        else:
            slot = old_sound[t.cut_track].copy()
            old_id = old_sound[t.cut_track].slot_id
        if t.mode is not Mode.EXTRA:
            slot.name = t.name
        new_sound.append((old_id, slot))

    ordered = []  # (old slot id or None, slot copy)
    placed = False
    for s in comp.slots:
        if s.media_kind == "Sound":
            if not placed:
                ordered.extend(new_sound)
                placed = True
            continue
        if s.slot_id in repaired_picture:
            ordered.append((s.slot_id, repaired_picture[s.slot_id]))
            continue
        ordered.append((s.slot_id, s.copy()))

    id_map = {}
    for n, (old_id, slot) in enumerate(ordered, start=1):
        if old_id is not None:
            id_map[old_id] = n
        slot.slot_id = n
    for n, (_, slot) in enumerate((x for x in ordered if x[1].media_kind == "Sound"), start=1):
        slot["PhysicalTrackNumber"].value = n
    _remap_described_slots(ordered, id_map)

    new = comp.copy()
    new.slots.clear()
    for _, slot in ordered:
        new.slots.append(slot)
    new.mob_id = MobID.new()
    new.name = name
    f.content.mobs.pop(comp.mob_id)
    f.content.mobs.append(new)
    return new


def _remap_described_slots(ordered, id_map) -> None:
    """Markers name the tracks they sit on by slot id: keep them pointing right."""
    for _, slot in ordered:
        for obj, _ in slot.walk_references():
            if "DescribedSlots" in obj.keys():
                ids = [id_map[i] for i in obj["DescribedSlots"].value if i in id_map]
                obj["DescribedSlots"].value = ids

"""Decide what every output track and event should be. Pure: no pyaaf2.

Rules (agreed with the editor):

- The reference (master layout) defines the output audio tracks: their order,
  names and which group channel each one plays.
- A cut track that already carries one of those tracks (matched by the channel
  its group events play) is kept as is: edits, gain, dissolves, ADR and all.
  Only events that are not provably from the correct multigroup and channel are
  corrected, and only when the same material is found in a reference group.
- Reference tracks the cut lacks are built on the pin track's edit points, so
  split edits stay split. Audio dissolves are copied; gain and pan are not.
- Cut tracks the layout doesn't have (music, SFX) are kept after the layout's
  tracks. Empty cut tracks are dropped.
- Picture tracks are repaired in place: multigroup events are kept whatever
  camera angle they play (that is an editorial choice), and footage used
  outside the multigroup is swapped for the multigroup when it is provably the
  same picture. Effects on the event stay.
- When the same material sits in more than one place in the reference, the
  only place in sync with the cut's multigroup events at that time wins.
- Anything that can't be conformed safely is flagged, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .model import (
    Cut,
    CutItem,
    CutTrack,
    Kind,
    Mode,
    OutItem,
    OutTrack,
    Plan,
    Reference,
    RefSegment,
    RefTrack,
    Status,
)


class MatchError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    seg: RefSegment  # whose mapping (and Selector) applies
    group: str
    src_start: int
    channel: int  # the channel this event plays in its group
    note: str = ""


def group_name(ref: Reference, group: str) -> str:
    return ref.group_names.get(group) or f"group {group[-8:]}"


def lookup(
    track: RefTrack, group: str, src_start: int, length: int, ref: Reference | None = None
) -> tuple[RefSegment | None, str]:
    """Find the reference mapping for a stretch of a group on one track.

    Returns (segment, note) on success, or (None, reason) when there is no
    single safe answer.
    """
    name = group_name(ref, group) if ref else group
    same = [s for s in track.segments if s.group == group]
    if not same:
        return None, f"{name} is not on reference track '{track.name}'"
    end = src_start + length
    overlapping = sorted(
        (s for s in same if s.src_start < end and s.src_end > src_start),
        key=lambda s: s.src_start,
    )
    if overlapping:
        if len({s.mapping for s in overlapping}) > 1:
            return None, f"the reference mapping changes inside this event ({name})"
        pos = src_start
        for s in overlapping:
            if s.src_start > pos:
                break
            pos = max(pos, s.src_end)
        if pos >= end:
            return overlapping[0], ""
    mappings = {s.mapping for s in same}
    if len(mappings) == 1:
        seg = overlapping[0] if overlapping else same[0]
        return seg, f"extends outside the reference's range of {name}; used its only mapping"
    return None, f"outside the reference's range of {name}, which has several mappings here"


def locate_material(ref: Reference, item: CutItem) -> list[tuple[str, int, int]]:
    """Where the item's material sits inside reference groups: (group, channel, pos)."""
    m = item.material
    if m is None:
        return []
    hits = []
    for r in ref.channel_ranges:
        if r.material.file_mob != m.file_mob or r.material.slot != m.slot:
            continue
        off = m.position - r.material.position
        if 0 <= off and off + item.length <= r.length:
            hits.append((r.group, r.channel, r.group_start + off))
    return sorted(set(hits))


NOT_GROUP = "not multigroup material"

# (group, src_start - record_start) of the cut's own multigroup events.
Sync = frozenset[tuple[str, int]]
SyncIndex = tuple[tuple[int, int, str, int], ...]


def sync_index(ref: Reference, cut: Cut) -> SyncIndex:
    """Where the cut's correct multigroup events sit: (rec in, rec out, group, offset)."""
    out = []
    for t in (*cut.tracks, *cut.picture):
        for i in t.items:
            if i.kind is Kind.GROUP and i.group in ref.groups and not i.timing_change:
                end = i.record_start + i.length
                out.append((i.record_start, end, i.group, i.src_start - i.record_start))
    return tuple(out)


def sync_at(index: SyncIndex, item: CutItem) -> Sync:
    """Group offsets of the cut's multigroup events overlapping `item`."""
    start, end = item.record_start, item.record_start + item.length
    return frozenset((g, off) for s, e, g, off in index if s < end and e > start)


def target_for(
    ref: Reference, track: RefTrack, item: CutItem, sync: Sync = frozenset()
) -> Target | str:
    """Where `item` sits in the correct multigroup, for reference `track`.

    Group events from a reference group are looked up directly. Anything else
    (another group, a master clip used directly) is matched by its resolved
    material. Returns a reason string when there is no single safe answer.

    `sync` breaks ties when the material is in more than one place: only a
    place in sync with the cut's multigroup events around the item is taken.
    """
    if item.kind is Kind.GROUP and item.group in ref.groups:
        seg, note = lookup(track, item.group, item.src_start, item.length, ref)
        if seg is None:
            return note
        return Target(seg, item.group, item.src_start, item.selected, note)

    hits = locate_material(ref, item)
    if not hits:
        if item.kind is Kind.GROUP:
            return f"{group_name(ref, item.group)} is not in the reference"
        return NOT_GROUP
    found = []
    reasons = []
    for g, ch, pos in hits:
        seg, note = lookup(track, g, pos, item.length, ref)
        if seg is None:
            reasons.append(note)
        else:
            found.append(
                Target(seg, g, pos, ch, "matched by material" + (f"; {note}" if note else ""))
            )
    if not found:
        return reasons[0]
    # Prefer hits on the channel this track plays.
    pool = [t for t in found if t.channel == t.seg.mapping.selected] or found
    places = {(t.group, t.src_start) for t in pool}
    if len(places) > 1 and sync:
        synced = [t for t in pool if (t.group, t.src_start - item.record_start) in sync]
        if len({(t.group, t.src_start) for t in synced}) == 1:
            t = synced[0]
            return replace(t, note=f"{t.note}; the only match in sync with the multigroup here")
    if len(places) > 1:
        names = ", ".join(sorted({group_name(ref, t.group) for t in pool}))
        return (
            f"material appears in {len(places)} places in the reference ({names}) "
            "and none is uniquely in sync with the multigroup here"
        )
    return pool[0]


def _track_mapping_at(ref: Reference, track: RefTrack, item: CutItem) -> int | None:
    """The channel reference `track` plays where `item` sits, if known."""
    if item.kind is Kind.GROUP and item.group in ref.groups:
        seg, _ = lookup(track, item.group, item.src_start, item.length, ref)
        return seg.mapping.selected if seg else None
    return None


def score(ref: Reference, rtrack: RefTrack, ctrack: CutTrack) -> int:
    """How many of the cut track's events play what `rtrack` plays."""
    n = 0
    for it in ctrack.items:
        if it.kind is Kind.GROUP and it.group in ref.groups:
            if _track_mapping_at(ref, rtrack, it) == it.selected:
                n += 1
        elif it.kind in (Kind.GROUP, Kind.OTHER):
            for g, ch, pos in locate_material(ref, it):
                seg, _ = lookup(rtrack, g, pos, it.length, ref)
                if seg and seg.mapping.selected == ch:
                    n += 1
                    break
    return n


def pair_tracks(ref: Reference, cut: Cut) -> dict[int, int]:
    """Pair reference track index -> cut track index by what they play."""
    candidates = []
    for r in ref.tracks:
        for c in cut.tracks:
            s = score(ref, r, c)
            if s:
                candidates.append((-s, abs(r.index - c.index), r.index, c.index))
    pairs: dict[int, int] = {}
    used: set[int] = set()
    for _, _, r, c in sorted(candidates):
        if r not in pairs and c not in used:
            pairs[r] = c
            used.add(c)
    return pairs


def choose_pin(ref: Reference, cut: Cut, pairs: dict[int, int], pin: int | None) -> int:
    if pin is not None:
        if not 0 <= pin < len(cut.tracks):
            raise MatchError(f"pin track A{pin + 1} does not exist in the cut")
        return pin
    for r in ref.tracks:
        if r.index in pairs:
            return pairs[r.index]
    for c in cut.tracks:
        if any(i.kind is Kind.GROUP for i in c.items):
            return c.index
    raise MatchError("the cut has no multigroup audio to take edit points from")


def repair(
    ref: Reference,
    rtrack: RefTrack,
    ctrack: CutTrack,
    sync: SyncIndex = (),
    editorial: bool = False,
) -> OutTrack:
    """Keep a cut track, swapping only events not from the right multigroup.

    With `editorial` (picture), the channel a multigroup event plays is the
    editor's choice of camera and is never changed.
    """
    out = []
    for it in ctrack.items:
        base = dict(record_start=it.record_start, length=it.length, cut_index=it.index)
        if it.kind is Kind.FILLER:
            out.append(OutItem(Status.FILLER, **base))
            continue
        if it.kind is Kind.TRANSITION:
            out.append(OutItem(Status.TRANSITION, **base))
            continue
        if it.timing_change:
            out.append(OutItem(Status.FLAGGED, note="speed change or timewarp: left as is", **base))
            continue
        if it.kind is Kind.GROUP and it.group in ref.groups and editorial:
            out.append(
                OutItem(
                    Status.KEPT,
                    group=it.group,
                    src_start=it.src_start,
                    channel=it.selected,
                    **base,
                )
            )
            continue
        if it.kind is Kind.GROUP and it.group in ref.groups:
            seg, note = lookup(rtrack, it.group, it.src_start, it.length, ref)
            if seg is None:
                out.append(OutItem(Status.FLAGGED, note=note + ": left as is", **base))
            elif seg.mapping.selected == it.selected:
                out.append(
                    OutItem(
                        Status.KEPT,
                        group=it.group,
                        src_start=it.src_start,
                        channel=it.selected,
                        note=note,
                        **base,
                    )
                )
            else:
                out.append(
                    OutItem(
                        Status.CORRECTED,
                        ref_key=seg.key,
                        group=it.group,
                        src_start=it.src_start,
                        channel=seg.mapping.selected,
                        note=(
                            f"was playing channel {it.selected}, the layout plays "
                            f"channel {seg.mapping.selected} here" + (f"; {note}" if note else "")
                        ),
                        **base,
                    )
                )
            continue
        # Foreign group, or a plain clip: only correct it if it is provably the
        # same material as what this track plays in a reference group.
        t = target_for(ref, rtrack, it, sync_at(sync, it))
        if isinstance(t, Target) and t.channel == t.seg.mapping.selected:
            out.append(
                OutItem(
                    Status.CORRECTED,
                    ref_key=t.seg.key,
                    group=t.group,
                    src_start=t.src_start,
                    channel=t.channel,
                    note=f"was {it.label}, same material; now from the multigroup ({t.note})",
                    **base,
                )
            )
        elif isinstance(t, Target) and editorial:
            note = (
                f"{it.label}: same picture as channel {t.channel} of "
                f"{group_name(ref, t.group)}, a different camera from the layout's "
                f"channel {t.seg.mapping.selected}: left as is"
            )
            out.append(OutItem(Status.FLAGGED, note=note, **base))
        elif isinstance(t, Target):
            note = (
                f"{it.label}: material is channel {t.channel} of {group_name(ref, t.group)}, "
                f"but this track plays channel {t.seg.mapping.selected}: left as is"
            )
            out.append(OutItem(Status.FLAGGED, note=note, **base))
        elif it.kind is Kind.OTHER and t == NOT_GROUP:
            out.append(OutItem(Status.KEPT_OTHER, note=it.label, **base))
        else:
            out.append(OutItem(Status.FLAGGED, note=f"{it.label}: {t}: left as is", **base))
    name = ctrack.name if editorial else rtrack.name
    return OutTrack(
        name, Mode.REPAIR, ctrack.index, rtrack.index, tuple(out), ctrack.length, ctrack.kind
    )


def build(ref: Reference, rtrack: RefTrack, pin: CutTrack, sync: SyncIndex = ()) -> OutTrack:
    out = []
    for it in pin.items:
        if it.kind is Kind.FILLER:
            out.append(OutItem(Status.FILLER, it.record_start, it.length))
            continue
        if it.kind is Kind.TRANSITION:
            out.append(OutItem(Status.TRANSITION, it.record_start, it.length, cut_index=it.index))
            continue
        if it.timing_change:
            out.append(
                OutItem(
                    Status.FLAGGED,
                    it.record_start,
                    it.length,
                    note="speed change or timewarp on the pin track: filler here",
                )
            )
            continue
        t = target_for(ref, rtrack, it, sync_at(sync, it))
        if isinstance(t, Target):
            out.append(
                OutItem(
                    Status.BUILT,
                    it.record_start,
                    it.length,
                    ref_key=t.seg.key,
                    group=t.group,
                    src_start=t.src_start,
                    channel=t.seg.mapping.selected,
                    note=t.note,
                )
            )
        elif it.kind is Kind.OTHER and t == NOT_GROUP:
            out.append(
                OutItem(Status.FILLER, it.record_start, it.length, note=f"pin has {it.label}")
            )
        else:
            out.append(
                OutItem(Status.FLAGGED, it.record_start, it.length, note=f"{t}: filler here")
            )
    items = _tidy(out)
    return OutTrack(rtrack.name, Mode.BUILD, pin.index, rtrack.index, items, pin.length)


def _is_gap(i: OutItem) -> bool:
    """Built-track items that are written as filler."""
    return i.status in (Status.FILLER, Status.FLAGGED)


def _tidy(items: list[OutItem]) -> tuple[OutItem, ...]:
    """Drop transitions between two gaps and merge neighbouring plain fillers."""
    out: list[OutItem] = []
    for k, i in enumerate(items):
        if i.status is Status.TRANSITION:
            prev = out[-1] if out else None
            nxt = items[k + 1] if k + 1 < len(items) else None
            if prev is None or nxt is None or (_is_gap(prev) and _is_gap(nxt)):
                # Overlap disappears with the transition: shorten what follows.
                if nxt is not None:
                    items[k + 1] = _replace(nxt, length=nxt.length - i.length)
                continue
        out.append(i)
    merged: list[OutItem] = []
    for i in out:
        if (
            merged
            and i.status is Status.FILLER
            and merged[-1].status is Status.FILLER
            and not i.note
            and not merged[-1].note
        ):
            p = merged.pop()
            i = _replace(p, length=p.length + i.length)
        merged.append(i)
    return tuple(merged)


def _replace(i: OutItem, **kw) -> OutItem:
    return replace(i, **kw)


def extra(ref: Reference, ctrack: CutTrack) -> OutTrack:
    out = []
    for it in ctrack.items:
        base = dict(record_start=it.record_start, length=it.length, cut_index=it.index)
        if it.kind is Kind.FILLER:
            out.append(OutItem(Status.FILLER, **base))
        elif it.kind is Kind.TRANSITION:
            out.append(OutItem(Status.TRANSITION, **base))
        elif it.kind is Kind.GROUP or locate_material(ref, it):
            out.append(
                OutItem(
                    Status.FLAGGED,
                    note=f"{it.label}: multigroup audio on a track the layout doesn't have",
                    **base,
                )
            )
        else:
            out.append(OutItem(Status.KEPT_OTHER, note=it.label, **base))
    return OutTrack(ctrack.name, Mode.EXTRA, ctrack.index, None, tuple(out), ctrack.length)


def plan(ref: Reference, cut: Cut, pin: int | None = None) -> Plan:
    if not ref.tracks:
        raise MatchError("the reference has no audio tracks")
    if not any(t.segments for t in ref.tracks):
        raise MatchError("the reference has no multigroup audio")
    pairs = pair_tracks(ref, cut)
    pin_index = choose_pin(ref, cut, pairs, pin)
    pin_track = cut.tracks[pin_index]
    sync = sync_index(ref, cut)
    tracks = []
    for r in ref.tracks:
        if r.index in pairs:
            tracks.append(repair(ref, r, cut.tracks[pairs[r.index]], sync))
        else:
            tracks.append(build(ref, r, pin_track, sync))
    picture = []
    if ref.picture:
        for c in cut.picture:
            r = ref.picture[min(c.index, len(ref.picture) - 1)]
            picture.append(repair(ref, r, c, sync, editorial=True))
    used = set(pairs.values())
    dropped = []
    warnings = []
    for c in cut.tracks:
        if c.index in used:
            continue
        if c.is_empty:
            dropped.append(c.index)
        else:
            tracks.append(extra(ref, c))
    if pin_index not in used:
        warnings.append(
            f"pin track {pin_track.label} doesn't match any layout track; "
            "edit points still taken from it"
        )
    if cut.picture and not ref.picture:
        warnings.append("the reference has no picture track: picture left as it is")
    return Plan(tuple(tracks), pin_index, tuple(dropped), tuple(warnings), tuple(picture))

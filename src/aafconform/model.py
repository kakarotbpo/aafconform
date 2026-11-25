"""Plain data structures shared by the AAF reader, the matcher and the writer.

Nothing in here touches pyaaf2, so the matching logic can be unit tested with
hand-built values. Positions and lengths are in edit units (frames) of the
sequence edit rate. A "group" is identified by the MobID string of the
multigroup's inner CompositionMob, which is what Avid's sequence Selectors
point at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Mapping:
    """Which group channel a track plays, plus the switchable alternates."""

    selected: int  # slot id of the channel inside the group composition
    alternates: tuple[int, ...] = ()


@dataclass(frozen=True)
class Material:
    """The essence an event really plays, resolved down the mob chain.

    `file_mob` is the first SourceMob with an essence descriptor (the .PHYS
    file mob in Avid exports). Its MobID is stable across exports, unlike some
    master clips that Avid regenerates on every export.
    """

    file_mob: str
    slot: int
    position: int


@dataclass(frozen=True)
class RefSegment:
    """One group event on a reference (master layout) track."""

    key: int  # opaque handle the writer uses to find the original Selector
    record_start: int
    length: int
    group: str
    src_start: int
    mapping: Mapping

    @property
    def src_end(self) -> int:
        return self.src_start + self.length


@dataclass(frozen=True)
class RefTrack:
    index: int  # 0-based position among the sequence's sound tracks
    name: str
    segments: tuple[RefSegment, ...]


@dataclass(frozen=True)
class GroupChannelRange:
    """A stretch of one group channel and the material it plays."""

    group: str
    channel: int
    group_start: int
    length: int
    material: Material


@dataclass(frozen=True)
class Reference:
    tracks: tuple[RefTrack, ...]  # sound
    channel_ranges: tuple[GroupChannelRange, ...] = ()
    group_names: dict[str, str] = field(default_factory=dict)
    picture: tuple[RefTrack, ...] = ()

    @property
    def groups(self) -> frozenset[str]:
        return frozenset(s.group for t in (*self.tracks, *self.picture) for s in t.segments)


class Kind(str, Enum):
    GROUP = "group"  # Selector into a multigroup composition
    OTHER = "other"  # any other clip (ADR, music, a master clip used directly)
    FILLER = "filler"
    TRANSITION = "transition"


@dataclass(frozen=True)
class CutItem:
    index: int  # component index in the cut track's Sequence
    kind: Kind
    record_start: int
    length: int
    label: str = ""
    # GROUP only
    group: str | None = None
    src_start: int | None = None
    selected: int | None = None
    # GROUP and OTHER: what is audible, when it could be resolved
    material: Material | None = None
    # effects wrapped around the clip (Audio Gain, ...)
    effects: tuple[str, ...] = ()
    # a wrapper changes timing (speed change, timewarp): never conform this
    timing_change: bool = False
    # TRANSITION only
    cutpoint: int | None = None


@dataclass(frozen=True)
class CutTrack:
    index: int  # 0-based position among the sequence's sound tracks
    name: str
    items: tuple[CutItem, ...]
    length: int
    effects: tuple[str, ...] = ()  # track-level effects, e.g. Audio Pan
    kind: str = "sound"  # or "picture"

    @property
    def is_empty(self) -> bool:
        return all(i.kind is Kind.FILLER for i in self.items)

    @property
    def label(self) -> str:
        prefix = "V" if self.kind == "picture" else "A"
        return f"{prefix}{self.index + 1}" + (f" '{self.name}'" if self.name else "")


@dataclass(frozen=True)
class Cut:
    tracks: tuple[CutTrack, ...]  # sound
    picture: tuple[CutTrack, ...] = ()


class Status(str, Enum):
    KEPT = "kept"  # cut event left exactly as it was, already correct
    KEPT_OTHER = "kept-other"  # not group material (ADR, music): left alone
    BUILT = "built"  # new event from the reference mapping
    CORRECTED = "corrected"  # cut event was wrong material, swapped for the group
    FILLER = "filler"
    TRANSITION = "transition"
    FLAGGED = "flagged"  # needs a human: see note


class Mode(str, Enum):
    REPAIR = "repair"  # the cut already has this track: keep it, fix bad events
    BUILD = "build"  # the cut lacks this track: build it on the pin's edits
    EXTRA = "extra"  # a cut track the layout doesn't have: carried over as is


@dataclass(frozen=True)
class OutItem:
    status: Status
    record_start: int
    length: int
    cut_index: int | None = None  # component index in the source cut track
    ref_key: int | None = None  # reference Selector to copy (BUILT, CORRECTED)
    group: str | None = None
    src_start: int | None = None
    channel: int | None = None
    note: str = ""


@dataclass(frozen=True)
class OutTrack:
    name: str
    mode: Mode
    cut_track: int | None  # cut track the items' cut_index refers to
    ref_track: int | None
    items: tuple[OutItem, ...]
    length: int
    kind: str = "sound"  # or "picture"


@dataclass(frozen=True)
class Plan:
    tracks: tuple[OutTrack, ...]
    pin: int  # cut track index whose edits drive built tracks
    dropped: tuple[int, ...]  # empty cut tracks left out of the output
    warnings: tuple[str, ...] = ()
    picture: tuple[OutTrack, ...] = ()  # one per cut picture track, in order

    @property
    def flagged(self) -> list[tuple[OutTrack, OutItem]]:
        return [
            (t, i)
            for t in (*self.picture, *self.tracks)
            for i in t.items
            if i.status is Status.FLAGGED
        ]

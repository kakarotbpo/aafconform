"""Conform report: terminal summary plus CSV and JSON exports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass

from .match import group_name
from .model import Cut, Mode, Plan, Reference, Status


def timecode(frame: int, fps: int, drop: bool = False) -> str:
    """Frame count to HH:MM:SS:FF (or HH:MM:SS;FF for drop frame)."""
    if drop:
        drop_frames = round(fps / 15)  # 2 at 29.97, 4 at 59.94
        per_10min = fps * 600 - drop_frames * 9
        per_min = fps * 60 - drop_frames
        tens, rem = divmod(frame, per_10min)
        if rem > drop_frames:
            frame += drop_frames * 9 * tens + drop_frames * ((rem - drop_frames) // per_min)
        else:
            frame += drop_frames * 9 * tens
    ff = frame % fps
    s = frame // fps
    sep = ";" if drop else ":"
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}{sep}{ff:02d}"


@dataclass(frozen=True)
class Row:
    track: str
    name: str
    mode: str
    status: str
    record_in: str
    record_out: str
    frames: int
    group: str
    group_pos: int | None
    channel: int | None
    note: str


def _labelled(plan: Plan):
    """(label, track) for picture then audio output tracks."""
    for n, t in enumerate(plan.picture, start=1):
        yield f"V{n}", t
    for n, t in enumerate(plan.tracks, start=1):
        yield f"A{n}", t


def rows(plan: Plan, ref: Reference, tc_start: int, fps: int, drop: bool) -> list[Row]:
    out = []
    for label, t in _labelled(plan):
        for i in t.items:
            if i.status is Status.FILLER and not i.note:
                continue
            out.append(
                Row(
                    track=label,
                    name=t.name,
                    mode=t.mode.value,
                    status=i.status.value,
                    record_in=timecode(tc_start + i.record_start, fps, drop),
                    record_out=timecode(tc_start + i.record_start + i.length, fps, drop),
                    frames=i.length,
                    group=group_name(ref, i.group) if i.group else "",
                    group_pos=i.src_start,
                    channel=i.channel,
                    note=i.note,
                )
            )
    return out


def track_summary(label: str, cut: Cut, t) -> dict:
    """One output track: where it comes from and what happened to its events."""
    counts = Counter(i.status for i in t.items)
    tracks = cut.picture if t.kind == "picture" else cut.tracks
    src = tracks[t.cut_track].label if t.cut_track is not None else ""
    return {
        "label": label,
        "name": t.name,
        "kind": t.kind,
        "mode": t.mode.value,
        "source": src,
        "kept": counts[Status.KEPT],
        "built": counts[Status.BUILT],
        "corrected": counts[Status.CORRECTED],
        "other": counts[Status.KEPT_OTHER],
        "flagged": counts[Status.FLAGGED],
        "dissolves": counts[Status.TRANSITION],
    }


def track_summaries(plan: Plan, cut: Cut) -> list[dict]:
    return [track_summary(label, cut, t) for label, t in _labelled(plan)]


def _track_line(label: str, cut: Cut, t) -> str:
    sm = track_summary(label, cut, t)
    parts = []
    for key, word in (
        ("kept", "kept"),
        ("built", "built"),
        ("corrected", "corrected"),
        ("other", "other material"),
        ("flagged", "FLAGGED"),
    ):
        if sm[key]:
            parts.append(f"{sm[key]} {word}")
    if sm["dissolves"]:
        parts.append(f"{sm['dissolves']} dissolve{'s' if sm['dissolves'] > 1 else ''}")
    src = sm["source"]
    how = {
        Mode.REPAIR: f"kept from cut {src}",
        Mode.BUILD: f"built on {src} edits",
        Mode.EXTRA: f"carried over from cut {src}",
    }[t.mode]
    name = t.name or "-"
    return f"  {label:<4} {name[:16]:<16} {how:<30} {', '.join(parts) or 'empty'}"


def effects_kept(plan: Plan, cut: Cut) -> list[tuple[str, object, object, tuple[str, ...]]]:
    """(label, track, item, effect names) for kept or corrected events with effects."""
    out = []
    for label, t in _labelled(plan):
        if t.mode is not Mode.REPAIR:
            continue
        for i in t.items:
            if i.cut_index is None or i.status not in (Status.KEPT, Status.CORRECTED):
                continue
            names = _effects(cut, t, i)
            if names:
                out.append((label, t, i, names))
    return out


def text(plan: Plan, ref: Reference, cut: Cut, tc_start: int, fps: int, drop: bool) -> str:
    lines = []
    pin = cut.tracks[plan.pin]
    lines.append(f"Edit points for new tracks taken from cut {pin.label}.")
    lines.append("")
    lines.append("Output tracks:")
    for label, t in _labelled(plan):
        lines.append(_track_line(label, cut, t))
    if plan.dropped:
        names = ", ".join(cut.tracks[i].label for i in plan.dropped)
        lines.append(f"  Empty cut tracks left out: {names}")
    for w in plan.warnings:
        lines.append(f"  Warning: {w}")
    lines.append("")
    all_rows = rows(plan, ref, tc_start, fps, drop)
    flagged = [r for r in all_rows if r.status == Status.FLAGGED.value]
    corrected = [r for r in all_rows if r.status == Status.CORRECTED.value]
    # "matched by material" alone is routine for built tracks: CSV/JSON only.
    noted = [
        r
        for r in all_rows
        if r.note and r.note != "matched by material" and r.status in ("kept", "built")
    ]
    effects = effects_kept(plan, cut)
    for title, items in (
        ("Needs attention", flagged),
        ("Corrected", corrected),
        ("Notes", noted),
    ):
        if not items:
            continue
        lines.append(f"{title} ({len(items)}):")
        for r in items:
            lines.append(f"  {r.track:<4} {r.name[:12]:<12} {r.record_in}-{r.record_out}  {r.note}")
        lines.append("")
    if effects:
        lines.append(f"Effects kept ({len(effects)}):")
        for label, t, i, fx in effects:
            tc_in = timecode(tc_start + i.record_start, fps, drop)
            tc_out = timecode(tc_start + i.record_start + i.length, fps, drop)
            names = ", ".join(fx)
            lines.append(f"  {label:<4} {t.name[:12]:<12} {tc_in}-{tc_out}  {names}")
        lines.append("")
    if not flagged:
        lines.append("Nothing flagged.")
    return "\n".join(lines).rstrip() + "\n"


# Avid's own names for common effects, as shown in the Effect Palette.
_EFFECT_NAMES = {"PaintResize_v2": "Resize"}


def _effects(cut: Cut, t, i) -> tuple[str, ...]:
    tracks = cut.picture if t.kind == "picture" else cut.tracks
    item = tracks[t.cut_track].items[i.cut_index]
    return tuple(_EFFECT_NAMES.get(e, e) for e in item.effects)


def write_csv(path, all_rows: list[Row]) -> None:
    fields = list(Row.__dataclass_fields__)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in all_rows:
            w.writerow(r.__dict__)


def write_json(path, all_rows: list[Row], summary: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({**summary, "events": [r.__dict__ for r in all_rows]}, fh, indent=2)
        fh.write("\n")

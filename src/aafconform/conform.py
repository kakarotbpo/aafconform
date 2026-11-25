"""End-to-end conform: read both AAFs, plan, write a new AAF, verify it."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import aaf2

from . import aafread, aafwrite, match
from .model import Cut, Mode, Plan, Reference, Status


class ConformError(Exception):
    pass


@dataclass
class Result:
    plan: Plan
    reference: Reference
    cut: Cut
    reference_name: str
    cut_name: str
    output_name: str
    tc_start: int
    fps: int
    drop: bool


def _plan(rf, f, pin, reference_seq, cut_seq):
    """Read both open files and plan. Returns (Result without output, selectors, comp)."""
    rcomp = aafread.pick_sequence(rf, reference_seq)
    comp = aafread.pick_sequence(f, cut_seq)
    if aafread.edit_rate(rcomp) != aafread.edit_rate(comp):
        raise ConformError(
            f"edit rates differ: reference {aafread.edit_rate(rcomp)}, "
            f"cut {aafread.edit_rate(comp)}"
        )
    ref, selectors = aafread.read_reference(rf, rcomp)
    cut_model = aafread.read_cut(comp)
    plan = match.plan(ref, cut_model, pin)
    tc_start, fps, drop = aafread.timecode_start(comp)
    result = Result(plan, ref, cut_model, rcomp.name, comp.name, "", tc_start, fps, drop)
    return result, selectors, comp


def preview(
    reference: Path,
    cut: Path,
    pin: int | None = None,
    reference_seq: str | None = None,
    cut_seq: str | None = None,
) -> Result:
    """What a conform would do, without writing anything."""
    reference, cut = Path(reference), Path(cut)
    for p in (reference, cut):
        if not p.is_file():
            raise ConformError(f"not found: {p}")
    with aaf2.open(str(reference), "r") as rf, aaf2.open(str(cut), "r") as f:
        result, _, _ = _plan(rf, f, pin, reference_seq, cut_seq)
    return result


def _check_paths(reference: Path, cut: Path, output: Path, force: bool) -> None:
    for p in (reference, cut):
        if not p.is_file():
            raise ConformError(f"not found: {p}")
    out = output.resolve()
    if out in (reference.resolve(), cut.resolve()):
        raise ConformError("the output must be a new file, not one of the inputs")
    if output.exists() and not force:
        raise ConformError(f"{output} already exists (use --force to replace it)")


def conform(
    reference: Path,
    cut: Path,
    output: Path,
    pin: int | None = None,
    reference_seq: str | None = None,
    cut_seq: str | None = None,
    force: bool = False,
) -> Result:
    reference, cut, output = Path(reference), Path(cut), Path(output)
    _check_paths(reference, cut, output, force)
    partial = output.with_name(output.name + ".partial")
    shutil.copyfile(cut, partial)
    try:
        with aaf2.open(str(reference), "r") as rf, aaf2.open(str(partial), "rw") as f:
            result, selectors, comp = _plan(rf, f, pin, reference_seq, cut_seq)
            new = aafwrite.write(f, comp, result.plan, rf, selectors)
            result.output_name = new.name
        _verify(partial, result.output_name, result.plan, result.cut)
        os.replace(partial, output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return result


def _verify(path: Path, name: str, plan: Plan, cut: Cut) -> None:
    """Re-read the written file and check it matches the plan."""
    with aaf2.open(str(path), "r") as f:
        comp = aafread.pick_sequence(f, name)
        written = aafread.read_cut(comp)
    _verify_repaired(written.picture, cut.picture, plan.picture)
    _verify_repaired(
        written.tracks, cut.tracks, [t for t in plan.tracks if t.mode is Mode.REPAIR], by_plan=True
    )
    if len(written.tracks) != len(plan.tracks):
        raise ConformError("verification failed: wrong number of audio tracks written")
    for w, t in zip(written.tracks, plan.tracks, strict=True):
        if w.length != t.length:
            raise ConformError(f"verification failed: track '{t.name}' has the wrong length")
        if t.mode is not Mode.EXTRA and w.name != t.name:
            raise ConformError(f"verification failed: track '{t.name}' written as '{w.name}'")
        want = [
            (i.record_start, i.length)
            for i in t.items
            if i.status in (Status.BUILT, Status.CORRECTED, Status.KEPT)
        ]
        got = {(i.record_start, i.length) for i in w.items if i.group is not None}
        missing = [x for x in want if x not in got]
        if missing:
            raise ConformError(
                f"verification failed: track '{t.name}' is missing events at {missing}"
            )


def _verify_repaired(written_tracks, cut_tracks, out_tracks, by_plan: bool = False) -> None:
    """Repaired tracks: every event in place, effects intact, corrections applied."""
    for n, t in enumerate(out_tracks):
        w = written_tracks[_index_of(t, n, written_tracks, by_plan)]
        c = cut_tracks[t.cut_track]
        if len(w.items) != len(c.items) or w.effects != c.effects:
            raise ConformError(f"verification failed: track '{t.name}' structure changed")
        for i in t.items:
            if i.cut_index is None:
                continue
            got, was = w.items[i.cut_index], c.items[i.cut_index]
            if (got.record_start, got.length, got.effects) != (
                was.record_start,
                was.length,
                was.effects,
            ):
                raise ConformError(
                    f"verification failed: track '{t.name}' event at {i.record_start} changed"
                )
            if i.status is Status.CORRECTED and (got.group, got.src_start) != (
                i.group,
                i.src_start,
            ):
                raise ConformError(
                    f"verification failed: track '{t.name}' event at {i.record_start} "
                    "was not corrected"
                )


def _index_of(t, n, written_tracks, by_plan) -> int:
    """Picture tracks keep their order; audio tracks are found by name."""
    if not by_plan:
        return n
    for k, w in enumerate(written_tracks):
        if w.name == t.name:
            return k
    raise ConformError(f"verification failed: track '{t.name}' missing")

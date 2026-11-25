"""Entry points for front ends such as the desktop app.

Everything returns plain dicts and lists of str, int, bool and None, so it can
be passed straight to a web view as JSON. Every expected failure raises
ApiError with a message written for the editor, not a traceback.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import aaf2

from . import aafread, report
from .aafwrite import WriteError
from .conform import ConformError, Result
from .conform import conform as _conform
from .conform import preview as _preview
from .inspect_aaf import DumpOptions, dump_json
from .match import MatchError
from .model import Kind


class ApiError(Exception):
    pass


_EXPECTED = (ConformError, aafread.ReadError, MatchError, WriteError, OSError)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _EXPECTED as e:
        raise ApiError(str(e)) from e
    except Exception as e:  # unreadable or unexpected AAF content
        raise ApiError(f"could not read the AAF: {type(e).__name__}: {e}") from e


def default_output(cut: str | Path) -> str:
    """Where a conform writes by default: next to the cut, named '<cut> CONFORMED.aaf'."""
    cut = Path(cut)
    return str(cut.with_name(f"{cut.stem} CONFORMED.aaf"))


def _track_info(t) -> dict:
    return {
        "label": t.label.split(" ")[0],
        "name": t.name,
        "kind": t.kind,
        "events": sum(1 for i in t.items if i.kind in (Kind.GROUP, Kind.OTHER)),
        "multigroup_events": sum(1 for i in t.items if i.kind is Kind.GROUP),
        "empty": t.is_empty,
        "effects": list(t.effects),
    }


def _describe(path: Path, sequence: str | None) -> dict:
    if not path.is_file():
        raise ConformError(f"not found: {path}")
    with aaf2.open(str(path), "r") as f:
        names = [m.name for m in f.content.toplevel()]
        out = {"path": str(path), "file": path.name, "sequences": names, "sequence": None}
        if sequence is None and len(names) != 1:
            return out
        comp = aafread.pick_sequence(f, sequence)
        cut = aafread.read_cut(comp)
        tc_start, fps, drop = aafread.timecode_start(comp)
        length = max((t.length for t in (*cut.picture, *cut.tracks)), default=0)
        groups = aafread.group_names(f)
        used = sorted({i.group for t in (*cut.picture, *cut.tracks) for i in t.items if i.group})
        out["sequence"] = {
            "name": comp.name,
            "fps": fps,
            "drop": drop,
            "start": report.timecode(tc_start, fps, drop),
            "duration": report.timecode(length, fps, drop),
            "frames": length,
            "picture": [_track_info(t) for t in cut.picture],
            "sound": [_track_info(t) for t in cut.tracks],
            "groups": [groups.get(g, g[-8:]) for g in used],
        }
    return out


def describe(path: str | Path, sequence: str | None = None) -> dict:
    """Summary of an AAF for the load screen: its sequence, tracks and groups."""
    return _guard(_describe, Path(path), sequence)


def _result(r: Result, output: str | None) -> dict:
    rows = report.rows(r.plan, r.reference, r.tc_start, r.fps, r.drop)
    tracks = report.track_summaries(r.plan, r.cut)
    effects = [
        {
            "track": label,
            "name": t.name,
            "record_in": report.timecode(r.tc_start + i.record_start, r.fps, r.drop),
            "record_out": report.timecode(r.tc_start + i.record_start + i.length, r.fps, r.drop),
            "effects": list(fx),
        }
        for label, t, i, fx in report.effects_kept(r.plan, r.cut)
    ]
    # Per output track, every event's position for drawing a timeline lane.
    lanes = [
        {
            "label": label,
            "name": t.name,
            "mode": t.mode.value,
            "length": t.length,
            "items": [
                [i.record_start, i.length, i.status.value]
                for i in t.items
                if i.status.value not in ("filler", "transition")
            ],
        }
        for label, t in report.labelled(r.plan)
    ]
    totals = {k: sum(t[k] for t in tracks) for k in ("kept", "built", "corrected", "other")}
    totals["flagged"] = len(r.plan.flagged)
    totals["effects"] = len(effects)
    return {
        "reference": r.reference_name,
        "cut": r.cut_name,
        "sequence": r.output_name or None,
        "output": output,
        "timecode": {"fps": r.fps, "drop": r.drop, "start": r.tc_start},
        "pin": r.cut.tracks[r.plan.pin].label,
        "tracks": tracks,
        "dropped": [r.cut.tracks[i].label for i in r.plan.dropped],
        "warnings": list(r.plan.warnings),
        "totals": totals,
        "effects": effects,
        "events": [asdict(row) for row in rows],
        "lanes": lanes,
        "length": max((ln["length"] for ln in lanes), default=0),
        "csv": None,
    }


def preview(
    reference: str | Path,
    cut: str | Path,
    pin: int | None = None,
    reference_seq: str | None = None,
    cut_seq: str | None = None,
) -> dict:
    """What a conform would do, without writing anything."""
    r = _guard(_preview, Path(reference), Path(cut), pin, reference_seq, cut_seq)
    return _result(r, None)


def conform(
    reference: str | Path,
    cut: str | Path,
    output: str | Path | None = None,
    pin: int | None = None,
    reference_seq: str | None = None,
    cut_seq: str | None = None,
    force: bool = False,
    csv_path: str | Path | None = None,
    json_path: str | Path | None = None,
) -> dict:
    """Write the conformed AAF (and optional CSV/JSON reports). Inputs are never modified."""
    out = Path(output) if output else Path(default_output(cut))
    r = _guard(
        _conform,
        Path(reference),
        Path(cut),
        out,
        pin=pin,
        reference_seq=reference_seq,
        cut_seq=cut_seq,
        force=force,
    )
    result = _result(r, str(out))
    rows = report.rows(r.plan, r.reference, r.tc_start, r.fps, r.drop)
    if csv_path:
        _guard(report.write_csv, csv_path, rows)
        result["csv"] = str(csv_path)
    if json_path:
        summary = {k: result[k] for k in ("reference", "cut", "output", "sequence")}
        summary["flagged"] = result["totals"]["flagged"]
        _guard(report.write_json, json_path, rows, summary)
    return result


def inspect(path: str | Path) -> dict:
    """The full structure dump used by the Inspect screen."""
    return _guard(lambda: json.loads(dump_json(str(path), DumpOptions())))

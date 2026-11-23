"""Human-readable and JSON dumps of AAF structure.

This module is diagnostic only. It never writes to the input file. Its job is to
show exactly what an AAF contains (mobs, slots, sequences, selectors, operation
groups, source clips, timecodes, edit rates and any Avid-specific properties) so
the conform design can be based on real data rather than assumptions.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

import aaf2
from aaf2 import components, core, mobs, mobslots, properties
from aaf2.auid import AUID
from aaf2.mobid import MobID

# Properties rendered explicitly by the tree printer. Anything else found on an
# object is printed as an "extra" so nothing Avid-specific is hidden.
_HANDLED = {
    "DataDefinition",
    "Length",
    "Components",
    "SourceID",
    "SourceMobSlotID",
    "StartTime",
    "Selected",
    "Alternates",
    "Operation",
    "InputSegments",
    "Parameters",
    "Start",
    "FPS",
    "Drop",
    "CutPoint",
    "OperationGroup",
    "Segment",
    "SlotID",
    "SlotName",
    "EditRate",
    "Origin",
    "Choices",
    "StillFrame",
    "Slots",
    "Mobs",
    "MobID",
    "Name",
}

_MAX_VALUE_CHARS = 160


@dataclass
class DumpOptions:
    extras: bool = True  # print properties not otherwise rendered
    mob_filter: str | None = None  # substring match on mob name or id
    kinds: tuple[str, ...] = ("CompositionMob", "MasterMob", "SourceMob")


@dataclass
class _Out:
    lines: list[str] = field(default_factory=list)

    def add(self, depth: int, text: str) -> None:
        self.lines.append("  " * depth + text)


# ---------------------------------------------------------------------------
# value formatting


def fmt_value(value: Any, depth: int = 0) -> str:
    """Compact, deterministic string for any AAF property value."""
    if depth > 3:
        return "..."
    if value is None:
        return "None"
    if isinstance(value, (MobID, AUID)):
        return str(value)
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, bytes | bytearray):
        return f"<{len(value)} bytes>"
    if isinstance(value, core.AAFObject):
        return _fmt_object_ref(value, depth)
    if isinstance(value, dict):
        inner = ", ".join(f"{k}={fmt_value(v, depth + 1)}" for k, v in value.items())
        return "{" + inner + "}"
    if isinstance(value, list | tuple | set):
        inner = ", ".join(fmt_value(v, depth + 1) for v in value)
        return "[" + inner + "]"
    text = str(value)
    if len(text) > _MAX_VALUE_CHARS:
        text = text[:_MAX_VALUE_CHARS] + "..."
    return text


def _fmt_object_ref(obj: core.AAFObject, depth: int) -> str:
    cls = obj.classdef.class_name if obj.classdef else type(obj).__name__
    # Tagged values (Avid attribute lists, comments) are name/value pairs.
    if "Name" in obj and "Value" in obj:
        return f"{obj['Name'].value}={fmt_value(obj['Value'].value, depth + 1)}"
    # Definitions (DataDef, OperationDef, ParameterDef ...) are best shown by name.
    if "Name" in obj and cls.endswith("Definition"):
        return f"{cls}({obj['Name'].value})"
    if isinstance(obj, mobs.Mob):
        return f"{cls}({obj.name!r} {obj.mob_id})"
    # Generic small object: show its scalar properties.
    parts = []
    for p in obj.properties():
        if isinstance(p, properties.StrongRefVectorProperty | properties.StrongRefSetProperty):
            parts.append(f"{p.name}=[{len(list(p.value or []))} items]")
            continue
        parts.append(f"{p.name}={fmt_value(_safe_value(p), depth + 1)}")
    return f"{cls}({', '.join(parts)})"


def _safe_value(p: properties.Property) -> Any:
    try:
        return p.value
    except Exception as exc:  # pyaaf2 can raise on unknown/opaque types
        return f"<unreadable: {type(exc).__name__}>"


def _class_name(obj: core.AAFObject) -> str:
    return obj.classdef.class_name if obj.classdef else type(obj).__name__


def _datadef_name(obj: core.AAFObject) -> str:
    try:
        return obj.media_kind or "?"
    except Exception:
        return "?"


def _extras(obj: core.AAFObject) -> list[str]:
    out = []
    for p in obj.properties():
        if p.name in _HANDLED:
            continue
        out.append(f"{p.name}={fmt_value(_safe_value(p))}")
    return out


# ---------------------------------------------------------------------------
# tree printing


def _describe_clip_target(clip: components.SourceReference) -> str:
    mob_id = clip.mob_id
    if mob_id is None or mob_id.int == 0:
        return "-> <end of chain>"
    mob = clip.mob
    if mob is None:
        return f"-> <mob not in file> slot={clip.slot_id} id={mob_id}"
    return f"-> {_class_name(mob)} {mob.name!r} slot={clip.slot_id} id={mob_id}"


def _segment(
    out: _Out, seg: core.AAFObject, depth: int, opts: DumpOptions, pos: int | None
) -> None:
    cls = _class_name(seg)
    length = seg.getvalue("Length")
    head = (
        f"[{pos} +{length}] "
        if pos is not None
        else (f"[+{length}] " if length is not None else "")
    )
    kind = _datadef_name(seg) if isinstance(seg, components.Component) else ""
    kind_s = f" ({kind})" if kind else ""

    if isinstance(seg, components.SourceClip):
        out.add(depth, f"{head}SourceClip{kind_s} start={seg.start} {_describe_clip_target(seg)}")
    elif isinstance(seg, components.Timecode):
        out.add(depth, f"{head}Timecode start={seg.start} fps={seg.fps} drop={seg.drop}")
    elif isinstance(seg, components.Transition):
        out.add(depth, f"{head}Transition{kind_s} cutpoint={seg.getvalue('CutPoint')}")
        op = seg.getvalue("OperationGroup")
        if op is not None:
            _segment(out, op, depth + 1, opts, None)
    elif isinstance(seg, components.OperationGroup):
        op = seg.getvalue("Operation")
        op_name = op["Name"].value if op is not None and "Name" in op else "?"
        out.add(depth, f"{head}OperationGroup{kind_s} op={op_name!r}")
        for param in seg.getvalue("Parameters") or []:
            out.add(depth + 1, f"param {fmt_value(param)}")
        for i, inp in enumerate(seg.getvalue("InputSegments") or []):
            out.add(depth + 1, f"input[{i}]:")
            _segment(out, inp, depth + 2, opts, None)
    elif isinstance(seg, components.Selector):
        alternates = seg.getvalue("Alternates") or []
        out.add(depth, f"{head}Selector{kind_s} alternates={len(alternates)}")
        selected = seg.getvalue("Selected")
        if selected is not None:
            out.add(depth + 1, "selected:")
            _segment(out, selected, depth + 2, opts, None)
        for i, alt in enumerate(alternates):
            out.add(depth + 1, f"alternate[{i}]:")
            _segment(out, alt, depth + 2, opts, None)
    elif isinstance(seg, components.EssenceGroup):
        choices = seg.getvalue("Choices") or []
        out.add(depth, f"{head}EssenceGroup{kind_s} choices={len(choices)}")
        for i, ch in enumerate(choices):
            out.add(depth + 1, f"choice[{i}]:")
            _segment(out, ch, depth + 2, opts, None)
    elif isinstance(seg, components.Sequence):
        comps = list(seg.components)
        out.add(depth, f"{head}Sequence{kind_s} components={len(comps)}")
        _sequence_body(out, comps, depth + 1, opts)
    elif isinstance(seg, components.NestedScope):
        slots = seg.getvalue("Slots") or []
        out.add(depth, f"{head}NestedScope{kind_s} slots={len(slots)}")
        for i, s in enumerate(slots):
            out.add(depth + 1, f"scope[{i}]:")
            _segment(out, s, depth + 2, opts, None)
    else:
        out.add(depth, f"{head}{cls}{kind_s}")

    if opts.extras:
        for e in _extras(seg):
            out.add(depth + 1, f". {e}")


def _sequence_body(out: _Out, comps: list, depth: int, opts: DumpOptions) -> None:
    # Record position in the sequence. Transitions overlap the components on
    # either side, so they subtract from the running position.
    pos = 0
    for comp in comps:
        length = comp.getvalue("Length") or 0
        if isinstance(comp, components.Transition):
            pos -= length
            _segment(out, comp, depth, opts, pos)
        else:
            _segment(out, comp, depth, opts, pos)
            pos += length


def _slot(out: _Out, slot: mobslots.MobSlot, depth: int, opts: DumpOptions) -> None:
    cls = _class_name(slot)
    rate = slot.getvalue("EditRate")
    rate_s = f" rate={fmt_value(rate)}" if rate is not None else ""
    origin = slot.getvalue("Origin")
    origin_s = f" origin={origin}" if origin else ""
    phys = slot.getvalue("PhysicalTrackNumber")
    phys_s = f" phys={phys}" if phys is not None else ""
    name = slot.getvalue("SlotName")
    kind = _datadef_name(slot)
    out.add(depth, f"{cls} id={slot.slot_id} name={name!r} kind={kind}{rate_s}{origin_s}{phys_s}")
    if opts.extras:
        for e in _extras(slot):
            if not e.startswith("PhysicalTrackNumber="):
                out.add(depth + 1, f". {e}")
    seg = slot.segment
    if seg is not None:
        _segment(out, seg, depth + 1, opts, None)


def _mob(out: _Out, mob: mobs.Mob, opts: DumpOptions) -> None:
    cls = _class_name(mob)
    out.add(0, f"{cls} {mob.name!r}")
    out.add(1, f"mob_id={mob.mob_id}")
    usage = mob.getvalue("UsageCode")
    if usage is not None:
        out.add(1, f"usage={fmt_value(usage)}")
    if isinstance(mob, mobs.SourceMob):
        desc = mob.getvalue("EssenceDescription")
        if desc is not None:
            out.add(1, f"descriptor={_class_name(desc)}")
            if opts.extras:
                for e in _extras(desc):
                    out.add(2, f". {e}")
    if opts.extras:
        for e in _extras(mob):
            if e.startswith(("UsageCode=", "EssenceDescription=")):
                continue
            out.add(1, f". {e}")
    for slot in mob.slots:
        _slot(out, slot, 1, opts)
    out.add(0, "")


def _matches(mob: mobs.Mob, needle: str | None) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    return needle in (mob.name or "").lower() or needle in str(mob.mob_id).lower()


def iter_mobs(f: aaf2.file.AAFFile, opts: DumpOptions) -> Iterator[mobs.Mob]:
    order = {"CompositionMob": 0, "MasterMob": 1, "SourceMob": 2}
    selected = [
        m for m in f.content.mobs if _class_name(m) in opts.kinds and _matches(m, opts.mob_filter)
    ]
    selected.sort(key=lambda m: (order.get(_class_name(m), 9), m.name or "", str(m.mob_id)))
    return iter(selected)


def summary_lines(f: aaf2.file.AAFFile) -> list[str]:
    counts: dict[str, int] = {}
    for m in f.content.mobs:
        counts[_class_name(m)] = counts.get(_class_name(m), 0) + 1
    lines = ["# Summary"]
    lines += [f"{k}: {v}" for k, v in sorted(counts.items())]
    top = [m for m in f.content.toplevel()]
    lines.append(f"top-level compositions: {len(top)}")
    for m in top:
        lines.append(f"  {m.name!r} {m.mob_id}")
    ident = f.header.getvalue("IdentificationList") or []
    for i in ident:
        product = i.getvalue("ProductName")
        version = i.getvalue("ProductVersionString")
        company = i.getvalue("CompanyName")
        lines.append(f"written by: {company} {product} {version}")
    lines.append("")
    return lines


def dump_text(path: str, opts: DumpOptions | None = None) -> str:
    opts = opts or DumpOptions()
    out = _Out()
    with aaf2.open(path, "r") as f:
        out.lines += summary_lines(f)
        for mob in iter_mobs(f, opts):
            _mob(out, mob, opts)
    return "\n".join(out.lines)


# ---------------------------------------------------------------------------
# JSON (full property tree, for diffing and offline analysis)


def _to_json(obj: Any, seen: set[int], depth: int = 0) -> Any:
    if depth > 64:
        return "<max depth>"
    if isinstance(obj, core.AAFObject):
        if id(obj) in seen:
            return f"<cycle {_class_name(obj)}>"
        seen = seen | {id(obj)}
        node: dict[str, Any] = {"_class": _class_name(obj)}
        for p in obj.properties():
            if isinstance(p, properties.WeakRefProperty | properties.WeakRefArrayProperty):
                node[p.name] = fmt_value(_safe_value(p))
                continue
            if isinstance(p, properties.StreamProperty):
                node[p.name] = "<stream>"
                continue
            node[p.name] = _to_json(_safe_value(p), seen, depth + 1)
        return node
    if isinstance(obj, list | tuple | set):
        return [_to_json(v, seen, depth + 1) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _to_json(v, seen, depth + 1) for k, v in obj.items()}
    if isinstance(obj, int | float | str | bool) or obj is None:
        return obj
    return fmt_value(obj)


def dump_json(path: str, opts: DumpOptions | None = None) -> str:
    opts = opts or DumpOptions()
    with aaf2.open(path, "r") as f:
        data = {
            "file": path,
            "mobs": [_to_json(m, set()) for m in iter_mobs(f, opts)],
        }
    return json.dumps(data, indent=2, sort_keys=False)

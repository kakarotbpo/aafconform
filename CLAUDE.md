# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`aafconform`: a Python CLI that rebuilds an Avid Media Composer cut (cut.aaf) using
the multigroup from a reference sequence (reference.aaf), keeping the cut's edit
points but filling every event from the matching reference range on all tracks.
The user is a TV picture editor. They test outputs by importing them into Media
Composer and reporting back, so Avid's actual behaviour is the source of truth
over the AAF spec.

## Commands

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                                          # all tests
.venv/bin/pytest tests/test_inspect.py::test_name         # single test
.venv/bin/ruff check . && .venv/bin/ruff format --check . # lint
.venv/bin/aafconform inspect FILE.aaf [--kind CompositionMob] [--mob NAME] [--json]
.venv/bin/aafconform conform LAYOUT.aaf CUT.aaf -o OUT.aaf [--pin A1] [--csv F] [--json F]
.venv/bin/pip install -e '.[dev,app]' && .venv/bin/aafconform-app   # desktop app
.venv/bin/python -m aafconform.app --serve                          # UI in a browser
```

## How Avid exports a multigroup (from the real samples, MC 25.12)

- The group is an unnamed inner `CompositionMob` whose slots are the group's
  channels (slot 1 picture, 2/3 mix L/R, 4+ isos), plus a bin mob flagged
  `_MLT_GRP=1` in `MobAttributeList`. A group is identified by the inner
  composition's MobID.
- Sequence tracks hold `Selector`s whose clips all point into the inner
  composition at the same start: `Selected` is the channel the track plays,
  `Alternates` the switchable others, `ComponentAttributeList._AAF_SELECTED` an
  index. The "mapping" of a layout is which channel each track selects.
- Every picture clip is wrapped in an OperationGroup 'SpatialAdapter' (the clip's
  framing). It belongs to the clip, not an effect: `aafread.CLIP_WRAPPERS`. A
  picture group event is Selector -> SpatialAdapter -> Sequence -> SourceClip;
  a user effect (e.g. Resize, op 'PaintResize_v2') wraps the whole thing.
  Correcting a clip replaces the SpatialAdapter node, keeping effects above it.
- Group footage can repeat (same file at several group positions), so material
  matches are tie-broken by sync with the cut's own multigroup events
  (`match.sync_index`). No unique synced match means flagged.
- A track-level effect (e.g. Audio Pan set on the track) wraps the slot's whole
  Sequence in an OperationGroup. Always go through `aafread.track_sequence()`.
- A plain group clip (bin name `X.Grp.01`, no `_MLT_GRP`) looks exactly like a
  multigroup in a sequence. Only groups used by the master layout count; any
  other group is matched by material.
- Avid regenerates some master clip MobIDs on every export (e.g. a mixdown
  master clip, AppCode=10), so material is matched by the essence file mob (.PHYS SourceMob),
  which is stable.

## Architecture

- `cli.py` - argparse entry point: `inspect`, `conform`.
- `model.py` - plain dataclasses shared by everything below.
- `aafread.py` - AAF to model: reference segments (group, position, mapping), cut
  items (group / other / filler / transition), material resolved down the mob
  chain to the file mob.
- `match.py` - pure planning, no pyaaf2: pairs cut tracks to layout tracks by the
  channel they play, then per layout track either repairs the cut's track (keep
  correct events, swap provably-same material for the group) or builds it on the
  pin track's edits. Unit tested on hand-built data in `tests/test_match.py`.
- `aafwrite.py` - copies the cut file, opens it 'rw', rebuilds the top-level
  sequence's audio slots (reference Selectors are copied across files and
  retimed), gives the sequence a new MobID and name.
- `conform.py` - orchestration: writes to `<out>.partial`, re-reads it to verify
  against the plan, then renames. `report.py` - terminal, CSV, JSON.
- `api.py` - JSON-safe entry points for front ends (describe, preview, conform,
  inspect); expected failures raise ApiError with an editor-facing message.
- `app/` - the desktop app. `bridge.py` is what the window can call (returns
  {ok, data|error}); `window.py` opens it with pywebview, served over its local
  http server (fonts fail over file://); `devserver.py` serves the same UI to a
  browser for development and the Playwright test in `tests/test_app.py`;
  `ui/` is plain HTML/CSS/JS (escape everything from AAFs before innerHTML).
  `aafconform-app --self-test` checks a packaged build end to end without a window.
- `packaging/launcher.py` + `.github/workflows/build.yml` - PyInstaller build of
  the Windows app, self-tested on the runner, zipped; attached to a Release on `v*` tags.
- `inspect_aaf.py` - read-only dump. Prints every unmodelled property as an
  "extra" so Avid-specific data is never hidden.
- `synthetic.py` - pyaaf2-built fixtures (in the package so the app self-test can use them); `build_avid_group` mirrors the real
  multigroup structure and exercises correction paths the samples don't.
  Real files in `samples/` (git-ignored) are ground truth: `test_conform.py`
  checks the output matches Avid's own fixed RESULT sample exactly.

Design constraints:
- Matching logic stays separate from AAF reading and writing.
- Never modify input files. Always write a new output.
- Anything not safely conformable is flagged in the report, never guessed.

## pyaaf2 gotchas

- Never nest `f.create.X(...)` calls inside another `f.create.Y(...)`'s arguments.
  The factory stores the class name before arguments are evaluated, so the
  outer call silently creates the inner class. Assign to a variable first.
- `Selector` has no helper properties. Use `sel["Selected"].value` and
  `sel["Alternates"].value`.
- `Transition` requires an `OperationGroup`, which requires a registered
  `OperationDef` (`f.dictionary.register_def`).
- `Sequence.length` is not computed from its components. Set it explicitly
  (transitions overlap their neighbours and subtract from the total).
- A `SourceClip` with an all-zero MobID marks the end of a mob chain (tape or
  import source).
- `obj.copy(root=other_file)` copies across files (registers class defs). A
  copied or new object must not already be attached: use `.copy()` then
  `vector.pop(i)` / `vector.insert(i, new)` to swap components.
- `aaf2.open(path, "rw")` edits in place: always on a copy, never an input.
- Writing is validated on save: missing required properties raise
  `AAFPropertyError` at close time, not at assignment.

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
```

## Architecture

- `src/aafconform/cli.py` - argparse entry point, subcommands.
- `src/aafconform/inspect_aaf.py` - read-only structure dump (text tree and JSON).
  Prints every property it doesn't model as an "extra" so Avid-specific data
  (attribute lists, multigroup/audio mapping hints) is never hidden.
- `tests/synthetic.py` - builds small AAFs with pyaaf2 for tests. These only
  approximate Avid exports; real files in `samples/` are ground truth and are
  auto-tested by `test_real_samples_dump_without_error`.

Planned design constraints (from the project brief):
- Matching logic must stay separate from AAF reading and writing, operating on
  plain data structures so it can be unit tested without AAF files.
- Never modify input files. Always write a new output.
- Anything not safely conformable (speed changes, timewarps, etc.) is flagged in
  the report, never guessed.
- Match by MobID plus source position first, then fall back to source timecode
  plus tape or clip name.

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
- Writing is validated on save: missing required properties raise
  `AAFPropertyError` at close time, not at assignment.

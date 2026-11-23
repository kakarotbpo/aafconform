# aafconform

Rebuild an Avid Media Composer cut against the proper multigroup from a reference
sequence.

Given two linked AAFs (no embedded media):

- **reference.aaf** - a sequence built from a multigroup with the correct camera
  angles on V1 and the full iso audio mapping (for example A1 to A23)
- **cut.aaf** - an edit of the same material with the wrong clip structure (pulled
  multigroup video with one audio stream, or a single ungrouped camera with
  ungrouped audio)

`aafconform` produces a new AAF with the edit points of the cut, where every
event is filled from the matching range of the reference multigroup on all tracks.
The inputs are never modified.

## Status

Early development. The read-only `inspect` command works. The `conform`
command will be designed once real Media Composer sample exports have been
inspected.

## Install

Requires Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Usage

### Inspect an AAF

```sh
aafconform inspect cut.aaf                       # all mobs as an indented tree
aafconform inspect cut.aaf --kind CompositionMob # sequences and group clips only
aafconform inspect ref.aaf --mob MULTIGROUP      # mobs whose name or MobID matches
aafconform inspect ref.aaf --json -o ref.json    # full property tree as JSON
```

The tree shows each sequence component as `[record position +length]`, follows
source clips to the mob they reference, expands Selectors (group clips),
transitions and effects, and lists every property it doesn't model explicitly
(prefixed with `.`). Use `--no-extras` to hide those.

## Development

```sh
.venv/bin/pytest            # tests (real AAFs in ./samples are picked up automatically)
.venv/bin/ruff check .      # lint
.venv/bin/ruff format .     # format
```

## Licence

MIT, see [LICENSE](LICENSE).

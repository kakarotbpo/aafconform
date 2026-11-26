# aafconform

Rebuild an Avid Media Composer cut against the proper multigroup from a reference
sequence.

Given two linked AAFs (no embedded media) exported from Media Composer:

- **master layout** - a sequence with the episode's track layout, where each audio
  track plays the right channel of each scene's multigroup (for example MIX L,
  MIX R, then one iso track per contributor)
- **cut** - an edit built on the wrong sequence template, so some of those tracks
  are missing or carry the wrong material

`aafconform` writes a new AAF with the master layout's audio tracks and the cut's
edit points. The inputs are never modified.

- Audio tracks the cut already has (for example MIX L and MIX R) are kept exactly
  as the editor left them, with gain, dissolves and any non-group material such
  as ADR. An event is only replaced when it is not provably from the correct
  multigroup and channel, and the same material is found in the master layout.
- Tracks the cut lacks are built on the cut's mix track edit points, so split
  edits (L and J cuts) stay split. Audio dissolves are copied, gain is not.
- Tracks the layout doesn't have (music, SFX) are kept after the layout's tracks.
  Empty tracks are dropped.
- Picture is checked too. Multigroup events are kept whatever camera angle they
  play (that's an editing choice). Footage cut in outside the multigroup, such
  as a camera master clip, is swapped for the multigroup when it is provably the
  same picture. Effects on the event (Resize and so on) stay.
- When the same footage sits in more than one place in the multigroup, the place
  in sync with the cut's multigroup audio at that point is used. If none is, the
  event is flagged.
- Anything that can't be conformed safely (speed changes, material that belongs to
  a different channel, ambiguous matches) is flagged in the report, never guessed.

## Status

Early development. `inspect` and `conform` work against the sample exports from
Media Composer 25.12, and conformed AAFs have been imported back into Media
Composer successfully. Not yet tried on an episode-length cut.

## Desktop app (Windows)

Download `aafconform-windows.zip` from the latest
[release](https://github.com/kakarotbpo/aafconform/releases) (or from the
"Windows app" workflow run on the Actions tab), unzip it anywhere and run
`aafconform.exe`. Nothing is installed and nothing leaves the machine.

- Drop the master sequence AAF and the pull AAF onto the window (or use Choose
  file, Ctrl+O), check the track plan, then Conform (Ctrl+Enter).
- The new AAF is written next to the pull by default, with a CSV report beside it.
- The app isn't code-signed yet, so the first launch shows Windows SmartScreen's
  "Windows protected your PC": choose More info, then Run anyway.
- It uses Microsoft Edge WebView2, which is built into Windows 10 and 11.

## Install


Requires Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Usage

### Conform a cut

```sh
aafconform conform "MASTER LAYOUT.aaf" "EDIT.aaf"                 # writes "EDIT CONFORMED.aaf"
aafconform conform layout.aaf edit.aaf -o fixed.aaf --csv report.csv --json report.json
aafconform conform layout.aaf edit.aaf --pin A2                   # take edits from A2
```

The new sequence is named after the output file (by default the cut's name with
` CONFORMED` added), since that name is what Media Composer's bin shows, and gets
a new MobID, so it can sit in the same bin as the original. The terminal report lists
each output track, what was kept, built or corrected, and anything that needs
attention, with record timecodes. The CSV and JSON reports have every event.

### Importing the result into Media Composer

Import the conformed AAF into the project the cut came from. Media Composer may
ask about a "Group clip conflict" for the multigroup: answer **No** (or **No To
All**). The conformed sequence links to the multigroup by ID, so it uses the
project's own copy; answering Yes would replace it with the snapshot stored in
the AAF, which can be older than the one in the project.

Tested with Media Composer 25.12 (HD 1080i/50, 25 fps).

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
.venv/bin/pip install -e '.[dev,app]'
.venv/bin/aafconform-app                    # the desktop app
.venv/bin/python -m aafconform.app --serve  # the same interface in a browser
.venv/bin/pytest            # tests (real AAFs in ./samples are picked up automatically)
.venv/bin/ruff check .      # lint
.venv/bin/ruff format .     # format
```

## Licence

MIT, see [LICENSE](LICENSE).

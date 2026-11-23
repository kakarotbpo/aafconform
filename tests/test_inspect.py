import hashlib
import json
from pathlib import Path

import pytest

from aafconform.cli import main
from aafconform.inspect_aaf import DumpOptions, dump_json, dump_text

from . import synthetic

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(scope="module")
def ref_aaf(tmp_path_factory):
    path = tmp_path_factory.mktemp("aaf") / "ref.aaf"
    synthetic.build_reference(str(path))
    return path


@pytest.fixture(scope="module")
def cut_aaf(tmp_path_factory):
    path = tmp_path_factory.mktemp("aaf") / "cut.aaf"
    synthetic.build_cut(str(path))
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_selector_alternates_are_dumped(ref_aaf):
    text = dump_text(str(ref_aaf), DumpOptions(mob_filter="MULTIGROUP"))
    assert "Selector (Picture) alternates=1" in text
    assert "selected:" in text
    assert "MasterMob 'A001C001'" in text
    assert "MasterMob 'B001C001'" in text
    assert "name='A4' kind=Sound" in text


def test_record_positions_account_for_transitions(cut_aaf):
    text = dump_text(str(cut_aaf), DumpOptions(kinds=("CompositionMob",)))
    assert "[0 +50] SourceClip (Picture) start=100" in text
    assert "[40 +10] Transition (Picture) cutpoint=5" in text
    assert "op='Video Dissolve'" in text
    assert "[40 +40] SourceClip (Picture) start=200" in text
    assert "[80 +10] Filler (Picture)" in text
    # nested OperationGroup is rendered once, not repeated as an extra property
    assert text.count("Video Dissolve") == 1


def test_tape_mob_is_end_of_chain_and_has_timecode(ref_aaf):
    text = dump_text(str(ref_aaf), DumpOptions(mob_filter="A001", kinds=("SourceMob",)))
    assert "descriptor=TapeDescriptor" in text
    assert "-> <end of chain>" in text
    assert "Timecode start=900000 fps=25 drop=False" in text


def test_json_is_valid_and_complete(ref_aaf):
    data = json.loads(dump_json(str(ref_aaf)))
    classes = [m["_class"] for m in data["mobs"]]
    assert classes.count("CompositionMob") == 2
    assert classes.count("MasterMob") == 3
    assert classes.count("SourceMob") == 6  # tape + file per master


def test_inspect_never_modifies_input(ref_aaf, tmp_path, capsys):
    before = _sha(ref_aaf)
    assert main(["inspect", str(ref_aaf)]) == 0
    assert main(["inspect", str(ref_aaf), "--json", "-o", str(tmp_path / "d.json")]) == 0
    assert _sha(ref_aaf) == before
    assert "MULTIGROUP_01" in capsys.readouterr().out


@pytest.mark.parametrize("sample", sorted(SAMPLES.glob("*.aaf")), ids=lambda p: p.name)
def test_real_samples_dump_without_error(sample):
    """Runs against whatever real Avid exports are dropped into ./samples."""
    before = _sha(sample)
    assert dump_text(str(sample))
    assert json.loads(dump_json(str(sample)))
    assert _sha(sample) == before

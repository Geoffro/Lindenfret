from pathlib import Path

from lindenfret.cli import main

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"


def run(capsys, *args):
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_inspect_is_deterministic_for_a_seed(capsys):
    first = run(capsys, "inspect", "--config", str(PRESET), "--seed", "1234")
    second = run(capsys, "inspect", "--config", str(PRESET), "--seed", "1234")
    assert first[0] == 0
    assert first == second


def test_inspect_differs_between_seeds(capsys):
    outputs = {run(capsys, "inspect", "--config", str(PRESET), "--seed", str(s))[1] for s in range(5)}
    assert len(outputs) > 1


def test_inspect_lists_every_section_of_the_form(capsys):
    _, out, _ = run(capsys, "inspect", "--config", str(PRESET), "--seed", "7")
    form = next(line for line in out.splitlines() if line.startswith("form:"))
    sections = form.split("->")[-1].strip()
    assert out.count("\nsection ") == len(sections)


def test_inspect_chord_lists_fingerings(capsys):
    code, out, _ = run(capsys, "inspect", "--config", str(PRESET), "--chord", "Em7", "--region", "0-4")
    assert code == 0
    assert "0 2 2 0 3 0" in out  # the familiar open Em7
    assert "E2 B2 E3 G3 D4 E4" in out


def test_inspect_chord_says_when_nothing_fits(capsys):
    code, out, _ = run(capsys, "inspect", "--config", str(PRESET), "--chord", "Em/G", "--region", "5-10")
    assert code == 0
    assert "no fingering passes the hard rules" in out  # the G bass is at fret 3


def test_inspect_center_lists_the_transposed_palette(capsys):
    code, out, _ = run(capsys, "inspect", "--config", str(PRESET), "--center", "Gm")
    assert code == 0
    assert out.startswith("G minor")
    assert "\nGm " in out and "D7/A" in out


def test_inspect_center_flags_unplayable_chords(capsys):
    _, out, _ = run(capsys, "inspect", "--config", str(PRESET), "--center", "Ebm")
    assert "no fingering anywhere: Ebm/Gb" in out


def test_inspect_rejects_a_bad_center(capsys):
    code, _, err = run(capsys, "inspect", "--config", str(PRESET), "--center", "H")
    assert code == 2
    assert "--center" in err


def test_bad_config_exits_with_an_error(capsys, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[meter]\n")
    code, _, err = run(capsys, "inspect", "--config", str(bad), "--seed", "1")
    assert code == 2
    assert "lindenfret:" in err


def test_regenerate_rejects_a_file_that_isnt_a_manifest(capsys, tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{}")
    code, _, err = run(capsys, "regenerate", str(bad))
    assert code == 2
    assert "not a piece manifest" in err

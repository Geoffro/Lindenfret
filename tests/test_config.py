import copy
import tomllib
from pathlib import Path

import pytest

from lindenfret.config import BASS, ConfigError, Meter, load_config, note_to_midi, parse_config, pitch_class

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"
CONTOUR_PRESET = PRESET.with_name("etude2.toml")
BASS_PRESET = PRESET.with_name("carulli1.toml")
MODE_PRESET = PRESET.with_name("etude1-messiaen.toml")
ALL_MODE_PRESET = PRESET.with_name("etude2-messiaen.toml")


def load(path):
    with path.open("rb") as f:
        return tomllib.load(f)


@pytest.fixture
def data():
    return load(PRESET)


def parse_with(data, edit):
    changed = copy.deepcopy(data)
    edit(changed)
    return parse_config(changed)


def test_preset_loads():
    config = load_config(PRESET)
    assert config.pattern.strings == (6, 4, 5, 3, 4, 2, 3, 1, 2, 1, 3, 2, 4, 3, 5, 4)
    assert config.fretboard.open_midi == (40, 45, 50, 55, 59, 64)
    assert config.fretboard.open_pitch(6) == 40 and config.fretboard.open_pitch(1) == 64
    assert config.meter.bar_quarters == 4.0
    assert set(config.sections) == {"A", "B", "C"}
    assert config.sections["B"].harmony == "planing"
    assert config.form.rules["S"][0].to == "ABA"  # whitespace is stripped


def test_other_fills_unnamed_centers():
    start = load_config(PRESET).centers.start
    assert start[pitch_class("E")] == 3
    assert start[pitch_class("C")] == 1  # "other"


@pytest.mark.parametrize(
    "time_signature, beat, groups",
    [
        ("4/4", 1.0, (1.0,) * 4),
        ("2/2", 2.0, (1.0,) * 4),
        ("3/8", 1.5, (1.5,)),
        ("6/8", 1.5, (1.5, 1.5)),
        ("12/8", 1.5, (1.5,) * 4),
        ("1/8", 0.5, (0.5,)),
        ("2/8", 0.5, (1.0,)),
        ("4/8", 0.5, (1.0, 1.0)),
        ("5/8", 0.5, (1.0, 1.5)),
        ("7/8", 0.5, (1.0, 1.0, 1.5)),
        ("6/16", 0.75, (0.75, 0.75)),
    ],
)
def test_a_meter_knows_its_beat_and_beaming(time_signature, beat, groups):
    beats, unit = map(int, time_signature.split("/"))
    meter = Meter(beats, unit, 120.0, 1, 0.1)
    assert meter.beat_quarters == beat and meter.beam_groups == groups


@pytest.mark.parametrize("unit", [1, 2, 4, 8, 16])
def test_beam_groups_fill_the_bar(unit):
    for beats in range(1, 17):
        meter = Meter(beats, unit, 120.0, 1, 0.1)
        assert sum(meter.beam_groups) == meter.bar_quarters, f"{beats}/{unit}"


def test_note_names():
    assert note_to_midi("E2") == 40
    assert note_to_midi("C4") == 60
    assert note_to_midi("F#3") == 54
    assert note_to_midi("Bb3") == 58


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d["meter"].update(tempo_bpm=120), "meter: unknown tempo_bpm"),
        (lambda d: d["notation"].pop("title"), "notation: missing title"),
        (lambda d: d["pattern"].update(contour=[0, 1]), "needs exactly one of strings or contour"),
        (lambda d: d["pattern"].pop("strings"), "needs exactly one of strings or contour"),
        (lambda d: d["pattern"].update(max_slide=3), "pattern: unknown max_slide"),
        (lambda d: d["voicer"]["weights"].update(shift=1), "voicer.weights: unknown shift"),
        (lambda d: d["pattern"].update(strings=[6, 4, 5]), "don't fill a bar"),
        (lambda d: d["pattern"].update(velocities=[100] * 15), "need one per note"),
        (lambda d: d["pattern"]["velocities"].__setitem__(0, 128), "between 1 and 127"),
        (lambda d: d["meter"].update(ritardando=1.0), "ritardando"),
        (lambda d: d["meter"].update(time_signature="4/3"), "unsupported '4/3'"),
        (lambda d: d["fretboard"]["tuning"].__setitem__(0, "H2"), "not a note name"),
        (lambda d: d["pattern"].update(strings=[7] * 16), "strings are numbered 1 to 6"),
        (lambda d: d["fretboard"].update(max_fingers=5), "max_fingers"),
        (lambda d: d["voicer"].update(comfortable_span=6), "comfortable_span"),
        (lambda d: d["voicer"].update(temperature=-1), "temperature"),
        (lambda d: d["voicer"]["weights"].pop("doubling"), "voicer.weights: missing doubling"),
        (lambda d: d["centers"]["start"].update(Fb=1), "same pitch class"),
        (lambda d: d["centers"]["moves"].update(semitone=1), "unknown semitone"),
        (lambda d: d["palette"]["minor"].append("Em"), "repeated chords Em"),
        (lambda d: d["palette"].update(tonic="H"), "palette.tonic: not a pitch class"),
        (lambda d: d["palette"].update(optional_intervals=[12]), "1 to 11 semitones"),
        (lambda d: d["graph"]["reference_paths"].append(["Em", "Gm"]), "Gm not in the palette"),
        (lambda d: d["graph"]["bass_step"].update({"7": 1}), "semitone count from 0 to 6"),
        (lambda d: d.pop("graph"), "sections.A: a graph section needs a [graph] table"),
        (lambda d: [d.pop("palette"), d.pop("graph")], "sections.A: a graph section needs a [palette] table"),
        (lambda d: d.pop("palette"), "graph: its reference_paths need a [palette]"),
        (lambda d: d["centers"].pop("start_mode"), "sections.A: a graph section needs [centers] start_mode"),
        (lambda d: d["form"]["rules"]["S"].append({"to": "A D", "weight": 1}), "no [sections.D]"),
        (lambda d: d["form"]["rules"]["S"].append({"to": "A b", "weight": 1}), "must be capital letters"),
        (lambda d: d["sections"].update(a=d["sections"]["A"]), "single capital letter"),
        (lambda d: d["sections"]["A"].update(region="0-14"), "within frets 0-13"),
        (lambda d: d["sections"]["A"].update(length=[8, 4]), "1 <= min <= max"),
        (lambda d: d["sections"]["A"]["rules"]["F"].append({"to": "F[+F", "weight": 1}), "unbalanced"),
        (lambda d: d["sections"]["A"]["rules"]["F"].append({"to": "FX", "weight": 1}), "unknown symbols"),
        (lambda d: d["sections"]["A"]["rules"]["F"].append({"to": "F", "weight": 0}), "must be positive"),
        (lambda d: d["sections"]["B"]["rules"]["F"].append({"to": "FMF", "weight": 1}), "no tonal center"),
        (lambda d: d["sections"]["A"].update(open_strings=2), "unknown open_strings"),
        (lambda d: d["sections"]["B"].pop("shape_types"), "missing shape_types"),
        (lambda d: d["sections"]["B"].update(open_strings=4), "at least three strings"),
    ],
)
def test_bad_configs_name_the_problem(data, edit, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[")):
        parse_with(data, edit)


def test_the_contour_preset_loads():
    pattern = parse_config(load(CONTOUR_PRESET)).pattern
    assert pattern.strings == () and pattern.stops == 9
    assert (pattern.notes_per_string, pattern.hand_positions, pattern.max_slide) == (2, 2, 3)


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d["pattern"]["contour"].__setitem__(8, 9), "every stop from 0 up to its highest"),
        (lambda d: d["pattern"].pop("max_slide"), "pattern: missing max_slide"),
        (lambda d: d["pattern"].update(max_slide=0), "max_slide: must be at least 1"),
        (lambda d: d["pattern"].update(hand_positions=0), "hand_positions must be at least 1"),
        (lambda d: d["pattern"].update(notes_per_string=1), "9 stops don't fit on 6 strings"),
        (lambda d: d["voicer"]["weights"].pop("shift"), "voicer.weights: missing shift"),
        (
            lambda d: d["sections"]["A"].update(
                harmony="planing", rules={"F": [{"to": "F-F", "weight": 1}]}, shape_types={"any": 1}, open_strings=2
            ),
            "planing needs a string pattern",
        ),
    ],
)
def test_bad_contour_configs_name_the_problem(edit, message):
    with pytest.raises(ConfigError, match=message):
        parse_with(load(CONTOUR_PRESET), edit)


def test_the_bass_preset_loads():
    pattern = load_config(BASS_PRESET).pattern
    assert pattern.strings == (BASS, 2, 1, 3, 2, 1) and pattern.bass_strings == (6, 5, 4)
    assert pattern.plucked == {3, 2, 1}
    assert load_config(PRESET).pattern.bass_strings == ()


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d["pattern"].pop("bass_strings"), 'a "bass" note needs bass_strings'),
        (lambda d: d["pattern"]["strings"].__setitem__(0, 5), 'only a pattern with a "bass" note uses them'),
        (lambda d: d["pattern"]["strings"].__setitem__(0, "p"), 'expected string numbers or "bass"'),
        (lambda d: d["pattern"]["strings"].__setitem__(1, 0), "pattern.strings: strings are numbered 1 to 6"),
        (lambda d: d["pattern"].update(bass_strings=[]), "bass_strings: must not be empty"),
        (lambda d: d["pattern"].update(bass_strings=[7]), "strings are numbered 1 to 6"),
        (lambda d: d["pattern"].update(bass_strings=[6, 6]), "repeated strings"),
        (lambda d: d["pattern"].update(bass_strings=[6, 2]), "string 2 isn't below the pattern's string 3"),
        (
            lambda d: d["sections"]["A"].update(
                harmony="planing", axiom="F", rules={"F": [{"to": "F-F", "weight": 1}]}, shape_types={"any": 1},
                open_strings=2,
            ),
            'planing needs fixed strings, not a "bass" note',
        ),
    ],
)
def test_bad_bass_patterns_name_the_problem(edit, message):
    with pytest.raises(ConfigError, match=message):
        parse_with(load(BASS_PRESET), edit)


def test_the_mode_preset_loads():
    config = load_config(MODE_PRESET)
    assert config.sections["B"].harmony == "mode"
    assert config.sections["B"].modes == {2: 3, 3: 1}
    assert config.modes == {2, 3}
    assert config.modal.chord_types[:3] == ("", "m", "+")
    assert load_config(PRESET).modal is None and load_config(PRESET).modes == set()


def test_a_preset_of_only_mode_sections_needs_no_palette_or_graph():
    config = load_config(ALL_MODE_PRESET)
    assert {section.harmony for section in config.sections.values()} == {"mode"}
    assert (config.palette, config.graph, config.centers.start_mode) == (None, None, {})


def test_a_config_of_only_planing_sections_needs_no_chord_tables(data):
    def planing_only(d):
        del d["palette"], d["graph"], d["centers"]["start_mode"]
        d["sections"] = {"B": d["sections"]["B"]}
        d["form"]["rules"]["S"] = [{"to": "B", "weight": 1}]

    config = parse_with(data, planing_only)
    assert (config.palette, config.graph, config.modal) == (None, None, None)


def test_a_mode_weighted_zero_is_not_built():
    assert parse_with(load(MODE_PRESET), lambda d: d["sections"]["B"]["modes"].update({"3": 0})).modes == {2}


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d.pop("modal"), "sections.B: a mode section needs a [modal] table"),
        (lambda d: d["modal"].update(chord_types=[]), "modal.chord_types: must not be empty"),
        (lambda d: d["modal"]["chord_types"].append("m"), "repeated types 'm'"),
        (lambda d: d["modal"].update(types=["m"]), "modal: unknown types"),
        (lambda d: d["modal"].pop("bass_step"), "modal: missing bass_step"),
        (lambda d: d["modal"].update(optional_intervals=[0]), "modal.optional_intervals: each must be 1 to 11"),
        (lambda d: d["modal"]["bass_step"].update({"7": 1}), "modal.bass_step: key '7'"),
        (lambda d: d["sections"]["B"].pop("modes"), "sections.B: missing modes"),
        (lambda d: d["sections"]["B"]["modes"].update({"8": 1}), "unknown 8; expected 1, 2, 3"),
        (lambda d: d["sections"]["A"].update(modes={"2": 1}), "sections.A: unknown modes"),
        (lambda d: d["sections"]["B"]["rules"]["F"].append({"to": "FK", "weight": 1}), "a mode has no dominant"),
        (lambda d: d["sections"]["B"].update(harmony="modal"), "expected 'graph', 'planing' or 'mode'"),
    ],
)
def test_bad_mode_configs_name_the_problem(edit, message):
    with pytest.raises(ConfigError, match=message.replace("[", r"\[")):
        parse_with(load(MODE_PRESET), edit)


def test_toml_syntax_errors_are_config_errors(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[meter\n")
    with pytest.raises(ConfigError):
        load_config(bad)

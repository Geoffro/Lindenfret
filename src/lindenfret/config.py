"""Load and validate a generator config.

Every table and key is checked when the file loads, so a typo or an
inconsistent value fails with a message naming the key instead of surfacing
later as odd music.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from lindenfret.alphabet import BAR_LENGTHS, BAR_SYMBOLS
from lindenfret.lsystem import Production

HarmonyMode = Literal["graph", "planing", "mode"]

MODES = ("minor", "major")
CENTER_MOVES = (
    "stay",
    "fifth_up",
    "fifth_down",
    "relative",
    "parallel",
    "third_up",
    "third_down",
    "semitone_up",
    "semitone_down",
)
SHAPE_TYPES = ("dim7", "augmented", "any")
VOICER_WEIGHTS = ("movement", "span", "open_strings", "doubling")
CONTOUR_WEIGHTS = ("shift",)  # voicer weights that only a contour pattern needs
NOTE_VALUES = {"32nd": 0.125, "16th": 0.25, "8th": 0.5, "quarter": 1.0}
BASS = 0  # in a string pattern, the bass note: "bass" in the config, plucked on one of bass_strings
PLANING_FORBIDDEN = frozenset("MK")  # planing has no center to move or cadence to
MODE_FORBIDDEN = frozenset("K")  # a mode has no dominant to cadence from
SECTION_TABLES = {"graph": ("palette", "graph"), "mode": ("modal",)}  # what each kind of section needs
# Messiaen's modes of limited transposition: semitones above the first degree.
MESSIAEN_MODES = {
    1: (0, 2, 4, 6, 8, 10),
    2: (0, 1, 3, 4, 6, 7, 9, 10),
    3: (0, 2, 3, 4, 6, 7, 8, 10, 11),
    4: (0, 1, 2, 5, 6, 7, 8, 11),
    5: (0, 1, 5, 6, 7, 11),
    6: (0, 2, 4, 5, 6, 8, 10, 11),
    7: (0, 1, 2, 3, 5, 6, 7, 8, 9, 11),
}
MAX_FRET_LIMIT = 24

_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ALTERS = {"": 0, "#": 1, "b": -1}
_NOTE_RE = re.compile(r"^([A-G])([#b]?)(-?\d)$")
_PITCH_CLASS_RE = re.compile(r"^([A-G])([#b]?)$")
_REGION_RE = re.compile(r"^(\d+)-(\d+)$")
_TIME_SIGNATURE_RE = re.compile(r"^(\d+)/(\d+)$")


class ConfigError(ValueError):
    """The config file is malformed or inconsistent."""


@dataclass(frozen=True)
class Notation:
    title: str  # the score's title; the seed is added
    direction: str  # a text direction at the start of the score, or "" for none


@dataclass(frozen=True)
class Meter:
    beats: int
    beat_unit: int
    tempo: float  # quarter notes per minute
    repeat_bars: int
    ritardando: float  # how much slower a section's last bar ends, repeats included, e.g. 0.1

    @property
    def bar_quarters(self) -> float:
        return self.beats * 4 / self.beat_unit

    @property
    def beat_quarters(self) -> float:
        """The beat a tempo mark counts: a dotted quarter in 3/8, 6/8, 9/8 or 12/8, else the time signature's note."""
        note = 4 / self.beat_unit
        return 3 * note if self.beat_unit >= 8 and self.beats % 3 == 0 else note

    @property
    def beam_groups(self) -> tuple[float, ...]:
        """The bar's beamed groups in quarter notes.

        Eighths and 16ths group in threes when the count allows, as in 6/8, and
        otherwise in twos closing with a three if the count is odd: 7/8 is
        2 + 2 + 3 eighths. Longer notes group by the quarter.
        """
        if self.beat_unit < 8:
            return (1.0,) * int(self.bar_quarters)
        if self.beats % 3 == 0:
            counts = [3] * (self.beats // 3)
        elif self.beats == 1:
            counts = [1]
        else:
            counts = [2] * (self.beats // 2 - self.beats % 2) + [3] * (self.beats % 2)
        return tuple(c * 4 / self.beat_unit for c in counts)


@dataclass(frozen=True)
class Fretboard:
    open_midi: tuple[int, ...]  # low string (6) first
    max_span: int
    max_fret: int
    max_fingers: int
    tension_strings: tuple[int, ...]

    @property
    def string_count(self) -> int:
        return len(self.open_midi)

    def open_pitch(self, string: int) -> int:
        """MIDI pitch of an open string, numbered 1 (highest) to string_count."""
        return self.open_midi[self.string_count - string]


@dataclass(frozen=True)
class VoicerSettings:
    comfortable_span: int  # spans above this cost extra
    top_candidates: int  # the voicer samples among this many of the best
    temperature: float  # 0 always takes the best; higher gives more variety
    weights: Mapping[str, float]  # one per VOICER_WEIGHTS


@dataclass(frozen=True)
class Pattern:
    """The right hand's notes in one bar, as a string pattern or a contour.

    A string pattern names the string each note plucks, and the left hand
    holds one fret per string. It may also play BASS, the bar's bass note,
    on whichever of `bass_strings` the fingering puts it. A contour names the
    stop each note plays, counting up the bar's ladder of stops from 0; see
    ladder.py.
    """

    strings: tuple[int, ...]  # the string each note plucks, or BASS; empty for a contour
    contour: tuple[int, ...]  # the stop each note plays; empty for a string pattern
    note: str
    note_quarters: float
    velocities: tuple[int, ...]  # MIDI velocity for each note of the pattern
    notes_per_string: int  # stops one string may carry; 1 for a string pattern
    hand_positions: int  # hand positions one bar may use; 1 for a string pattern
    max_slide: int  # frets the hand may slide to reach a new position; 0 for a string pattern
    bass_strings: tuple[int, ...] = ()  # the strings BASS may pluck, each below every other pattern string

    @property
    def plucked(self) -> frozenset[int]:
        """The strings every bar plucks, leaving out BASS, whose string varies."""
        return frozenset(self.strings) - {BASS}

    @property
    def stops(self) -> int:
        """Stops in a contour's ladder."""
        return max(self.contour) + 1


@dataclass(frozen=True)
class Centers:
    start: tuple[float, ...]  # weight per pitch class, C = 0
    start_mode: Mapping[str, float]  # graph sections only; empty if left out
    moves: Mapping[str, float]


@dataclass(frozen=True)
class Palette:
    tonic: str  # the key the chords are written in, e.g. "E"
    optional_intervals: frozenset[int]  # semitones above a chord's root that a voicing may leave out
    minor: tuple[str, ...]
    major: tuple[str, ...]


@dataclass(frozen=True)
class Modal:
    chord_types: tuple[str, ...]  # chord symbol suffixes such as "m7"; "|" stacks a major triad over another
    optional_intervals: frozenset[int]  # as in Palette, for the generated chords
    bass_step: Mapping[int, float]  # as in Graph, for the walk through a mode


@dataclass(frozen=True)
class Graph:
    bass_step: Mapping[int, float]  # weight by bass motion in semitones, 0 to 6
    reference_bonus: float
    reference_paths: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Form:
    axiom: str
    iterations: int
    rules: Mapping[str, tuple[Production, ...]]


@dataclass(frozen=True)
class Section:
    name: str
    axiom: str
    rules: Mapping[str, tuple[Production, ...]]
    length: tuple[int, int]  # bars before repetition
    harmony: HarmonyMode
    region: tuple[int, int]
    shape_types: Mapping[str, float]  # planing only; empty otherwise
    open_strings: int | None  # planing only
    modes: Mapping[int, float] = field(default_factory=dict)  # mode sections only: Messiaen mode weights


@dataclass(frozen=True)
class Config:
    notation: Notation
    meter: Meter
    pattern: Pattern
    fretboard: Fretboard
    voicer: VoicerSettings
    centers: Centers
    palette: Palette | None  # graph sections' chords
    graph: Graph | None  # graph sections' chord changes
    form: Form
    sections: Mapping[str, Section]
    modal: Modal | None  # mode sections' chords and chord changes

    @property
    def modes(self) -> frozenset[int]:
        """The Messiaen modes that some mode section can draw."""
        return frozenset(n for s in self.sections.values() for n, weight in s.modes.items() if weight > 0)


def load_config(path: str | Path) -> Config:
    path = Path(path)
    return parse_config_text(path.read_text(encoding="utf-8"), str(path))


def parse_config_text(text: str, where: str = "config") -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{where}: {e}") from e
    return parse_config(data)


def parse_config(data: Mapping[str, Any]) -> Config:
    _check_keys(
        data,
        required={"notation", "meter", "pattern", "fretboard", "voicer", "centers", "form", "sections"},
        where="config",
        optional={"palette", "graph", "modal"},
    )
    notation = _parse_notation(data["notation"])
    meter = _parse_meter(data["meter"])
    fretboard = _parse_fretboard(data["fretboard"])
    pattern = _parse_pattern(data["pattern"], meter, fretboard)
    voicer = _parse_voicer(data["voicer"], fretboard, pattern)
    centers = _parse_centers(data["centers"])
    palette = _parse_palette(data["palette"]) if "palette" in data else None
    graph = None
    if "graph" in data:
        if palette is None:
            raise ConfigError("graph: its reference_paths need a [palette]")
        graph = _parse_graph(data["graph"], palette)
    modal = _parse_modal(data["modal"]) if "modal" in data else None
    sections_table = _as_table(data["sections"], "sections")
    if not sections_table:
        raise ConfigError("sections: at least one section is required")
    sections = {
        name: _parse_section(name, table, fretboard) for name, table in sections_table.items()
    }
    for section in sections.values():
        where = f"sections.{section.name}"
        if section.harmony == "planing" and pattern.contour:
            raise ConfigError(f"{where}: planing needs a string pattern, not a contour")
        if section.harmony == "planing" and pattern.bass_strings:
            raise ConfigError(f'{where}: planing needs fixed strings, not a "bass" note')
        for table in SECTION_TABLES.get(section.harmony, ()):
            if table not in data:
                raise ConfigError(f"{where}: a {section.harmony} section needs a [{table}] table")
        if section.harmony == "graph" and not centers.start_mode:
            raise ConfigError(f"{where}: a graph section needs [centers] start_mode")
    form = _parse_form(data["form"], sections)
    return Config(notation, meter, pattern, fretboard, voicer, centers, palette, graph, form, sections, modal)


def parse_region(text: str, max_fret: int, where: str = "region") -> tuple[int, int]:
    """A fret range such as "0-9", checked against the highest fret."""
    match = _REGION_RE.match(text)
    if not match:
        raise ConfigError(f"{where}: expected a fret range like '0-9'")
    region = (int(match[1]), int(match[2]))
    if not region[0] <= region[1] <= max_fret:
        raise ConfigError(f"{where}: must be low-high within frets 0-{max_fret}")
    return region


def note_to_midi(name: str) -> int:
    """MIDI number of a note name such as "E2" or "F#3" (C4 = 60)."""
    match = _NOTE_RE.match(name)
    if not match:
        raise ValueError(f"not a note name: {name!r}")
    step, alter, octave = match.groups()
    return (int(octave) + 1) * 12 + _STEPS[step] + _ALTERS[alter]


def pitch_class(name: str) -> int:
    """Pitch class of a name such as "E" or "Bb" (C = 0)."""
    match = _PITCH_CLASS_RE.match(name)
    if not match:
        raise ValueError(f"not a pitch class: {name!r}")
    step, alter = match.groups()
    return (_STEPS[step] + _ALTERS[alter]) % 12


def mode_name(number: int) -> str:
    """A Messiaen mode's name as a center mode, e.g. "mode 2"."""
    return f"mode {number}"


# --- tables ---------------------------------------------------------------


def _parse_notation(value: Any) -> Notation:
    t = _as_table(value, "notation")
    _check_keys(t, required={"title", "direction"}, where="notation")
    return Notation(_as_str(t["title"], "notation.title"), _as_str(t["direction"], "notation.direction"))


def _parse_meter(value: Any) -> Meter:
    t = _as_table(value, "meter")
    _check_keys(t, required={"time_signature", "tempo", "repeat_bars", "ritardando"}, where="meter")
    match = _TIME_SIGNATURE_RE.match(_as_str(t["time_signature"], "meter.time_signature"))
    if not match:
        raise ConfigError("meter.time_signature: expected a form like '4/4'")
    beats, beat_unit = int(match[1]), int(match[2])
    if beats < 1 or beat_unit not in (1, 2, 4, 8, 16):
        raise ConfigError(f"meter.time_signature: unsupported {t['time_signature']!r}")
    tempo = _as_number(t["tempo"], "meter.tempo")
    if tempo <= 0:
        raise ConfigError("meter.tempo: must be positive")
    repeat_bars = _as_int(t["repeat_bars"], "meter.repeat_bars")
    if repeat_bars < 1:
        raise ConfigError("meter.repeat_bars: must be at least 1")
    ritardando = _as_number(t["ritardando"], "meter.ritardando")
    if not 0 <= ritardando < 1:
        raise ConfigError("meter.ritardando: must be at least 0 and below 1")
    return Meter(beats, beat_unit, tempo, repeat_bars, ritardando)


def _parse_fretboard(value: Any) -> Fretboard:
    t = _as_table(value, "fretboard")
    _check_keys(
        t,
        required={"tuning", "max_span", "max_fret", "max_fingers", "tension_strings"},
        where="fretboard",
    )
    tuning = _as_list(t["tuning"], "fretboard.tuning")
    if not tuning:
        raise ConfigError("fretboard.tuning: must name at least one string")
    try:
        open_midi = tuple(note_to_midi(_as_str(n, "fretboard.tuning")) for n in tuning)
    except ValueError as e:
        raise ConfigError(f"fretboard.tuning: {e}") from e
    max_span = _as_int(t["max_span"], "fretboard.max_span")
    max_fret = _as_int(t["max_fret"], "fretboard.max_fret")
    max_fingers = _as_int(t["max_fingers"], "fretboard.max_fingers")
    if max_span < 0:
        raise ConfigError("fretboard.max_span: must not be negative")
    if not 0 <= max_fret <= MAX_FRET_LIMIT:
        raise ConfigError(f"fretboard.max_fret: must be between 0 and {MAX_FRET_LIMIT}")
    if not 1 <= max_fingers <= 4:
        raise ConfigError("fretboard.max_fingers: must be between 1 and 4")
    tension_strings = tuple(
        _as_int(s, "fretboard.tension_strings")
        for s in _as_list(t["tension_strings"], "fretboard.tension_strings")
    )
    _check_strings(tension_strings, len(open_midi), "fretboard.tension_strings")
    return Fretboard(open_midi, max_span, max_fret, max_fingers, tension_strings)


def _parse_voicer(value: Any, fretboard: Fretboard, pattern: Pattern) -> VoicerSettings:
    t = _as_table(value, "voicer")
    _check_keys(
        t, required={"comfortable_span", "top_candidates", "temperature", "weights"}, where="voicer"
    )
    comfortable_span = _as_int(t["comfortable_span"], "voicer.comfortable_span")
    if not 0 <= comfortable_span <= fretboard.max_span:
        raise ConfigError(f"voicer.comfortable_span: must be between 0 and max_span ({fretboard.max_span})")
    top_candidates = _as_int(t["top_candidates"], "voicer.top_candidates")
    if top_candidates < 1:
        raise ConfigError("voicer.top_candidates: must be at least 1")
    temperature = _as_number(t["temperature"], "voicer.temperature")
    if temperature < 0:
        raise ConfigError("voicer.temperature: must not be negative")
    weights = _as_table(t["weights"], "voicer.weights")
    names = VOICER_WEIGHTS + (CONTOUR_WEIGHTS if pattern.contour else ())
    _check_keys(weights, required=set(names), where="voicer.weights")
    parsed = {name: _as_number(weights[name], f"voicer.weights.{name}") for name in names}
    if any(w < 0 for w in parsed.values()):
        raise ConfigError("voicer.weights: must not be negative")
    return VoicerSettings(comfortable_span, top_candidates, temperature, parsed)


def _parse_pattern(value: Any, meter: Meter, fretboard: Fretboard) -> Pattern:
    t = _as_table(value, "pattern")
    if ("strings" in t) == ("contour" in t):
        raise ConfigError("pattern: needs exactly one of strings or contour")
    kind = "strings" if "strings" in t else "contour"
    contour_keys = {"notes_per_string", "hand_positions", "max_slide"} if kind == "contour" else set()
    _check_keys(
        t,
        required={kind, "note", "velocities"} | contour_keys,
        where="pattern",
        optional={"bass_strings"} if kind == "strings" else set(),
    )
    raw = _as_list(t[kind], f"pattern.{kind}")
    if kind == "strings":
        if any(isinstance(n, str) and n != "bass" for n in raw):
            raise ConfigError('pattern.strings: expected string numbers or "bass"')
        numbered = [_as_int(n, "pattern.strings") for n in raw if n != "bass"]
        _check_strings(numbered, fretboard.string_count, "pattern.strings")
    notes = tuple(BASS if kind == "strings" and n == "bass" else _as_int(n, f"pattern.{kind}") for n in raw)
    if not notes:
        raise ConfigError(f"pattern.{kind}: must not be empty")
    notes_per_string = hand_positions = 1
    max_slide = 0
    bass_strings: tuple[int, ...] = ()
    if kind == "strings":
        bass_strings = _parse_bass_strings(t, notes, fretboard)
    else:
        if set(notes) != set(range(max(notes) + 1)):
            raise ConfigError("pattern.contour: must use every stop from 0 up to its highest")
        notes_per_string = _as_int(t["notes_per_string"], "pattern.notes_per_string")
        hand_positions = _as_int(t["hand_positions"], "pattern.hand_positions")
        max_slide = _as_int(t["max_slide"], "pattern.max_slide")
        if notes_per_string < 1 or hand_positions < 1:
            raise ConfigError("pattern: notes_per_string and hand_positions must be at least 1")
        if max_slide < 1:
            raise ConfigError("pattern.max_slide: must be at least 1")
        if max(notes) + 1 > notes_per_string * fretboard.string_count:
            raise ConfigError(
                f"pattern.contour: {max(notes) + 1} stops don't fit on {fretboard.string_count} strings "
                f"with {notes_per_string} per string"
            )
    note = _as_str(t["note"], "pattern.note")
    if note not in NOTE_VALUES:
        raise ConfigError(f"pattern.note: expected one of {', '.join(NOTE_VALUES)}")
    note_quarters = NOTE_VALUES[note]
    if len(notes) * note_quarters != meter.bar_quarters:
        raise ConfigError(
            f"pattern: {len(notes)} {note} notes don't fill a bar of "
            f"{meter.beats}/{meter.beat_unit}"
        )
    velocities = tuple(
        _as_int(v, "pattern.velocities") for v in _as_list(t["velocities"], "pattern.velocities")
    )
    if len(velocities) != len(notes):
        raise ConfigError(f"pattern.velocities: need one per note ({len(notes)}), got {len(velocities)}")
    if not all(1 <= v <= 127 for v in velocities):
        raise ConfigError("pattern.velocities: each must be between 1 and 127")
    strings, contour = (notes, ()) if kind == "strings" else ((), notes)
    return Pattern(
        strings, contour, note, note_quarters, velocities, notes_per_string, hand_positions, max_slide,
        bass_strings,
    )


def _parse_bass_strings(t: Mapping[str, Any], strings: Sequence[int], fretboard: Fretboard) -> tuple[int, ...]:
    where = "pattern.bass_strings"
    if BASS not in strings:
        if "bass_strings" in t:
            raise ConfigError(f'{where}: only a pattern with a "bass" note uses them')
        return ()
    if "bass_strings" not in t:
        raise ConfigError('pattern: a "bass" note needs bass_strings, the strings it may pluck')
    bass_strings = tuple(_as_int(s, where) for s in _as_list(t["bass_strings"], where))
    if not bass_strings:
        raise ConfigError(f"{where}: must not be empty")
    _check_strings(bass_strings, fretboard.string_count, where)
    if len(set(bass_strings)) != len(bass_strings):
        raise ConfigError(f"{where}: repeated strings")
    plucked = set(strings) - {BASS}
    if plucked and min(bass_strings) <= max(plucked):
        raise ConfigError(f"{where}: string {min(bass_strings)} isn't below the pattern's string {max(plucked)}")
    return bass_strings


def _parse_centers(value: Any) -> Centers:
    t = _as_table(value, "centers")
    _check_keys(t, required={"start", "moves"}, where="centers", optional={"start_mode"})
    start_table = _weights(t["start"], "centers.start")
    other = start_table.pop("other", 0.0)
    start = [other] * 12
    named: dict[int, str] = {}
    for name, weight in start_table.items():
        try:
            pc = pitch_class(name)
        except ValueError as e:
            raise ConfigError(f"centers.start: {e}") from e
        if pc in named:
            raise ConfigError(f"centers.start: {name!r} and {named[pc]!r} are the same pitch class")
        named[pc] = name
        start[pc] = weight
    if not any(start):
        raise ConfigError("centers.start: at least one weight must be positive")
    start_mode = _weights(t["start_mode"], "centers.start_mode", allowed=MODES) if "start_mode" in t else {}
    moves = _weights(t["moves"], "centers.moves", allowed=CENTER_MOVES)
    return Centers(tuple(start), start_mode, moves)


def _parse_palette(value: Any) -> Palette:
    t = _as_table(value, "palette")
    _check_keys(t, required={"tonic", "optional_intervals", *MODES}, where="palette")
    tonic = _as_str(t["tonic"], "palette.tonic")
    try:
        pitch_class(tonic)
    except ValueError as e:
        raise ConfigError(f"palette.tonic: {e}") from e
    optional = _parse_optional_intervals(t["optional_intervals"], "palette.optional_intervals")
    lists = {}
    for mode in MODES:
        chords = tuple(_as_str(c, f"palette.{mode}") for c in _as_list(t[mode], f"palette.{mode}"))
        if not chords:
            raise ConfigError(f"palette.{mode}: must not be empty")
        duplicates = sorted({c for c in chords if chords.count(c) > 1})
        if duplicates:
            raise ConfigError(f"palette.{mode}: repeated chords {', '.join(duplicates)}")
        lists[mode] = chords
    return Palette(tonic, optional, lists["minor"], lists["major"])


def _parse_graph(value: Any, palette: Palette) -> Graph:
    t = _as_table(value, "graph")
    _check_keys(t, required={"bass_step", "reference_bonus", "reference_paths"}, where="graph")
    bass_step = _parse_bass_step(t["bass_step"], "graph.bass_step")
    reference_bonus = _as_number(t["reference_bonus"], "graph.reference_bonus")
    if reference_bonus < 0:
        raise ConfigError("graph.reference_bonus: must not be negative")
    known = set(palette.minor) | set(palette.major)
    paths = []
    for path in _as_list(t["reference_paths"], "graph.reference_paths"):
        chords = tuple(_as_str(c, "graph.reference_paths") for c in _as_list(path, "graph.reference_paths"))
        if len(chords) < 2:
            raise ConfigError("graph.reference_paths: each path needs at least two chords")
        unknown = [c for c in chords if c not in known]
        if unknown:
            raise ConfigError(f"graph.reference_paths: {', '.join(unknown)} not in the palette")
        paths.append(chords)
    return Graph(bass_step, reference_bonus, tuple(paths))


def _parse_modal(value: Any) -> Modal:
    t = _as_table(value, "modal")
    _check_keys(t, required={"chord_types", "optional_intervals", "bass_step"}, where="modal")
    chord_types = tuple(_as_str(c, "modal.chord_types") for c in _as_list(t["chord_types"], "modal.chord_types"))
    if not chord_types:
        raise ConfigError("modal.chord_types: must not be empty")
    duplicates = sorted({c for c in chord_types if chord_types.count(c) > 1})
    if duplicates:
        raise ConfigError(f"modal.chord_types: repeated types {', '.join(map(repr, duplicates))}")
    optional = _parse_optional_intervals(t["optional_intervals"], "modal.optional_intervals")
    return Modal(chord_types, optional, _parse_bass_step(t["bass_step"], "modal.bass_step"))


def _parse_optional_intervals(value: Any, where: str) -> frozenset[int]:
    optional = frozenset(_as_int(i, where) for i in _as_list(value, where))
    if not all(1 <= i <= 11 for i in optional):
        raise ConfigError(f"{where}: each must be 1 to 11 semitones above the root")
    return optional


def _parse_bass_step(value: Any, where: str) -> dict[int, float]:
    bass_step = {}
    for key, weight in _weights(value, where).items():
        if not key.isdigit() or not 0 <= int(key) <= 6:
            raise ConfigError(f"{where}: key {key!r} must be a semitone count from 0 to 6")
        bass_step[int(key)] = weight
    return bass_step


def _parse_form(value: Any, sections: Mapping[str, Section]) -> Form:
    t = _as_table(value, "form")
    _check_keys(t, required={"axiom", "iterations", "rules"}, where="form")
    axiom = _strip(_as_str(t["axiom"], "form.axiom"))
    iterations = _as_int(t["iterations"], "form.iterations")
    if iterations < 0:
        raise ConfigError("form.iterations: must not be negative")
    rules = _parse_rules(t["rules"], "form.rules")
    for where, word in [("form.axiom", axiom), *_productions(rules, "form.rules")]:
        bad = sorted({s for s in word if not s.isupper()})
        if bad:
            raise ConfigError(f"{where}: form symbols must be capital letters, found {''.join(bad)!r}")
    for symbol in _reachable(axiom, rules):
        if symbol not in rules and symbol not in sections:
            raise ConfigError(f"form: {symbol!r} can appear in the form but has no [sections.{symbol}]")
    return Form(axiom, iterations, rules)


def _parse_section(name: str, value: Any, fretboard: Fretboard) -> Section:
    where = f"sections.{name}"
    if len(name) != 1 or not name.isupper():
        raise ConfigError(f"{where}: section names must be a single capital letter")
    t = _as_table(value, where)
    if "harmony" not in t:
        raise ConfigError(f"{where}: missing harmony")
    harmony = _as_str(t["harmony"], f"{where}.harmony")
    if harmony not in ("graph", "planing", "mode"):
        raise ConfigError(f"{where}.harmony: expected 'graph', 'planing' or 'mode'")
    extra_keys = {"planing": {"shape_types", "open_strings"}, "mode": {"modes"}}.get(harmony, set())
    _check_keys(t, required={"axiom", "rules", "length", "harmony", "region"} | extra_keys, where=where)

    axiom = _strip(_as_str(t["axiom"], f"{where}.axiom"))
    rules = _parse_rules(t["rules"], f"{where}.rules")
    for symbol in rules:
        if symbol not in BAR_SYMBOLS or symbol in "[]":
            raise ConfigError(f"{where}.rules: can't rewrite {symbol!r}")
    for w, word in [(f"{where}.axiom", axiom), *_productions(rules, f"{where}.rules")]:
        bad = sorted(set(word) - BAR_SYMBOLS)
        if bad:
            raise ConfigError(f"{w}: unknown symbols {''.join(bad)!r}")
        _check_brackets(word, w)
        if harmony == "planing" and PLANING_FORBIDDEN & set(word):
            raise ConfigError(f"{w}: planing sections can't use M or K; they have no tonal center")
        if harmony == "mode" and MODE_FORBIDDEN & set(word):
            raise ConfigError(f"{w}: mode sections can't use K; a mode has no dominant")
    if not any(s in BAR_LENGTHS for s in _reachable(axiom, rules)):
        raise ConfigError(f"{where}: the grammar never produces a bar (F, H or K)")

    length = tuple(_as_int(n, f"{where}.length") for n in _as_list(t["length"], f"{where}.length"))
    if len(length) != 2 or not 1 <= length[0] <= length[1]:
        raise ConfigError(f"{where}.length: expected [min, max] with 1 <= min <= max")

    region = parse_region(_as_str(t["region"], f"{where}.region"), fretboard.max_fret, f"{where}.region")

    shape_types: Mapping[str, float] = {}
    open_strings = None
    if harmony == "planing":
        shape_types = _weights(t["shape_types"], f"{where}.shape_types", allowed=SHAPE_TYPES)
        open_strings = _as_int(t["open_strings"], f"{where}.open_strings")
        if not 0 <= open_strings <= fretboard.string_count - 3:
            raise ConfigError(
                f"{where}.open_strings: must be between 0 and {fretboard.string_count - 3}; "
                "a shape frets at least three strings"
            )
    modes: dict[int, float] = {}
    if harmony == "mode":
        allowed = [str(n) for n in MESSIAEN_MODES]
        modes = {int(n): w for n, w in _weights(t["modes"], f"{where}.modes", allowed=allowed).items()}
    return Section(
        name, axiom, rules, (length[0], length[1]), harmony, region, shape_types, open_strings, modes
    )


# --- helpers --------------------------------------------------------------


def _parse_rules(value: Any, where: str) -> dict[str, tuple[Production, ...]]:
    table = _as_table(value, where)
    rules = {}
    for symbol, productions in table.items():
        if len(symbol) != 1:
            raise ConfigError(f"{where}: rule key {symbol!r} must be a single symbol")
        parsed = []
        for i, p in enumerate(_as_list(productions, f"{where}.{symbol}")):
            pw = f"{where}.{symbol}[{i}]"
            entry = _as_table(p, pw)
            _check_keys(entry, required={"to", "weight"}, where=pw)
            weight = _as_number(entry["weight"], f"{pw}.weight")
            if weight <= 0:
                raise ConfigError(f"{pw}.weight: must be positive")
            parsed.append(Production(_strip(_as_str(entry["to"], f"{pw}.to")), weight))
        if not parsed:
            raise ConfigError(f"{where}.{symbol}: needs at least one production")
        rules[symbol] = tuple(parsed)
    return rules


def _productions(rules: Mapping[str, Sequence[Production]], where: str):
    for symbol, productions in rules.items():
        for i, p in enumerate(productions):
            yield f"{where}.{symbol}[{i}]", p.to


def _reachable(axiom: str, rules: Mapping[str, Sequence[Production]]) -> set[str]:
    seen: set[str] = set()
    todo = list(axiom)
    while todo:
        symbol = todo.pop()
        if symbol in seen:
            continue
        seen.add(symbol)
        for p in rules.get(symbol, ()):
            todo.extend(p.to)
    return seen


def _check_brackets(word: str, where: str) -> None:
    depth = 0
    for symbol in word:
        depth += {"[": 1, "]": -1}.get(symbol, 0)
        if depth < 0:
            break
    if depth != 0:
        raise ConfigError(f"{where}: unbalanced brackets in {word!r}")


def _check_strings(strings: Sequence[int], count: int, where: str) -> None:
    bad = sorted({s for s in strings if not 1 <= s <= count})
    if bad:
        raise ConfigError(f"{where}: strings are numbered 1 to {count}, got {bad}")


def _check_keys(
    table: Mapping[str, Any], required: set[str], where: str, optional: set[str] = frozenset()
) -> None:
    missing = sorted(required - table.keys())
    unknown = sorted(table.keys() - required - optional)
    if missing:
        raise ConfigError(f"{where}: missing {', '.join(missing)}")
    if unknown:
        raise ConfigError(f"{where}: unknown {', '.join(unknown)}")


def _weights(value: Any, where: str, allowed: Sequence[str] | None = None) -> dict[str, float]:
    table = _as_table(value, where)
    if allowed is not None:
        unknown = sorted(table.keys() - set(allowed))
        if unknown:
            raise ConfigError(f"{where}: unknown {', '.join(unknown)}; expected {', '.join(allowed)}")
    weights = {key: _as_number(w, f"{where}.{key}") for key, w in table.items()}
    if any(w < 0 for w in weights.values()):
        raise ConfigError(f"{where}: weights must not be negative")
    if not any(weights.values()):
        raise ConfigError(f"{where}: at least one weight must be positive")
    return weights


def _strip(word: str) -> str:
    return "".join(word.split())


def _as_table(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a table")
    return value


def _as_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{where}: expected a list")
    return value


def _as_str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where}: expected a string")
    return value


def _as_int(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{where}: expected an integer")
    return value


def _as_number(value: Any, where: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{where}: expected a number")
    return float(value)

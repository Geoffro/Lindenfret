"""Golden snapshots: a diff means generation changed.

To accept a change on purpose, delete the snapshot and run the tests again;
the test writes a fresh one and skips.
"""

import json
from pathlib import Path

import pytest

from lindenfret.config import parse_config_text
from lindenfret.export import manifest
from lindenfret.pipeline import plan_piece

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden"
UNSTABLE = {"generator", "git_commit", "config"}  # config_sha256 stands in for the config text


@pytest.mark.parametrize(
    "preset, seed",
    [("etude1", 1), ("etude1", 2), ("etude1", 8), ("etude2", 1), ("etude2", 2)],  # etude1 seed 8 is A B C A
)
def test_manifest_matches_its_snapshot(preset, seed):
    text = (ROOT / "configs" / f"{preset}.toml").read_text(encoding="utf-8")
    data = manifest(plan_piece(parse_config_text(text), seed), text, preset)
    snapshot = json.loads(json.dumps({k: v for k, v in data.items() if k not in UNSTABLE}))  # as written
    path = GOLDEN / f"{preset}-{seed}.json"
    if not path.exists():
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip(f"wrote {path.relative_to(ROOT)}")
    assert snapshot == json.loads(path.read_text(encoding="utf-8"))

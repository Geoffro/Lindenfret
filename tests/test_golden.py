"""Golden snapshots: a diff means generation changed.

To accept a change on purpose, delete the snapshot and run the tests again;
the test writes a fresh one and skips.
"""

import json
from pathlib import Path

import pytest

from etudegen.config import parse_config_text
from etudegen.export import manifest
from etudegen.pipeline import plan_piece

ROOT = Path(__file__).resolve().parent.parent
PRESET = ROOT / "configs" / "etude1.toml"
GOLDEN = ROOT / "tests" / "golden"
UNSTABLE = {"generator", "git_commit", "config"}  # config_sha256 stands in for the config text


@pytest.mark.parametrize("seed", [1, 2, 8])  # seed 8 has the form A B C A
def test_manifest_matches_its_snapshot(seed):
    text = PRESET.read_text(encoding="utf-8")
    data = manifest(plan_piece(parse_config_text(text), seed), text, "etude1")
    snapshot = {k: v for k, v in data.items() if k not in UNSTABLE}
    path = GOLDEN / f"etude1-{seed}.json"
    if not path.exists():
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip(f"wrote {path.relative_to(ROOT)}")
    assert snapshot == json.loads(path.read_text(encoding="utf-8"))

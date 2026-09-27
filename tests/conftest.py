import importlib.util
import sys
from pathlib import Path

import pytest

from lindenfret.config import load_config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def reference_tool():
    """tools/analyze_reference.py, loaded as a module."""
    spec = importlib.util.spec_from_file_location("analyze_reference", ROOT / "tools" / "analyze_reference.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def reference_facts(tool, midi: str, preset: str):
    config = load_config(ROOT / "configs" / preset)
    return tool.analyze(ROOT / "reference" / midi, config.pattern, config.fretboard.open_midi), config


@pytest.fixture(scope="session")
def etude1_facts(reference_tool):
    return reference_facts(reference_tool, "Villa-Lobos_Etude_No1b.mid", "etude1.toml")


@pytest.fixture(scope="session")
def etude2_facts(reference_tool):
    return reference_facts(reference_tool, "Villa-Lobos_Etude_No2.mid", "etude2.toml")

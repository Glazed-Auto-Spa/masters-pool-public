"""Counterfactual pool (excluding Alfredo) config helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import load_runtime_config
from app.service import _config_without_participant_by_name


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_config_without_alfredo_drops_one_participant(repo_root: Path) -> None:
    cfg = load_runtime_config(repo_root)
    names = [p.name for p in cfg.participants]
    if "Alfredo" not in names:
        pytest.skip("pool_config has no Alfredo")
    sans = _config_without_participant_by_name(cfg, "Alfredo")
    assert sans is not None
    assert len(sans.participants) == len(cfg.participants) - 1
    assert all(p.name != "Alfredo" for p in sans.participants)


def test_config_without_missing_name_returns_none(repo_root: Path) -> None:
    cfg = load_runtime_config(repo_root)
    assert _config_without_participant_by_name(cfg, "DefinitelyNotInPool") is None

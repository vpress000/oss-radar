from __future__ import annotations

import pytest

from radar.config import load_config

from helpers import ROOT


@pytest.fixture
def cfg():
    return load_config(ROOT / "config.toml")

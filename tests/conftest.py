from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import SAMPLES


@pytest.fixture
def samples() -> Path:
    return SAMPLES

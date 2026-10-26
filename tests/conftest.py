import copy
import json
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


@pytest.fixture
def payload():
    with (DATA / "sample_payload.json").open(encoding="utf-8") as f:
        return copy.deepcopy(json.load(f))

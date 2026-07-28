import shutil
from pathlib import Path

import pytest

RSRC = Path(__file__).parent / "rsrc"


@pytest.fixture
def media_path(tmp_path):
    """Copy a fixture audio file into tmp and return its path."""

    def _copy(ext):
        dst = tmp_path / f"track.{ext}"
        shutil.copyfile(RSRC / f"full.{ext}", dst)
        return dst

    return _copy

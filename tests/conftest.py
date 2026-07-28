import shutil
from pathlib import Path

import pytest
from beets.util import cached_classproperty

RSRC = Path(__file__).parent / "rsrc"


@pytest.fixture(autouse=True)
def _reset_model_type_cache():
    """Recompute Item._types/_fields per test.

    beets caches the plugin-contributed flexible-field types on the model
    class the first time they are read. A test that touches Item without
    loading plugins would otherwise freeze an empty type map for the rest
    of the session, silently turning typed queries into substring ones.
    """
    cached_classproperty.cache.clear()
    yield
    cached_classproperty.cache.clear()


@pytest.fixture
def media_path(tmp_path):
    """Copy a fixture audio file into tmp and return its path."""

    def _copy(ext):
        dst = tmp_path / f"track.{ext}"
        shutil.copyfile(RSRC / f"full.{ext}", dst)
        return dst

    return _copy

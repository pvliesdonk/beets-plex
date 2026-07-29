"""Shared pytest fixtures.

beets does not ship its own test resources (`beets.test._common.RSRC`) in a way a
downstream suite can rely on, so this package carries its own audio fixtures
under `tests/rsrc/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from beets.util import cached_classproperty

RSRC = Path(__file__).parent / "rsrc"


@pytest.fixture(autouse=True)
def _reset_model_type_cache():
    """Clear beets' per-process ``Item._types`` cache around each test.

    ``Item._types`` is a ``cached_classproperty`` computed once per process, so a
    test that reads it with no plugins loaded would freeze an empty type map for
    the rest of the session, silently downgrading typed-field queries to
    substring matches. ``TestHelper``'s setup/teardown does not clear it.
    """
    cached_classproperty.cache.clear()
    yield
    cached_classproperty.cache.clear()


@pytest.fixture
def rsrc_dir() -> Path:
    """Directory holding the committed audio test fixtures."""
    return RSRC

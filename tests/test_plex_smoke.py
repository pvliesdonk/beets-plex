"""Optional live smoke test against a real Plex server.

Skipped unless PLEX_SMOKE_URL and PLEX_SMOKE_TOKEN are set. Run manually:

    PLEX_SMOKE_URL=https://host:32400 PLEX_SMOKE_TOKEN=... \\
        PLEX_SMOKE_LIBRARY='Muziek Archief' pytest tests/test_plex_smoke.py -v

It verifies the connection and that building the path map from one sweep does
not trigger a per-track reload (the performance question the fake suite cannot
answer).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.getenv("PLEX_SMOKE_URL") and os.getenv("PLEX_SMOKE_TOKEN")),
    reason="set PLEX_SMOKE_URL and PLEX_SMOKE_TOKEN to run the live Plex smoke test",
)


def test_sweep_returns_paths_without_per_track_reload():
    from plexapi.server import PlexServer

    from beetsplug.plex import matching

    server = PlexServer(os.environ["PLEX_SMOKE_URL"], os.environ["PLEX_SMOKE_TOKEN"])

    calls = {"n": 0}
    original_send = server._session.send

    def counting_send(*args, **kwargs):
        calls["n"] += 1
        return original_send(*args, **kwargs)

    server._session.send = counting_send

    section = server.library.section(os.getenv("PLEX_SMOKE_LIBRARY", "Music"))
    tracks = section.searchTracks()
    assert tracks, "library has no tracks"

    after_sweep = calls["n"]
    path_map = matching.build_path_map(tracks)
    after_map = calls["n"]

    assert path_map, "the sweep returned no file paths"
    assert after_map == after_sweep, (
        f"building the path map made {after_map - after_sweep} extra request(s) — "
        "the sweep is lazy-loading media parts per track"
    )

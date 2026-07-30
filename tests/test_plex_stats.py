"""plex stats pull: the pure track->stats mapping and the plugin pull."""

from __future__ import annotations

from datetime import datetime, timezone

from beets.dbcore import types as _types

from beetsplug import plex
from beetsplug.plex import stats


class _Track:
    """Minimal stand-in carrying only the attributes track_stats reads."""

    def __init__(self, viewCount, skipCount, lastViewedAt, lastRatedAt):
        self.viewCount = viewCount
        self.skipCount = skipCount
        self.lastViewedAt = lastViewedAt
        self.lastRatedAt = lastRatedAt


def test_track_stats_played_track_has_all_fields():
    viewed = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    rated = datetime(2024, 6, 7, 8, 9, 10, tzinfo=timezone.utc)
    result = stats.track_stats(_Track(5, 2, viewed, rated))
    assert result == {
        "plex_viewcount": 5,
        "plex_skipcount": 2,
        "plex_lastviewedat": viewed.timestamp(),
        "plex_lastratedat": rated.timestamp(),
    }


def test_track_stats_never_played_omits_timestamps():
    result = stats.track_stats(_Track(0, None, None, None))
    assert result == {"plex_viewcount": 0, "plex_skipcount": 0}
    assert "plex_lastviewedat" not in result
    assert "plex_lastratedat" not in result


def test_plugin_declares_stat_fields():
    it = plex.PlexPlugin.item_types
    assert it["plex_viewcount"] is _types.INTEGER
    assert it["plex_skipcount"] is _types.INTEGER
    for key in ("plex_lastviewedat", "plex_lastratedat", "plex_updated"):
        assert isinstance(it[key], _types.DateType)

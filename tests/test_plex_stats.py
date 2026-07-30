"""plex stats pull: the pure track->stats mapping and the plugin pull."""

from __future__ import annotations

from datetime import datetime, timezone

from beets.dbcore import types as _types

from beetsplug import plex
from beetsplug.plex import stats
from tests.fake_plex import FakeItem, FakeLib, FakeSection, FakeServer, FakeTrack

BEETS_DIR = "/mnt/music"
PLEX_DIR = "/srv/media"


def _plugin(section):
    p = plex.PlexPlugin()
    p._server = FakeServer(section)
    p.config["beets_dir"].set(BEETS_DIR)
    p.config["plex_dir"].set(PLEX_DIR)
    p.config["library_name"].set(section.title)
    return p


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


# -- pull_stats() -------------------------------------------------------------


def test_pull_writes_stats_for_matched_items():
    viewed = datetime(2024, 1, 2, tzinfo=timezone.utc)
    track = FakeTrack(1, ["/srv/media/a.mp3"], viewCount=3, lastViewedAt=viewed)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3")
    p.pull_stats(FakeLib([item]), None, pretend=False)
    assert item["plex_viewcount"] == 3
    assert item["plex_lastviewedat"] == viewed.timestamp()
    assert "plex_updated" in item._fields
    assert item.stored == 1


def test_pull_forwards_query_and_skips_unmatched():
    track = FakeTrack(1, ["/srv/media/a.mp3"], viewCount=1)
    p = _plugin(FakeSection("Muziek", [track]))
    lib = FakeLib([FakeItem("/mnt/music/a.mp3"), FakeItem("/mnt/music/gone.mp3")])
    p.pull_stats(lib, ["artist:x"], pretend=False)
    assert lib.last_query == ["artist:x"]  # query forwarded to beets
    assert lib._items[1].stored == 0  # unmatched item untouched


def test_pretend_writes_nothing(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], viewCount=7)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3")
    p.pull_stats(FakeLib([item]), None, pretend=True)
    assert item.stored == 0
    assert "plex_viewcount" not in item._fields
    assert "would update" in capsys.readouterr().out


def test_store_only_if_changed(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], viewCount=2)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3")
    p.pull_stats(FakeLib([item]), None, pretend=False)  # first pull stores
    assert item.stored == 1
    p.pull_stats(FakeLib([item]), None, pretend=False)  # nothing changed
    assert item.stored == 1  # not re-stored
    assert "0 updated" in capsys.readouterr().out


def test_run_dispatches_stats(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], viewCount=4)
    p = _plugin(FakeSection("Muziek", [track]))

    class _Opts:
        pretend = False

    p._run(FakeLib([FakeItem("/mnt/music/a.mp3")]), _Opts(), ["stats"])
    assert "1 matched" in capsys.readouterr().out

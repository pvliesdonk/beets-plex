"""plex rating sync: the pure three-way merge and the plugin sync."""

from __future__ import annotations

import pytest
from beets import ui
from beets.dbcore import types as _types

from beetsplug import plex
from beetsplug.plex import rating
from beetsplug.plex.rating import ADOPT, NONE, PUSH
from tests.fake_plex import FakeItem, FakeLib, FakeSection, FakeServer, FakeTrack


def test_noop_when_both_equal():
    assert rating.rating_merge(6.0, 6.0, 6.0) == (NONE, 6.0, 6.0, False)


def test_only_beets_changed_pushes():
    assert rating.rating_merge(8.0, 6.0, 6.0) == (PUSH, 8.0, 8.0, False)


def test_only_plex_changed_adopts():
    assert rating.rating_merge(6.0, 4.0, 6.0) == (ADOPT, 4.0, 4.0, False)


def test_both_changed_to_same_value_agrees():
    assert rating.rating_merge(5.0, 5.0, 2.0) == (NONE, 5.0, 5.0, False)


def test_conflict_default_plex_wins():
    assert rating.rating_merge(8.0, 4.0, 6.0) == (ADOPT, 4.0, 4.0, True)


def test_conflict_policy_beets_wins():
    assert rating.rating_merge(8.0, 4.0, 6.0, "beets") == (PUSH, 8.0, 8.0, True)


def test_conflict_policy_skip_leaves_both():
    assert rating.rating_merge(8.0, 4.0, 6.0, "skip") == (NONE, 6.0, 6.0, True)


def test_plex_none_normalized_beets_pushes():
    # beets rated, Plex unrated (None -> 0), baseline unrated -> push beets
    assert rating.rating_merge(7.0, None, None) == (PUSH, 7.0, 7.0, False)


def test_beets_cleared_pushes_unrated():
    # beets cleared to 0, Plex still at the baseline -> push the clear
    assert rating.rating_merge(0, 6.0, 6.0) == (PUSH, 0.0, 0.0, False)


def test_first_sync_both_rated_differently_seeds_plex():
    # no baseline (None -> 0); both rated, differ -> Plex-authoritative seed
    assert rating.rating_merge(8.0, 4.0, None) == (ADOPT, 4.0, 4.0, True)


def test_subdecimal_drift_is_not_a_change():
    # a baseline that round-tripped to 6.04 must not read as changed vs 6.0
    assert rating.rating_merge(6.04, 6.0, 6.0) == (NONE, 6.0, 6.0, False)


def test_plugin_declares_rating_fields_and_config():
    it = plex.PlexPlugin.item_types
    assert it["plex_rating_baseline"] is _types.FLOAT
    assert it["plex_userrating"] is _types.FLOAT
    assert "rating" not in it  # ratingtag owns `rating`; declaring it here collides
    p = plex.PlexPlugin()
    assert p.config["rating_conflict"].as_str() == "plex"


BEETS_DIR = "/mnt/music"
PLEX_DIR = "/srv/media"


def _plugin(section, policy="plex"):
    p = plex.PlexPlugin()
    p._server = FakeServer(section)
    p.config["beets_dir"].set(BEETS_DIR)
    p.config["plex_dir"].set(PLEX_DIR)
    p.config["library_name"].set(section.title)
    p.config["rating_conflict"].set(policy)
    return p


def test_sync_pushes_beets_rating_to_plex():
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=None)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3", rating=7.0)  # rated in beets, not Plex
    p.sync_ratings(FakeLib([item]), None, pretend=False)
    assert track.rated == [7.0]  # pushed to Plex
    assert item["plex_rating_baseline"] == 7.0
    assert item["plex_userrating"] == 7.0
    assert item.stored == 1


def test_sync_adopts_plex_rating_into_beets():
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3")  # unrated in beets, rated in Plex
    p.sync_ratings(FakeLib([item]), None, pretend=False)
    assert item["rating"] == 4.0  # adopted into beets
    assert track.rated == []  # Plex not written
    assert item["plex_rating_baseline"] == 4.0
    assert item["plex_userrating"] == 4.0  # mirror reflects Plex's value


def test_sync_conflict_default_plex_wins_and_counts(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3", rating=8.0, plex_rating_baseline=6.0)
    p.sync_ratings(FakeLib([item]), None, pretend=False)
    assert item["rating"] == 4.0  # Plex wins
    out = capsys.readouterr().out
    # a real run names the conflicted track (not just the aggregate count)
    assert "conflict /mnt/music/a.mp3: beets 8.0 vs plex 4.0 → 4.0" in out
    assert "1 conflict" in out


def test_sync_push_failure_is_logged_and_batch_continues(capsys):
    # One track's Plex write fails; the batch must continue, count the failure,
    # and leave that item's baseline untouched so the next sync retries it.
    bad = FakeTrack(1, ["/srv/media/a.mp3"], userRating=None, rate_raises=True)
    good = FakeTrack(2, ["/srv/media/b.mp3"], userRating=None)
    p = _plugin(FakeSection("Muziek", [bad, good]))
    item_bad = FakeItem("/mnt/music/a.mp3", rating=7.0)
    item_good = FakeItem("/mnt/music/b.mp3", rating=5.0)
    p.sync_ratings(FakeLib([item_bad, item_good]), None, pretend=False)
    assert good.rated == [5.0]  # the good push still happened
    assert "plex_rating_baseline" not in item_bad._fields  # untouched → retried
    assert item_good["plex_rating_baseline"] == 5.0
    assert "1 failed" in capsys.readouterr().out


def test_sync_conflict_skip_writes_nothing(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]), policy="skip")
    item = FakeItem("/mnt/music/a.mp3", rating=8.0, plex_rating_baseline=6.0)
    p.sync_ratings(FakeLib([item]), None, pretend=False)
    assert item["rating"] == 8.0  # untouched
    assert item["plex_rating_baseline"] == 6.0  # untouched
    assert track.rated == []
    assert item["plex_userrating"] == 4.0  # mirror still tracks Plex's value
    assert item.stored == 1  # store happened for the mirror, not the rating
    assert "1 conflict" in capsys.readouterr().out


def test_sync_pushes_a_clear_to_plex():
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=6.0)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3", rating=0.0, plex_rating_baseline=6.0)
    p.sync_ratings(FakeLib([item]), None, pretend=False)
    assert track.rated == [None]  # cleared on Plex (rate(None))


def test_sync_pretend_writes_nothing(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3")
    p.sync_ratings(FakeLib([item]), None, pretend=True)
    assert item.stored == 0
    assert "rating" not in item._fields
    assert track.rated == []
    out = capsys.readouterr().out
    assert "would adopt /mnt/music/a.mp3: →4.0" in out


def test_sync_pretend_prints_push_decision(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=None)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3", rating=7.0)  # rated in beets, not Plex
    p.sync_ratings(FakeLib([item]), None, pretend=True)
    assert item.stored == 0
    assert track.rated == []
    out = capsys.readouterr().out
    assert "would push /mnt/music/a.mp3: 7.0→7.0" in out


def test_sync_pretend_marks_conflict(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3", rating=8.0, plex_rating_baseline=6.0)
    p.sync_ratings(FakeLib([item]), None, pretend=True)
    out = capsys.readouterr().out
    assert "conflict /mnt/music/a.mp3: beets 8.0 vs plex 4.0 → 4.0" in out
    assert "would adopt /mnt/music/a.mp3: →4.0" in out
    assert track.rated == []  # pretend writes nothing


def test_sync_store_only_if_changed(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=5.0)
    p = _plugin(FakeSection("Muziek", [track]))
    item = FakeItem("/mnt/music/a.mp3")
    p.sync_ratings(FakeLib([item]), None, pretend=False)  # adopt 5.0, store
    assert item.stored == 1
    capsys.readouterr()  # discard the first call's summary
    p.sync_ratings(FakeLib([item]), None, pretend=False)  # nothing changed
    assert item.stored == 1
    assert "unchanged 1" in capsys.readouterr().out


def test_run_dispatches_sync(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]))

    class _Opts:
        pretend = False

    p._run(FakeLib([FakeItem("/mnt/music/a.mp3")]), _Opts(), ["sync"])
    assert "1 matched" in capsys.readouterr().out


def test_sync_rejects_unknown_policy():
    track = FakeTrack(1, ["/srv/media/a.mp3"], userRating=4.0)
    p = _plugin(FakeSection("Muziek", [track]), policy="bogus")
    item = FakeItem("/mnt/music/a.mp3", rating=7.0)
    with pytest.raises(ui.UserError):
        p.sync_ratings(FakeLib([item]), None, pretend=False)

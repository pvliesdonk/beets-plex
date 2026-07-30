"""plex rating sync: the pure three-way merge and the plugin sync."""

from __future__ import annotations

from beets.dbcore import types as _types

from beetsplug import plex
from beetsplug.plex import rating
from beetsplug.plex.rating import ADOPT, NONE, PUSH


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

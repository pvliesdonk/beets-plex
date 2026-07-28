from datetime import datetime, timedelta

import pytest

from beetsplug.plex.sync import NONE, PULL, PUSH, decide, normalize


def test_normalize():
    assert normalize(None) == 0.0
    assert normalize(0) == 0.0
    assert normalize(7.96) == 8.0


def test_no_changes():
    d = decide(8.0, 8.0, 8.0, None, None, "plex")
    assert (d.action, d.value) == (NONE, 8.0)


def test_never_synced_and_unrated_everywhere():
    d = decide(None, None, None, None, None, "plex")
    assert (d.action, d.value) == (NONE, 0.0)


def test_plex_changed_pulls():
    d = decide(6.0, 6.0, 9.0, None, None, "plex")
    assert (d.action, d.value) == (PULL, 9.0)


def test_plex_cleared_pulls_clear():
    d = decide(6.0, 6.0, None, None, None, "plex")
    assert (d.action, d.value) == (PULL, 0.0)


def test_beets_changed_pushes():
    d = decide(6.0, 9.0, 6.0, None, None, "plex")
    assert (d.action, d.value) == (PUSH, 9.0)


def test_beets_cleared_pushes_clear():
    d = decide(6.0, None, 6.0, None, None, "plex")
    assert (d.action, d.value) == (PUSH, 0.0)


def test_first_sync_pull_only_plex_rated():
    # base absent, beets unrated, plex rated -> pull
    d = decide(None, None, 8.0, None, None, "plex")
    assert (d.action, d.value) == (PULL, 8.0)


def test_first_sync_push_only_beets_rated():
    d = decide(None, 8.0, None, None, None, "plex")
    assert (d.action, d.value) == (PUSH, 8.0)


def test_both_changed_to_same_value_needs_no_network_action():
    d = decide(6.0, 9.0, 9.0, None, None, "plex")
    assert (d.action, d.value) == (NONE, 9.0)


def test_both_changed_newest_wins_beets():
    now = datetime.now()
    d = decide(
        6.0,
        9.0,
        4.0,
        rating_updated=now.timestamp(),
        plex_lastratedat=now - timedelta(hours=1),
        conflict="plex",
    )
    assert (d.action, d.value) == (PUSH, 9.0)


def test_both_changed_newest_wins_plex():
    now = datetime.now()
    d = decide(
        6.0,
        9.0,
        4.0,
        rating_updated=(now - timedelta(hours=1)).timestamp(),
        plex_lastratedat=now,
        conflict="beets",
    )
    assert (d.action, d.value) == (PULL, 4.0)


@pytest.mark.parametrize(
    "conflict,action,value",
    [("plex", PULL, 4.0), ("beets", PUSH, 9.0)],
)
def test_both_changed_without_timestamp_uses_conflict_policy(conflict, action, value):
    d = decide(6.0, 9.0, 4.0, None, datetime.now(), conflict)
    assert (d.action, d.value) == (action, value)

"""plex auto-scan: pure scan planning, the accumulate handlers, and cli_exit."""

from __future__ import annotations

from beetsplug.plex import scanning

BEETS_DIR = "/mnt/music"
PLEX_DIR = "/srv/media"


def test_plan_targeted_translates_and_sorts():
    plan = scanning.plan_scan(
        {"/mnt/music/b", "/mnt/music/a"}, 100, BEETS_DIR, PLEX_DIR
    )
    assert plan.full is False
    assert plan.paths == ["/srv/media/a", "/srv/media/b"]
    assert plan.skipped == []


def test_plan_full_past_threshold():
    dirs = {f"/mnt/music/d{i}" for i in range(5)}
    plan = scanning.plan_scan(dirs, 3, BEETS_DIR, PLEX_DIR)
    assert plan.full is True
    assert plan.paths == []


def test_plan_skips_dirs_outside_beets_dir():
    plan = scanning.plan_scan({"/mnt/music/a", "/other/x"}, 100, BEETS_DIR, PLEX_DIR)
    assert plan.paths == ["/srv/media/a"]
    assert plan.skipped == ["/other/x"]


def test_plan_empty():
    plan = scanning.plan_scan(set(), 100, BEETS_DIR, PLEX_DIR)
    assert plan == (False, [], [])

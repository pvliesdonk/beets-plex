"""plex auto-scan: pure scan planning, the accumulate handlers, and cli_exit."""

from __future__ import annotations

from beetsplug import plex
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


class _Item:
    def __init__(self, path):
        self.path = path.encode()


def test_handlers_accumulate_dirs():
    p = plex.PlexPlugin()
    p._scan_item(item=_Item("/mnt/music/a/x.mp3"))
    p._scan_move(source=b"/mnt/music/b/y.mp3", destination=b"/mnt/music/c/y.mp3")
    p._scan_place(destination=b"/mnt/music/d/z.mp3")
    p._scan_item(item=_Item("/mnt/music/a/w.mp3"))  # same dir → deduped
    assert p._scan_dirs == {
        "/mnt/music/a",
        "/mnt/music/b",  # move source
        "/mnt/music/c",  # move destination
        "/mnt/music/d",  # copy/link destination
    }


def test_config_defaults():
    p = plex.PlexPlugin()
    assert p.config["auto_scan"].get(bool) is False
    assert p.config["scan_threshold"].get(int) == 100


def test_listeners_registered_only_when_auto_scan(monkeypatch):
    from beets import config

    registered = []
    monkeypatch.setattr(
        plex.PlexPlugin,
        "register_listener",
        lambda self, event, func: registered.append(event),
    )
    config["plex"]["auto_scan"].set(True)
    try:
        plex.PlexPlugin()
        assert "cli_exit" in registered
        assert "item_moved" in registered
    finally:
        config["plex"]["auto_scan"].set(False)
    registered.clear()
    plex.PlexPlugin()
    assert "cli_exit" not in registered

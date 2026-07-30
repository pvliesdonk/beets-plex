"""plex auto-scan: pure scan planning, the accumulate handlers, and cli_exit."""

from __future__ import annotations

from beetsplug import plex
from beetsplug.plex import scanning
from tests.fake_plex import FakeSection, FakeServer

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


def _plugin(section):
    p = plex.PlexPlugin()
    p._server = FakeServer(section)
    p.config["beets_dir"].set(BEETS_DIR)
    p.config["plex_dir"].set(PLEX_DIR)
    p.config["library_name"].set(section.title)
    return p


def test_cli_exit_runs_targeted_scans_and_clears():
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    p._scan_dirs = {"/mnt/music/a", "/mnt/music/b"}
    p._scan_cli_exit()
    assert sorted(section.updates) == ["/srv/media/a", "/srv/media/b"]
    assert p._scan_dirs == set()  # cleared


def test_cli_exit_full_refresh_past_threshold():
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    p.config["scan_threshold"].set(1)
    p._scan_dirs = {"/mnt/music/a", "/mnt/music/b"}
    p._scan_cli_exit()
    assert section.updates == [None]  # one full refresh (no path)


def test_cli_exit_warns_and_skips_dirs_outside_beets_dir():
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    p._scan_dirs = {"/mnt/music/a", "/other/x"}
    p._scan_cli_exit()
    assert section.updates == ["/srv/media/a"]
    assert p._scan_dirs == set()  # cleared


def test_cli_exit_no_dirs_does_nothing():
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    p._scan_cli_exit()
    assert section.updates == []


def test_cli_exit_scan_failure_warns_not_raises():
    section = FakeSection("Muziek", [])
    section.update_raises = True
    p = _plugin(section)
    p._scan_dirs = {"/mnt/music/a"}
    p._scan_cli_exit()  # must NOT raise
    assert p._scan_dirs == set()  # still cleared

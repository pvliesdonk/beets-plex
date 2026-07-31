"""plex auto-scan: pure scan planning, the accumulate handlers, and cli_exit."""

from __future__ import annotations

import pytest

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


def test_plan_threshold_boundary_is_strict():
    # exactly at the threshold stays targeted; one over goes full — pins `>` vs `>=`
    dirs = {f"/mnt/music/d{i}" for i in range(3)}
    at = scanning.plan_scan(dirs, 3, BEETS_DIR, PLEX_DIR)
    assert at.full is False and len(at.paths) == 3
    over = scanning.plan_scan(dirs, 2, BEETS_DIR, PLEX_DIR)
    assert over.full is True and over.paths == []


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


# The scan events this plugin wires, each to its handler (beets' own base-class
# registrations, e.g. pluginload, are not ours and are ignored below).
_SCAN_WIRING = {
    "item_imported": "_scan_item",
    "item_removed": "_scan_item",
    "item_moved": "_scan_move",
    "item_copied": "_scan_place",
    "item_linked": "_scan_place",
    "item_hardlinked": "_scan_place",
    "item_reflinked": "_scan_place",
    "cli_exit": "_scan_cli_exit",
}


def test_all_listeners_registered_and_wired_when_auto_scan(monkeypatch):
    from beets import config

    registered = {}
    monkeypatch.setattr(
        plex.PlexPlugin,
        "register_listener",
        lambda self, event, func: registered.__setitem__(event, func.__name__),
    )
    config["plex"]["auto_scan"].set(True)  # reset per test by _isolate_beets_config
    plex.PlexPlugin()
    # every scan event is wired to its intended handler — dropping or mis-wiring
    # any one would silently disable auto-scan for that operation.
    assert {e: registered.get(e) for e in _SCAN_WIRING} == _SCAN_WIRING


def test_no_scan_listeners_registered_when_auto_scan_off(monkeypatch):
    registered = []
    monkeypatch.setattr(
        plex.PlexPlugin,
        "register_listener",
        lambda self, event, func: registered.append(event),
    )
    plex.PlexPlugin()  # auto_scan defaults to False
    assert not set(registered) & set(_SCAN_WIRING)  # no scan listener registered


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


def test_cli_exit_unreachable_plex_warns_not_raises():
    # The headline guarantee: a beets command must not break because Plex is
    # unreachable. Here section() itself raises ui.UserError (library not found),
    # which the scan must swallow as a warning — never propagate.
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    p.config["library_name"].set("Missing")  # section() → UserError
    p._scan_dirs = {"/mnt/music/a"}
    p._scan_cli_exit()  # must NOT raise
    assert section.updates == []  # never reached the scan
    assert p._scan_dirs == set()  # still cleared


def test_cli_exit_unexpected_error_propagates():
    # A non-Plex error (a real bug) must NOT be swallowed by the warning path —
    # the catch is narrow, so a logic error still surfaces.
    section = FakeSection("Muziek", [])

    def boom(path=None):
        raise RuntimeError("a real bug, not a Plex error")

    section.update = boom
    p = _plugin(section)
    p._scan_dirs = {"/mnt/music/a"}
    with pytest.raises(RuntimeError):
        p._scan_cli_exit()


def test_cli_exit_one_failing_scan_does_not_drop_the_rest():
    # Per-item resilience: a single failing directory scan must not abort the
    # batch — the other directories are still scanned (matches sync/push).
    section = FakeSection("Muziek", [])
    section.update_fail_paths = {"/srv/media/a"}
    p = _plugin(section)
    p._scan_dirs = {"/mnt/music/a", "/mnt/music/b", "/mnt/music/c"}
    p._scan_cli_exit()  # a fails; b and c still get scanned
    assert sorted(section.updates) == ["/srv/media/b", "/srv/media/c"]
    assert p._scan_dirs == set()


def test_cli_exit_all_dirs_skipped_never_touches_plex():
    # When every touched dir is outside beets_dir, there is nothing to scan and
    # the plugin never even connects to Plex.
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    p._scan_dirs = {"/other/x", "/other/y"}
    p._scan_cli_exit()
    assert section.updates == []
    assert p._scan_dirs == set()

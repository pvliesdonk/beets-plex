"""plex core: path matching, server construction, and status — driven by the
fake Plex model."""

from __future__ import annotations

import pytest
from beets import ui
from beets.dbcore import types
from fake_plex import FakeItem, FakeLib, FakeSection, FakeServer, FakeTrack

from beetsplug import plex
from beetsplug.plex import matching

BEETS_DIR = "/mnt/music"
PLEX_DIR = "/srv/media"


# -- matching (pure) --------------------------------------------------------


@pytest.mark.parametrize(
    "item_path, expected",
    [
        ("/mnt/music/a/b.mp3", "/srv/media/a/b.mp3"),
        ("/mnt/music", "/srv/media"),  # library root maps to plex_dir
        ("/mnt/music/", "/srv/media"),  # trailing slash
        ("/other/x.mp3", None),  # outside beets_dir
        ("/mnt/musicfoo/x.mp3", None),  # prefix look-alike, not actually under
    ],
)
def test_plex_path(item_path, expected):
    assert matching.plex_path(item_path, BEETS_DIR, PLEX_DIR) == expected


def test_resolve_hit_and_miss():
    track = FakeTrack(ratingKey=1, files=["/srv/media/a.mp3"])
    path_map = matching.build_path_map([track])
    assert matching.resolve("/mnt/music/a.mp3", path_map, BEETS_DIR, PLEX_DIR) is track
    assert matching.resolve("/mnt/music/x.mp3", path_map, BEETS_DIR, PLEX_DIR) is None


def test_multi_location_track_found_by_any_file():
    track = FakeTrack(1, ["/srv/media/a.mp3", "/srv/media/b.mp3"])
    path_map = matching.build_path_map([track])
    assert matching.resolve("/mnt/music/b.mp3", path_map, BEETS_DIR, PLEX_DIR) is track


# -- server() ---------------------------------------------------------------


def test_server_builds_url_and_passes_token(monkeypatch):
    captured = {}

    class StubServer:
        def __init__(self, baseurl, token):
            captured["baseurl"] = baseurl
            captured["token"] = token

    monkeypatch.setattr("plexapi.server.PlexServer", StubServer)
    p = plex.PlexPlugin()
    p.config["host"].set("192.168.1.5")
    p.config["port"].set(32400)
    p.config["token"].set("SECRET")
    p.config["secure"].set(True)
    p.server()
    assert captured == {"baseurl": "https://192.168.1.5:32400", "token": "SECRET"}


def test_server_insecure_uses_http(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "plexapi.server.PlexServer",
        lambda baseurl, token: captured.update(baseurl=baseurl),
    )
    p = plex.PlexPlugin()
    p.config["host"].set("h")
    p.config["secure"].set(False)
    p.server()
    assert captured["baseurl"].startswith("http://")


def test_server_connection_failure_is_user_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr("plexapi.server.PlexServer", boom)
    p = plex.PlexPlugin()
    with pytest.raises(ui.UserError):
        p.server()


# -- match() + status via the fake server -----------------------------------


def _plugin_with(section):
    p = plex.PlexPlugin()
    p._server = FakeServer(section)
    p.config["beets_dir"].set(BEETS_DIR)
    p.config["plex_dir"].set(PLEX_DIR)
    p.config["library_name"].set(section.title)
    return p


def test_match_counts_matched_and_unmatched():
    section = FakeSection(
        "Muziek",
        [FakeTrack(1, ["/srv/media/a.mp3"]), FakeTrack(2, ["/srv/media/b.mp3"])],
    )
    p = _plugin_with(section)
    items = [FakeItem("/mnt/music/a.mp3"), FakeItem("/mnt/music/gone.mp3")]
    matched, unmatched = p.match(items)
    assert [t.ratingKey for _, t in matched] == [1]
    assert len(unmatched) == 1


def test_match_by_path_ignores_stale_ratingkey():
    section = FakeSection("Muziek", [FakeTrack(999, ["/srv/media/a.mp3"])])
    p = _plugin_with(section)
    item = FakeItem("/mnt/music/a.mp3", plex_ratingkey=111)  # stale cache
    matched, _ = p.match([item])
    assert matched[0][1].ratingKey == 999  # resolved by path, not the stale key


def test_status_reports_counts(capsys):
    section = FakeSection("Muziek", [FakeTrack(1, ["/srv/media/a.mp3"])])
    p = _plugin_with(section)
    lib = FakeLib([FakeItem("/mnt/music/a.mp3"), FakeItem("/other/x.mp3")])
    p.status(lib)
    out = capsys.readouterr().out
    assert "Muziek" in out and "1 tracks" in out
    assert "1 of 2 items matched" in out and "1 unmatched" in out


def test_status_resolves_section_once():
    section = FakeSection("Muziek", [FakeTrack(1, ["/srv/media/a.mp3"])])
    p = _plugin_with(section)
    p.status(FakeLib([FakeItem("/mnt/music/a.mp3")]))
    assert p._server.library.section_calls == 1


def test_library_name_is_case_and_space_insensitive():
    # plexapi's Library.section normalizes the title; a case/spacing variant of
    # the configured library_name must still resolve, as it would against Plex.
    section = FakeSection("Muziek Archief", [])
    p = plex.PlexPlugin()
    p._server = FakeServer(section)
    p.config["library_name"].set("  muziek archief  ")
    assert p.section() is section


def test_plugin_declares_ratingkey_field():
    assert plex.PlexPlugin.item_types == {"plex_ratingkey": types.INTEGER}


def test_run_dispatches_status_and_rejects_unknown(capsys):
    section = FakeSection("Muziek", [FakeTrack(1, ["/srv/media/a.mp3"])])
    p = _plugin_with(section)
    p._run(FakeLib([FakeItem("/mnt/music/a.mp3")]), None, ["status"])
    assert "Muziek" in capsys.readouterr().out
    with pytest.raises(ui.UserError):
        p._run(FakeLib([]), None, ["bogus"])

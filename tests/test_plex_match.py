from beets.library import Item

from beetsplug.plex import match
from tests.fakeplex import FakeMusicSection, FakeTrack


def test_plex_path_translates_prefix():
    assert (
        match.plex_path(b"/mnt/music/A/b.flac", "/mnt/music", "/data/music")
        == "/data/music/A/b.flac"
    )


def test_plex_path_identity_mapping():
    assert (
        match.plex_path(b"/mnt/music/A/b.flac", "/mnt/music", "/mnt/music")
        == "/mnt/music/A/b.flac"
    )


def test_plex_path_outside_library_is_none():
    assert match.plex_path(b"/elsewhere/x.mp3", "/mnt/music", "/mnt/music") is None


def test_plex_path_rejects_sibling_prefix():
    # /mnt/music2 must not match the /mnt/music prefix
    assert match.plex_path(b"/mnt/music2/x.mp3", "/mnt/music", "/plex") is None


def test_build_path_map_covers_all_locations():
    a = FakeTrack(1, ["/plex/A/a.flac"])
    b = FakeTrack(2, ["/plex/B/b.mp3", "/plex/B/b.flac"])
    music = FakeMusicSection(tracks=[a, b])
    path_map = match.build_path_map(music)
    assert path_map["/plex/A/a.flac"] is a
    assert path_map["/plex/B/b.mp3"] is b
    assert path_map["/plex/B/b.flac"] is b


def test_resolve_by_path_ignores_stale_ratingkey():
    track = FakeTrack(99, ["/plex/A/a.flac"])
    music = FakeMusicSection(tracks=[track])
    path_map = match.build_path_map(music)
    item = Item(path=b"/music/A/a.flac")
    item["plex_ratingkey"] = 12345  # stale; must not matter
    assert match.resolve(item, path_map, "/music", "/plex") is track


def test_resolve_unmatched_returns_none():
    path_map = {}
    item = Item(path=b"/music/A/missing.flac")
    assert match.resolve(item, path_map, "/music", "/plex") is None

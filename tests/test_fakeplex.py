import pytest
from plexapi.exceptions import NotFound

from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack


def test_rate_records_and_bumps_lastratedat():
    track = FakeTrack(1, ["/music/a.mp3"])
    track.rate(8.0)
    assert track.userRating == 8.0
    assert track.rate_calls == [8.0]
    assert track.lastRatedAt is not None


def test_unknown_section_raises_notfound():
    server = FakeServer(FakeMusicSection())
    with pytest.raises(NotFound):
        server.library.section("nope")


def test_playlist_lifecycle():
    server = FakeServer(FakeMusicSection())
    tracks = [FakeTrack(1, ["/music/a.mp3"]), FakeTrack(2, ["/music/b.mp3"])]
    playlist = server.createPlaylist("mix", items=tracks)
    assert [t.ratingKey for t in playlist.items()] == [1, 2]
    playlist.delete()
    assert server.playlists() == []


def test_collection_diff_surface():
    section = FakeMusicSection()
    server = FakeServer(section)
    a, b = FakeTrack(1, ["/music/a.mp3"]), FakeTrack(2, ["/music/b.mp3"])
    collection = server.createCollection("col", section=section, items=[a])
    collection.addItems([b])
    collection.removeItems([a])
    assert [t.ratingKey for t in collection.items()] == [2]

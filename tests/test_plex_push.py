"""plex playlists + collections push: pure diff/order helpers and the commands."""

from __future__ import annotations

import pytest
from plexapi.exceptions import BadRequest, NotFound

from beetsplug import plex
from beetsplug.plex import pushing
from tests.fake_plex import FakeSection, FakeServer, FakeTrack


class _T:
    """A stand-in track carrying just the ratingKey the helpers compare on."""

    def __init__(self, ratingKey):
        self.ratingKey = ratingKey


def test_playlist_matches_is_order_sensitive():
    a, b, c = _T(1), _T(2), _T(3)
    assert pushing.playlist_matches([a, b, c], [a, b, c]) is True
    assert pushing.playlist_matches([a, b, c], [a, c, b]) is False  # order matters
    assert pushing.playlist_matches([a, b], [a, b, c]) is False


def test_collection_diff_is_set_based():
    a, b, c = _T(1), _T(2), _T(3)
    to_add, to_remove = pushing.collection_diff(current=[a, b], desired=[b, c])
    assert [t.ratingKey for t in to_add] == [3]  # c is new
    assert [t.ratingKey for t in to_remove] == [1]  # a is extra


def test_collection_diff_no_change():
    a, b = _T(1), _T(2)
    to_add, to_remove = pushing.collection_diff([a, b], [b, a])  # order irrelevant
    assert to_add == [] and to_remove == []


def test_config_defaults_and_entries():
    p = plex.PlexPlugin()
    assert p.config["playlists"].get(list) == []
    assert p.config["collections"].get(list) == []
    assert p.config["prune_empty"].get(bool) is False
    p.config["playlists"].set(
        [
            {"name": "Fav", "query": "rating:8..10"},
            {"name": "New", "query": "x"},
        ]
    )
    assert p._entries("playlists", []) == [("Fav", "rating:8..10"), ("New", "x")]
    assert p._entries("playlists", ["New"]) == [("New", "x")]  # named subset


def test_fake_playlist_lookup_asymmetry():
    # Mirrors plexapi: server.playlist raises NotFound when absent; a regular
    # playlist is created on the SERVER with no section; a collection on the SECTION.
    section = FakeSection("Muziek", [])
    server = FakeServer(section)
    with pytest.raises(NotFound):
        server.playlist("nope")
    with pytest.raises(NotFound):
        section.collection("nope")
    pl = server.createPlaylist("P", items=[FakeTrack(1, ["/srv/media/a.mp3"])])
    assert server.playlist("P") is pl
    coll = section.createCollection("C", items=[FakeTrack(2, ["/srv/media/b.mp3"])])
    assert section.collection("C") is coll


def test_fake_create_requires_items():
    # Mirrors plexapi: createPlaylist and createCollection raise BadRequest
    # if items is empty or None; Tasks 3/4 must never call create() with
    # an empty list when prune_empty is true.
    section = FakeSection("Muziek", [])
    server = FakeServer(section)
    with pytest.raises(BadRequest, match="Must include items"):
        server.createPlaylist("Empty", items=[])
    with pytest.raises(BadRequest, match="Must include items"):
        server.createPlaylist("None", items=None)
    with pytest.raises(BadRequest, match="Must include items"):
        section.createCollection("Empty", items=[])
    with pytest.raises(BadRequest, match="Must include items"):
        section.createCollection("None", items=None)

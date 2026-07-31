"""plex playlists + collections push: pure diff/order helpers and the commands."""

from __future__ import annotations

import pytest
from beets import ui
from plexapi.exceptions import BadRequest, NotFound

from beetsplug import plex
from beetsplug.plex import pushing
from tests.fake_plex import FakeItem, FakeLib, FakeSection, FakeServer, FakeTrack

BEETS_DIR = "/mnt/music"
PLEX_DIR = "/srv/media"


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


def test_entries_malformed_entry_raises_usererror():
    p = plex.PlexPlugin()
    p.config["playlists"].set(["not-a-dict"])
    with pytest.raises(ui.UserError):
        p._entries("playlists", [])

    p2 = plex.PlexPlugin()
    p2.config["collections"].set([{"name": "Rated"}])  # missing 'query'
    with pytest.raises(ui.UserError):
        p2._entries("collections", [])

    p3 = plex.PlexPlugin()
    p3.config["playlists"].set([{"query": "x"}])  # missing 'name'
    with pytest.raises(ui.UserError):
        p3._entries("playlists", [])


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


def test_fake_lookup_is_case_insensitive():
    # Real plexapi's Server.playlist / Section.collection match title__iexact
    # (case-insensitive); the fakes must be no stricter than the real API.
    section = FakeSection("Muziek", [])
    server = FakeServer(section)
    pl = server.createPlaylist("Fav", items=[FakeTrack(1, ["/srv/media/a.mp3"])])
    assert server.playlist("FAV") is pl
    assert server.playlist(" fav ") is pl
    coll = section.createCollection("Rated", items=[FakeTrack(2, ["/srv/media/b.mp3"])])
    assert section.collection("RATED") is coll
    assert section.collection(" rated ") is coll


def _plugin(section):
    p = plex.PlexPlugin()
    p._server = FakeServer(section)
    p.config["beets_dir"].set(BEETS_DIR)
    p.config["plex_dir"].set(PLEX_DIR)
    p.config["library_name"].set(section.title)
    return p


def test_playlist_created_from_query(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [track])
    p = _plugin(section)
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    p.push_playlists(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=False)
    pl = p._server.playlist("Fav")
    assert [t.ratingKey for t in pl.items()] == [1]


def test_playlist_unchanged_is_noop(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    p = _plugin(FakeSection("Muziek", [track]))
    p._server.createPlaylist("Fav", items=[track])  # already matches
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    p.push_playlists(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=False)
    assert "keep" in capsys.readouterr().out


def test_playlist_rebuilt_to_match_order():
    a = FakeTrack(1, ["/srv/media/a.mp3"])
    b = FakeTrack(2, ["/srv/media/b.mp3"])
    p = _plugin(FakeSection("Muziek", [a, b]))
    p._server.createPlaylist("Fav", items=[b, a])  # wrong order
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    lib = FakeLib([FakeItem("/mnt/music/a.mp3"), FakeItem("/mnt/music/b.mp3")])
    p.push_playlists(lib, [], pretend=False)
    assert [t.ratingKey for t in p._server.playlist("Fav").items()] == [1, 2]


def test_playlist_empty_query_skips_unless_prune(capsys):
    p = _plugin(FakeSection("Muziek", []))
    existing = p._server.createPlaylist(
        "Fav", items=[FakeTrack(9, ["/srv/media/z.mp3"])]
    )
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    p.push_playlists(FakeLib([]), [], pretend=False)  # nothing matches
    assert existing.deleted is False  # left as-is
    assert "prune_empty" in capsys.readouterr().out
    p.config["prune_empty"].set(True)
    p.push_playlists(FakeLib([]), [], pretend=False)
    assert existing.deleted is True  # now pruned


def test_playlist_pretend_writes_nothing(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    p = _plugin(FakeSection("Muziek", [track]))
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    p.push_playlists(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=True)
    with pytest.raises(NotFound):
        p._server.playlist("Fav")  # not created
    assert "would" in capsys.readouterr().out


def test_playlist_pretend_prune_does_not_delete(capsys):
    p = _plugin(FakeSection("Muziek", []))
    existing = p._server.createPlaylist(
        "Fav", items=[FakeTrack(9, ["/srv/media/z.mp3"])]
    )
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    p.config["prune_empty"].set(True)
    p.push_playlists(FakeLib([]), [], pretend=True)
    assert existing.deleted is False  # pretend writes nothing
    assert "would prune" in capsys.readouterr().out


def test_playlist_resolution_failure_is_per_entry(capsys):
    # A transient Plex error while resolving one entry's tracks (a live
    # section.searchTracks() call inside _entry_tracks) must be caught and
    # counted like an apply failure, not abort the whole batch.
    from plexapi.exceptions import PlexApiException

    track = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [track])
    real_search_tracks = section.searchTracks
    calls = {"n": 0}

    def flaky_search_tracks(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PlexApiException("transient")
        return real_search_tracks(**kwargs)

    section.searchTracks = flaky_search_tracks
    p = _plugin(section)
    p.config["playlists"].set(
        [{"name": "Bad", "query": "x"}, {"name": "Fav", "query": "x"}]
    )
    p.push_playlists(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=False)
    out = capsys.readouterr().out
    assert "1 failed" in out
    assert [t.ratingKey for t in p._server.playlist("Fav").items()] == [1]


def test_playlist_excludes_unmatched_items(capsys):
    # _entry_tracks's "item not in Plex → excluded+warned" branch: a lib item
    # with no corresponding Plex track must not appear in the pushed playlist.
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [track])
    p = _plugin(section)
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    lib = FakeLib(
        [
            FakeItem("/mnt/music/a.mp3"),  # matches the Plex track
            FakeItem("/mnt/music/missing.mp3"),  # not in Plex
        ]
    )
    p.push_playlists(lib, [], pretend=False)
    pl = p._server.playlist("Fav")
    assert [t.ratingKey for t in pl.items()] == [1]


def test_push_playlists_warns_when_names_not_found(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    p = _plugin(FakeSection("Muziek", [track]))
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])
    p.push_playlists(
        FakeLib([FakeItem("/mnt/music/a.mp3")]), ["Missing"], pretend=False
    )
    assert "no playlists named: Missing" in capsys.readouterr().out
    with pytest.raises(NotFound):
        p._server.playlist("Fav")  # not touched: name filter matched nothing


def test_run_dispatches_playlists(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    p = _plugin(FakeSection("Muziek", [track]))
    p.config["playlists"].set([{"name": "Fav", "query": "x"}])

    class _Opts:
        pretend = False

    p._run(FakeLib([FakeItem("/mnt/music/a.mp3")]), _Opts(), ["playlists"])
    assert p._server.playlist("Fav") is not None


def test_collection_created_and_diffed(capsys):
    a = FakeTrack(1, ["/srv/media/a.mp3"])
    b = FakeTrack(2, ["/srv/media/b.mp3"])
    section = FakeSection("Muziek", [a, b])
    p = _plugin(section)
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    lib = FakeLib([FakeItem("/mnt/music/a.mp3"), FakeItem("/mnt/music/b.mp3")])
    p.push_collections(lib, [], pretend=False)
    coll = section.collection("Rated")
    assert {t.ratingKey for t in coll.items()} == {1, 2}
    # drop b from the query result → next push removes it (diff)
    lib2 = FakeLib([FakeItem("/mnt/music/a.mp3")])
    p.push_collections(lib2, [], pretend=False)
    assert {t.ratingKey for t in coll.items()} == {1}


def test_collection_adds_new_track_to_existing(capsys):
    # The existing-collection add path (existing.addItems(to_add)) is
    # otherwise untested: test_collection_created_and_diffed only ever
    # exercises removeItems on its second push.
    a = FakeTrack(1, ["/srv/media/a.mp3"])
    b = FakeTrack(2, ["/srv/media/b.mp3"])
    section = FakeSection("Muziek", [a, b])
    p = _plugin(section)
    section.createCollection("Rated", items=[a])
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    lib = FakeLib([FakeItem("/mnt/music/a.mp3"), FakeItem("/mnt/music/b.mp3")])
    p.push_collections(lib, [], pretend=False)
    assert {t.ratingKey for t in section.collection("Rated").items()} == {1, 2}


def test_collection_unchanged_is_noop(capsys):
    a = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [a])
    p = _plugin(section)
    section.createCollection("Rated", items=[a])
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    p.push_collections(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=False)
    assert "keep" in capsys.readouterr().out


def test_collection_pretend_writes_nothing(capsys):
    a = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [a])
    p = _plugin(section)
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    p.push_collections(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=True)
    with pytest.raises(NotFound):
        section.collection("Rated")
    assert "would" in capsys.readouterr().out


def test_collection_empty_query_skips_unless_prune(capsys):
    # The _push_collection "not tracks" branch is destructive (prune deletes
    # an existing collection) and was previously untested.
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    existing = section.createCollection(
        "Rated", items=[FakeTrack(9, ["/srv/media/z.mp3"])]
    )
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    p.push_collections(FakeLib([]), [], pretend=False)  # nothing matches, default keeps
    assert existing.deleted is False  # left as-is
    assert "prune_empty" in capsys.readouterr().out
    p.config["prune_empty"].set(True)
    p.push_collections(FakeLib([]), [], pretend=False)
    assert existing.deleted is True  # now pruned


def test_collection_pretend_prune_does_not_delete(capsys):
    section = FakeSection("Muziek", [])
    p = _plugin(section)
    existing = section.createCollection(
        "Rated", items=[FakeTrack(9, ["/srv/media/z.mp3"])]
    )
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    p.config["prune_empty"].set(True)
    p.push_collections(FakeLib([]), [], pretend=True)
    assert existing.deleted is False  # pretend writes nothing
    assert "would prune" in capsys.readouterr().out


def test_collection_resolution_failure_is_per_entry(capsys):
    # Mirrors test_playlist_resolution_failure_is_per_entry: a transient Plex
    # error while resolving one entry's tracks must be caught and counted,
    # not abort the whole batch.
    from plexapi.exceptions import PlexApiException

    track = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [track])
    real_search_tracks = section.searchTracks
    calls = {"n": 0}

    def flaky_search_tracks(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PlexApiException("transient")
        return real_search_tracks(**kwargs)

    section.searchTracks = flaky_search_tracks
    p = _plugin(section)
    p.config["collections"].set(
        [{"name": "Bad", "query": "x"}, {"name": "Rated", "query": "x"}]
    )
    p.push_collections(FakeLib([FakeItem("/mnt/music/a.mp3")]), [], pretend=False)
    out = capsys.readouterr().out
    assert "1 failed" in out
    assert [t.ratingKey for t in section.collection("Rated").items()] == [1]


def test_push_collections_warns_when_names_not_found(capsys):
    track = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [track])
    p = _plugin(section)
    p.config["collections"].set([{"name": "Rated", "query": "x"}])
    p.push_collections(
        FakeLib([FakeItem("/mnt/music/a.mp3")]), ["Missing"], pretend=False
    )
    assert "no collections named: Missing" in capsys.readouterr().out
    with pytest.raises(NotFound):
        section.collection("Rated")  # not touched: name filter matched nothing


def test_run_dispatches_collections(capsys):
    a = FakeTrack(1, ["/srv/media/a.mp3"])
    section = FakeSection("Muziek", [a])
    p = _plugin(section)
    p.config["collections"].set([{"name": "Rated", "query": "x"}])

    class _Opts:
        pretend = False

    p._run(FakeLib([FakeItem("/mnt/music/a.mp3")]), _Opts(), ["collections"])
    assert section.collection("Rated") is not None

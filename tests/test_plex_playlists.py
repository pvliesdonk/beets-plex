import pytest
from beets import ui
from beets.test.helper import PluginTestHelper
from plexapi.exceptions import BadRequest

from tests.fakeplex import (
    FakeMusicSection,
    FakePlaylist,
    FakeServer,
    FakeTrack,
)
from tests.test_plex_plugin import plex_plugin


class PlaylistBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self, tracks, playlists_config):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        config["plex"]["playlists"] = playlists_config
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin


class TestPlaylists(PlaylistBase):
    def test_creates_playlist_in_query_order(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        b = FakeTrack(2, ["/plex/B/b.mp3"])
        # A descending sort, so the expected order contradicts beets'
        # default ordering and the test fails if the sort is dropped.
        plugin = self.setup_plex([a, b], [{"name": "mix", "query": "title:t artist-"}])
        self.add_item(path=b"/music/B/b.mp3", title="t", artist="zz")
        self.add_item(path=b"/music/A/a.mp3", title="t", artist="aa")

        self.run_command("plex", "playlists")

        playlists = plugin._server.playlists()
        assert len(playlists) == 1
        assert [t.ratingKey for t in playlists[0].items()] == [2, 1]

    def test_rebuilds_when_content_differs(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        stale = plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        playlists = plugin._server.playlists()
        assert len(playlists) == 1
        assert playlists[0] is not stale
        assert [t.ratingKey for t in playlists[0].items()] == [1]

    def test_unchanged_playlist_is_left_alone(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")
        existing = plugin._server.createPlaylist("mix", items=[a])

        self.run_command("plex", "playlists")

        assert plugin._server.playlists()[0] is existing

    def test_empty_query_leaves_the_playlist_alone_by_default(self):
        # A query matching nothing is usually a typo, not an instruction to
        # delete, so the default must be conservative.
        plugin = self.setup_plex([], [{"name": "mix", "query": "title:none"}])
        existing = plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [existing]

    def test_empty_query_result_deletes_playlist_when_pruning(self):
        from beets import config

        plugin = self.setup_plex([], [{"name": "mix", "query": "title:none"}])
        config["plex"]["prune"] = True
        plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == []

    def test_non_audio_playlist_with_same_name_is_skipped(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        video = FakePlaylist(plugin._server, "mix", [], playlistType="video")
        plugin._server._playlists.append(video)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [video]

    def test_smart_playlist_is_skipped(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        smart = FakePlaylist(plugin._server, "mix", [], smart=True)
        plugin._server._playlists.append(smart)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [smart]

    def test_unmatched_items_are_skipped_not_fatal(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")
        self.add_item(path=b"/music/C/missing.mp3", title="u")

        self.run_command("plex", "playlists")

        assert [t.ratingKey for t in plugin._server.playlists()[0].items()] == [1]

    def test_name_argument_selects_playlist_and_unknown_name_errors(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [{"name": "one", "query": ""}, {"name": "two", "query": "title:none"}],
        )
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists", "one")
        assert [p.title for p in plugin._server.playlists()] == ["one"]

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists", "nope")

    def test_failed_create_leaves_the_previous_playlist_intact(self):
        # Pins create-before-delete: the end state alone is identical under
        # either ordering, so only a failing create distinguishes them.
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        existing = plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        def broken_create(title, items=None, **kwargs):
            raise BadRequest("server busy")

        plugin._server.createPlaylist = broken_create

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [existing]

    def test_reordered_playlist_is_rebuilt(self):
        # Playlist order carries the query's sort, so the same tracks in a
        # different order are a real difference, not "unchanged".
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        b = FakeTrack(2, ["/plex/B/b.mp3"])
        plugin = self.setup_plex([a, b], [{"name": "mix", "query": "title:t artist+"}])
        self.add_item(path=b"/music/A/a.mp3", title="t", artist="aa")
        self.add_item(path=b"/music/B/b.mp3", title="t", artist="zz")
        plugin._server.createPlaylist("mix", items=[b, a])  # reversed

        self.run_command("plex", "playlists")

        assert [t.ratingKey for t in plugin._server.playlists()[0].items()] == [1, 2]

    def test_one_failing_entry_does_not_cancel_the_others(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [{"name": "bad", "query": ""}, {"name": "good", "query": ""}],
        )
        self.add_item(path=b"/music/A/a.mp3", title="t")
        real_create = plugin._server.createPlaylist

        def flaky(title, items=None, **kwargs):
            if title == "bad":
                raise BadRequest("nope")
            return real_create(title, items=items, **kwargs)

        plugin._server.createPlaylist = flaky

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

        assert [p.title for p in plugin._server.playlists()] == ["good"]

    def test_refused_resolve_does_not_cancel_the_others(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [
                {"name": "bad", "query": "title:orphan"},
                {"name": "good", "query": "title:t"},
            ],
        )
        self.add_item(path=b"/music/C/orphan.mp3", title="orphan")
        self.add_item(path=b"/music/A/a.mp3", title="t")

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

        assert [p.title for p in plugin._server.playlists()] == ["good"]

    def test_malformed_query_does_not_cancel_the_others(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [
                {"name": "bad", "query": "'unterminated"},
                {"name": "good", "query": "title:t"},
            ],
        )
        self.add_item(path=b"/music/A/a.mp3", title="t")

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

        assert [p.title for p in plugin._server.playlists()] == ["good"]

    def test_duplicate_titles_are_collapsed_to_one(self):
        # An interrupted earlier run can leave two playlists with the same
        # title; every stale one must go, not just the first.
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        plugin._server.createPlaylist("mix", items=[a])
        plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        playlists = plugin._server.playlists()
        assert len(playlists) == 1
        assert [t.ratingKey for t in playlists[0].items()] == [1]

    def test_empty_query_deletes_every_duplicate_when_pruning(self):
        from beets import config

        plugin = self.setup_plex([], [{"name": "mix", "query": "title:none"}])
        config["plex"]["prune"] = True
        plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])
        plugin._server.createPlaylist("mix", items=[FakeTrack(8, ["/y"])])

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == []

    def test_total_match_failure_does_not_delete_the_playlist(self):
        # Every item unresolvable (e.g. a wrong plex_dir) must not be
        # mistaken for an empty query and delete the playlist.
        plugin = self.setup_plex([], [{"name": "mix", "query": ""}])
        existing = plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [existing]

    def test_entry_without_a_name_is_rejected(self):
        self.setup_plex([], [{"query": "title:t"}])

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

    def test_pretend_changes_nothing(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists", "--pretend")

        assert plugin._server.playlists() == []


class TestPlaylistEntryValidation(PlaylistBase):
    def test_entry_without_a_query_is_rejected(self):
        self.setup_plex([], [{"name": "mix"}])
        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists")

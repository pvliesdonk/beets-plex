import pytest
from beets import ui
from beets.test.helper import PluginTestHelper

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
        plugin = self.setup_plex([a, b], [{"name": "mix", "query": "title:t artist+"}])
        self.add_item(path=b"/music/B/b.mp3", title="t", artist="zz")
        self.add_item(path=b"/music/A/a.mp3", title="t", artist="aa")

        self.run_command("plex", "playlists")

        playlists = plugin._server.playlists()
        assert len(playlists) == 1
        assert [t.ratingKey for t in playlists[0].items()] == [1, 2]

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

    def test_empty_query_result_deletes_playlist(self):
        plugin = self.setup_plex([], [{"name": "mix", "query": "title:none"}])
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

    def test_pretend_changes_nothing(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists", "--pretend")

        assert plugin._server.playlists() == []

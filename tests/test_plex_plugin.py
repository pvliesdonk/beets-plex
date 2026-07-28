import pytest
from beets import plugins as plugin_registry
from beets import ui
from beets.test.helper import IOMixin, PluginTestHelper

from tests.fakeplex import FakeMusicSection, FakeServer


def plex_plugin():
    return next(p for p in plugin_registry.find_plugins() if p.name == "plex")


class TestPlexPluginSkeleton(PluginTestHelper):
    plugin = "plex"

    def test_config_defaults(self):
        from beets import config

        assert config["plex"]["port"].get(int) == 32400
        assert config["plex"]["library_name"].as_str() == "Music"
        assert config["plex"]["auto_scan"].get(bool) is True
        assert config["plex"]["conflict"].as_str() == "plex"
        assert config["plex"]["token"].redact

    def test_dirs_default_to_beets_directory(self):
        from beets import config

        config["directory"] = "/music"
        beets_dir, plex_dir = plex_plugin().dirs()
        assert beets_dir == "/music"
        assert plex_dir == "/music"

    def test_dirs_use_configured_prefixes(self):
        from beets import config

        config["plex"]["beets_dir"] = "/mnt/music/"
        config["plex"]["plex_dir"] = "/data/music/"
        assert plex_plugin().dirs() == ("/mnt/music", "/data/music")

    def test_music_reports_missing_library_section(self):
        from beets import config

        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(title="Muziek"))
        config["plex"]["library_name"] = "Does Not Exist"
        with pytest.raises(ui.UserError):
            plugin.music()

    def test_music_finds_section(self):
        from beets import config

        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(title="Muziek"))
        config["plex"]["library_name"] = "Muziek"
        assert plugin.music().title == "Muziek"

    def test_unknown_subcommand_raises(self):
        with pytest.raises(ui.UserError):
            self.run_command("plex", "bogus")

    def test_missing_subcommand_raises(self):
        with pytest.raises(ui.UserError):
            self.run_command("plex")

    def test_dispatch_reaches_handler(self, monkeypatch):
        calls = []
        plugin = plex_plugin()
        monkeypatch.setattr(
            plugin,
            "cmd_status",
            lambda lib, opts, args: calls.append(args),
            raising=False,
        )
        self.run_command("plex", "status", "extra")
        assert calls == [["extra"]]

    def test_suspend_stamp_context(self):
        plugin = plex_plugin()
        assert not plugin._suspend_depth
        with plugin.suspend_stamp():
            assert plugin._suspend_depth
        assert not plugin._suspend_depth

    def test_suspend_stamp_nests(self):
        # A nested use must not re-arm stamping when the inner block exits.
        plugin = plex_plugin()
        with plugin.suspend_stamp():
            with plugin.suspend_stamp():
                assert plugin._suspend_depth == 2
            assert plugin._suspend_depth == 1
        assert plugin._suspend_depth == 0

    def test_suspend_stamp_unwinds_on_exception(self):
        plugin = plex_plugin()
        with pytest.raises(RuntimeError), plugin.suspend_stamp():
            raise RuntimeError("boom")
        assert plugin._suspend_depth == 0


class TestStatus(IOMixin, PluginTestHelper):
    plugin = "plex"

    def test_status_reports_counts(self):
        from beets import config

        from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        plugin = plex_plugin()
        plugin._server = FakeServer(
            FakeMusicSection(
                tracks=[
                    FakeTrack(1, ["/plex/A/a.mp3"]),
                    FakeTrack(2, ["/plex/A/b.mp3"]),
                ]
            )
        )
        self.add_item(path=b"/music/A/a.mp3", title="hit")
        self.add_item(path=b"/music/A/b.mp3", title="hit2")
        self.add_item(path=b"/music/B/missing.mp3", title="miss")

        output = self.run_with_output("plex", "status")

        # Asymmetric counts asserted as a whole line, so swapping the two
        # counters in the implementation cannot pass.
        assert "items: 2 matched, 1 unmatched" in output

    def test_status_respects_a_query(self):
        from beets import config

        from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        plugin = plex_plugin()
        plugin._server = FakeServer(
            FakeMusicSection(tracks=[FakeTrack(1, ["/plex/A/a.mp3"])])
        )
        self.add_item(path=b"/music/A/a.mp3", title="keepme")
        self.add_item(path=b"/music/B/missing.mp3", title="zzz")

        output = self.run_with_output("plex", "status", "title:keepme")

        assert "items: 1 matched, 0 unmatched" in output


class TestServerConnection(PluginTestHelper):
    plugin = "plex"

    def test_builds_the_configured_url_and_passes_the_token(self, monkeypatch):
        import plexapi.server
        from beets import config

        config["plex"]["host"] = "nas.local"
        config["plex"]["port"] = 32500
        config["plex"]["secure"] = True
        config["plex"]["token"] = "sekrit"
        seen = {}

        class Recorder:
            def __init__(self, baseurl, token):
                seen["baseurl"] = baseurl
                seen["token"] = token

        monkeypatch.setattr(plexapi.server, "PlexServer", Recorder)
        plugin = plex_plugin()
        plugin._server = None
        plugin.server()

        assert seen == {"baseurl": "https://nas.local:32500", "token": "sekrit"}

    def test_connection_failure_becomes_a_clean_user_error(self, monkeypatch):
        import plexapi.server

        def boom(baseurl, token):
            raise OSError("refused")

        monkeypatch.setattr(plexapi.server, "PlexServer", boom)
        plugin = plex_plugin()
        plugin._server = None

        with pytest.raises(ui.UserError):
            plugin.server()

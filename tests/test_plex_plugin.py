import pytest
from beets import plugins as plugin_registry
from beets import ui
from beets.test.helper import PluginTestHelper

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
        assert plugin._suspend_rating_stamp is False
        with plugin.suspend_stamp():
            assert plugin._suspend_rating_stamp is True
        assert plugin._suspend_rating_stamp is False

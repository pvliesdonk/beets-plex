import pytest
from beets import plugins as plugin_registry
from beets import ui
from beets.test.helper import PluginTestHelper

from beetsplug.plex import scan
from tests.fakeplex import FakeMusicSection, FakeServer
from tests.test_plex_plugin import plex_plugin


class ScanBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection())
        return plugin


class TestAutoScan(ScanBase):
    def test_import_and_remove_events_collect_directories(self):
        plugin = self.setup_plex()
        item = self.add_item(path=b"/music/A/a.mp3")
        plugin_registry.send("item_imported", lib=self.lib, item=item)
        plugin_registry.send("item_removed", item=item)
        assert plugin._scan_dirs == {"/plex/A"}

    def test_album_import_collects_directories(self):
        # beets dispatches album_imported (not item_imported) for album
        # imports, which is the dominant import workflow.
        plugin = self.setup_plex()
        items = [
            self.add_item(path=b"/music/Album/01.mp3", album="A"),
            self.add_item(path=b"/music/Album/02.mp3", album="A"),
        ]
        album = self.lib.add_album(items)
        plugin._scan_dirs.clear()

        plugin_registry.send("album_imported", lib=self.lib, album=album)

        assert plugin._scan_dirs == {"/plex/Album"}

    def test_move_collects_both_directories(self):
        plugin = self.setup_plex()
        item = self.add_item(path=b"/music/B/b.mp3")
        plugin_registry.send(
            "item_moved",
            item=item,
            source=b"/music/A/b.mp3",
            destination=b"/music/B/b.mp3",
        )
        assert plugin._scan_dirs == {"/plex/A", "/plex/B"}

    def test_flush_scans_each_directory(self):
        plugin = self.setup_plex()
        plugin._scan_dirs = {"/plex/A", "/plex/B"}
        scan.flush(plugin)
        section = plugin._server._section
        assert sorted(section.update_calls) == ["/plex/A", "/plex/B"]
        assert plugin._scan_dirs == set()

    def test_flush_twice_scans_only_once(self):
        # cli_exit can fire after an explicit flush; the queue is consumed,
        # so the second call must not re-scan.
        plugin = self.setup_plex()
        plugin._scan_dirs = {"/plex/A"}
        scan.flush(plugin)
        scan.flush(plugin)
        assert plugin._server._section.update_calls == ["/plex/A"]

    def test_one_failing_directory_does_not_cancel_the_rest(self):
        plugin = self.setup_plex()
        section = plugin._server._section
        real_update = section.update

        def flaky(path=None):
            if path == "/plex/B":
                raise RuntimeError("boom")
            real_update(path=path)

        section.update = flaky
        plugin._scan_dirs = {"/plex/A", "/plex/B", "/plex/C"}

        scan.flush(plugin)

        assert sorted(section.update_calls) == ["/plex/A", "/plex/C"]

    def test_flush_falls_back_to_full_scan_over_threshold(self):
        plugin = self.setup_plex()
        plugin._scan_dirs = {f"/plex/dir{i}" for i in range(25)}
        scan.flush(plugin)
        assert plugin._server._section.update_calls == [None]

    def test_flush_respects_auto_scan_off(self):
        from beets import config

        plugin = self.setup_plex()
        config["plex"]["auto_scan"] = False
        plugin._scan_dirs = {"/plex/A"}
        scan.flush(plugin)
        assert plugin._server._section.update_calls == []

    def test_flush_survives_malformed_auto_scan_config(self):
        # flush() runs from cli_exit, which beets does not guard, so a bad
        # config value must not traceback out of every beets command.
        from beets import config

        plugin = self.setup_plex()
        config["plex"]["auto_scan"] = "maybe"
        plugin._scan_dirs = {"/plex/A"}
        scan.flush(plugin)  # must not raise
        assert plugin._server._section.update_calls == []

    def test_flush_swallows_connection_errors(self):
        from beets import config

        plugin = self.setup_plex()
        plugin._server = None  # forces a real (failing) connection attempt
        config["plex"]["port"] = 1  # nothing listens here
        plugin._scan_dirs = {"/plex/A"}
        scan.flush(plugin)  # must not raise


class TestScanCommand(ScanBase):
    def test_full_scan(self):
        plugin = self.setup_plex()
        self.run_command("plex", "scan", "--full")
        assert plugin._server._section.update_calls == [None]

    def test_path_scan_translates(self):
        plugin = self.setup_plex()
        self.run_command("plex", "scan", "/music/A")
        assert plugin._server._section.update_calls == ["/plex/A"]

    def test_pretend_scans_nothing(self):
        plugin = self.setup_plex()
        self.run_command("plex", "scan", "--pretend", "/music/A")
        assert plugin._server._section.update_calls == []

    def test_pretend_full_scans_nothing(self):
        plugin = self.setup_plex()
        self.run_command("plex", "scan", "--pretend", "--full")
        assert plugin._server._section.update_calls == []

    def test_path_outside_library_errors(self):
        self.setup_plex()
        with pytest.raises(ui.UserError):
            self.run_command("plex", "scan", "/elsewhere/A")

    def test_no_args_without_full_errors(self):
        self.setup_plex()
        with pytest.raises(ui.UserError):
            self.run_command("plex", "scan")

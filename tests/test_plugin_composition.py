"""The two plugins are independent but must compose.

`plex` only ever writes the `rating` database field and asks beets to write
tags; `ratingtag` supplies the tag format. Neither imports the other, so
nothing but a test pins the contract that enabling both makes a rating
pulled from Plex land in the file.
"""

import shutil
from pathlib import Path

import pytest
from beets.library import Item
from beets.test.helper import PluginMixin, TestHelper

from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack

RSRC = Path(__file__).parent / "rsrc"


class TestBothPlugins(PluginMixin, TestHelper):
    preload_plugin = False

    @pytest.fixture(autouse=True)
    def _both_plugins(self, tmp_path):
        self.music_dir = tmp_path / "music"
        self.music_dir.mkdir()
        self.load_plugins("plex", "ratingtag")
        yield
        self.unload_plugins()

    def _plugin(self, name):
        from beets import plugins as plugin_registry

        return next(p for p in plugin_registry.find_plugins() if p.name == name)

    def _setup(self, tracks):
        from beets import config

        config["plex"]["beets_dir"] = str(self.music_dir)
        config["plex"]["plex_dir"] = "/plex"
        plugin = self._plugin("plex")
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin

    def _add(self, relpath, **values):
        dst = self.music_dir / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RSRC / "full.flac", dst)
        return self.add_item(path=str(dst).encode(), **values)

    def test_rating_pulled_from_plex_reaches_the_file(self):
        track = FakeTrack(7, ["/plex/A/a.flac"], userRating=9.0)
        self._setup([track])
        item = self._add("A/a.flac")

        self.run_command("plex", "sync")

        # Read the file back through a fresh Item: the tag, not the DB.
        assert Item.from_path(item.path)["rating"] == 9.0

    def test_rating_cleared_in_plex_clears_the_file_tag(self):
        track = FakeTrack(7, ["/plex/A/a.flac"], userRating=None)
        self._setup([track])
        item = self._add("A/a.flac", rating=8.0, plex_userrating=8.0)
        item.write()
        assert Item.from_path(item.path)["rating"] == 8.0

        self.run_command("plex", "sync")

        assert not Item.from_path(item.path).get("rating")

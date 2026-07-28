import shutil
from datetime import datetime
from pathlib import Path

import pytest
from beets.test.helper import PluginTestHelper
from plexapi.exceptions import BadRequest

from beetsplug.plex import sync
from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack
from tests.test_plex_plugin import plex_plugin

RSRC = Path(__file__).parent / "rsrc"


class _Opts:
    """Stand-in for the optparse values object, all flags off."""

    pretend = False
    pull = False
    push = False


class SyncBase(PluginTestHelper):
    plugin = "plex"

    @pytest.fixture(autouse=True)
    def _music_dir(self, tmp_path):
        """Give items real files: a pull writes tags before storing."""
        self.music_dir = tmp_path / "music"
        self.music_dir.mkdir()

    def setup_plex(self, tracks):
        from beets import config

        config["plex"]["beets_dir"] = str(self.music_dir)
        config["plex"]["plex_dir"] = "/plex"
        config["plex"]["library_name"] = "Music"
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin

    def add_track_item(self, relpath, **values):
        dst = self.music_dir / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RSRC / "full.mp3", dst)
        return self.add_item(path=str(dst).encode(), **values)


class TestSyncCommand(SyncBase):
    def test_pull_updates_rating_and_mirrors(self):
        track = FakeTrack(
            7,
            ["/plex/A/a.mp3"],
            userRating=9.0,
            lastRatedAt=datetime(2026, 1, 2),
            viewCount=4,
            skipCount=1,
            lastViewedAt=datetime(2026, 1, 3),
        )
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync")

        item.load()
        assert item["rating"] == 9.0
        assert item["plex_userrating"] == 9.0
        assert item["plex_ratingkey"] == 7
        assert item["plex_guid"] == "plex://track/7"
        assert item["plex_viewcount"] == 4
        assert item["plex_skipcount"] == 1
        # Each timestamp must come from its own source field, not the other.
        assert item["plex_lastratedat"] == datetime(2026, 1, 2).timestamp()
        assert item["plex_lastviewedat"] == datetime(2026, 1, 3).timestamp()
        assert item["plex_updated"] > 0
        assert track.rate_calls == []

    def test_pull_does_not_advance_base_when_the_tag_write_fails(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        plugin = self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")
        # An unwritable file: the rating cannot reach the tag, so the sync
        # base must stay put or the next run would consider it done.
        Path(item.path.decode()).unlink()

        counts = sync.run(plugin, self.lib, _Opts(), [])

        assert counts["failed"] == 1
        assert counts["pulled"] == 0
        item.load()
        assert not item.get("plex_userrating")

    def test_push_flag_skips_pulls(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync", "--push")

        item.load()
        # A pull must not happen, so neither the rating nor the base moves.
        assert not item.get("rating")
        assert not item.get("plex_userrating")

    def test_restricted_direction_is_counted_as_deferred(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)
        plugin = self.setup_plex([track])
        self.add_track_item("A/a.mp3", rating=8.0)

        opts = _Opts()
        opts.pull = True
        counts = sync.run(plugin, self.lib, opts, [])

        assert counts["deferred"] == 1
        assert counts["pushed"] == 0

    def test_pretend_does_not_write_mirrors_on_the_unchanged_branch(self):
        # Nothing to do, but --pretend must still not touch the database.
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=8.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0, plex_userrating=8.0)

        self.run_command("plex", "sync", "--pretend")

        item.load()
        assert not item.get("plex_updated")
        assert not item.get("plex_ratingkey")

    def test_pull_stamp_guard_is_active_at_write_time(self):
        # Pins the suspend_stamp guard itself rather than statement order:
        # if the guard were removed, a pulled rating would stamp
        # rating_updated and win the next conflict against Plex.
        from beets import plugins as plugin_registry

        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        plugin = self.setup_plex([track])
        self.add_track_item("A/a.mp3")

        seen = []
        plugin_registry.BeetsPlugin.listeners.setdefault("write", []).append(
            lambda **kw: seen.append(plugin._suspend_rating_stamp)
        )

        self.run_command("plex", "sync")

        assert seen == [True]

    def test_push_rates_track(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0)

        self.run_command("plex", "sync")

        assert track.rate_calls == [8.0]
        item.load()
        assert item["plex_userrating"] == 8.0

    def test_push_clear_sends_none(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=6.0)
        self.setup_plex([track])
        self.add_track_item("A/a.mp3", rating=0.0, plex_userrating=6.0)

        self.run_command("plex", "sync")

        assert track.rate_calls == [None]

    def test_unmatched_item_is_skipped(self):
        self.setup_plex([])
        item = self.add_track_item("A/missing.mp3", rating=8.0)
        self.run_command("plex", "sync")
        item.load()
        assert not item.get("plex_updated")

    def test_pretend_changes_nothing(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync", "--pretend")

        item.load()
        assert not item.get("rating")
        assert not item.get("plex_updated")
        assert track.rate_calls == []

    def test_pull_flag_skips_pushes(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0)

        self.run_command("plex", "sync", "--pull")

        assert track.rate_calls == []
        item.load()
        # The pending push must survive for a later unrestricted run.
        assert not item.get("plex_userrating")

    def test_push_failure_leaves_base_untouched(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)

        def broken_rate(value):
            raise BadRequest("boom")

        track.rate = broken_rate
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0)

        self.run_command("plex", "sync")

        item.load()
        assert not item.get("plex_userrating")  # retried next run

    def test_push_failure_is_not_counted_as_pushed(self):
        # The summary must not claim a push that never reached the server.
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)

        def broken_rate(value):
            raise BadRequest("boom")

        track.rate = broken_rate
        plugin = self.setup_plex([track])
        self.add_track_item("A/a.mp3", rating=8.0)

        counts = sync.run(plugin, self.lib, _Opts(), [])

        assert counts["pushed"] == 0
        assert counts["failed"] == 1

    def test_successful_push_is_counted(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)
        plugin = self.setup_plex([track])
        self.add_track_item("A/a.mp3", rating=8.0)

        counts = sync.run(plugin, self.lib, _Opts(), [])

        assert counts["pushed"] == 1
        assert counts["failed"] == 0

    def test_pull_does_not_stamp_rating_updated(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync")

        item.load()
        assert not item.get("rating_updated")

    def test_query_restricts_scope(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"], userRating=9.0)
        b = FakeTrack(2, ["/plex/B/b.mp3"], userRating=9.0)
        self.setup_plex([a, b])
        item_a = self.add_track_item("A/a.mp3", title="aaa")
        item_b = self.add_track_item("B/b.mp3", title="bbb")

        self.run_command("plex", "sync", "title:aaa")

        item_a.load()
        item_b.load()
        assert item_a["rating"] == 9.0
        assert not item_b.get("rating")

import pytest
from beets import ui
from beets.test.helper import PluginTestHelper

from tests.fakeplex import (
    FakeCollection,
    FakeMusicSection,
    FakeServer,
    FakeTrack,
)
from tests.test_plex_plugin import plex_plugin


class CollectionBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self, tracks, collections_config):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        config["plex"]["collections"] = collections_config
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin

    def section(self, plugin):
        return plugin._server._section


class TestCollections(CollectionBase):
    def test_creates_collection(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        cols = self.section(plugin).collections()
        assert len(cols) == 1
        assert [t.ratingKey for t in cols[0].items()] == [1]

    def test_diffs_existing_collection(self):
        keep = FakeTrack(1, ["/plex/A/a.mp3"])
        add = FakeTrack(2, ["/plex/B/b.mp3"])
        drop = FakeTrack(3, ["/plex/C/c.mp3"])
        plugin = self.setup_plex(
            [keep, add, drop], [{"name": "Top2000", "query": "title:keepme"}]
        )
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [keep, drop])
        section._collections.append(existing)
        # `title:keepme` is a substring query, so the excluded item's title
        # must not contain it as a substring.
        self.add_item(path=b"/music/A/a.mp3", title="keepme")
        self.add_item(path=b"/music/B/b.mp3", title="keepme")
        self.add_item(path=b"/music/C/c.mp3", title="zzz")

        self.run_command("plex", "collections")

        assert existing.added == [[add]]
        assert existing.removed == [[drop]]
        assert {t.ratingKey for t in existing.items()} == {1, 2}

    def test_unchanged_collection_makes_no_calls(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [a])
        section._collections.append(existing)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        assert existing.added == []
        assert existing.removed == []

    def test_empty_query_leaves_the_collection_alone_by_default(self):
        plugin = self.setup_plex([], [{"name": "Top2000", "query": "title:none"}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        section._collections.append(existing)

        self.run_command("plex", "collections")

        assert section.collections() == [existing]

    def test_empty_query_deletes_collection_when_pruning(self):
        from beets import config

        plugin = self.setup_plex([], [{"name": "Top2000", "query": "title:none"}])
        config["plex"]["prune"] = True
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        section._collections.append(existing)

        self.run_command("plex", "collections")

        assert section.collections() == []

    def test_empty_query_leaves_duplicates_alone_without_prune(self):
        # The duplicate collapse must not run ahead of the prune guard, or
        # a typo'd query still destroys collections while the log claims
        # nothing was touched.
        plugin = self.setup_plex([], [{"name": "Top2000", "query": "title:none"}])
        section = self.section(plugin)
        first = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        second = FakeCollection(section, "Top2000", [FakeTrack(8, ["/y"])])
        section._collections.extend([first, second])

        self.run_command("plex", "collections")

        assert section.collections() == [first, second]

    def test_one_failing_entry_does_not_cancel_the_others(self):
        # A refused resolve is far likelier than a server fault, so it must
        # not abort the entries queued behind it either.
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [
                {"name": "Bad", "query": "title:orphan"},
                {"name": "Good", "query": "title:t"},
            ],
        )
        # Matches the query but is not in Plex, so resolve refuses.
        self.add_item(path=b"/music/C/orphan.mp3", title="orphan")
        self.add_item(path=b"/music/A/a.mp3", title="t")

        with pytest.raises(ui.UserError):
            self.run_command("plex", "collections")

        assert [c.title for c in self.section(plugin).collections()] == ["Good"]

    def test_malformed_query_does_not_cancel_the_others(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [
                {"name": "Bad", "query": "'unterminated"},
                {"name": "Good", "query": "title:t"},
            ],
        )
        self.add_item(path=b"/music/A/a.mp3", title="t")

        with pytest.raises(ui.UserError):
            self.run_command("plex", "collections")

        assert [c.title for c in self.section(plugin).collections()] == ["Good"]

    def test_duplicate_collection_titles_are_collapsed(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        section = self.section(plugin)
        keep = FakeCollection(section, "Top2000", [a])
        dupe = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        section._collections.extend([keep, dupe])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        assert section.collections() == [keep]

    def test_smart_and_foreign_subtype_are_skipped(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [{"name": "Smart", "query": ""}, {"name": "Albums", "query": ""}],
        )
        section = self.section(plugin)
        smart = FakeCollection(section, "Smart", [], smart=True)
        albums = FakeCollection(section, "Albums", [], subtype="album")
        section._collections.extend([smart, albums])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        assert smart.added == [] and albums.added == []
        assert len(section.collections()) == 2  # nothing new, nothing deleted

    def test_pretend_changes_nothing(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections", "--pretend")

        assert self.section(plugin).collections() == []

    def test_pretend_does_not_delete_on_empty_query(self):
        plugin = self.setup_plex([], [{"name": "Top2000", "query": "title:none"}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        section._collections.append(existing)

        self.run_command("plex", "collections", "--pretend")

        assert section.collections() == [existing]

    def test_pretend_does_not_diff_an_existing_collection(self):
        keep = FakeTrack(1, ["/plex/A/a.mp3"])
        add = FakeTrack(2, ["/plex/B/b.mp3"])
        plugin = self.setup_plex([keep, add], [{"name": "Top2000", "query": ""}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [keep])
        section._collections.append(existing)
        self.add_item(path=b"/music/A/a.mp3", title="t")
        self.add_item(path=b"/music/B/b.mp3", title="t")

        self.run_command("plex", "collections", "--pretend")

        assert existing.added == []
        assert existing.removed == []

    def test_total_match_failure_does_not_delete_the_collection(self):
        # A misconfigured plex_dir makes every item unresolvable; that must
        # not look like "the query matched nothing" and delete the object.
        plugin = self.setup_plex([], [{"name": "Top2000", "query": ""}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        section._collections.append(existing)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        with pytest.raises(ui.UserError):
            self.run_command("plex", "collections")

        assert section.collections() == [existing]

    def test_entry_without_a_name_is_rejected(self):
        self.setup_plex([], [{"query": "title:t"}])

        with pytest.raises(ui.UserError):
            self.run_command("plex", "collections")

    def test_unknown_name_error_says_collection_not_playlist(self):
        self.setup_plex([], [{"name": "Top2000", "query": ""}])

        with pytest.raises(ui.UserError) as excinfo:
            self.run_command("plex", "collections", "Nope")

        assert "collection(s)" in str(excinfo.value)
        assert "playlist" not in str(excinfo.value)

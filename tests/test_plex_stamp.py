from beets.test.helper import PluginTestHelper

from tests.test_plex_plugin import plex_plugin


class TestRatingStamp(PluginTestHelper):
    plugin = "plex"

    def test_dirty_rating_is_stamped_on_write(self):
        item = self.add_item(title="x")
        item["rating"] = 8.0  # marks the field dirty
        plex_plugin().on_write(item, item.path, {})
        assert item["rating_updated"] > 0

    def test_clean_item_is_not_stamped(self):
        item = self.add_item(title="x")
        item["rating"] = 8.0
        item.store()  # clears the dirty set
        plex_plugin().on_write(item, item.path, {})
        assert not item.get("rating_updated")

    def test_guard_suppresses_stamping(self):
        plugin = plex_plugin()
        item = self.add_item(title="x")
        item["rating"] = 8.0
        with plugin.suspend_stamp():
            plugin.on_write(item, item.path, {})
        assert not item.get("rating_updated")

    def test_stamp_flows_through_the_write_event(self):
        # End to end: the event dispatched by beets reaches the handler.
        from beets import plugins as plugin_registry

        item = self.add_item(title="x")
        item["rating"] = 8.0
        plugin_registry.send("write", item=item, path=item.path, tags={})
        assert item["rating_updated"] > 0

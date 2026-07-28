import shutil
from pathlib import Path

import pytest
from beets.library import Item
from beets.test.helper import PluginTestHelper

RSRC = Path(__file__).parent / "rsrc"


class TestRatingTagPlugin(PluginTestHelper):
    plugin = "ratingtag"

    def _item_with_file(self, ext, tmp_path):
        dst = tmp_path / f"track.{ext}"
        shutil.copyfile(RSRC / f"full.{ext}", dst)
        item = Item.from_path(bytes(dst))
        item.add(self.lib)
        return item, dst

    @pytest.mark.parametrize("ext", ["mp3", "flac", "m4a", "opus"])
    def test_write_read_roundtrip_through_beets(self, tmp_path, ext):
        item, dst = self._item_with_file(ext, tmp_path)
        item["rating"] = 7.0
        item.write()

        fresh = Item.from_path(bytes(dst))
        assert fresh["rating"] == 7.0

    def test_unrated_file_reads_as_unrated(self, tmp_path):
        item, dst = self._item_with_file("flac", tmp_path)
        fresh = Item.from_path(bytes(dst))
        assert not fresh.get("rating")

    def test_clearing_rating_clears_tag(self, tmp_path):
        item, dst = self._item_with_file("flac", tmp_path)
        item["rating"] = 7.0
        item.write()
        item["rating"] = 0.0
        item.write()
        fresh = Item.from_path(bytes(dst))
        assert not fresh.get("rating")

    def test_rating_is_a_typed_float_field(self):
        item = self.add_item(title="x")
        item["rating"] = 8.0
        item.store()
        results = self.lib.items("rating:7..9")
        assert [i.title for i in results] == ["x"]

    def test_format_without_rating_style_writes_safely(self, tmp_path):
        # ASF/WMA has no rating storage style; write() must succeed and
        # simply not store a rating tag.
        item, dst = self._item_with_file("wma", tmp_path)
        item["rating"] = 7.0
        item.write()
        fresh = Item.from_path(bytes(dst))
        assert not fresh.get("rating")

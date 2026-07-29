"""ratingtag: round-trip ratings through real files and check the contract edges.

The rating media field is registered once for the session with a fixed POPM
email; tests operate on temp copies of the committed fixtures.
"""

from __future__ import annotations

import shutil

import mediafile
import pytest
from beets.dbcore import types

from beetsplug import ratingtag

POPM_EMAIL = "beets-plex@test"


@pytest.fixture(scope="session", autouse=True)
def _register_rating_field():
    field = ratingtag.rating_media_field(popm_email_getter=lambda: POPM_EMAIL)
    try:
        mediafile.MediaFile.add_field("rating", field)
    except ValueError:
        pass  # already registered by an earlier run in the same process


def _copy(rsrc_dir, tmp_path, name):
    dst = tmp_path / name
    shutil.copy(rsrc_dir / name, dst)
    return str(dst)


@pytest.mark.parametrize(
    "name, value, expected",
    [
        ("full.mp3", 7.7, 7.7),  # POPM (ID3), linear 0-255
        ("full.aiff", 5.0, 5.0),  # POPM via ID3 on a non-MP3 container
        ("full.flac", 7.0, 7.0),  # Vorbis RATING, 0-100
        ("full.m4a", 6.0, 6.0),  # MP4 iTunes freeform
    ],
)
def test_round_trip(rsrc_dir, tmp_path, name, value, expected):
    path = _copy(rsrc_dir, tmp_path, name)
    media = mediafile.MediaFile(path)
    media.rating = value
    media.save()
    assert mediafile.MediaFile(path).rating == expected


def test_popm_byte_one_reads_as_rated_not_unrated(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.mp3")
    raw = mediafile.mutagen.File(path)
    raw.tags.add(mediafile.mutagen.id3.POPM(email=POPM_EMAIL, rating=1, count=0))
    raw.save()
    # A byte of 1 (Windows Media Player one star) must not collapse to the
    # unrated sentinel 0.0...
    assert mediafile.MediaFile(path).rating == 0.1
    # ...and writing the read-back value must not delete the frame.
    media = mediafile.MediaFile(path)
    media.rating = media.rating
    media.save()
    assert "POPM:" + POPM_EMAIL in mediafile.mutagen.File(path).tags


def test_popm_tiny_rating_is_not_lost(rsrc_dir, tmp_path):
    # A sub-0.02 rating must not serialize to byte 0 (the unrated sentinel) and
    # then be deleted; it floors to byte 1 and reads back as 0.1.
    path = _copy(rsrc_dir, tmp_path, "full.mp3")
    media = mediafile.MediaFile(path)
    media.rating = 0.01
    media.save()
    assert mediafile.MediaFile(path).rating == 0.1


def test_vorbis_below_one_clamps_to_one_not_inflated(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.flac")
    media = mediafile.MediaFile(path)
    media.rating = 0.5
    media.save()
    # 0.5 cannot be written below 1.0 without landing in the legacy 1-5 star
    # range the reader doubles; it clamps to 1.0 rather than inflating to 10.0.
    assert mediafile.MediaFile(path).rating == 1.0


def test_unrated_removes_the_tag(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.mp3")
    media = mediafile.MediaFile(path)
    media.rating = 8.0
    media.save()
    assert mediafile.MediaFile(path).rating == 8.0
    media = mediafile.MediaFile(path)
    media.rating = 0.0
    media.save()
    reread = mediafile.MediaFile(path)
    assert reread.rating is None
    assert "POPM:" + POPM_EMAIL not in reread.mgfile.tags


def test_no_tag_reads_as_none(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.flac")
    assert mediafile.MediaFile(path).rating is None


def test_flac_legacy_0_to_5_read_as_stars(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.flac")
    raw = mediafile.mutagen.File(path)
    raw["RATING"] = "4"  # a 0-5 star value written by another tagger
    raw.save()
    assert mediafile.MediaFile(path).rating == 8.0


def test_flac_out_of_range_and_non_numeric_ignored(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.flac")
    raw = mediafile.mutagen.File(path)
    for bad in ("150", "-5", "abc"):
        raw["RATING"] = bad
        raw.save()
        assert mediafile.MediaFile(path).rating is None


def test_popm_preserves_count_and_other_frames(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.mp3")
    raw = mediafile.mutagen.File(path)
    raw.tags.add(mediafile.mutagen.id3.POPM(email=POPM_EMAIL, rating=10, count=42))
    raw.tags.add(mediafile.mutagen.id3.POPM(email="other@x", rating=200, count=7))
    raw.save()

    media = mediafile.MediaFile(path)
    media.rating = 6.0
    media.save()

    raw = mediafile.mutagen.File(path)
    ours = raw.tags.get("POPM:" + POPM_EMAIL)
    other = raw.tags.get("POPM:other@x")
    assert ours.count == 42  # our frame's count is preserved
    assert other.rating == 200 and other.count == 7  # other frame untouched


def test_tagless_container_stores_nothing(rsrc_dir, tmp_path):
    path = _copy(rsrc_dir, tmp_path, "full.wma")
    media = mediafile.MediaFile(path)
    media.rating = 6.0
    media.save()  # no matching style for ASF — a no-op, not an error
    assert mediafile.MediaFile(path).rating is None


def test_popm_store_creates_tags_when_absent(rsrc_dir, tmp_path):
    # store() is normally reached through mediafile's save (which creates the ID3
    # container first), but it guards `tags is None` like fetch/delete so a direct
    # write to a container with no tags does not crash.
    path = _copy(rsrc_dir, tmp_path, "full.aiff")
    raw = mediafile.mutagen.File(path)
    raw.delete()
    raw.save()
    raw = mediafile.mutagen.File(path)
    assert raw.tags is None
    style = ratingtag.PopmStorageStyle(lambda: POPM_EMAIL)
    style.store(raw, style.serialize(6.0))
    raw.save()
    assert mediafile.MediaFile(path).rating == 6.0


def test_plugin_declares_rating_as_float():
    assert ratingtag.RatingTagPlugin.item_types == {"rating": types.FLOAT}


def test_configured_popm_email_reads_config():
    import beets

    beets.config["ratingtag"]["popm_email"].set("real@example.com")
    assert ratingtag._configured_popm_email() == "real@example.com"


def test_plugin_registration_tolerates_reregistration():
    # `rating` is already registered (session fixture); the plugin registers it
    # too and must tolerate the existing registration rather than raise.
    ratingtag.RatingTagPlugin()
    ratingtag.RatingTagPlugin()


@pytest.mark.parametrize(
    "value, disk_byte",
    [(10.0, 255), (5.0, 128), (0.1, 3)],
)
def test_popm_serialize_scale(value, disk_byte):
    assert ratingtag.PopmStorageStyle(lambda: POPM_EMAIL).serialize(value) == disk_byte


def test_vorbis_serialize_is_0_to_100():
    assert ratingtag.VorbisRatingStorageStyle().serialize(7.0) == "70"

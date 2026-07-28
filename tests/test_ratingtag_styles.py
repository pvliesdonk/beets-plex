import mutagen
import pytest

from beetsplug.ratingtag import (
    MP4RatingStorageStyle,
    VorbisRatingStorageStyle,
)


@pytest.mark.parametrize("ext", ["flac", "opus"])
def test_vorbis_write_read_roundtrip(media_path, ext):
    path = media_path(ext)
    style = VorbisRatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 8.0)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 8.0
    assert f2["RATING"] == ["80"]


def test_vorbis_legacy_value_read(media_path):
    path = media_path("flac")
    f = mutagen.File(path)
    f["RATING"] = ["4"]  # legacy 0-5 stars
    f.save()
    assert VorbisRatingStorageStyle().get(mutagen.File(path)) == 8.0


def test_vorbis_unrated_write_removes_tag(media_path):
    path = media_path("flac")
    style = VorbisRatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 6.0)
    style.set(f, 0.0)
    f.save()
    f2 = mutagen.File(path)
    assert "RATING" not in f2
    assert style.get(f2) is None


@pytest.mark.parametrize("ext", ["flac", "opus"])
def test_vorbis_unrated_write_on_untagged_file_is_a_noop(media_path, ext):
    # item.write() on an unrated item deletes a tag that was never there.
    path = media_path(ext)
    style = VorbisRatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 0.0)
    f.save()
    assert style.get(mutagen.File(path)) is None


def test_mp4_write_read_roundtrip(media_path):
    path = media_path("m4a")
    style = MP4RatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 7.5)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 7.5


def test_mp4_unrated_write_removes_tag(media_path):
    path = media_path("m4a")
    style = MP4RatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 7.5)
    style.set(f, 0.0)
    f.save()
    assert style.get(mutagen.File(path)) is None

import mutagen
import mutagen.id3
import pytest

from beetsplug.ratingtag import (
    MP4RatingStorageStyle,
    PopmRatingStorageStyle,
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


def strip_id3(path):
    """Remove the ID3 tag entirely, so mutagen reports tags as None.

    The ffmpeg-generated fixture carries a TSSE encoder frame; real
    libraries contain both tagged and completely untagged MP3s, and the
    two take different branches in PopmRatingStorageStyle.
    """
    mutagen.id3.delete(path)


def test_popm_write_read_roundtrip_on_tagged_file(media_path):
    path = media_path("mp3")
    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    assert f.tags is not None  # fixture has an encoder frame
    style.set(f, 8.0)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 8.0
    assert f2.tags.getall("POPM")[0].rating == 204


def test_popm_write_read_roundtrip_on_tagless_file(media_path):
    # A file with no ID3 tag at all; set() must create one.
    path = media_path("mp3")
    strip_id3(path)
    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    assert f.tags is None
    style.set(f, 8.0)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 8.0
    assert f2.tags.getall("POPM")[0].rating == 204


def test_popm_foreign_email_frames_are_ignored_and_preserved(media_path):
    path = media_path("mp3")
    f = mutagen.File(path)
    f.tags.add(mutagen.id3.POPM(email="other@player", rating=100))
    f.save()

    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    assert style.get(f) is None  # only our email counts
    style.set(f, 5.0)
    f.save()

    f2 = mutagen.File(path)
    frames = {frame.email: frame.rating for frame in f2.tags.getall("POPM")}
    assert frames["other@player"] == 100
    assert frames["beets@example.com"] == 128


def test_popm_zero_rating_reads_as_unrated(media_path):
    path = media_path("mp3")
    f = mutagen.File(path)
    f.tags.add(mutagen.id3.POPM(email="beets@example.com", rating=0))
    f.save()
    assert PopmRatingStorageStyle("beets@example.com").get(mutagen.File(path)) is None


def test_popm_unrated_write_removes_only_our_frame(media_path):
    path = media_path("mp3")
    f = mutagen.File(path)
    f.tags.add(mutagen.id3.POPM(email="other@player", rating=100))
    f.tags.add(mutagen.id3.POPM(email="beets@example.com", rating=200))
    f.save()

    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    style.set(f, 0.0)
    f.save()

    f2 = mutagen.File(path)
    emails = [frame.email for frame in f2.tags.getall("POPM")]
    assert emails == ["other@player"]


def test_popm_unrated_write_on_tagless_file_is_a_noop(media_path):
    path = media_path("mp3")
    strip_id3(path)
    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    assert f.tags is None
    style.set(f, 0.0)  # must not raise on a file with no ID3 tag
    assert style.get(f) is None


def test_popm_empty_email_config(media_path):
    path = media_path("mp3")
    style = PopmRatingStorageStyle("")
    f = mutagen.File(path)
    style.set(f, 9.0)
    f.save()
    assert style.get(mutagen.File(path)) == 9.0

import pytest

from beetsplug.ratingtag import (
    rating_from_popm,
    rating_from_vorbis,
    rating_to_popm,
    rating_to_vorbis,
)


def half_stars():
    return [n / 2.0 for n in range(2, 21)]  # 1.0 .. 10.0


@pytest.mark.parametrize("value", half_stars())
def test_popm_roundtrip_is_exact_for_half_stars(value):
    assert rating_from_popm(rating_to_popm(value)) == value


@pytest.mark.parametrize("value", half_stars())
def test_vorbis_roundtrip_is_exact_for_half_stars(value):
    assert rating_from_vorbis(rating_to_vorbis(value)) == value


def test_popm_zero_and_none_read_as_unrated():
    assert rating_from_popm(0) is None
    assert rating_from_popm(None) is None


def test_popm_full_scale_endpoints():
    assert rating_to_popm(10.0) == 255
    assert rating_from_popm(255) == 10.0


def test_vorbis_legacy_five_star_scale_on_read():
    assert rating_from_vorbis("3") == 6.0
    assert rating_from_vorbis("4.5") == 9.0
    assert rating_from_vorbis("5") == 10.0


def test_vorbis_mediamonkey_scale_on_read():
    assert rating_from_vorbis("45") == 4.5
    assert rating_from_vorbis("100") == 10.0


def test_vorbis_zero_negative_and_junk_read_as_unrated():
    assert rating_from_vorbis("0") is None
    assert rating_from_vorbis("-3") is None
    assert rating_from_vorbis("abc") is None
    assert rating_from_vorbis(None) is None


@pytest.mark.parametrize("value", [n / 10.0 for n in range(1, 101)])
def test_mp4_roundtrip_is_exact_for_every_representable_rating(value):
    # The legacy-avoidance floor belongs to Vorbis only; on MP4 it would
    # promote every rating below 1.0 to 1.0 and break the round trip.
    written = rating_to_vorbis(value, legacy=False)
    assert rating_from_vorbis(written, legacy=False) == value


def test_mp4_scale_has_no_legacy_star_handling():
    # The MP4 atom is 0-100 only; a small value there is a low rating,
    # not a star count (unlike the Vorbis RATING comment).
    assert rating_from_vorbis("4", legacy=False) == 0.4
    assert rating_from_vorbis("5", legacy=False) == 0.5
    assert rating_from_vorbis("80", legacy=False) == 8.0
    assert rating_from_vorbis("0", legacy=False) is None


def test_vorbis_write_clamps_below_one_to_avoid_legacy_range():
    # Written values must never land in 1..5, which reads as star scale.
    assert rating_to_vorbis(0.5) == "10"
    assert rating_from_vorbis(rating_to_vorbis(0.5)) == 1.0

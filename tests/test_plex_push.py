"""plex playlists + collections push: pure diff/order helpers and the commands."""

from __future__ import annotations

from beetsplug.plex import pushing


class _T:
    """A stand-in track carrying just the ratingKey the helpers compare on."""

    def __init__(self, ratingKey):
        self.ratingKey = ratingKey


def test_playlist_matches_is_order_sensitive():
    a, b, c = _T(1), _T(2), _T(3)
    assert pushing.playlist_matches([a, b, c], [a, b, c]) is True
    assert pushing.playlist_matches([a, b, c], [a, c, b]) is False  # order matters
    assert pushing.playlist_matches([a, b], [a, b, c]) is False


def test_collection_diff_is_set_based():
    a, b, c = _T(1), _T(2), _T(3)
    to_add, to_remove = pushing.collection_diff(current=[a, b], desired=[b, c])
    assert [t.ratingKey for t in to_add] == [3]  # c is new
    assert [t.ratingKey for t in to_remove] == [1]  # a is extra


def test_collection_diff_no_change():
    a, b = _T(1), _T(2)
    to_add, to_remove = pushing.collection_diff([a, b], [b, a])  # order irrelevant
    assert to_add == [] and to_remove == []

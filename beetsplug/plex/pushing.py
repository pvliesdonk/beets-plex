"""Pure set/order logic for the playlist and collection push.

Playlists are ordered, so a playlist "matches" only when its tracks equal the
desired tracks in the same order. Collections are unordered sets, so they are
reconciled by a ratingKey set difference. Tracks are compared by ``ratingKey``.
No IO — the plugin performs the Plex calls.
"""

from __future__ import annotations


def playlist_matches(current, desired) -> bool:
    """True if the playlist already holds exactly ``desired`` in the same order."""
    return [t.ratingKey for t in current] == [t.ratingKey for t in desired]


def collection_diff(current, desired):
    """``(to_add, to_remove)`` tracks to reconcile ``current`` to ``desired`` as
    a set, keyed on ``ratingKey`` and preserving each input list's order."""
    current_keys = {t.ratingKey for t in current}
    desired_keys = {t.ratingKey for t in desired}
    to_add = [t for t in desired if t.ratingKey not in current_keys]
    to_remove = [t for t in current if t.ratingKey not in desired_keys]
    return to_add, to_remove

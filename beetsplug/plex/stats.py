"""Map a plexapi track to the beets stat fields it populates.

Pure: no IO and no clock. Counts are always present (a missing count is 0, a
real value); timestamp keys are omitted when Plex has no value, so a
never-played track never gets a misleading 1970 timestamp. ``plex_updated`` is
the plugin's concern (it is the pull time), not this function's.

Timestamps are truncated to whole seconds. beets stores these flexible fields
as SQLite TEXT, which keeps only ~15 significant digits, so a sub-second
``.timestamp()`` would not survive the store/reload round-trip unchanged — the
reloaded value would never equal the freshly computed one, and every pull would
re-store the item. Whole-second epochs round-trip exactly, keeping the pull
idempotent; one-second resolution is ample for a "last played/rated" time.
"""

from __future__ import annotations


def track_stats(track) -> dict:
    result = {
        "plex_viewcount": int(track.viewCount or 0),
        "plex_skipcount": int(track.skipCount or 0),
    }
    if track.lastViewedAt is not None:
        result["plex_lastviewedat"] = int(track.lastViewedAt.timestamp())
    if track.lastRatedAt is not None:
        result["plex_lastratedat"] = int(track.lastRatedAt.timestamp())
    return result

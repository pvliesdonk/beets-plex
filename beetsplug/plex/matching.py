"""Path-based matching between beets items and Plex tracks.

Beets and Plex index the same files on a shared mount, so an item's Plex-side
path is its beets path with the directory prefix rewritten. Matching is exact
and case-sensitive, comparing paths as ``os.path.normpath``'d strings — no
fuzzy matching.
"""

from __future__ import annotations

import os


def _normalize(path: str) -> str:
    """Collapse redundant separators and trailing slashes for comparison."""
    return os.path.normpath(path)


def plex_path(item_path: str, beets_dir: str, plex_dir: str) -> str | None:
    """The Plex-side path for a beets item path, or ``None`` if the item lies
    outside ``beets_dir``.

    The prefix check is inclusive of the library root: ``beets_dir`` itself maps
    to ``plex_dir``.
    """
    item = _normalize(item_path)
    base = _normalize(beets_dir)
    if item != base and not item.startswith(base + os.sep):
        return None
    rel = os.path.relpath(item, base)
    target = plex_dir if rel == os.curdir else os.path.join(plex_dir, rel)
    return _normalize(target)


def build_path_map(tracks) -> dict[str, object]:
    """Map every track file path to its track, from one sweep of the section.

    Every ``media.parts[].file`` location of a track maps to it, so a track with
    several files is found by any of them.
    """
    path_map: dict[str, object] = {}
    for track in tracks:
        for media in track.media:
            for part in media.parts:
                if part.file:
                    path_map[_normalize(part.file)] = track
    return path_map

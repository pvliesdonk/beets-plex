"""Map beets items to Plex tracks by file path."""

import os

from beets import util


def plex_path(item_path, beets_dir, plex_dir):
    """Translate a beets item path to the path the Plex server sees.

    Returns None when the path lies outside beets_dir. The library root
    itself translates to the Plex root, so `beet plex scan <beets_dir>`
    works rather than reporting the root as outside itself.
    """
    path = util.displayable_path(item_path)
    base = beets_dir.rstrip(os.sep)
    target = plex_dir.rstrip(os.sep)
    if path == base:
        return target
    if not path.startswith(base + os.sep):
        return None
    return target + path[len(base) :]


def build_path_map(music, container_size=1000):
    """One paged sweep of the music section: every file location -> track."""
    path_map = {}
    for track in music.searchTracks(container_size=container_size):
        for location in track.locations:
            path_map[location] = track
    return path_map


def resolve(item, path_map, beets_dir, plex_dir):
    """Find the Plex track for a beets item, or None when unmatched.

    The path map is authoritative; cached ratingKeys in the database are
    mirrors for queries, not identities.
    """
    target = plex_path(item.path, beets_dir, plex_dir)
    if target is None:
        return None
    return path_map.get(target)

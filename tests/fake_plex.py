"""Minimal fakes of the plexapi objects the plex plugin touches, plus fakes for
beets' library and items, so matching and status can be tested without a live
server.

Kept no more forgiving than the real API: ``searchTracks`` returns every track
(the real call auto-pages), and ``Library.section`` raises on an unknown name.
"""

from __future__ import annotations


class FakePart:
    def __init__(self, file):
        self.file = file


class FakeMedia:
    def __init__(self, files):
        self.parts = [FakePart(f) for f in files]


class FakeTrack:
    def __init__(
        self,
        ratingKey,
        files,
        viewCount=0,
        skipCount=0,
        lastViewedAt=None,
        lastRatedAt=None,
    ):
        self.ratingKey = ratingKey
        self.media = [FakeMedia(files)]
        self.viewCount = viewCount
        self.skipCount = skipCount
        self.lastViewedAt = lastViewedAt
        self.lastRatedAt = lastRatedAt


class FakeSection:
    def __init__(self, title, tracks):
        self.title = title
        self._tracks = list(tracks)
        self.totalSize = len(self._tracks)

    def searchTracks(self, **kwargs):
        return list(self._tracks)


class FakeLibrary:
    def __init__(self, section):
        self._section = section
        self.section_calls = 0

    def section(self, title):
        self.section_calls += 1
        # plexapi's Library.section normalizes with title.lower().strip(); mirror
        # it so the fake is no stricter than the real API.
        if title.lower().strip() != self._section.title.lower().strip():
            raise NotFoundError(f"Unknown library section {title!r}")
        return self._section


class NotFoundError(Exception):
    pass


class FakeServer:
    def __init__(self, section):
        self.library = FakeLibrary(section)


class FakeItem:
    """Stands in for a beets Item: a byte-string ``path`` and dict-like fields."""

    def __init__(self, path, **fields):
        self.path = path.encode() if isinstance(path, str) else path
        self._fields = dict(fields)
        self.stored = 0

    def __getitem__(self, key):
        return self._fields[key]

    def __setitem__(self, key, value):
        self._fields[key] = value

    def __delitem__(self, key):
        del self._fields[key]

    def get(self, key, default=None):
        return self._fields.get(key, default)

    def store(self):
        self.stored += 1


class FakeLib:
    def __init__(self, items):
        self._items = list(items)
        self.last_query = "unset"

    def items(self, query=None):
        self.last_query = query
        return list(self._items)

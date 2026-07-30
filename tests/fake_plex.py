"""Minimal fakes of the plexapi objects the plex plugin touches, plus fakes for
beets' library and items, so matching and status can be tested without a live
server.

Kept no more forgiving than the real API: ``searchTracks`` returns every track
(the real call auto-pages), and ``Library.section`` raises on an unknown name.
"""

from __future__ import annotations

from plexapi.exceptions import BadRequest


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
        userRating=None,
        rate_raises=False,
    ):
        self.ratingKey = ratingKey
        self.media = [FakeMedia(files)]
        self.viewCount = viewCount
        self.skipCount = skipCount
        self.lastViewedAt = lastViewedAt
        self.lastRatedAt = lastRatedAt
        self.userRating = userRating
        self.rated = []  # records rate() calls
        self._rate_raises = rate_raises  # simulate a Plex write failure

    def rate(self, rating=None):
        # plexapi: rate(None) resets the rating; 0-10 sets it. Real plexapi's
        # rate() only issues a PUT to the server and does NOT update
        # userRating locally, so the fake must not either. A real rate() raises
        # BadRequest (a PlexApiException) on a bad request; rate_raises mirrors
        # that so the narrowed except in sync_ratings is genuinely exercised.
        if self._rate_raises:
            raise BadRequest("simulated Plex rate() failure")
        self.rated.append(rating)


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

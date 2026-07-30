"""Minimal fakes of the plexapi objects the plex plugin touches, plus fakes for
beets' library and items, so matching and status can be tested without a live
server.

Kept no more forgiving than the real API: ``searchTracks`` returns every track
(the real call auto-pages), and ``Library.section`` raises on an unknown name.
"""

from __future__ import annotations

from plexapi.exceptions import BadRequest, NotFound


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


class FakePlaylist:
    def __init__(self, title, items):
        self.title = title
        self._items = list(items)
        self.deleted = False

    def items(self):
        return list(self._items)

    def addItems(self, items):
        self._items.extend(items)

    def removeItems(self, items):
        drop = {t.ratingKey for t in items}
        current = {t.ratingKey for t in self._items}
        missing = drop - current
        if missing:
            raise NotFound(
                f"Cannot remove item(s) with ratingKey {missing} not in playlist"
            )
        self._items = [t for t in self._items if t.ratingKey not in drop]

    def delete(self):
        self.deleted = True


class FakeCollection(FakePlaylist):
    def removeItems(self, items):
        # Unlike Playlist.removeItems, real Collection.removeItems has no
        # existence check — it silently no-ops on an absent ratingKey rather
        # than raising NotFound. Override rather than inherit, so the fake is
        # not stricter than the real API.
        drop = {t.ratingKey for t in items}
        self._items = [t for t in self._items if t.ratingKey not in drop]


class FakeSection:
    def __init__(self, title, tracks):
        self.title = title
        self._tracks = list(tracks)
        self.totalSize = len(self._tracks)
        self._collections = {}

    def searchTracks(self, **kwargs):
        return list(self._tracks)

    def collection(self, title):
        try:
            return self._collections[title]
        except KeyError:
            raise NotFound(f"no collection {title!r}") from None

    def createCollection(self, title, items=None, **kwargs):
        if not items:
            raise BadRequest(
                "Must include items to add when creating new playlist/collection."
            )
        coll = FakeCollection(title, items)
        self._collections[title] = coll
        return coll


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
        self._playlists = {}

    def playlist(self, title):
        try:
            return self._playlists[title]
        except KeyError:
            raise NotFound(f"no playlist {title!r}") from None

    def createPlaylist(self, title, section=None, items=None, **kwargs):
        if not items:
            raise BadRequest(
                "Must include items to add when creating new playlist/collection."
            )
        pl = FakePlaylist(title, items)
        self._playlists[title] = pl
        return pl


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

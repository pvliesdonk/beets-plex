"""In-memory stand-ins for the plexapi objects the plex plugin touches."""

from datetime import datetime

from plexapi.exceptions import NotFound


class FakeTrack:
    def __init__(
        self,
        ratingKey,
        locations,
        title="t",
        userRating=None,
        lastRatedAt=None,
        viewCount=0,
        skipCount=0,
        lastViewedAt=None,
        guid=None,
    ):
        self.ratingKey = ratingKey
        self.locations = list(locations)
        self.title = title
        self.userRating = userRating
        self.lastRatedAt = lastRatedAt
        self.viewCount = viewCount
        self.skipCount = skipCount
        self.lastViewedAt = lastViewedAt
        self.guid = guid or f"plex://track/{ratingKey}"
        self.rate_calls = []

    def rate(self, value):
        self.rate_calls.append(value)
        self.userRating = value
        self.lastRatedAt = datetime.now()


class FakePlaylist:
    def __init__(self, server, title, items, smart=False, playlistType="audio"):
        self._server = server
        self.title = title
        self._items = list(items)
        self.smart = smart
        self.playlistType = playlistType

    def items(self):
        return list(self._items)

    def delete(self):
        self._server._playlists.remove(self)


class FakeCollection:
    def __init__(self, section, title, items, smart=False, subtype="track"):
        self._section = section
        self.title = title
        self._items = list(items)
        self.smart = smart
        self.subtype = subtype
        self.added = []
        self.removed = []

    def items(self):
        return list(self._items)

    def addItems(self, items):
        self.added.append(list(items))
        self._items.extend(items)

    def removeItems(self, items):
        self.removed.append(list(items))
        keys = {t.ratingKey for t in items}
        self._items = [t for t in self._items if t.ratingKey not in keys]

    def delete(self):
        self._section._collections.remove(self)


class FakeMusicSection:
    def __init__(self, tracks=(), title="Music", key=1):
        self.tracks = list(tracks)
        self.title = title
        self.key = key
        self.update_calls = []
        self._collections = []

    def searchTracks(self, container_size=None, **kwargs):
        return list(self.tracks)

    def update(self, path=None):
        self.update_calls.append(path)

    def collections(self):
        return list(self._collections)


class _FakeLibrary:
    def __init__(self, sections):
        self._sections = {s.title: s for s in sections}

    def section(self, name):
        try:
            return self._sections[name]
        except KeyError:
            raise NotFound(name) from None


class FakeServer:
    def __init__(self, section):
        self.library = _FakeLibrary([section])
        self.friendlyName = "fakeplex"
        self._playlists = []
        self._section = section

    def playlists(self, playlistType=None, **kwargs):
        return [
            p
            for p in self._playlists
            if playlistType is None or p.playlistType == playlistType
        ]

    def createPlaylist(self, title, items=None, **kwargs):
        playlist = FakePlaylist(self, title, items or [])
        self._playlists.append(playlist)
        return playlist

    def createCollection(self, title, section=None, items=None, **kwargs):
        section = section or self._section
        collection = FakeCollection(section, title, items or [])
        section._collections.append(collection)
        return collection

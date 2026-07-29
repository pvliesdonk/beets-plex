"""ratingtag: store a rating in the beets database and in file tags.

The canonical rating is a float on a 0-10 scale (Plex-native: 0-5 stars
doubled); ``0.0`` or an absent field means unrated, and the two are equivalent.
Per-container tag storage, adopting the conventions of the maintainer's prior
sync script:

- ID3 (MP3/AIFF/WAVE/DSF): a ``POPM`` frame keyed on the configured email, on a
  linear 0-255 scale.
- Vorbis comment (FLAC/Ogg/...): a ``RATING`` comment, 0-100 on write; a legacy
  value of 5 or less is read as a 0-5 star rating (doubled).
- MP4 (m4a): an iTunes freeform ``RATING`` atom, 0-100.

Containers without one of these tags store nothing, which is not an error.
``mutagen`` is reached through ``mediafile``, so it is not a direct dependency.
"""

from __future__ import annotations

import beets
import mediafile
from beets.dbcore import types
from beets.plugins import BeetsPlugin

mutagen = mediafile.mutagen  # reached through mediafile; not a direct dependency


def _configured_popm_email() -> str:
    """The configured POPM identifier, read at use time.

    Media-field registrations are class-level and survive plugin reloads, so the
    email is read when a tag is accessed rather than captured once at
    registration (otherwise the first value seen in a process would win forever).
    A missing or malformed setting falls back to an empty identifier on purpose:
    reading config must never raise from inside a tag write.
    """
    try:
        return beets.config["ratingtag"]["popm_email"].as_str()
    except Exception:
        return ""


def _float_in_range(value, low, high):
    """Parse ``value`` to a float in ``[low, high]``; return ``None`` otherwise."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


class _UnratedDeletes:
    """Mixin: writing an unrated rating (``0.0``) removes the tag entirely rather
    than storing a literal zero."""

    def set(self, mutagen_file, value):
        if value is None or value == 0.0:
            self.delete(mutagen_file)
        else:
            self.store(mutagen_file, self.serialize(value))


class PopmStorageStyle(_UnratedDeletes, mediafile.StorageStyle):
    """An ID3 ``POPM`` frame on a linear 0-255 scale.

    Only the ``POPM`` frame whose email matches the configuration is read or
    written; other ``POPM`` frames and the play ``count`` are preserved.
    """

    formats = ["MP3", "AIFF", "DSF", "WAVE"]

    def __init__(self, email_getter=_configured_popm_email):
        self._email_getter = email_getter
        super().__init__(key="POPM", as_type=int)

    def _frame_key(self):
        return "POPM:" + self._email_getter()

    def fetch(self, mutagen_file):
        tags = mutagen_file.tags
        frame = tags.get(self._frame_key()) if tags is not None else None
        return frame.rating if frame is not None else None

    def store(self, mutagen_file, value):
        if mutagen_file.tags is None:
            mutagen_file.add_tags()  # a container with no ID3 tags yet
        frame = mutagen_file.tags.get(self._frame_key())
        if frame is not None:
            frame.rating = value  # preserve email and count
        else:
            mutagen_file.tags.add(
                mutagen.id3.POPM(email=self._email_getter(), rating=value, count=0)
            )

    def delete(self, mutagen_file):
        tags = mutagen_file.tags
        key = self._frame_key()
        if tags is not None and key in tags:
            del tags[key]

    def deserialize(self, mutagen_value):
        if mutagen_value is None:
            return None
        if mutagen_value == 0:
            return 0.0  # a byte of 0 is unrated
        # A rated byte must never round down to 0.0 — the unrated sentinel that
        # triggers deletion. Byte 1 is Windows Media Player's one star and would
        # otherwise collapse to 0.0 and be deleted on the next write.
        return max(0.1, round(mutagen_value / 255 * 10, 1))

    def serialize(self, value):
        # Floor to byte 1 so a rated value never lands on byte 0, which
        # `deserialize` treats as unrated (the mixin never passes 0.0 here).
        return max(1, int(round(value / 10 * 255)))


class VorbisRatingStorageStyle(_UnratedDeletes, mediafile.StorageStyle):
    """A Vorbis ``RATING`` comment, 0-100 on write; a legacy 0-5 value read as
    stars (doubled)."""

    def __init__(self):
        super().__init__(key="RATING", as_type=str)

    def deserialize(self, mutagen_value):
        number = _float_in_range(mutagen_value, 0, 100)
        if number is None:
            return None
        return round(number * 2, 1) if number <= 5 else round(number / 10, 1)

    def serialize(self, value):
        # Clamp above the legacy 1-5 star range so a written value is never
        # re-read as a star rating; a rating below 1.0 cannot be represented and
        # rounds up to 1.0.
        return str(max(10, min(100, int(round(value * 10)))))


class MP4RatingStorageStyle(_UnratedDeletes, mediafile.MP4StorageStyle):
    """An MP4 iTunes freeform ``RATING`` atom, 0-100 (no legacy rule)."""

    def __init__(self):
        super().__init__(key="----:com.apple.iTunes:RATING", as_type=str)

    def deserialize(self, mutagen_value):
        if isinstance(mutagen_value, bytes):
            mutagen_value = mutagen_value.decode("utf-8", "ignore")
        number = _float_in_range(mutagen_value, 0, 100)
        return None if number is None else round(number / 10, 1)

    def serialize(self, value):
        # MP4StorageStyle.serialize encodes the string into a freeform bytes atom.
        return super().serialize(str(int(round(value * 10))))


def rating_media_field(popm_email_getter=_configured_popm_email):
    """The composed ``rating`` media field: POPM for ID3, RATING for Vorbis,
    freeform for MP4."""
    return mediafile.MediaField(
        PopmStorageStyle(popm_email_getter),
        VorbisRatingStorageStyle(),
        MP4RatingStorageStyle(),
        out_type=float,
    )


class RatingTagPlugin(BeetsPlugin):
    item_types = {"rating": types.FLOAT}

    def __init__(self):
        super().__init__()
        self.config.add({"popm_email": ""})
        self._register_rating_field()

    def _register_rating_field(self):
        # Media-field registrations are class-level and survive plugin reloads,
        # so re-adding an already-present field would raise. Tolerate our own
        # registration; warn if another plugin already owns the `rating` name.
        existing = mediafile.MediaFile.__dict__.get("rating")
        if existing is None:
            self.add_media_field("rating", rating_media_field())
        elif isinstance(existing, mediafile.MediaField) and any(
            isinstance(style, PopmStorageStyle) for style in existing._styles
        ):
            self._log.debug("media field 'rating' already registered by ratingtag")
        else:
            self._log.warning(
                "media field 'rating' is already registered by another plugin; "
                "leaving it in place"
            )

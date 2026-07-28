"""Store track ratings (0-10) in the beets DB and in file tags.

Tag conventions:
- MP3: POPM frame (0-255 linear), identified by the configured popm_email.
- FLAC/Ogg/Opus: RATING Vorbis comment, 0-100 (MediaMonkey scale); legacy
  values of 5 or less are read as a 0-5 star scale.
- MP4: ----:com.apple.iTunes:RATING freeform atom, 0-100.

Unrated is 0.0 or an absent field; writing an unrated value removes the tag.
"""

import mediafile
import mutagen.id3


def rating_from_popm(raw):
    """POPM byte (0-255) to canonical 0-10 float; 0/None means unrated."""
    if not raw:
        return None
    return round(float(raw) * 10.0 / 255.0, 1)


def rating_to_popm(value):
    """Canonical 0-10 float to POPM byte, minimum 1."""
    return max(1, min(255, int(round(float(value) * 25.5))))


def rating_from_vorbis(raw):
    """RATING comment string to canonical 0-10 float; None when unrated."""
    if raw is None:
        return None
    try:
        num = float(str(raw))
    except ValueError:
        return None
    if num <= 0:
        return None
    if num <= 5:  # legacy 0-5 star scale
        return round(num * 2.0, 1)
    return round(num / 10.0, 1)


def rating_to_vorbis(value):
    """Canonical 0-10 float to a 0-100 integer string.

    Clamped to a minimum of "10" so written values never land in the 1-5
    range, which reads back as the legacy star scale.
    """
    return str(max(10, min(100, int(round(float(value) * 10)))))


class VorbisRatingStorageStyle(mediafile.StorageStyle):
    """RATING Vorbis comment, 0-100; values <= 5 read as 0-5 stars."""

    def __init__(self):
        super().__init__("RATING")

    def get(self, mutagen_file):
        return rating_from_vorbis(self.fetch(mutagen_file))

    def set(self, mutagen_file, value):
        value = float(value or 0)
        if value <= 0:
            self.delete(mutagen_file)
        else:
            super().set(mutagen_file, rating_to_vorbis(value))


class PopmRatingStorageStyle(mediafile.MP3StorageStyle):
    """Rating in a POPM frame, linear 0-255, matched by email."""

    def __init__(self, email):
        super().__init__("POPM")
        self.email = email or ""

    def _frame(self, mutagen_file):
        if mutagen_file.tags is None:
            return None
        for frame in mutagen_file.tags.getall("POPM"):
            if (frame.email or "") == self.email:
                return frame
        return None

    def get(self, mutagen_file):
        frame = self._frame(mutagen_file)
        return rating_from_popm(frame.rating) if frame else None

    def set(self, mutagen_file, value):
        value = float(value or 0)
        if value <= 0:
            self.delete(mutagen_file)
            return
        if mutagen_file.tags is None:
            mutagen_file.add_tags()
        frame = self._frame(mutagen_file)
        if frame is None:
            mutagen_file.tags.add(
                mutagen.id3.POPM(email=self.email, rating=rating_to_popm(value))
            )
        else:
            frame.rating = rating_to_popm(value)

    def delete(self, mutagen_file):
        if mutagen_file.tags is None:
            return
        keep = [
            frame
            for frame in mutagen_file.tags.getall("POPM")
            if (frame.email or "") != self.email
        ]
        mutagen_file.tags.setall("POPM", keep)


class MP4RatingStorageStyle(mediafile.MP4StorageStyle):
    """RATING freeform atom, 0-100 scale (no legacy star handling)."""

    def __init__(self):
        super().__init__("----:com.apple.iTunes:RATING")

    def get(self, mutagen_file):
        raw = self.fetch(mutagen_file)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")
        return rating_from_vorbis(raw)

    def set(self, mutagen_file, value):
        value = float(value or 0)
        if value <= 0:
            self.delete(mutagen_file)
        else:
            super().set(mutagen_file, rating_to_vorbis(value))

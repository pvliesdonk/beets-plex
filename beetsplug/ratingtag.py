"""Store track ratings (0-10) in the beets DB and in file tags.

Tag conventions:
- MP3: POPM frame (0-255 linear), identified by the configured popm_email.
- FLAC/Ogg/Opus: RATING Vorbis comment, 0-100 (MediaMonkey scale); legacy
  values of 5 or less are read as a 0-5 star scale.
- MP4: ----:com.apple.iTunes:RATING freeform atom, 0-100.

Unrated is 0.0 or an absent field; writing an unrated value removes the tag.
"""


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

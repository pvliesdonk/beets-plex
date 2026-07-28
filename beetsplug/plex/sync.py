"""Three-way rating merge between beets and Plex."""

from dataclasses import dataclass

NONE = "none"
PULL = "pull"
PUSH = "push"


def normalize(value):
    """Map a rating-ish value onto the canonical scale: 0-10, 0.0 = unrated."""
    if value is None:
        return 0.0
    return round(float(value), 1)


@dataclass
class Decision:
    action: str
    value: float


def decide(base, beets_value, plex_value, rating_updated, plex_lastratedat, conflict):
    """Pick the sync action for one item.

    base: last synced value (plex_userrating), beets_value: the rating field,
    plex_value: Plex userRating. rating_updated is an epoch float or None;
    plex_lastratedat a datetime or None; conflict is "plex" or "beets".
    """
    base = normalize(base)
    beets_val = normalize(beets_value)
    plex_val = normalize(plex_value)
    beets_changed = beets_val != base
    plex_changed = plex_val != base

    if not beets_changed and not plex_changed:
        return Decision(NONE, base)
    if beets_changed and not plex_changed:
        return Decision(PUSH, beets_val)
    if plex_changed and not beets_changed:
        return Decision(PULL, plex_val)
    if beets_val == plex_val:
        return Decision(NONE, beets_val)

    if rating_updated is not None and plex_lastratedat is not None:
        beets_wins = rating_updated > plex_lastratedat.timestamp()
    else:
        beets_wins = conflict == "beets"
    if beets_wins:
        return Decision(PUSH, beets_val)
    return Decision(PULL, plex_val)

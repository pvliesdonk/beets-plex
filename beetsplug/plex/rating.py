"""Pure three-way rating merge between beets and Plex.

Values are on Plex's 0-10 scale (the same as ratingtag's), 0 = unrated (the
caller lets Plex's None normalize to 0). Ratings are compared at one-decimal
resolution so neither float imprecision nor beets' SQLite-TEXT flex round-trip
can fake a change. No IO — the plugin applies the returned Decision.
"""

from __future__ import annotations

from collections import namedtuple

PUSH = "push"  # write the beets rating to Plex
ADOPT = "adopt"  # write the Plex rating into beets
NONE = "none"  # no rating write

# action: PUSH/ADOPT/NONE; value: agreed 0-10 rating (0 = unrated);
# baseline: value to record as last-agreed; conflict: both sides moved apart.
Decision = namedtuple("Decision", "action value baseline conflict")


def quantize(value) -> float:
    """One-decimal 0-10 rating; None/0/absent -> 0.0 (unrated)."""
    return round(float(value or 0), 1)


def rating_merge(beets, plex, baseline, policy="plex") -> Decision:
    b, p, base = quantize(beets), quantize(plex), quantize(baseline)
    if b == p:
        return Decision(NONE, b, b, False)
    b_changed = b != base
    p_changed = p != base
    if b_changed and not p_changed:
        return Decision(PUSH, b, b, False)
    if p_changed and not b_changed:
        return Decision(ADOPT, p, p, False)
    # both moved apart (or first sync: baseline unknown, so both look changed)
    if policy == "beets":
        return Decision(PUSH, b, b, True)
    if policy == "skip":
        return Decision(NONE, base, base, True)
    return Decision(ADOPT, p, p, True)  # default: Plex wins

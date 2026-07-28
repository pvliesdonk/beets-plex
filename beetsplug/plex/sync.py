"""Three-way rating merge between beets and Plex."""

import time
from dataclasses import dataclass

from plexapi.exceptions import PlexApiException
from requests.exceptions import RequestException

from . import match

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
    by_policy: bool = False
    """True when both sides changed and no timestamp was available, so the
    `conflict` setting picked the winner rather than recency."""


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

    by_policy = rating_updated is None or plex_lastratedat is None
    if by_policy:
        beets_wins = conflict == "beets"
    else:
        beets_wins = rating_updated > plex_lastratedat.timestamp()
    if beets_wins:
        return Decision(PUSH, beets_val, by_policy)
    return Decision(PULL, plex_val, by_policy)


def _update_mirrors(item, track, agreed_value):
    item.plex_userrating = agreed_value
    item.plex_ratingkey = track.ratingKey
    item.plex_guid = track.guid or ""
    item.plex_viewcount = track.viewCount or 0
    item.plex_skipcount = track.skipCount or 0
    if track.lastViewedAt:
        item.plex_lastviewedat = track.lastViewedAt.timestamp()
    if track.lastRatedAt:
        item.plex_lastratedat = track.lastRatedAt.timestamp()
    item.plex_updated = time.time()


def run(plugin, lib, opts, args):
    """beet plex sync [QUERY] [--pretend] [--pull|--push]"""
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    conflict = plugin.config["conflict"].as_str()
    pretend = bool(getattr(opts, "pretend", False))
    counts = {
        "pulled": 0,
        "pushed": 0,
        "unchanged": 0,
        "unmatched": 0,
        "failed": 0,
        "deferred": 0,
        "by_policy": 0,
    }

    for item in lib.items(args):
        track = match.resolve(item, path_map, beets_dir, plex_dir)
        if track is None:
            counts["unmatched"] += 1
            plugin._log.debug("unmatched: {0}", item)
            continue

        decision = decide(
            item.get("plex_userrating"),
            item.get("rating"),
            track.userRating,
            item.get("rating_updated"),
            track.lastRatedAt,
            conflict,
        )
        # A restricted direction leaves the other side's change pending.
        if (decision.action == PUSH and getattr(opts, "pull", False)) or (
            decision.action == PULL and getattr(opts, "push", False)
        ):
            counts["deferred"] += 1
            continue
        if decision.by_policy:
            counts["by_policy"] += 1

        if decision.action == PUSH:
            plugin._log.info(
                "plex: push rating {0} for {1}", decision.value or "clear", item
            )
            if pretend:
                counts["pushed"] += 1
                continue
            try:
                track.rate(decision.value if decision.value > 0 else None)
            except (PlexApiException, RequestException) as exc:
                # Counted as failed, not pushed: the base is left alone so
                # the next run retries this item.
                counts["failed"] += 1
                plugin._log.warning("plex: rating push failed for {0}: {1}", item, exc)
                continue
            counts["pushed"] += 1
        elif decision.action == PULL:
            plugin._log.info(
                "plex: pull rating {0} for {1}", decision.value or "clear", item
            )
            if pretend:
                counts["pulled"] += 1
                continue
            item.rating = decision.value
            # Write the tag before advancing the sync base. If the file
            # cannot be written, the base must stay put: otherwise the next
            # run sees all three values agreeing and never retries, leaving
            # the rating permanently missing from the file.
            with plugin.suspend_stamp():
                written = item.try_write()
            if not written:
                counts["failed"] += 1
                plugin._log.warning(
                    "plex: tag write failed for {0}; not advancing sync state", item
                )
                continue
            counts["pulled"] += 1
        else:
            counts["unchanged"] += 1
            if pretend:
                continue

        _update_mirrors(item, track, decision.value)
        with plugin.suspend_stamp():
            item.store()

    plugin._log.info(
        "plex: sync done: {0} pulled, {1} pushed, {2} unchanged, "
        "{3} unmatched, {4} failed, {5} deferred",
        counts["pulled"],
        counts["pushed"],
        counts["unchanged"],
        counts["unmatched"],
        counts["failed"],
        counts["deferred"],
    )
    if counts["by_policy"]:
        plugin._log.warning(
            "plex: {0} conflict(s) resolved by the '{1}' policy because no "
            "beets-side rating timestamp was available",
            counts["by_policy"],
            conflict,
        )
    return counts

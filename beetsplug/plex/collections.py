"""Sync query-defined track collections from beets to Plex."""

from beets import ui
from beets.dbcore.query import InvalidQueryError
from beets.library import Item, parse_query_string
from plexapi.exceptions import PlexApiException
from requests.exceptions import RequestException

from . import match
from .playlists import read_entries, resolve_tracks, select


def configured(plugin):
    """Read [(name, query)] from the plex.collections config list."""
    return read_entries(plugin, "collections", "collection")


def run(plugin, lib, opts, args):
    """beet plex collections [NAME...] [--pretend]"""
    server = plugin.server()
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    pretend = bool(getattr(opts, "pretend", False))
    prune = plugin.config["prune"].get(bool)

    failed = 0
    for name, query_string in select(configured(plugin), args, kind="collection"):
        # One entry's failure must not cancel the entries behind it.
        # A refused resolve or a malformed query is the likeliest
        # failure here, so those count too, not just server faults.
        try:
            query, _ = parse_query_string(query_string, Item)
            tracks = resolve_tracks(
                plugin,
                lib.items(query),
                path_map,
                beets_dir,
                plex_dir,
                "collection",
                name,
            )
            _apply(plugin, server, music, name, tracks, pretend, prune)
        except (
            PlexApiException,
            RequestException,
            ui.UserError,
            InvalidQueryError,
        ) as exc:
            failed += 1
            plugin._log.warning("plex: collection {0} failed: {1}", name, exc)
    if failed:
        raise ui.UserError(f"plex: {failed} collection(s) failed; see the log")


def _apply(plugin, server, music, name, tracks, pretend, prune=False):
    same_name = [c for c in music.collections() if c.title == name]
    for collection in same_name:
        if getattr(collection, "smart", False):
            plugin._log.warning("plex: {0} is a smart collection, skipped", name)
            return
        if collection.subtype != "track":
            plugin._log.warning(
                "plex: {0} is a {1} collection, skipped", name, collection.subtype
            )
            return
    existing = same_name[0] if same_name else None

    if not tracks and same_name and not prune:
        # A query matching nothing is far more often a typo than an
        # instruction to delete. This has to come before the duplicate
        # collapse below, or a typo would still destroy the duplicates.
        plugin._log.warning(
            "plex: collection {0} left alone: the query matched nothing "
            "(set plex.prune to delete it instead)",
            name,
        )
        return

    # Duplicate titles are possible in Plex; the extras would otherwise be
    # invisible to every later run.
    for stale in same_name[1:]:
        if pretend:
            ui.print_(f"plex: would delete a duplicate collection {name}")
        else:
            plugin._log.warning("plex: deleting a duplicate collection {0}", name)
            stale.delete()

    desired = {t.ratingKey: t for t in tracks}

    if existing is None:
        if not tracks:
            plugin._log.info("plex: collection {0}: nothing to do", name)
            return
        if pretend:
            ui.print_(f"plex: would create collection {name} ({len(tracks)} tracks)")
            return
        server.createCollection(name, section=music, items=tracks)
        plugin._log.info(
            "plex: collection {0} created with {1} tracks", name, len(tracks)
        )
        return

    if not tracks:
        if pretend:
            ui.print_(f"plex: would delete collection {name}")
            return
        existing.delete()
        plugin._log.warning("plex: collection {0} pruned (query matched nothing)", name)
        return

    current = {t.ratingKey: t for t in existing.items()}
    to_add = [t for key, t in desired.items() if key not in current]
    to_remove = [t for key, t in current.items() if key not in desired]
    if not to_add and not to_remove:
        plugin._log.info("plex: collection {0} unchanged", name)
        return
    if pretend:
        ui.print_(
            f"plex: would update collection {name}: +{len(to_add)} -{len(to_remove)}"
        )
        return
    if to_add:
        existing.addItems(to_add)
    if to_remove:
        existing.removeItems(to_remove)
    plugin._log.info(
        "plex: collection {0} updated: +{1} -{2}",
        name,
        len(to_add),
        len(to_remove),
    )

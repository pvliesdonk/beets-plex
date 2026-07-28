"""Sync query-defined track collections from beets to Plex."""

from beets import ui
from beets.library import Item, parse_query_string

from . import match
from .playlists import resolve_tracks, select


def configured(plugin):
    """Read [(name, query)] from the plex.collections config list."""
    entries = []
    for node in plugin.config["collections"].get(list):
        name = node.get("name")
        if not name:
            raise ui.UserError("plex: collection entry without a name")
        entries.append((str(name), str(node.get("query") or "")))
    return entries


def run(plugin, lib, opts, args):
    """beet plex collections [NAME...] [--pretend]"""
    server = plugin.server()
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    pretend = bool(getattr(opts, "pretend", False))

    for name, query_string in select(configured(plugin), args, kind="collection"):
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
        _apply(plugin, server, music, name, tracks, pretend)


def _apply(plugin, server, music, name, tracks, pretend):
    existing = next((c for c in music.collections() if c.title == name), None)
    if existing is not None:
        if getattr(existing, "smart", False):
            plugin._log.warning("plex: {0} is a smart collection, skipped", name)
            return
        if existing.subtype != "track":
            plugin._log.warning(
                "plex: {0} is a {1} collection, skipped", name, existing.subtype
            )
            return

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
        plugin._log.warning(
            "plex: collection {0} removed (query matched nothing)", name
        )
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

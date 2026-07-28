"""Push query-defined playlists from beets to Plex."""

from beets import ui
from beets.library import Item, parse_query_string

from . import match


def configured(plugin):
    """Read [(name, query)] from the plex.playlists config list."""
    entries = []
    for node in plugin.config["playlists"].get(list):
        name = node.get("name")
        if not name:
            raise ui.UserError("plex: playlist entry without a name")
        entries.append((str(name), str(node.get("query") or "")))
    return entries


def select(entries, names, kind="playlist"):
    """Restrict configured entries to the requested names.

    `kind` names the entry type in the error message; collections reuse
    this helper and must not report unknown names as playlists.
    """
    if not names:
        return entries
    by_name = dict(entries)
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise ui.UserError(f"plex: unknown {kind}(s): {', '.join(unknown)}")
    return [(n, by_name[n]) for n in names]


def resolve_tracks(plugin, items, path_map, beets_dir, plex_dir, kind, name):
    """Resolve beets items to Plex tracks, refusing a total match failure.

    An empty result means "delete the remote object", so it must only ever
    come from a query that genuinely matched nothing. If the query matched
    items but none of them are in Plex (a wrong `plex_dir`, a library
    mid-scan, a section that was re-created), deleting would destroy the
    user's playlists and collections on a misconfiguration.
    """
    tracks = []
    matched = 0
    for item in items:
        matched += 1
        track = match.resolve(item, path_map, beets_dir, plex_dir)
        if track is None:
            plugin._log.warning(
                "plex: {0} not in Plex, skipped for {1} {2}", item, kind, name
            )
            continue
        tracks.append(track)
    if matched and not tracks:
        raise ui.UserError(
            f"plex: {kind} {name!r}: the query matched {matched} item(s) but "
            "none of them are in Plex; refusing to delete it. Check plex_dir "
            "and whether the Plex library has been scanned."
        )
    return tracks


def run(plugin, lib, opts, args):
    """beet plex playlists [NAME...] [--pretend]"""
    server = plugin.server()
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    pretend = bool(getattr(opts, "pretend", False))

    for name, query_string in select(configured(plugin), args):
        query, sort = parse_query_string(query_string, Item)
        tracks = resolve_tracks(
            plugin,
            lib.items(query, sort),
            path_map,
            beets_dir,
            plex_dir,
            "playlist",
            name,
        )
        _apply(plugin, server, name, tracks, pretend)


def _apply(plugin, server, name, tracks, pretend):
    same_name = [p for p in server.playlists() if p.title == name]
    for playlist in same_name:
        if playlist.playlistType != "audio":
            plugin._log.warning(
                "plex: {0} exists as a {1} playlist, skipped",
                name,
                playlist.playlistType,
            )
            return
        if getattr(playlist, "smart", False):
            plugin._log.warning("plex: {0} is a smart playlist, skipped", name)
            return

    current = same_name[0] if same_name else None
    desired = [t.ratingKey for t in tracks]
    if current is not None and [t.ratingKey for t in current.items()] == desired:
        plugin._log.info("plex: playlist {0} unchanged", name)
        return

    if pretend:
        ui.print_(f"plex: would rebuild playlist {name} ({len(tracks)} tracks)")
        return
    if tracks:
        # Create the replacement before removing the old one: if the create
        # fails, the user still has the previous playlist rather than none.
        # Plex tolerates two playlists sharing a title for that moment.
        server.createPlaylist(name, items=tracks)
        if current is not None:
            current.delete()
        plugin._log.info(
            "plex: playlist {0} rebuilt with {1} tracks", name, len(tracks)
        )
    else:
        if current is not None:
            current.delete()
        plugin._log.warning("plex: playlist {0} removed (query matched nothing)", name)

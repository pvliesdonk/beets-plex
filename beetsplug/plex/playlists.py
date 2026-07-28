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


def run(plugin, lib, opts, args):
    """beet plex playlists [NAME...] [--pretend]"""
    server = plugin.server()
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    pretend = bool(getattr(opts, "pretend", False))

    for name, query_string in select(configured(plugin), args):
        query, sort = parse_query_string(query_string, Item)
        tracks = []
        for item in lib.items(query, sort):
            track = match.resolve(item, path_map, beets_dir, plex_dir)
            if track is None:
                plugin._log.warning(
                    "plex: {0} not in Plex, skipped for playlist {1}", item, name
                )
                continue
            tracks.append(track)
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
    if current is not None:
        current.delete()
    if tracks:
        server.createPlaylist(name, items=tracks)
        plugin._log.info(
            "plex: playlist {0} rebuilt with {1} tracks", name, len(tracks)
        )
    else:
        plugin._log.warning("plex: playlist {0} removed (query matched nothing)", name)

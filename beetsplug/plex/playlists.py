"""Push query-defined playlists from beets to Plex."""

from beets import ui
from beets.dbcore.query import InvalidQueryError
from beets.library import Item, parse_query_string
from plexapi.exceptions import PlexApiException
from requests.exceptions import RequestException

from . import match


def read_entries(plugin, section, kind):
    """Read [(name, query)] from a plex.<section> config list.

    A missing `query` key is rejected rather than defaulting to the empty
    query: the empty query matches the whole library, so a typo in the key
    would quietly push every track in the library. An explicit empty string
    still means "everything", which is occasionally what you want.
    """
    entries = []
    for node in plugin.config[section].get(list):
        name = node.get("name")
        if not name:
            raise ui.UserError(f"plex: {kind} entry without a name")
        query = node.get("query")
        if query is None:
            raise ui.UserError(f"plex: {kind} {str(name)!r} has no query")
        entries.append((str(name), str(query)))
    return entries


def configured(plugin):
    """Read [(name, query)] from the plex.playlists config list."""
    return read_entries(plugin, "playlists", "playlist")


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

    An empty result is treated as "the query matched nothing", which under
    `plex.prune` deletes the remote object. It must therefore only ever
    come from a query that really did match nothing. If the query matched
    items but none of them are in Plex (a wrong `plex_dir`, a library
    mid-scan, a section that was re-created), that is a misconfiguration
    and must not be mistaken for an empty result.
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
    prune = plugin.config["prune"].get(bool)

    failed = 0
    for name, query_string in select(configured(plugin), args):
        # One entry's failure must not cancel the entries behind it.
        # A refused resolve or a malformed query is the likeliest
        # failure here, so those count too, not just server faults.
        try:
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
            _apply(plugin, server, name, tracks, pretend, prune)
        except (
            PlexApiException,
            RequestException,
            ui.UserError,
            InvalidQueryError,
        ) as exc:
            failed += 1
            plugin._log.warning("plex: playlist {0} failed: {1}", name, exc)
    if failed:
        raise ui.UserError(f"plex: {failed} playlist(s) failed; see the log")


def _apply(plugin, server, name, tracks, pretend, prune=False):
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
    # Only a single playlist with this title, already correct, is a no-op.
    # Duplicates must be collapsed even when the first one matches.
    if (
        len(same_name) == 1
        and [t.ratingKey for t in current.items()] == desired
        and desired
    ):
        plugin._log.info("plex: playlist {0} unchanged", name)
        return

    if not tracks and same_name and not prune:
        # A query that matches nothing is far more often a typo or a
        # half-imported library than a real instruction to delete, so an
        # empty result leaves the playlist alone unless prune is enabled.
        plugin._log.warning(
            "plex: playlist {0} left alone: the query matched nothing "
            "(set plex.prune to delete it instead)",
            name,
        )
        return

    if pretend:
        if tracks:
            ui.print_(f"plex: would rebuild playlist {name} ({len(tracks)} tracks)")
        elif same_name:
            ui.print_(f"plex: would delete playlist {name}")
        return
    if tracks:
        # Create the replacement before removing the old ones: if the create
        # fails, the user still has the previous playlist rather than none.
        # Plex tolerates playlists sharing a title for that moment.
        server.createPlaylist(name, items=tracks)
        plugin._log.info(
            "plex: playlist {0} rebuilt with {1} tracks", name, len(tracks)
        )
    elif same_name:
        plugin._log.warning("plex: playlist {0} pruned (query matched nothing)", name)
    else:
        plugin._log.info("plex: playlist {0}: nothing to do", name)
    # Delete every pre-existing playlist of this title, not just the first:
    # an interrupted earlier run can leave duplicates behind.
    for stale in same_name:
        stale.delete()

"""The plex plugin: connect to a Plex Media Server, match beets items to tracks,
report status, pull play statistics, sync ratings two-way, and push
query-defined playlists and collections.

This module owns the shared ``plex:`` config (including the ``rating_conflict``
policy and the ``playlists``/``collections`` entries with their ``prune_empty``
guard), a lazily-created and reused server connection, the ``plex_ratingkey``
cache field, the play-statistics cache fields (``plex_viewcount``,
``plex_skipcount``, ``plex_lastviewedat``, ``plex_lastratedat``,
``plex_updated``), the rating-sync fields (``plex_rating_baseline``, the
last-agreed rating, and ``plex_userrating``, a mirror of Plex's current
rating), and the ``beet plex status``, ``beet plex stats``, ``beet plex sync``,
``beet plex playlists``, and ``beet plex collections`` commands.
"""

from __future__ import annotations

import os
import time

import beets
from beets import ui
from beets.dbcore import types
from beets.plugins import BeetsPlugin

from . import matching, pushing, rating, stats

# Stat fields Plex may stop reporting (a wiped play history drops the
# timestamps). track_stats omits an absent one, so pull_stats clears any
# previously-stored value rather than leave a play time Plex no longer has.
# Counts self-clear: Plex always reports them, as 0 when reset.
_CLEARABLE_STAT_FIELDS = ("plex_lastviewedat", "plex_lastratedat")


class PlexPlugin(BeetsPlugin):
    item_types = {
        "plex_ratingkey": types.INTEGER,
        "plex_viewcount": types.INTEGER,
        "plex_skipcount": types.INTEGER,
        "plex_lastviewedat": types.DateType(),
        "plex_lastratedat": types.DateType(),
        "plex_updated": types.DateType(),
        "plex_rating_baseline": types.FLOAT,
        "plex_userrating": types.FLOAT,
    }

    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "host": "localhost",
                "port": 32400,
                "token": "",
                "library_name": "Music",
                "secure": False,
                "beets_dir": "",
                "plex_dir": "",
                "rating_conflict": "plex",
                "playlists": [],
                "collections": [],
                "prune_empty": False,
                "auto_scan": False,
                "scan_threshold": 100,
            }
        )
        self.config["token"].redact = True
        self._server = None
        self._scan_dirs = set()
        if self.config["auto_scan"].get(bool):
            for event in ("item_imported", "item_removed"):
                self.register_listener(event, self._scan_item)
            self.register_listener("item_moved", self._scan_move)
            for event in (
                "item_copied",
                "item_linked",
                "item_hardlinked",
                "item_reflinked",
            ):
                self.register_listener(event, self._scan_place)
            self.register_listener("cli_exit", self._scan_cli_exit)

    # -- connection ---------------------------------------------------------

    def server(self):
        """A connected ``PlexServer``, created lazily and reused for the process
        lifetime. A connection or auth failure raises a clean ``UserError``."""
        if self._server is None:
            from plexapi.server import PlexServer

            scheme = "https" if self.config["secure"].get(bool) else "http"
            baseurl = "{}://{}:{}".format(
                scheme,
                self.config["host"].as_str(),
                self.config["port"].get(int),
            )
            try:
                self._server = PlexServer(baseurl, self.config["token"].as_str())
            except Exception as exc:
                raise ui.UserError(
                    f"cannot connect to Plex at {baseurl}: {exc}"
                ) from exc
        return self._server

    def section(self):
        """The configured Plex library section."""
        name = self.config["library_name"].as_str()
        try:
            return self.server().library.section(name)
        except ui.UserError:
            raise
        except Exception as exc:
            raise ui.UserError(f"Plex library {name!r} not found: {exc}") from exc

    # -- directories --------------------------------------------------------

    def directories(self):
        """``(beets_dir, plex_dir)``; ``beets_dir`` defaults to beets'
        ``directory`` and ``plex_dir`` to ``beets_dir``."""
        beets_dir = (
            self.config["beets_dir"].as_str() or beets.config["directory"].as_str()
        )
        plex_dir = self.config["plex_dir"].as_str() or beets_dir
        return beets_dir, plex_dir

    def _entries(self, kind, names):
        """The configured ``(name, query)`` entries for ``kind`` (``"playlists"``
        or ``"collections"``), filtered to ``names`` if any are given.

        Raises ``ui.UserError`` if a configured entry is not a mapping or is
        missing ``name``/``query`` — a raw ``KeyError``/``TypeError`` from a
        typo'd config would otherwise surface as an unhandled traceback.
        """
        entries = []
        for e in self.config[kind].get(list):
            if not isinstance(e, dict) or "name" not in e or "query" not in e:
                raise ui.UserError(
                    f"malformed plex.{kind} entry (need 'name' and 'query'): {e!r}"
                )
            entries.append((e["name"], e["query"]))
        if names:
            wanted = set(names)
            entries = [(n, q) for n, q in entries if n in wanted]
        return entries

    # -- matching -----------------------------------------------------------

    def match(self, items, section=None):
        """Resolve ``items`` against one fresh sweep of the section.

        Returns ``(matched, unmatched)``, where ``matched`` is a list of
        ``(item, track)`` pairs. Matching is by path, so a stale
        ``plex_ratingkey`` never misdirects; an item outside the library root is
        warned about and left unmatched. Pass ``section`` to reuse an already
        resolved section instead of resolving it again.
        """
        beets_dir, plex_dir = self.directories()
        if section is None:
            section = self.section()
        path_map = matching.build_path_map(section.searchTracks())
        matched, unmatched = [], []
        for item in items:
            item_path = os.fsdecode(item.path)
            target = matching.plex_path(item_path, beets_dir, plex_dir)
            track = path_map.get(target) if target is not None else None
            if track is not None:
                matched.append((item, track))
                continue
            unmatched.append(item)
            if target is None:
                self._log.warning("item outside beets_dir, not matched: {}", item_path)
        return matched, unmatched

    # -- auto-scan ----------------------------------------------------------

    def _touch(self, path):
        """Record the directory of a bytes file ``path`` as touched."""
        self._scan_dirs.add(os.path.dirname(os.fsdecode(path)))

    def _scan_item(self, item=None, **kwargs):
        self._touch(item.path)  # item_imported / item_removed

    def _scan_move(self, source=None, destination=None, **kwargs):
        self._touch(source)  # the file left this directory
        self._touch(destination)  # and arrived in this one

    def _scan_place(self, destination=None, **kwargs):
        self._touch(destination)  # item_copied / _linked / _hardlinked / _reflinked

    def _scan_cli_exit(self, lib=None, **kwargs):
        pass

    # -- playlists --------------------------------------------------------

    def _entry_tracks(self, lib, query, section):
        """Matched Plex tracks for a config entry's query, in query order.
        Unmatched items (not in Plex) are excluded and warned about."""
        matched, unmatched = self.match(list(lib.items(query)), section=section)
        if unmatched:
            self._log.warning(
                "{} item(s) for query {!r} are not in Plex; excluded",
                len(unmatched),
                query,
            )
        return [track for _item, track in matched]

    def _push_playlist(self, name, tracks, pretend):
        from plexapi.exceptions import NotFound

        try:
            existing = self.server().playlist(name)
        except NotFound:
            existing = None
        if not tracks:  # the query matched nothing in Plex
            if existing is None:
                return "keep"
            if self.config["prune_empty"].get(bool):
                if not pretend:
                    existing.delete()
                return "prune"
            ui.print_(
                f"playlist {name!r} query matches nothing; left as-is "
                "(set plex.prune_empty to delete)"
            )
            return "skip"
        if existing is None:
            if not pretend:
                self.server().createPlaylist(name, items=tracks)
            return "create"
        current = existing.items()
        if pushing.playlist_matches(current, tracks):
            return "keep"
        if not pretend:
            # Remove-then-add: a failure between removeItems and addItems
            # leaves the playlist transiently empty, but it self-heals on the
            # next run. The collection path below adds before it removes and
            # never wipes the collection in between.
            existing.removeItems(current)
            existing.addItems(tracks)
        return "update"

    def push_playlists(self, lib, names, pretend=False):
        from plexapi.exceptions import PlexApiException
        from requests.exceptions import RequestException

        section = self.section()
        entries = self._entries("playlists", names)
        if names and not entries:
            ui.print_(f"no playlists named: {', '.join(names)}")
        failed = 0
        for name, query in entries:
            try:
                tracks = self._entry_tracks(lib, query, section)
                outcome = self._push_playlist(name, tracks, pretend)
            except (PlexApiException, RequestException) as exc:
                failed += 1
                self._log.warning("playlist {!r} failed: {}", name, exc)
                continue
            head = "would " if pretend else ""
            ui.print_(f"{head}{outcome} playlist {name!r} ({len(tracks)} track(s))")
        failtail = f"; {failed} failed" if failed else ""
        ui.print_(f"playlists done{failtail}.")

    # -- collections --------------------------------------------------------

    def _push_collection(self, section, name, tracks, pretend):
        from plexapi.exceptions import NotFound

        try:
            existing = section.collection(name)
        except NotFound:
            existing = None
        if not tracks:  # the query matched nothing in Plex
            if existing is None:
                return "keep"
            if self.config["prune_empty"].get(bool):
                if not pretend:
                    existing.delete()
                return "prune"
            ui.print_(
                f"collection {name!r} query matches nothing; left as-is "
                "(set plex.prune_empty to delete)"
            )
            return "skip"
        if existing is None:
            if not pretend:
                section.createCollection(name, items=tracks)
            return "create"
        to_add, to_remove = pushing.collection_diff(existing.items(), tracks)
        if not to_add and not to_remove:
            return "keep"
        if not pretend:
            if to_add:
                existing.addItems(to_add)
            if to_remove:
                existing.removeItems(to_remove)
        return "update"

    def push_collections(self, lib, names, pretend=False):
        from plexapi.exceptions import PlexApiException
        from requests.exceptions import RequestException

        section = self.section()
        entries = self._entries("collections", names)
        if names and not entries:
            ui.print_(f"no collections named: {', '.join(names)}")
        failed = 0
        for name, query in entries:
            try:
                # Resolve INSIDE the try: match() sweeps Plex, so a per-entry
                # network error there must be counted and skipped, not abort all.
                tracks = self._entry_tracks(lib, query, section)
                outcome = self._push_collection(section, name, tracks, pretend)
            except (PlexApiException, RequestException) as exc:
                failed += 1
                self._log.warning("collection {!r} failed: {}", name, exc)
                continue
            head = "would " if pretend else ""
            ui.print_(f"{head}{outcome} collection {name!r} ({len(tracks)} track(s))")
        failtail = f"; {failed} failed" if failed else ""
        ui.print_(f"collections done{failtail}.")

    # -- stats ----------------------------------------------------------------

    def pull_stats(self, lib, query, pretend=False):
        """Pull Plex play statistics into the matched items' beets fields.

        One-way and Plex-authoritative: each matched item's stat fields are set
        to what Plex currently reports, and a timestamp Plex no longer reports
        is cleared rather than left stale. Only items whose stats actually
        changed are stored (and only then is ``plex_updated`` bumped); with
        ``pretend`` the would-be changes are printed and nothing is written.
        """
        section = self.section()
        items = list(lib.items(query))
        matched, unmatched = self.match(items, section=section)
        updated = 0
        for item, track in matched:
            fields = stats.track_stats(track)
            stale = [
                k
                for k in _CLEARABLE_STAT_FIELDS
                if k not in fields and item.get(k) is not None
            ]
            if not stale and all(item.get(k) == v for k, v in fields.items()):
                continue
            updated += 1
            if pretend:
                cleared = f" (clear {', '.join(stale)})" if stale else ""
                ui.print_(f"would update {os.fsdecode(item.path)}: {fields}{cleared}")
                continue
            for key, value in fields.items():
                item[key] = value
            for key in stale:
                del item[key]
            # Whole seconds, like the pulled timestamps: these DateType fields
            # round-trip through SQLite TEXT, whose precision is build-dependent,
            # so a sub-second value could differ after reload (harmless here as
            # plex_updated is never compared, but consistent and query-safe).
            item["plex_updated"] = int(time.time())
            item.store()
        verb = "would update" if pretend else "updated"
        ui.print_(
            f"{len(matched)} matched; {updated} {verb}; {len(unmatched)} unmatched."
        )

    # -- rating sync ----------------------------------------------------------

    def sync_ratings(self, lib, query, pretend=False):
        """Two-way rating sync between beets and Plex over a private baseline.

        Per matched track, a value-based three-way merge decides whether the
        beets rating is pushed to Plex, Plex's rating is adopted into beets, or
        (on a genuine conflict) the configured ``rating_conflict`` policy picks
        a winner. Each conflict is named per track so the user sees which rating
        was overwritten or left. The beets ``rating`` DB field is the source of
        truth: an adopt writes it and stores the item in beets' database;
        ratingtag then carries it into the file's tags the next time beets writes
        the file (``beet write``) — the sync never writes tags itself. A Plex
        write that fails with a Plex API or network error is logged and counted,
        and its baseline is left untouched so the next sync retries it, rather
        than aborting the batch. With ``pretend``, each push/adopt/conflict
        decision is printed per track (unchanged tracks stay silent) and nothing
        is written.
        """
        from plexapi.exceptions import PlexApiException
        from requests.exceptions import RequestException

        policy = self.config["rating_conflict"].as_str()
        if policy not in ("plex", "beets", "skip"):
            raise ui.UserError(f"unknown rating_conflict policy: {policy!r}")
        section = self.section()
        items = list(lib.items(query))
        matched, unmatched = self.match(items, section=section)
        pushed = adopted = conflicts = unchanged = failed = 0
        for item, track in matched:
            path = os.fsdecode(item.path)
            b = rating.quantize(item.get("rating"))
            p = rating.quantize(track.userRating)
            dec = rating.rating_merge(
                item.get("rating"),
                track.userRating,
                item.get("plex_rating_baseline"),
                policy,
            )
            # A conflict is resolved by the configured policy — which may
            # overwrite the losing side's rating, or (under skip) leave both.
            # Name the track in both modes so the user sees what was resolved.
            if dec.conflict:
                conflicts += 1
                outcome = (
                    "left unresolved" if dec.action == rating.NONE else f"→ {dec.value}"
                )
                ui.print_(f"conflict {path}: beets {b} vs plex {p} {outcome}")

            if pretend:
                if dec.action == rating.PUSH:
                    pushed += 1
                    ui.print_(f"would push {path}: {b}→{dec.value}")
                elif dec.action == rating.ADOPT:
                    adopted += 1
                    ui.print_(f"would adopt {path}: →{dec.value}")
                elif not dec.conflict:
                    unchanged += 1
                continue

            # Real run: apply the write, then advance the baseline and mirror.
            if dec.action == rating.PUSH:
                try:
                    track.rate(dec.value or None)
                except (PlexApiException, RequestException) as exc:
                    # A Plex API or network error on one track must not abort the
                    # batch or leave an opaque traceback; skip it (its baseline is
                    # untouched, so the next sync retries it) and keep going. Other
                    # exceptions (a real bug) are left to propagate.
                    failed += 1
                    self._log.warning("Plex rating write failed for {}: {}", path, exc)
                    continue
                pushed += 1
            elif dec.action == rating.ADOPT:
                item["rating"] = dec.value
                adopted += 1
            elif not dec.conflict:
                unchanged += 1
            # The mirror is Plex's value after the op (only a push changes Plex);
            # the baseline is the agreed value. Store once, only if something moved.
            plex_after = dec.value if dec.action == rating.PUSH else p
            dirty = dec.action == rating.ADOPT
            if rating.quantize(item.get("plex_rating_baseline")) != dec.baseline:
                item["plex_rating_baseline"] = dec.baseline
                dirty = True
            if rating.quantize(item.get("plex_userrating")) != plex_after:
                item["plex_userrating"] = plex_after
                dirty = True
            if dirty:
                item.store()
        head = "would " if pretend else ""
        failtail = f", {failed} failed" if failed else ""
        ui.print_(
            f"{len(matched)} matched; {head}push {pushed}, adopt {adopted}, "
            f"unchanged {unchanged}; {conflicts} conflict(s){failtail}; "
            f"{len(unmatched)} unmatched."
        )

    # -- commands -----------------------------------------------------------

    def commands(self):
        cmd = ui.Subcommand("plex", help="synchronize with a Plex Media Server")
        cmd.parser.add_option(
            "-p",
            "--pretend",
            action="store_true",
            default=False,
            help="show what would change; write nothing",
        )
        cmd.func = self._run
        return [cmd]

    def _run(self, lib, opts, args):
        action = args[0] if args else "status"
        if action == "status":
            self.status(lib)
        elif action == "stats":
            query = args[1:]
            self.pull_stats(lib, query, pretend=getattr(opts, "pretend", False))
        elif action == "sync":
            self.sync_ratings(lib, args[1:], pretend=getattr(opts, "pretend", False))
        elif action == "playlists":
            self.push_playlists(lib, args[1:], pretend=getattr(opts, "pretend", False))
        elif action == "collections":
            self.push_collections(
                lib, args[1:], pretend=getattr(opts, "pretend", False)
            )
        else:
            raise ui.UserError(f"unknown plex subcommand: {action!r}")

    def status(self, lib):
        """Report the connection, library size, and match counts; writes
        nothing."""
        section = self.section()
        items = list(lib.items())
        matched, unmatched = self.match(items, section=section)
        ui.print_(
            f"Connected to Plex library {section.title!r} ({section.totalSize} tracks)."
        )
        ui.print_(
            f"{len(matched)} of {len(items)} items matched; {len(unmatched)} unmatched."
        )

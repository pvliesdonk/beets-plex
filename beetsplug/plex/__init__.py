"""Synchronize the beets library with a Plex music library."""

import os
import time
from contextlib import contextmanager
from typing import ClassVar

from beets import config, ui
from beets.dbcore import types
from beets.plugins import BeetsPlugin

from . import match

SUBCOMMANDS = ("sync", "playlists", "collections", "scan", "status")


class PlexPlugin(BeetsPlugin):
    item_types: ClassVar[dict] = {
        "rating": types.FLOAT,
        "plex_userrating": types.FLOAT,
        "plex_ratingkey": types.INTEGER,
        "plex_guid": types.STRING,
        "plex_lastratedat": types.DATE,
        "plex_lastviewedat": types.DATE,
        "plex_viewcount": types.INTEGER,
        "plex_skipcount": types.INTEGER,
        "plex_updated": types.DATE,
        "rating_updated": types.DATE,
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
                "beets_dir": None,
                "plex_dir": None,
                "auto_scan": True,
                "conflict": "plex",
                "prune": False,
                "playlists": [],
                "collections": [],
            }
        )
        self.config["token"].redact = True
        self._server = None
        self._suspend_depth = 0
        self._scan_dirs = set()
        self.register_listener("write", self.on_write)
        self.register_listener("item_imported", self._on_item_event)
        self.register_listener("album_imported", self._on_album_imported)
        self.register_listener("item_moved", self._on_item_moved)
        self.register_listener("item_removed", self._on_item_event)
        self.register_listener("cli_exit", self._on_cli_exit)

    # -- rating change tracking ----------------------------------------

    def on_write(self, item, path, tags):
        """Stamp rating_updated while the rating change is still dirty.

        Fires on the `write` event, which is dispatched before the store,
        so the dirty set still identifies what changed. Suppressed while
        the sync itself is applying a pull.
        """
        if self._suspend_depth:
            return
        if "rating" in item._dirty:
            item.rating_updated = time.time()

    # -- connection ----------------------------------------------------

    def server(self):
        if self._server is None:
            from plexapi.server import PlexServer

            scheme = "https" if self.config["secure"].get(bool) else "http"
            host = self.config["host"].as_str()
            port = self.config["port"].get(int)
            baseurl = f"{scheme}://{host}:{port}"
            # TLS certificates are always verified; plexupdate's
            # ignore_cert_errors is deliberately not supported.
            try:
                self._server = PlexServer(baseurl, self.config["token"].as_str())
            except Exception as exc:
                raise ui.UserError(f"plex: cannot connect to {baseurl}: {exc}") from exc
        return self._server

    def music(self):
        from plexapi.exceptions import NotFound

        name = self.config["library_name"].as_str()
        try:
            return self.server().library.section(name)
        except NotFound as exc:
            raise ui.UserError(f"plex: no library section named {name!r}") from exc

    def dirs(self):
        beets_dir = self.config["beets_dir"].get()
        if not beets_dir:
            beets_dir = config["directory"].as_filename()
        plex_dir = self.config["plex_dir"].get() or beets_dir
        return str(beets_dir).rstrip("/"), str(plex_dir).rstrip("/")

    @contextmanager
    def suspend_stamp(self):
        """Suppress rating_updated stamping for the duration of the block.

        Counted rather than boolean: a nested use must not re-arm stamping
        when the inner block exits while an outer one is still running.
        """
        self._suspend_depth += 1
        try:
            yield
        finally:
            self._suspend_depth -= 1

    # -- CLI -----------------------------------------------------------

    def commands(self):
        cmd = ui.Subcommand("plex", help="synchronize with a Plex music library")
        cmd.parser.add_option(
            "--pretend", action="store_true", help="report actions without changes"
        )
        cmd.parser.add_option(
            "--pull", action="store_true", help="sync: only pull changes from Plex"
        )
        cmd.parser.add_option(
            "--push", action="store_true", help="sync: only push changes to Plex"
        )
        cmd.parser.add_option(
            "--full", action="store_true", help="scan: refresh the whole section"
        )
        cmd.func = self._dispatch
        return [cmd]

    def cmd_sync(self, lib, opts, args):
        from . import sync

        counts = sync.run(self, lib, opts, args)
        if counts["failed"]:
            # Non-zero exit so a scheduled run can tell it did not finish.
            raise ui.UserError(
                f"plex: {counts['failed']} item(s) failed to sync; see the log"
            )

    def cmd_playlists(self, lib, opts, args):
        from . import playlists

        playlists.run(self, lib, opts, args)

    def cmd_collections(self, lib, opts, args):
        from . import collections

        collections.run(self, lib, opts, args)

    def cmd_status(self, lib, opts, args):
        server = self.server()
        music = self.music()
        beets_dir, plex_dir = self.dirs()
        path_map = match.build_path_map(music)
        matched = unmatched = 0
        for item in lib.items(args):
            if match.resolve(item, path_map, beets_dir, plex_dir) is None:
                unmatched += 1
            else:
                matched += 1
        ui.print_(f"server: {server.friendlyName}")
        ui.print_(f"library: {music.title} ({len(path_map)} track files)")
        ui.print_(f"items: {matched} matched, {unmatched} unmatched")

    # -- auto-scan -----------------------------------------------------

    def _note_path(self, item_path):
        # Runs inside beets' import/move/remove events, which beets does not
        # guard, so a malformed beets_dir/plex_dir must not break the user's
        # command. The scan itself reports the failure at exit.
        try:
            beets_dir, plex_dir = self.dirs()
            target = match.plex_path(item_path, beets_dir, plex_dir)
        except Exception as exc:
            self._log.warning("plex: cannot queue a scan for this change: {0}", exc)
            return
        if target:
            self._scan_dirs.add(os.path.dirname(target))

    def _on_item_event(self, item, lib=None):
        self._note_path(item.path)

    def _on_album_imported(self, lib, album):
        for item in album.items():
            self._note_path(item.path)

    def _on_item_moved(self, item, source, destination):
        self._note_path(source)
        self._note_path(destination)

    def _on_cli_exit(self, lib):
        from . import scan

        scan.flush(self)

    def cmd_scan(self, lib, opts, args):
        pretend = bool(getattr(opts, "pretend", False))
        music = self.music()
        if getattr(opts, "full", False):
            if pretend:
                ui.print_("plex: would start a full section scan")
                return
            music.update()
            ui.print_("plex: full section scan started")
            return
        if not args:
            raise ui.UserError("plex scan: give beets-side PATHs or --full")
        beets_dir, plex_dir = self.dirs()
        for arg in args:
            target = match.plex_path(os.path.abspath(arg), beets_dir, plex_dir)
            if target is None:
                raise ui.UserError(f"plex scan: {arg} is outside the beets directory")
            if pretend:
                ui.print_(f"plex: would scan {target}")
                continue
            music.update(path=target)
            ui.print_(f"plex: scan started for {target}")

    def _dispatch(self, lib, opts, args):
        if not args:
            raise ui.UserError("plex: subcommand required: " + ", ".join(SUBCOMMANDS))
        sub, rest = args[0], list(args[1:])
        handler = getattr(self, f"cmd_{sub}", None)
        if sub not in SUBCOMMANDS or handler is None:
            raise ui.UserError(f"plex: unknown subcommand {sub!r}")
        handler(lib, opts, rest)

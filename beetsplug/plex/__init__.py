"""Synchronize the beets library with a Plex music library."""

import time
from contextlib import contextmanager
from typing import ClassVar

from beets import config, ui
from beets.dbcore import types
from beets.plugins import BeetsPlugin

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
                "playlists": [],
                "collections": [],
            }
        )
        self.config["token"].redact = True
        self._server = None
        self._suspend_rating_stamp = False
        self._scan_dirs = set()
        self.register_listener("write", self.on_write)

    # -- rating change tracking ----------------------------------------

    def on_write(self, item, path, tags):
        """Stamp rating_updated while the rating change is still dirty.

        Fires on the `write` event, which is dispatched before the store,
        so the dirty set still identifies what changed. Suppressed while
        the sync itself is applying a pull.
        """
        if self._suspend_rating_stamp:
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
        self._suspend_rating_stamp = True
        try:
            yield
        finally:
            self._suspend_rating_stamp = False

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

        sync.run(self, lib, opts, args)

    def cmd_playlists(self, lib, opts, args):
        from . import playlists

        playlists.run(self, lib, opts, args)

    def _dispatch(self, lib, opts, args):
        if not args:
            raise ui.UserError("plex: subcommand required: " + ", ".join(SUBCOMMANDS))
        sub, rest = args[0], list(args[1:])
        handler = getattr(self, f"cmd_{sub}", None)
        if sub not in SUBCOMMANDS or handler is None:
            raise ui.UserError(f"plex: unknown subcommand {sub!r}")
        handler(lib, opts, rest)

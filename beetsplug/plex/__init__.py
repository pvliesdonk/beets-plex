"""The plex plugin: connect to a Plex Media Server, match beets items to tracks,
and report status.

This module owns the shared ``plex:`` config, a lazily-created and reused server
connection, the ``plex_ratingkey`` cache field, and ``beet plex status``.
"""

from __future__ import annotations

import os
import time

import beets
from beets import ui
from beets.dbcore import types
from beets.plugins import BeetsPlugin

from . import matching, stats


class PlexPlugin(BeetsPlugin):
    item_types = {
        "plex_ratingkey": types.INTEGER,
        "plex_viewcount": types.INTEGER,
        "plex_skipcount": types.INTEGER,
        "plex_lastviewedat": types.DateType(),
        "plex_lastratedat": types.DateType(),
        "plex_updated": types.DateType(),
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
            }
        )
        self.config["token"].redact = True
        self._server = None

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

    # -- stats ----------------------------------------------------------------

    def pull_stats(self, lib, query, pretend=False):
        """Pull Plex play statistics into the matched items' beets fields.

        One-way, Plex-authoritative. Only items whose stats actually changed are
        stored (and only then is ``plex_updated`` bumped); with ``pretend`` the
        would-be changes are printed and nothing is written.
        """
        section = self.section()
        items = list(lib.items(query))
        matched, unmatched = self.match(items, section=section)
        updated = 0
        for item, track in matched:
            fields = stats.track_stats(track)
            if all(item.get(k) == v for k, v in fields.items()):
                continue
            updated += 1
            if pretend:
                ui.print_(f"would update {os.fsdecode(item.path)}: {fields}")
                continue
            for key, value in fields.items():
                item[key] = value
            item["plex_updated"] = time.time()
            item.store()
        verb = "would update" if pretend else "updated"
        ui.print_(
            f"{len(matched)} matched; {updated} {verb}; {len(unmatched)} unmatched."
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

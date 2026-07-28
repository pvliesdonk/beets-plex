"""Trigger Plex partial scans for changed directories."""

FULL_SCAN_THRESHOLD = 20


def flush(plugin):
    """Run the queued partial scans; never raise.

    Called from `cli_exit`, which beets does not guard, so everything that
    can fail — including reading config, which raises on a malformed
    `auto_scan` value — stays inside a try.
    """
    dirs = sorted(plugin._scan_dirs)
    plugin._scan_dirs.clear()
    if not dirs:
        return
    try:
        if not plugin.config["auto_scan"].get(bool):
            return
        music = plugin.music()
    except Exception as exc:
        plugin._log.warning("plex: library scan skipped: {0}", exc)
        return

    if len(dirs) > FULL_SCAN_THRESHOLD:
        plugin._log.info("plex: {0} changed directories, full section scan", len(dirs))
        try:
            music.update()
        except Exception as exc:
            plugin._log.warning("plex: library scan failed: {0}", exc)
        return

    # One try per directory: a single unscannable path must not discard the
    # scans still queued behind it, since the queue has already been cleared.
    failed = 0
    for directory in dirs:
        try:
            plugin._log.info("plex: scanning {0}", directory)
            music.update(path=directory)
        except Exception as exc:
            failed += 1
            plugin._log.warning("plex: scan failed for {0}: {1}", directory, exc)
    if failed:
        plugin._log.warning(
            "plex: {0} of {1} directory scans failed", failed, len(dirs)
        )

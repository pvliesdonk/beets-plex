"""Trigger Plex partial scans for changed directories."""

FULL_SCAN_THRESHOLD = 20


def flush(plugin):
    """Run the queued partial scans; never raise."""
    dirs = sorted(plugin._scan_dirs)
    plugin._scan_dirs.clear()
    if not dirs or not plugin.config["auto_scan"].get(bool):
        return
    try:
        music = plugin.music()
        if len(dirs) > FULL_SCAN_THRESHOLD:
            plugin._log.info(
                "plex: {0} changed directories, full section scan", len(dirs)
            )
            music.update()
        else:
            for directory in dirs:
                plugin._log.info("plex: scanning {0}", directory)
                music.update(path=directory)
    except Exception as exc:
        plugin._log.warning("plex: library scan failed: {0}", exc)

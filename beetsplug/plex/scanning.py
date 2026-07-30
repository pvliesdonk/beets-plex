"""Pure planning for the auto-scan: turn the set of touched beets directories
into a Plex scan plan. No IO — the plugin runs the resulting section.update()
calls. A directory that maps outside ``beets_dir`` is reported as skipped; when
more mapped directories than the threshold are touched, a single full refresh is
planned instead of many targeted scans.
"""

from __future__ import annotations

from collections import namedtuple

from . import matching

# full: run one full-section refresh; paths: the Plex-side dirs to scan;
# skipped: touched dirs that could not be mapped into the Plex library.
ScanPlan = namedtuple("ScanPlan", "full paths skipped")


def plan_scan(dirs, threshold, beets_dir, plex_dir) -> ScanPlan:
    mapped, skipped = [], []
    for d in sorted(dirs):
        target = matching.plex_path(d, beets_dir, plex_dir)
        if target is None:
            skipped.append(d)
        else:
            mapped.append(target)
    if len(mapped) > threshold:
        return ScanPlan(True, [], skipped)
    return ScanPlan(False, mapped, skipped)

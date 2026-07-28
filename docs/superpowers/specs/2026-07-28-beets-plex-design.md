# beets-plex: design

Date: 2026-07-28
Status: approved design, pre-implementation

## Context

Synchronize a beets library (v2.12) with a Plex Media Server. Beets and Plex
index the same files: beets manages `/mnt/music` locally, and the Plex server
mounts the same share (at `/mnt/music` on the server as well, though the design
treats the prefix as configurable). This makes file-path matching exact and
deterministic; no fuzzy matching is needed.

Prior art and why it is not used:

- `beets-plexsync` (arsaboo): drifted into AI discovery features, with a large
  dependency surface (LLM agents, scrapers, vector scoring, a side SQLite
  cache). The conventions worth keeping are its beets field names and the
  shared `plex:` config section, both of which this design adopts.
- Built-in `plexupdate` plugin: only triggers a full section refresh. Replaced
  here by targeted partial scans.
- `sync-plex-music-ratings.py` (own prior script): synced Plex ratings with
  file tags directly (MP3 POPM, FLAC `RATING` 0-100). Its tag conventions are
  adopted by the `ratingtag` plugin.

## Goals

1. Update Plex when beets imports, moves, or removes files (partial scans).
2. Two-way rating sync between beets and Plex, newest change wins.
3. One-way pull of Plex play statistics into beets fields.
4. One-way push of query-defined playlists from beets to Plex.
5. One-way sync of query-defined track collections from beets to Plex.
6. Ratings stored in the beets DB and written to file tags.

## Non-goals

- Plex-to-beets playlist import, m3u handling, AI/discovery features.
- Multi-account sync (`switchUser`); the token's account only.
- Album- or artist-typed collections (track collections only in v1).
- Incremental timestamp-based sync (full three-way pass is cheap and
  self-healing; Plex-side `lastRatedAt` filtering is a known future
  optimization if ever needed).
- Writing play counts to Plex (the Plex API cannot set them).

## Architecture: two plugins, one package

File-tag rating storage and Plex synchronization are orthogonal concerns, so
they are separate plugins shipped in one repo and one pip package:

- `beetsplug/ratingtag.py`: owns the `rating` field and its file-tag
  representation. No network code.
- `beetsplug/plex/`: everything Plex (matching, sync, playlists, collections,
  scans). Touches only the `rating` DB field; never writes tags itself.

Composition is through beets itself: when the plex plugin changes `rating` it
calls `item.try_write()`; if `ratingtag` is enabled its registered media field
gets written, otherwise nothing happens. There is no direct dependency in
either direction. Both plugins declare `rating` as float; identical
declarations do not conflict in beets.

Packaging: hatchling, implicit `beetsplug` namespace package (PEP 420, no
`__init__.py` in `beetsplug/`), dependencies `beets>=2.12` (the test suite
uses `beets.test.helper.PluginTestHelper`, present from 2.12) and `plexapi`.
No entry points; beets discovers plugins by module name. During development
the repo's `beetsplug/` dir is added to `pluginpath`.

## Plugin: ratingtag

### Field

Declares item field `rating`: float, scale 0-10 (Plex-native; 0-5 stars times
two). "Unrated" is represented as 0.0 or an absent field; the two are
equivalent everywhere. Rationale: beets' `Item.write()` only writes fields
present on the item, so an absent field cannot clear a stale tag, and Plex's
own UI minimum is a half star (1.0), so 0 carries no rating information.
The user's `types: rating: int` config line must be removed (the types plugin
raises a conflict for differing declarations of the same field).

### Media field (tag storage)

Registered via `add_media_field("rating", ...)` so `beet write`, `beet
update`, and scrub-rewrite all handle it as a normal tag field. mediafile has
no built-in rating support, so custom storage styles are implemented:

| Format | Tag | Scale on disk |
|---|---|---|
| MP3 (ID3) | `POPM` frame, email from config `popm_email` | 0-255 |
| FLAC / Vorbis (ogg, opus) | `RATING` comment | 0-100 (MediaMonkey style) |
| MP4 (m4a) | `----:com.apple.iTunes:RATING` freeform | 0-100 |
| other | not stored | - |

Conversions to/from the canonical 0-10 DB value round to one decimal on read
so that tag round-trips are stable and never trigger spurious sync pushes.

### Config

```yaml
ratingtag:
  popm_email: ''       # POPM identifier; must match existing tags to be read
```

### Contract edges (each gets a test)

- FLAC `RATING` legacy 0-5 scale: a value of 5 or less on read is treated as
  a 0-5 star value and multiplied by 2; writes always use 0-100.
- POPM: only the frame matching `popm_email` is read; other POPM frames are
  ignored and preserved. Writing updates the matching frame or adds one.
- A tag value of 0 (POPM 0, FLAC "0") is read as unrated, following the
  common player convention. Writing an unrated value (0.0) removes the tag
  entirely rather than writing a literal 0.
- Non-numeric or out-of-range tag values are ignored with a debug log.
- Round-trip stability: DB -> tag -> DB reproduces the same value after
  one-decimal rounding for every representable rating.
- Formats without a defined style: `item.write()` succeeds and writes nothing
  rating-related.
- Migration path: `beet update <query>` re-reads tags and populates `rating`
  from existing POPM/RATING tags; no custom import command needed.

## Plugin: plex

### Config

Extends the existing shared `plex:` section (compatible with the built-in
plexupdate's keys, which this plugin replaces; remove `plexupdate` from the
plugins list):

```yaml
plex:
  host: 192.168.50.208
  port: 32400
  token: REDACTED            # marked redacted for `beet config` output
  library_name: 'Muziek Archief'
  secure: no                 # https; certificates are always verified
                             # (plexupdate's ignore_cert_errors is
                             # deliberately not supported)

  beets_dir: /mnt/music      # default: beets' `directory`
  plex_dir: /mnt/music       # path prefix as the Plex server sees it;
                             # default: same as beets_dir
  auto_scan: yes             # partial scans after import/move/remove
  conflict: plex             # both-sides-changed fallback: plex | beets

  playlists:
    - name: Top 2000 all
      query: 'top2000_score:1.. top2000_score-'

  collections:
    - name: Top2000
      query: 'top2000_score:1..'
```

### Beets fields (typed flexible attributes)

Names and types match beets-plexsync where they overlap, so existing DB data
and queries (e.g. the smartplaylist `unrated` playlist querying
`plex_lastratedat`) keep working, and co-loading with plexsync would not raise
a type conflict.

| Field | Type | Role |
|---|---|---|
| `rating` | FLOAT | user-facing rating 0-10 (declared identically to ratingtag) |
| `plex_userrating` | FLOAT | last synced value; merge base |
| `plex_ratingkey` | INTEGER | cached Plex track id (cache, not identity) |
| `plex_guid` | STRING | Plex guid, informational |
| `plex_lastratedat` | DATE | mirrored from Plex |
| `plex_lastviewedat` | DATE | mirrored from Plex |
| `plex_viewcount` | INTEGER | mirrored from Plex |
| `plex_skipcount` | INTEGER | mirrored from Plex |
| `plex_updated` | DATE | when this item last synced |
| `rating_updated` | DATE | when beets' rating last changed (see below) |

`rating_updated` maintenance: a `write` event listener stamps the current
time when the item being written has `rating` among its dirty fields, unless
the change was made by the sync itself (internal guard flag). The `write`
event is used because it fires before the store while the dirty set is still
populated; `database_change` fires after the dirty set is cleared and cannot
identify which field changed. Limitation: a rating change with tag writing
disabled (`beet modify -W`) is not stamped and falls back to the `conflict:`
policy on a both-sides conflict.

### Matching

1. Plex-side path for an item: `plex_dir + relpath(item.path, beets_dir)`.
   Prefixes are normalized (trailing slashes stripped); an item outside
   `beets_dir` is unmatched by definition and warned about once.
2. Per command run, build a path-to-track map from one paged sweep of
   `/library/sections/<id>/all?type=10` (plexapi `searchTracks` with a large
   `container_size`). The sweep's containers already include file paths,
   `userRating`, `lastRatedAt`, `viewCount`, `skipCount`, `lastViewedAt`;
   only attributes present in the sweep are accessed, so no per-track
   reloads ever fire. Every `Part.file` location of a track maps to it.
3. `plex_ratingkey` is a cache: stored on successful match, distrusted
   otherwise. If the cached key is absent from the sweep or its path no
   longer matches (file re-added, trash emptied, library rebuilt), the item
   is re-resolved by path and the cache silently updated.
4. Unmatched items (path not in Plex, typically not yet scanned) are counted
   and reported; commands proceed for the matched remainder.

Path comparison is byte-exact as stored (the library uses `asciify_paths`,
minimizing unicode surprises); no case folding.

### Rating and stats sync: `beet plex sync [QUERY]`

Three-way merge per matched item. base = `plex_userrating`, b = beets
`rating`, p = Plex `userRating`. All three are normalized to "unrated = 0.0"
before comparison (Plex reports unrated as None; beets may have 0.0 or an
absent field).

| b != base | p != base | action |
|---|---|---|
| no | no | none |
| no | yes | pull: set `rating` = p (0.0 when Plex is unrated), `try_write()` |
| yes | no | push: `track.rate(b)`, or `track.rate(None)` to clear when b is 0.0; this endpoint bumps Plex `lastRatedAt` |
| yes | yes | newest wins: compare `rating_updated` vs Plex `lastRatedAt`; if `rating_updated` is missing, use the `conflict:` config |

After the action succeeds (ordering contract: never before), the item's
base, stats mirrors, and `plex_updated` are updated and stored in one
`item.store()`.

Flags: `--pretend` (report, change nothing), `--pull` / `--push` (restrict
direction; the restricted direction's changes are left untouched, not
discarded).

Contract edges:

- A failed `rate()` call leaves base unchanged, so the next run retries; the
  sync is idempotent and resumable at item granularity.
- Rating cleared on either side propagates as a clear, not as "no change".
- The internal-change guard prevents the `write` listener from stamping
  `rating_updated` during pulls (which would turn every pull into a future
  conflict) and from re-entering itself.
- Float comparison is exact; both sides store plain floats and ratingtag's
  one-decimal read rounding keeps tag-derived values stable.

### Playlists: `beet plex playlists [NAME...] [--pretend]`

One-way beets to Plex. Per configured playlist: run the query with its sort,
resolve tracks via the path map, and make the Plex playlist match exactly
(same tracks, same order).

- Update strategy: if the existing playlist's ordered ratingKey list differs,
  delete and recreate in one batched create call. Rationale: Plex playlist
  item removal is one HTTP request per item and ambiguous for duplicate
  entries; recreate is O(1) requests and deterministic. Plex-side manual
  edits to these playlists are intentionally overwritten.
- An empty query result deletes the existing playlist (with a warning) and
  creates nothing.
- A same-named Plex smart playlist is never touched: warn and skip (the API
  refuses item manipulation on smart playlists anyway).
- A same-named non-audio playlist: warn and skip.
- Unmatched items are skipped with a warning naming the item.

### Collections: `beet plex collections [NAME...] [--pretend]`

One-way beets to Plex, track-typed collections. Per configured collection:
query, resolve, then diff against current collection items and apply batched
`addItems` / `removeItems`. Diff instead of recreate because collections are
library-global (visible to all accounts) and recreation would discard
Plex-side artwork and sort settings.

- An empty query result deletes the collection (with a warning).
- A same-named collection with a different subtype (album/artist) or a smart
  collection: warn and skip.
- Item order in collections is not managed.

### Auto-scan (replaces plexupdate)

Listeners: `item_imported`, `album_imported`, `item_moved`, `item_removed`.
Each collects affected directories (for moves: both source and destination
parents), translated to Plex-side paths, into a per-process set. At
`cli_exit` the set is deduplicated and one partial scan per directory is
fired: `section.update(path=...)`.

- If more than 20 distinct directories are queued, fall back to a single
  full section update instead.
- Plex being unreachable degrades to a warning; a beets command never fails
  because of Plex.
- `auto_scan: no` disables the listeners' network side entirely.
- Manual command: `beet plex scan [--full] [PATH...]` (PATHs are beets-side
  and get translated; no args with `--full` refreshes the whole section).

### Other commands

- `beet plex status`: connection check, library name/track count, matched vs
  unmatched item counts (runs the sweep, writes nothing).

### Error handling

- Connection/auth failure in a command raises `ui.UserError` with a clean
  message (no traceback).
- All event listeners wrap network work in try/except and log warnings.
- The plexapi server object is created lazily on first use and reused for
  the process lifetime.

## Testing

pytest with beets' own `beets.test.helper` harness (`PluginTestHelper`).
No live Plex needed for the suite; plexapi is faked at the object layer
(a small fake section/track/playlist/collection model). One optional live
smoke test gated behind an environment variable.

- ratingtag: round-trip tests on real temp media files (FLAC, MP3, MP4) via
  `create_mediafile_fixture`, covering every contract edge listed above.
- plex sync: table-driven tests over all merge cells including clears and
  both-changed with and without `rating_updated`; guard/reentrancy test for
  the `write`-event stamping listener.
- matching: prefix translation, stale-ratingkey re-resolution, multi-location
  tracks, out-of-library items.
- playlists/collections: diffing, empty-query deletion, smart/foreign
  name-collision skips, unmatched-item warnings.
- auto-scan: directory collection over import/move/remove events, the >20
  directory fallback, unreachable-server degradation.

## Repository layout

```
beets-plex/
  beetsplug/
    ratingtag.py
    plex/
      __init__.py      # plugin class, config, commands wiring
      match.py         # path mapping + sweep + resolution
      sync.py          # three-way rating/stats merge
      playlists.py
      collections.py
      scan.py          # auto-scan listeners + scan command
  tests/
  docs/superpowers/specs/
  pyproject.toml       # hatchling; deps: beets>=2.4, plexapi
  README.md
  LICENSE
```

Conventions: conventional commits, ruff (lint + format), pytest in CI via
GitHub Actions.

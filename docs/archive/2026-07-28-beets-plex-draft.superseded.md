> **Superseded (2026-07-28) by `docs/design.md` and `docs/roadmap.md`.**
> Retained as a historical record only. Not authoritative: it carries recalled
> API specifics, some of which later review found wrong. Do not build from it.

# beets-plex: design (superseded draft)

Date: 2026-07-28
Status: superseded — see `docs/design.md` and `docs/roadmap.md`

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

Packaging: `beetsplug` is an implicit namespace package (PEP 420, no
`__init__.py` in `beetsplug/`), dependencies `beets>=2.12` (the test suite
uses `beets.test.helper.PluginTestHelper`, present from 2.12) and `plexapi`.
The hatchling build backend arrives with the first plugin module, not with
the scaffolding: a wheel target for a directory that does not yet exist
builds a code-free wheel and reports success.
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
so that tag round-trips are stable and never trigger spurious sync pushes,
with two exceptions. A non-zero POPM byte clamps up to 0.1 rather than
rounding to 0.0. Byte 1 (one star in Windows Media Player) is 0.039, and
0.0 means unrated, so plain rounding would make the next write delete the
user's frame. And the Vorbis `RATING` comment cannot represent a value
below 1.0 at all, because writes clamp away from the legacy star range: a
disk value of `7` reads as 0.7, writes back as `10`, and re-reads as 1.0.
For a format that cannot represent the value, the stored value is
authoritative: after writing, re-read the tag and record what it holds as
both the beets rating and the sync base, so all three agree and no push is
generated for a rating the user never set.

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
- Accepted input ranges are per format: POPM is 0-255 by construction;
  Vorbis and MP4 accept `0 <= x <= 100`. The range check runs first, then
  the legacy mapping, which applies only to `0 < x <= 5` on the Vorbis
  comment. So `"150"` and `"-5"` are out of range, `"5"` is 10.0 by the
  legacy rule, and `"2.5"` is 5.0 rather than 0.25. Non-numeric or
  out-of-range values are ignored with a debug log.
- Round-trip stability: DB -> tag -> DB reproduces the same value after
  one-decimal rounding. The `RATING` comment cannot honour this below 1.0,
  because the legacy floor reserves 1-5 for star ratings: writes clamp up
  to `"10"` so a small value reads back as 1.0 rather than as 5 stars. MP4
  has no legacy rule and round-trips the whole range; POPM round-trips
  every half star. The 1.0 boundary needs its own test per format.
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
  prune: no                  # allow deleting a playlist or collection whose
                             # query now matches nothing (off: leave it)

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
identify which field changed. Limitation: a rating change that writes no tag is
not stamped and falls back to the `conflict:` policy on a both-sides
conflict. That covers `beet modify -W` and, for every command, a config
with `import.write: no`.

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
which avoids most unicode surprises); no case folding.

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
| yes | yes | newest wins: compare `rating_updated` vs Plex `lastRatedAt`; if either timestamp is missing, use the `conflict:` config |

Once the action has succeeded, and never before, the item's
base, stats mirrors, and `plex_updated` are updated and stored in one
`item.store()`.

Flags: `--pretend` (report, change nothing), `--pull` / `--push` (restrict
direction; the restricted direction's changes are left pending, not
discarded, and are counted as deferred in the summary so a restricted run
does not read as "nothing to do").

Contract edges:

- A failed `rate()` call leaves base unchanged, so the next run retries; the
  sync is idempotent and each item is retried on its own.
- Rating cleared on either side propagates as a clear, not as "no change".
- The internal-change guard prevents the `write` listener from stamping
  `rating_updated` during pulls (which would turn every pull into a future
  conflict) and from re-entering itself.
- Float comparison is exact; both sides store plain floats and ratingtag's
  one-decimal read rounding keeps tag-derived values stable, except where
  the format cannot represent the value (see the media-field section), in
  which case the stored value becomes the base rather than causing a push.

### Playlists: `beet plex playlists [NAME...] [--pretend]`

One-way beets to Plex. Per configured playlist: run the query with its sort,
resolve tracks via the path map, and make the Plex playlist match exactly
(same tracks, same order).

- Update strategy: if the existing playlist's ordered ratingKey list differs,
  delete and recreate in one batched create call. Rationale: Plex playlist
  item removal is one HTTP request per item and ambiguous for duplicate
  entries; recreate is O(1) requests and deterministic. Plex-side manual
  edits to these playlists are intentionally overwritten.
- An empty query result leaves the existing playlist alone with a warning,
  because a query matching nothing is usually a typo. It deletes the
  playlist only when `prune:` is enabled.
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

- An empty query result leaves the collection alone with a warning, and
  deletes it only when `prune:` is enabled (as for playlists).
- A same-named collection with a different subtype (album/artist) or a smart
  collection: warn and skip.
- Item order in collections is not managed.

### Auto-scan (replaces plexupdate)

Listeners: `item_imported`, `album_imported`, `item_moved`, `item_removed`.
Each adds the affected directories to a per-process set, translated to
Plex-side paths. A move contributes both its source and destination parent. At
`cli_exit` the set is deduplicated and one partial scan per directory is
fired: `section.update(path=...)`.

- If more than 20 distinct directories are queued, fall back to a single
  full section update instead.
- Plex being unreachable degrades to a warning; a beets command never fails
  because of Plex.
- `auto_scan: no` disables the listeners' network side entirely.
- Manual command: `beet plex scan [--full] [--pretend] [PATH...]` (PATHs are
  beets-side and get translated; no args with `--full` refreshes the whole
  section; `--pretend` reports without asking Plex to scan).

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

- ratingtag: round-trip tests on real temp media files (FLAC, MP3, MP4, and
  WMA as the format with no rating tag), copied from this repo's own
  `tests/rsrc/full.<ext>`, covering every contract edge listed above. Note
  that beets' `create_mediafile_fixture` and `add_album_fixture` helpers read
  `beets.test._common.RSRC`, which the wheel does not ship, so they raise in
  a downstream suite; that is why the fixtures live here.
- plex sync: table-driven tests over all merge cells including clears and
  both-changed with and without `rating_updated`; guard/reentrancy test for
  the `write`-event stamping listener.
- matching: prefix translation, stale-ratingkey re-resolution, multi-location
  tracks, out-of-library items.
- playlists/collections: diffing, the empty-query prune guard (and that it
  deletes only when `prune:` is set), smart/foreign name-collision skips,
  unmatched-item warnings.
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
  pyproject.toml       # deps: beets>=2.12, plexapi, mediafile, mutagen;
                       # hatchling from the first plugin module onward
  README.md
  LICENSE
```

Conventions: conventional commits. CI runs ruff (lint and format) and
pytest via GitHub Actions.

## Delivery: one plugin area per pull request

The first attempt at this design was built as a single branch of 32 commits
and roughly 7,500 lines, then reviewed. That is the wrong order. Three rounds
of review afterwards found about 30 real defects, and two of those were
introduced by fixes from the round before, because a diff that size cannot be
reviewed usefully by a person or a bot.

The work ships as six pull requests, each closing its own issue and
merged before the next begins:

1. Project scaffolding, CI, test fixtures, and this document
2. `ratingtag`: the rating field and its file-tag storage
3. `plex` core: plugin skeleton, config, path matching, `status`
4. Rating sync and the play-statistics pull
5. Playlists and collections
6. Auto-scan on import, move, and remove

## Failure-mode catalogue

Every entry below is a defect the first attempt actually shipped and review
later caught. They are recorded as requirements so the reimplementation
designs them in rather than rediscovering them. Each needs a test.

### Ordering

- A pull must write the file tag **before** advancing `plex_userrating`. The
  other order records a sync that never reached the file; the rating is then
  lost with nothing left to retry from.
- A push must count as pushed only **after** `track.rate()` returns. Counting
  first reports failures as successes.
- A playlist rebuild must create the replacement **before** deleting the old
  one, or a failed create leaves the user with nothing.
- Any "leave it alone unless pruning" guard must come **before** any deletion
  in the same function, including duplicate cleanup.
- **Every** event-driven entry point must read config inside its try, not
  only the obvious one: `scan.flush` from `cli_exit`, and the path-queueing
  helper called from `item_imported`, `album_imported`, `item_moved`, and
  `item_removed`. beets does not guard listeners, so a malformed
  `beets_dir`/`plex_dir` breaks the user's `beet import` rather than the
  Plex scan, and because this one does no network work the first version
  of it went unguarded.

### Lifecycle and reentrancy

- `suspend_stamp` must be a counter, not a flag, so a nested use does not
  re-arm stamping when the inner block exits.
- `flush()` must be idempotent: `cli_exit` can fire after an explicit flush.
- mediafile field registrations are class-level and survive plugin reloads,
  so a style must read config **at use time**. Capturing `popm_email` at
  construction means the first value seen in a process wins forever.
- Re-registering an existing media field must be tolerated, but a field
  registered by a *different* plugin must warn rather than be swallowed.

### Failure paths

- `item.try_write()` returns True for formats with no rating style (WMA,
  AIFF, WAV): it writes nothing. A pull must verify the tag actually holds
  the value, or a later `beet update` reads it back as unrated and the next
  sync pushes that phantom clear to Plex. The check must be skipped in two
  cases, and both matter: when `ratingtag` is not enabled (test `"rating"
  in Item._media_fields`), because ratings are database-only then; and when
  this item's format has no rating storage style, because the write
  correctly stored nothing. Keying the exemption on the plugin alone leaves
  the second cell uncovered, so with `ratingtag` enabled every pull on a
  WMA, AIFF, or WAV item fails forever. A test must cover a pull on the
  `full.wma` fixture with `ratingtag` enabled and assert it is not counted
  as a failure.
- One failing entry must not cancel the entries behind it, in scans,
  playlists, and collections alike. The likeliest failures are a refused
  resolve (`UserError`) and a malformed query (`InvalidQueryError`), not
  only server faults.
- Rating pushes must catch Plex and transport errors but not mask
  programming errors.
- Sync failures must reach the exit status, or a scheduled run reports
  success while every push failed.

### Reporting accuracy

- Every command that can mutate must honour `--pretend` on **every** branch
  that mutates, including duplicate cleanup and the "nothing changed" path,
  not only the obvious create/update branch. A dry-run flag that mutates is
  the worst kind of defect, because users reach for it when they do not
  trust the config.
- Items skipped by `--pull` / `--push` must be counted as deferred. Dropping
  them from the summary makes a restricted run read as "nothing to do".
- A conflict resolved by the `conflict:` policy rather than by recency must
  be reported, so the user can tell that a timestamp was missing.
- A push must be counted only after the call to Plex succeeds, and a
  playlist "removed" message must not be logged when no playlist existed.

### Boundaries

- The path prefix check is inclusive of the library root: `beets_dir` itself
  translates to `plex_dir`, so `beet plex scan <beets_dir>` works rather
  than reporting the root as outside the library.

### Destructive operations

- An empty query result must not delete a playlist or collection by default.
  A query matching nothing is far more often a typo than an instruction to
  delete. Deletion requires an explicit `prune` setting.
- A query that matched items but resolved **none** of them in Plex is a
  misconfiguration, not an empty result, and must be an error.
- A missing `query` key must be rejected. Defaulting it to the empty string
  silently selects the entire library.
- Helpers shared between playlists and collections must name the entry type
  in their errors. A shared selector that hardcodes "playlist" reports
  `plex collections BadName` as an unknown playlist.
- Duplicate remote objects sharing a title must all be handled, not just the
  first, or the extras are invisible to every later run.

### Data fidelity

- Unrated is `0.0` everywhere. A rated POPM byte must never round down to
  `0.0`: byte 1 is Windows Media Player's one star, and treating it as
  unrated makes the next write delete the user's frame.
- The Vorbis legacy floor (values of 5 or less read as 0-5 stars) applies to
  the `RATING` comment only. Applying it to MP4 promotes every rating below
  1.0 to 1.0 and breaks the round trip.
- Mirror fields must be assigned unconditionally, so clearing a rating or
  history in Plex clears the mirror instead of leaving a stale value that
  queries still match.
- plexapi's `rate()` does not reload the object, so after a push the track's
  own `lastRatedAt` is one rating behind and must not be mirrored.
- `rating_updated` must be stamped from the `write` event: `database_change`
  fires after beets clears the dirty set and cannot tell what changed.
- The conflict fallback fires when **either** timestamp is missing, not just
  the beets one; Plex drops `lastRatedAt` when a rating is cleared.

### Test-suite requirements

- Test doubles must be no more forgiving than the real API. `FakeTrack.rate`
  must not refresh local state, and the create calls must require `section`
  positionally and reject empty item lists, because plexapi does.
- Sync tests need real files on disk: a suite using non-existent paths hid
  the write-ordering defect entirely.
- `Item._types` is cached per process, so tests must reset
  `cached_classproperty.cache` or a plugin-free test freezes an empty type
  map and silently downgrades typed queries to substring matches.
- Sort-order tests must use a sort that contradicts beets' default, or they
  pass with the sort dropped.
- The recency tie-break must be exercised through the database, not only
  with hand-passed floats. Hand-passed floats pass whether or not
  `rating_updated` is declared `types.DATE`, so the declaration can be
  dropped and every recency comparison silently degrades to string ordering
  with a green suite.
- The event wiring itself needs a test: with only direct calls to the flush
  helper, the `cli_exit` registration can be deleted and the whole auto-scan
  feature disappears with every other scan test still passing.
- `server()` needs coverage of the URL it builds, the token it passes, and
  the clean error on a refused connection. Without it, `secure: yes` can be
  ignored and the token travels in cleartext unnoticed.
- beets' bundled test fixtures are not shipped in the wheel; the suite needs
  its own audio fixtures.

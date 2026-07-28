# beets-plex: design

Date: 2026-07-28
Status: revised design, not yet built
Revision: 2 (see "Revision history")

## Context

Synchronize a beets library (v2.12+) with a Plex Media Server. Beets and Plex
index the same files: beets manages `/mnt/music` locally, and the Plex server
mounts the same share (at `/mnt/music` on the server as well, though the design
treats the prefix as configurable). This makes file-path matching exact and
deterministic; no fuzzy matching is needed.

Prior art and why it is not used:

- `beets-plexsync` (arsaboo): drifted into AI discovery features, with a large
  dependency surface (LLM agents, scrapers, vector scoring, a side SQLite
  cache). The conventions worth keeping are its beets field names and the
  shared `plex:` config section, both of which this design adopts where the
  semantics genuinely match.
- Built-in `plexupdate` plugin: only triggers a full section refresh. Replaced
  here by targeted partial scans.
- `sync-plex-music-ratings.py` (own prior script): synced Plex ratings with
  file tags directly (MP3 POPM, FLAC `RATING` 0-100). Its tag conventions are
  adopted by the `ratingtag` plugin.

## Goals

1. Update Plex when beets imports, moves, copies, links, or removes files
   (partial scans).
2. Two-way rating sync between beets and Plex, newest change wins.
3. One-way pull of Plex play statistics into beets fields, for every matched
   item, independent of whether its rating changed.
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

## Verified platform facts

Every fact below was checked against the installed packages on 2026-07-28
(beets 2.13.0, mediafile 0.17.0, plexapi 4.18.2, mutagen 1.48.1) by reading or
running the installed source, not from recall. Implementation may rely on
these without re-deriving them. Anything *not* in this list and not in "Open
decisions" is ordinary API usage that the implementer must still look up.

| # | Fact | Where checked |
|---|---|---|
| F1 | `plugins.types()` compares type objects with `!=` and `dbcore.types.Type` defines no `__eq__`. Two plugins declaring the same field each with a *fresh* `types.Float()` raise `PluginConflictError`; only the shared module-level singleton `types.FLOAT` compares equal. | `beets/plugins.py:types()`; `t.FLOAT == t.Float()` is `False` |
| F2 | `PlexPartialObject.__getattribute__` reloads the object whenever the requested attribute's value is `None` or `[]` and the object is partial. `_DONT_RELOAD_FOR_KEYS` is only `{'key', 'centroid', 'sourceURI'}`; `USER_DONT_RELOAD_FOR_KEYS` is an empty module-level set callers may add to. | `plexapi/base.py:655` |
| F3 | Plex omits `userRating` for unrated tracks, `lastRatedAt` when never rated, and `lastViewedAt`/`viewCount`/`skipCount` when never played. Combined with F2, naive attribute access on sweep results issues one HTTP request per unrated track. | F2 plus Plex XML behaviour; the exact attribute set is Open decision D1 |
| F4 | `MediaField.styles(mutagen_file)` yields the styles whose `formats` list contains `mutagen_file.__class__.__name__`. This is a mechanical test of whether a field can be stored in a given file. | `mediafile/fields.py:MediaField.styles` |
| F5 | `MP3StorageStyle.formats == ['MP3', 'AIFF', 'DSF', 'WAVE']` and base `StorageStyle.formats == ['FLAC', 'OggOpus', 'OggTheora', 'OggSpeex', 'OggVorbis', 'OggFlac', 'APEv2File', 'WavPack', 'Musepack', 'MonkeysAudio']`. A POPM style built on `MP3StorageStyle` therefore also writes AIFF, DSF and WAVE. | read from the classes |
| F6 | Among the formats mediafile recognises (`mediafile.TYPES`), only ASF/Windows Media falls outside both style lists above. | F5 plus `mediafile.TYPES` |
| F7 | `Item.write()` sends the `write` event *before* opening the file, and `Item.try_sync()` calls `try_write()` before `store()`. The item's `_dirty` set is still populated when the `write` listener runs. | `beets/library/models.py:Item.write`, `Item.try_sync` |
| F8 | `Album.try_sync()` calls `self.store(inherit=...)` *first* and only then `item.try_sync()` per item. Album-level field inheritance does not mark the loaded item's field dirty. | `beets/library/models.py:634-644` |
| F9 | beets emits `item_copied`, `item_linked` and `item_hardlinked` alongside `item_moved`, all from `Item.move()`. `item_removed` is sent by `Item.remove()` *before* the file is deleted, so the path is still valid in the listener. | `beets/library/models.py:1048-1070`, `Item.remove` |
| F10 | `plexapi.utils.toDatetime` builds a naive local `datetime` (module default `DATETIME_TIMEZONE is None`). `dt.timestamp()` converts back to the correct epoch seconds whether the datetime is naive-local or aware. | `plexapi/utils.py:_parseTimestamp` |
| F11 | `RatingMixin.rate(value)` PUTs `/:/rate`, validates `0 <= value <= 10`, sends `-1` for `rate(None)`, returns `self` and does **not** reload the object. | `plexapi/mixins.py:RatingMixin.rate` |
| F12 | `LibrarySection.update(path=...)` issues `GET /library/sections/<key>/refresh?path=<quoted>` and returns immediately; there is no completion signal. | `plexapi/library.py:LibrarySection.update` |
| F13 | `BeetsPlugin.add_media_field(name, descriptor)` calls `mediafile.MediaFile.add_field` and adds the name to `library.Item._media_fields`. Both are class-level and survive plugin reload. | `beets/plugins.py:add_media_field` |
| F14 | `createPlaylist(title, section=None, items=None, ...)` — `section` is **optional**. `createCollection(title, section, items=None, ...)` — `section` is **required**. The two are not symmetric, and a fake that requires it for both is stricter than the real API. | `inspect.signature` on `PlexServer.createPlaylist` / `createCollection` |
| F15 | mediafile re-exports neither `POPM` nor `MP4FreeForm`. ratingtag imports them from `mutagen.id3` and `mutagen.mp4` directly, so mutagen is a direct dependency, not a transitive one. | `hasattr(mediafile, "POPM")` is `False` |
| F16 | The mutagen class names the fixtures produce, which are what `MediaField.styles()` matches on: `full.mp3` → `MP3`, `full.aiff` → `AIFF`, `full.wav` → `WAVE`, `full.flac` → `FLAC`, `full.opus` → `OggOpus`, `full.m4a` → `MP4`, `full.wma` → `ASF`. | `mutagen.File(path).__class__.__name__` on the fixtures |

## Open decisions

Items that cannot be settled by reading installed source. Each names the pull
request that must close it, and a default to implement if the check is
inconclusive. Closing one means editing this document in that pull request.

| ID | Question | Owner | Default if unresolved |
|---|---|---|---|
| D1 | Does a music section listing (`/library/sections/<id>/all?type=10`) carry `Media`/`Part` children, and which of `userRating`, `lastRatedAt`, `lastViewedAt`, `viewCount`, `skipCount`, `guid` are present? Determines whether the sweep can supply file paths and stats at all, and which names must go into `USER_DONT_RELOAD_FOR_KEYS`. | PR 3 | Suppress reload for all six names plus `media`, and fail the sweep loudly if the first page yields tracks with no parts (see "Matching"). |
| D2 | Does `section.update(path=...)` accept a path that is a *directory* below the section root and scan only it, and does it error or silently no-op on a path outside the section? | PR 6 | Treat any response as success, log at info, and rely on the >`max_scan_dirs` fallback for correctness. |
| D3 | Does Plex clear `lastRatedAt` when a rating is cleared via `rate(None)`, or retain the previous value? Affects the "either timestamp missing" branch. | PR 4 | Assume it is cleared; the missing-timestamp branch already falls back to the `conflict:` policy. |
| D4 | Is `container_size` honoured by `MusicSection.searchTracks` for a full-section sweep, and what is a safe page size for a library of this size? | PR 3 | 500, configurable via `plex.container_size`. |

## Architecture: two plugins, one package

File-tag rating storage and Plex synchronization are orthogonal concerns, so
they are separate plugins shipped in one repo and one pip package:

- `beetsplug/ratingtag.py`: owns the `rating` field and its file-tag
  representation. No network code.
- `beetsplug/plex/`: everything Plex (matching, sync, playlists, collections,
  scans). Touches only the `rating` DB field; never writes tags itself.

### The composition interface

The two plugins are not fully independent, and pretending otherwise is what
produced the format-exemption defect recorded in the failure catalogue. There
is exactly one interface, one-directional, and it is named:

```python
# beetsplug/ratingtag.py
FIELD = "rating"

def rating_is_tagged(item) -> bool:
    """True when the rating media field is registered AND this item's file
    format has a storage style that can hold it.

    Uses mediafile.MediaField.styles() (F4) rather than a format allowlist,
    so AIFF, DSF, WAVE, APE, WavPack, Musepack and Monkey's Audio are
    classified by what the styles actually declare (F5, F6).
    """

def tag_image(value: float, item) -> float:
    """The value that reading the tag back would yield after writing `value`
    to this item's file: `value` itself for every format and every rating,
    except the 0.1-0.5 range on a Vorbis comment in legacy mode, which the
    write clamps to 0.6. Returns `value` unchanged when the field is not
    tagged at all.
    """
```

`beetsplug/plex/` imports these two functions and calls them in exactly two
places: `rating_is_tagged` in the post-write verification of a rating pull,
and `tag_image` in the merge's "did beets change?" test. Both must tolerate
`ratingtag` being installed but not enabled, which `rating_is_tagged` reports
by returning `False` when `FIELD not in Item._media_fields`.

Both plugins declare `rating` as `beets.dbcore.types.FLOAT` — the module-level
singleton, never a fresh `types.Float()`, because a fresh instance raises
`PluginConflictError` (F1). A test loads both plugins together and asserts no
conflict; it is the only thing standing between this design and a crash on
every command.

Packaging: `beetsplug` is an implicit namespace package (PEP 420, no
`__init__.py` in `beetsplug/`), dependencies `beets>=2.12` (the test suite
uses `beets.test.helper.PluginTestHelper`, present from 2.12) and `plexapi`.
The hatchling wheel target arrives with the first plugin module, not with the
scaffolding: a wheel target for a directory that does not yet exist builds a
code-free wheel and reports success. No entry points; beets discovers plugins
by module name. During development the repo's `beetsplug/` dir is added to
`pluginpath`.

## Plugin: ratingtag

### Field

Declares item field `rating`: `types.FLOAT`, scale 0-10 (Plex-native; 0-5
stars times two). "Unrated" is represented as 0.0 or an absent field; the two
are equivalent everywhere. Rationale: beets' `Item.write()` only writes fields
present on the item, so an absent field cannot clear a stale tag, and Plex's
own UI minimum is a half star (1.0), so 0 carries no rating information.

A `types: rating: int` line in the user's config makes the `types` plugin
declare the same field with a different type, which raises
`PluginConflictError` at load. The plugin checks for it at init
(`config['types']['rating'].exists()`) and raises a `ui.UserError` naming the
line to remove, rather than letting the generic conflict error surface.

### Media field (tag storage)

Registered via `add_media_field("rating", ...)` so `beet write`, `beet
update`, and scrub-rewrite all handle it as a normal tag field. mediafile has
no built-in rating support, so custom storage styles are implemented:

| Style | Applies to (F5, F6) | Tag | Scale on disk |
|---|---|---|---|
| POPM, subclass of `MP3StorageStyle` | MP3, AIFF, DSF, WAVE | `POPM` frame, email from config `popm_email` | 0-255 |
| Vorbis comment, subclass of `StorageStyle` | FLAC, all Ogg variants, APEv2, WavPack, Musepack, Monkey's Audio | `RATING` comment | 0-100 |
| MP4 freeform, subclass of `MP4StorageStyle` | MP4/M4A | `----:com.apple.iTunes:RATING` | 0-100 |
| — | Windows Media (ASF) only | not stored | — |

The third column of each row is the style's `formats` list, and it is the
single source of truth: nothing in this repository may hardcode a parallel
list of "formats that store ratings" (see failure catalogue, "Failure paths").

Conversions to and from the canonical 0-10 DB value round to one decimal on
read so that tag round-trips are stable and never trigger spurious sync
pushes, with one exception: a non-zero POPM byte clamps up to 0.1 rather than
rounding to 0.0, because byte 1 is Windows Media Player's one star and 0.0
means unrated, so plain rounding would make the next write delete the user's
frame.

### The Vorbis legacy-star rule

Some taggers write `RATING` on a 0-5 star scale rather than 0-100. Reading a
disk value of `4` as 0.4 rather than as two stars is wrong for those files;
reading it as two stars is wrong for a genuine 0-100 file rated 4. The
ambiguity is inherent, so it is a config switch:

- `vorbis_legacy_stars: no` (**default**): `RATING` is always 0-100. The
  entire 0-10 DB range round-trips exactly. No clamping anywhere.
- `vorbis_legacy_stars: yes`: on **read**, a value of `0 < x <= 5` is
  interpreted as stars and doubled. Writes still use 0-100, so DB values 0.1
  to 0.5 (disk 1 to 5) would read back as stars; writes clamp them up to disk
  `6` (0.6). Nothing else in the range is affected: 0.6 through 10.0 write as
  6 through 100 and read back unchanged.

The previous revision of this document claimed the `RATING` comment "cannot
represent a value below 1.0 at all" and gave a worked example (disk 7 reads
0.7, writes back as 10) that contradicts its own 0-100 rule. The affected
range is 0.1-0.5, only in legacy mode, and by default there is no affected
range at all.

### Config

```yaml
ratingtag:
  popm_email: ''             # POPM identifier; must match existing tags to be read
  vorbis_legacy_stars: no    # read RATING values <= 5 as 0-5 stars
```

### Contract edges (each gets a test)

- POPM: only the frame matching `popm_email` is read; other POPM frames are
  ignored and preserved. Writing updates the matching frame or adds one.
- A tag value of 0 (POPM 0, `RATING` "0") is read as unrated, following the
  common player convention. Writing an unrated value (0.0) removes the tag
  entirely rather than writing a literal 0.
- Accepted input ranges are per format: POPM is 0-255 by construction; Vorbis
  and MP4 accept `0 <= x <= 100`. The range check runs first, then the legacy
  mapping, which applies only to `0 < x <= 5`, only on the `RATING` comment,
  and only when `vorbis_legacy_stars` is on. So `"150"` and `"-5"` are out of
  range; `"5"` is 0.5 by default and 10.0 in legacy mode; `"2.5"` is 0.25 by
  default. Non-numeric or out-of-range values are ignored with a debug log.
- Round-trip stability: DB -> tag -> DB reproduces the same value after
  one-decimal rounding, for every format, across the whole 0-10 range, with
  the single documented exception of 0.1-0.5 in legacy mode. The 1.0 boundary
  needs its own test per format.
- `rating_is_tagged` returns `False` when the plugin is not enabled, `False`
  for an ASF file, and `True` for MP3, FLAC, M4A, AIFF and WAVE fixtures.
- `tag_image` is the identity for every format and every value except
  0.1-0.5 on a Vorbis comment with `vorbis_legacy_stars` on, where it returns
  0.6, and it is the identity whenever the field is not tagged. Its test
  writes the value to a real fixture and reads it back, so it cannot drift
  away from what the styles actually do.
- Formats without a defined style: `item.write()` succeeds and writes nothing
  rating-related.
- Migration path: `beet update <query>` re-reads tags and populates `rating`
  from existing POPM/RATING tags; no custom import command needed.

## Plugin: plex

### Config

Extends the existing shared `plex:` section (compatible with the built-in
plexupdate's keys, which this plugin replaces; remove `plexupdate` from the
plugins list). Every key with its default:

```yaml
plex:
  host: localhost
  port: 32400
  token: ''                  # required; marked redacted for `beet config` output
  library_name: ''           # required
  secure: no                 # https; certificates are always verified
                             # (plexupdate's ignore_cert_errors is
                             # deliberately not supported)

  beets_dir:                 # default: beets' own `directory`
  plex_dir:                  # path prefix as the Plex server sees it;
                             # default: same as beets_dir
  container_size: 500        # sweep page size (D4)
  auto_scan: yes             # partial scans after import/move/copy/link/remove
  max_scan_dirs: 20          # above this many queued dirs, do one full scan
  conflict: plex             # both-sides-changed fallback: plex | beets
  clock_skew: 300            # seconds; timestamps closer than this are a tie
  prune: no                  # allow deleting a playlist or collection whose
                             # query now matches nothing (off: leave it)

  playlists: []
  collections: []
```

`playlists` and `collections` entries are mappings with a required `name` and
a required `query`. A missing `query` is an error: defaulting it to the empty
string silently selects the entire library.

```yaml
  playlists:
    - name: Top 2000 all
      query: 'top2000_score:1.. top2000_score-'
  collections:
    - name: Top2000
      query: 'top2000_score:1..'
```

### Beets fields (typed flexible attributes)

| Field | Type | Role |
|---|---|---|
| `rating` | `types.FLOAT` | user-facing rating 0-10 (declared identically to ratingtag, F1) |
| `plex_ratingbase` | `types.FLOAT` | merge base: the value beets and Plex last agreed on |
| `plex_userrating` | `types.FLOAT` | mirror of Plex's current `userRating` |
| `plex_ratingkey` | INTEGER | cached Plex track id (cache, not identity) |
| `plex_guid` | STRING | Plex guid, informational |
| `plex_lastratedat` | DATE | mirrored from Plex |
| `plex_lastviewedat` | DATE | mirrored from Plex |
| `plex_viewcount` | INTEGER | mirrored from Plex |
| `plex_skipcount` | INTEGER | mirrored from Plex |
| `plex_updated` | DATE | when this item last synced |
| `rating_updated` | DATE | when beets' rating last changed (see below) |

Revision 1 used `plex_userrating` as the merge base, on the grounds that the
name matches beets-plexsync. It does, but plexsync's field means "Plex's
current rating", not "the last synced value". Reusing the name for a different
meaning would reinterpret existing rows as a base they never were, and two
plugins loaded together would each corrupt the other's reading. The merge base
is therefore its own field, `plex_ratingbase`, and `plex_userrating` keeps the
plexsync meaning as a mirror. Names that survive unchanged (`plex_lastratedat`
and friends) keep existing smartplaylist queries working.

`rating_updated` maintenance: a `write` event listener stamps the current time
when the item being written has `rating` among its dirty fields, unless the
change was made by the sync itself (internal guard counter). The `write` event
is used because it fires before the store while the dirty set is still
populated (F7); `database_change` fires after the dirty set is cleared and
cannot identify which field changed.

Known coverage gaps, all of which degrade "newest wins" to the `conflict:`
policy rather than corrupting data, and all of which the sync reports when it
falls back:

- `beet modify -W`, and any command under a config with `import.write: no`:
  no `write` event fires at all.
- `beet modify -a rating=N`: `Album.try_sync` stores the album before syncing
  its items, and inherited fields are not marked dirty on the loaded item
  (F8), so the listener sees nothing.

### Matching

1. Plex-side path for an item: `plex_dir + relpath(item.path, beets_dir)`.
   Prefixes are normalized (trailing slashes stripped); the check is inclusive
   of the library root, so `beets_dir` itself translates to `plex_dir`. An
   item outside `beets_dir` is unmatched by definition and warned about once.
2. Per **process** (not per command; one `beet` invocation running both
   playlists and collections sweeps once), build a path-to-track map from one
   paged sweep of the section, page size `container_size`.
3. The sweep must not trigger per-track reloads. plexapi reloads a partial
   object whenever an accessed attribute is `None` or `[]` (F2), and Plex
   omits exactly the attributes this design reads when they are unset (F3),
   so the common case — an unrated, never-played track — would issue one HTTP
   request per track. Before the sweep, the plugin adds the names it reads to
   `plexapi.base.USER_DONT_RELOAD_FOR_KEYS`. This is a process-global mutation
   of a third-party module and is documented as such at the call site. The
   exact name list is Open decision D1.
4. Suppressing reloads makes a missing attribute silently read as `None`
   instead of slowly reading correctly, so the sweep validates its own
   assumption: if the first page yields tracks with no `Media`/`Part`
   children, the sweep cannot supply file paths at all, and the command fails
   with a `ui.UserError` explaining that the server did not return file
   locations. It never degrades to per-track fetching silently.
5. Every `Part.file` location of a track maps to it. If two tracks claim the
   same path (duplicate entries, overlapping libraries), that path is
   **ambiguous**: it is warned about once and treated as unmatched everywhere,
   in sync, playlists and collections alike. Last-write-wins on the map would
   make which track gets rated depend on server ordering.
6. `plex_ratingkey` is a cache: stored on successful match, distrusted
   otherwise. If the cached key is absent from the sweep or its path no longer
   matches (file re-added, trash emptied, library rebuilt), the item is
   re-resolved by path and the cache silently updated.
7. Unmatched items (path not in Plex, typically not yet scanned) are counted
   and reported; commands proceed for the matched remainder.

Path comparison is byte-exact as stored (the library uses `asciify_paths`,
which avoids most unicode surprises); no case folding.

### Rating and stats sync: `beet plex sync [QUERY]`

Two independent steps run for every matched item. Conflating them was a defect
in revision 1: it gated the statistics pull on a rating action having
occurred, so goal 3 never ran for the overwhelmingly common case of an item
whose rating had not changed on either side.

**Step 1, statistics mirror — unconditional.** For every matched item, assign
`plex_ratingkey`, `plex_guid`, `plex_userrating`, `plex_lastratedat`,
`plex_lastviewedat`, `plex_viewcount`, `plex_skipcount` and `plex_updated`
from the sweep, unconditionally, including assigning the empty value when Plex
has none, so that clearing a rating or history in Plex clears the mirror
rather than leaving a stale value that queries still match.

**Step 2, rating merge — three-way.** base = `plex_ratingbase`, b = beets
`rating`, p = Plex `userRating`. All three are normalized to "unrated = 0.0"
before comparison (Plex reports unrated as `None`; beets may have 0.0 or an
absent field).

"b changed" is `b != base and b != tag_image(base, item)`. The second clause
matters only where the file format cannot store the exact value — the 0.1-0.5
range on a Vorbis comment in legacy mode. Without it, a later `beet update`
reads the clamped value back into `rating`, the merge reads that as a
beets-side edit, and the clamped value is pushed to Plex, degrading a rating
the user never touched.

| b changed | p != base | action |
|---|---|---|
| no | no | none |
| no | yes | **pull**: set `rating` = p (0.0 when Plex is unrated), then write the tag (see ordering below) |
| yes | no | **push**: `track.rate(b)`, or `track.rate(None)` to clear when b is 0.0 (F11) |
| yes | yes | **newest wins**, by the timestamp rule below |

Timestamps. Comparison happens in epoch seconds as floats. `rating_updated` is
a beets `DATE` and already holds epoch seconds; Plex's `lastRatedAt` is
converted with `dt.timestamp()`, which is correct for both the naive-local
datetimes plexapi produces by default and for aware ones (F10). The two clocks
belong to different machines, so a difference within `clock_skew` seconds is a
tie. The `conflict:` policy decides when either timestamp is missing or the
difference is within `clock_skew`, and every such resolution is reported, so
the user can tell a policy decision from a recency decision.

Ordering, which is load-bearing:

- A **pull** writes the file tag *before* advancing `plex_ratingbase`. The
  other order records a sync that never reached the file, and the rating is
  then lost with nothing left to retry from.
- After the write, the pull verifies the tag actually holds the value, because
  `item.try_write()` returns `True` for a format with no applicable style —
  it wrote nothing. The verification is skipped in exactly two cases, both of
  which `rating_is_tagged(item)` reports in one call: ratingtag not enabled
  (ratings are database-only), and this file's format having no applicable
  style (the write correctly stored nothing). Keying the exemption on the
  plugin alone, or on a hardcoded format list, leaves the other cell
  uncovered; F5 shows why a hardcoded list gets AIFF and WAVE wrong.
- When verification finds a different value than intended — only possible in
  Vorbis legacy mode, for DB values 0.1-0.5 — the **Plex value stays
  authoritative**: `rating` and `plex_ratingbase` both hold the pulled value,
  and the item is reported once as having a lossy tag. Convergence comes from
  the `tag_image` clause above, not from adopting the clamped value. Adopting
  it instead, as revision 1 specified, either degrades the user's rating on
  both sides or re-pulls and rewrites the same file on every run, depending on
  which of the two the base is set to.
- A **push** counts as pushed only *after* `track.rate()` returns. Counting
  first reports failures as successes. `rate()` does not reload the object
  (F11), so the track's own `lastRatedAt` is one rating behind and must not be
  mirrored: after a successful push, `plex_userrating` is the pushed value and
  `plex_lastratedat` is the local push time. The next run overwrites both with
  the server's real values, which is self-healing by construction.
- `plex_ratingbase` and `plex_updated` advance only after the action
  succeeded, so a failed action is retried on the next run. Each item is
  independent: one failure never cancels the items behind it.

Flags: `--pretend` (report, change nothing, on *every* mutating branch),
`--pull` / `--push` (restrict direction; the restricted direction's changes
are left pending, not discarded, and are counted as deferred in the summary so
a restricted run does not read as "nothing to do").

Exit status: per-item failures are collected, the summary is printed, and the
command then raises `ui.UserError` naming the failure count, so a scheduled
run cannot report success while every push failed.

### Playlists: `beet plex playlists [NAME...] [--pretend]`

One-way beets to Plex. Per configured playlist: run the query with its sort,
resolve tracks via the path map, and make the Plex playlist match exactly
(same tracks, same order).

- Update strategy: if the existing playlist's ordered ratingKey list differs,
  create the replacement first and delete the old one only after the create
  succeeds. A failed create must never leave the user with nothing. Recreate
  rather than incremental edit because Plex playlist item removal is one HTTP
  request per item and ambiguous for duplicate entries. The cost is real and
  is accepted: recreation drops playlist artwork, share settings and the
  playlist's ratingKey. Plex-side manual edits to these playlists are
  intentionally overwritten.
- An empty query result leaves the existing playlist alone with a warning,
  because a query matching nothing is usually a typo. It deletes the playlist
  only when `prune:` is enabled. This guard runs *before* any deletion in the
  same function, including duplicate cleanup.
- A query that matched beets items but resolved **none** of them in Plex is a
  misconfiguration (usually a wrong `plex_dir`), not an empty result, and is
  an error.
- A same-named Plex smart playlist is never touched: warn and skip (the API
  refuses item manipulation on smart playlists anyway).
- A same-named non-audio playlist: warn and skip.
- Duplicate remote playlists sharing a title are all handled, not just the
  first, or the extras stay invisible to every later run.
- Unmatched items are skipped with a warning naming the item.
- One failing entry never cancels the entries behind it. The likely failures
  are a refused resolve (`UserError`) and a malformed query
  (`InvalidQueryError`), not only server faults.
- "Removed" is logged only when something was actually removed.

### Collections: `beet plex collections [NAME...] [--pretend]`

One-way beets to Plex, track-typed collections. Per configured collection:
query, resolve, then diff against current collection items and apply batched
`addItems` / `removeItems`. Diff instead of recreate because collections are
library-global (visible to all accounts) and recreation would discard
Plex-side artwork and sort settings.

Every guard listed for playlists applies here identically: the prune guard
before any deletion, matched-but-unresolved as an error, duplicates all
handled, per-entry failure isolation, `--pretend` on every mutating branch.
Helpers shared between playlists and collections take the entry type as an
argument and name it in their errors; a shared selector hardcoding "playlist"
reports `plex collections BadName` as an unknown playlist.

- A same-named collection with a different subtype (album/artist) or a smart
  collection: warn and skip.
- Item order in collections is not managed.

### Auto-scan (replaces plexupdate)

Listeners: `item_imported`, `album_imported`, `item_removed`, and all four
move-family events `item_moved`, `item_copied`, `item_linked`,
`item_hardlinked` (F9). Revision 1 listened only to `item_moved`, so
`beet move --copy` and `beet move --link` never scanned the destination.

Each listener adds the affected directories to a per-process set, translated
to Plex-side paths. A move or copy contributes both its source and destination
parent. `item_removed` fires before the file is deleted (F9), so the path is
still valid. At `cli_exit` the set is deduplicated and one partial scan per
directory is fired: `section.update(path=...)` (F12).

- If more than `max_scan_dirs` distinct directories are queued, fall back to a
  single full section update instead.
- Plex being unreachable degrades to a warning; a beets command never fails
  because of Plex.
- `auto_scan: no` disables the listeners' network side entirely.
- `flush()` is idempotent: `cli_exit` can fire after an explicit flush.
- **Every** event-driven entry point reads config inside its try, not only the
  obvious one: `flush` from `cli_exit`, and the path-queueing helper called
  from all six item events. beets does not guard listeners, so a malformed
  `beets_dir`/`plex_dir` would break the user's `beet import` rather than the
  Plex scan. The queueing helper does no network work, which is exactly why
  the first version of it went unguarded.
- Manual command: `beet plex scan [--full] [--pretend] [PATH...]` (PATHs are
  beets-side and get translated; no args with `--full` refreshes the whole
  section; `--pretend` reports without asking Plex to scan).

### Other commands

- `beet plex status`: connection check, library name/track count, matched vs
  unmatched item counts (runs the sweep, writes nothing).

### Error handling

- Connection/auth failure in a command raises `ui.UserError` with a clean
  message (no traceback).
- All event listeners wrap their work in try/except and log warnings.
- Rating pushes catch Plex and transport errors but never mask programming
  errors.
- The plexapi server object is created lazily on first use and reused for the
  process lifetime.
- `server()` is covered by tests for the URL it builds, the token it passes,
  and the clean error on a refused connection; without that, `secure: yes` can
  be ignored and the token travels in cleartext unnoticed.

## Testing

pytest with beets' own `beets.test.helper` harness (`PluginTestHelper`). No
live Plex needed for the suite; plexapi is faked at the object layer (a small
fake section/track/playlist/collection model). One optional live smoke test
gated behind an environment variable.

Harness facts that cost real time to rediscover, recorded so they are not
rediscovered again:

- `beets.test._common.RSRC` is not shipped in the wheel, so
  `create_mediafile_fixture` and `add_album_fixture` raise in a downstream
  suite. This repo ships its own `tests/rsrc/full.<ext>` fixtures.
- `TestHelper` has an autouse fixture running both `setup_beets` and
  `teardown_beets`; calling either by hand leaks state.
- `Item._types` is a `cached_classproperty` computed once per process, so a
  test touching `Item` with no plugins loaded freezes an empty type map and
  silently downgrades typed queries to substring matches. Tests reset
  `cached_classproperty.cache`.
- beets ships `IOMixin` but defines the `io` fixture only in its own conftest.

Coverage requirements:

- composition: both plugins loaded together raise no `PluginConflictError`
  (F1), and a `types: rating: int` config produces this plugin's own error.
- ratingtag: round-trip tests on real temp media files (FLAC, MP3, MP4, WAVE
  as a format the POPM style *does* cover, and WMA as the one that stores
  nothing), covering every contract edge above.
- `rating_is_tagged`: true for MP3/FLAC/M4A/AIFF/WAVE, false for WMA, false
  when the plugin is not enabled.
- plex sync: table-driven over all merge cells including clears, both-changed
  with and without `rating_updated`, and the `clock_skew` tie; guard and
  reentrancy tests for the `write`-event stamping listener; a pull on the
  `full.wma` fixture with `ratingtag` enabled asserting it is not counted as a
  failure; statistics mirrored for an item whose rating did not change.
- matching: prefix translation including the root itself, stale-ratingkey
  re-resolution, multi-location tracks, ambiguous duplicate paths,
  out-of-library items, and the no-parts sweep failure.
- playlists/collections: diffing, the empty-query prune guard (and that it
  deletes only when `prune:` is set), matched-but-unresolved as an error,
  smart/foreign name-collision skips, duplicate remote titles, unmatched-item
  warnings, per-entry failure isolation, `--pretend` on every mutating branch.
- auto-scan: directory collection over all six events, the `max_scan_dirs`
  fallback, unreachable-server degradation, and the `cli_exit` registration
  itself — with only direct calls to the flush helper, the registration can be
  deleted and the whole feature disappears with every other scan test still
  passing.

Test doubles must be no more forgiving than the real API — and no stricter
either. `FakeTrack.rate` must not refresh local state (F11). The fake's
`createCollection` requires `section`; its `createPlaylist` does not, because
plexapi's does not (F14). A fake that requires it for both hides nothing and
invents a constraint the server will not enforce. Sync
tests need real files on disk: a suite using non-existent paths hid a
write-ordering defect entirely. Sort-order tests must use a sort that
contradicts beets' default, or they pass with the sort dropped. The recency
tie-break must be exercised through the database, not with hand-passed floats:
hand-passed floats pass whether or not `rating_updated` is declared
`types.DATE`, so the declaration can be dropped and every recency comparison
silently degrades to string ordering with a green suite.

## Repository layout

```
beets-plex/
  beetsplug/
    ratingtag.py
    plex/
      __init__.py      # plugin class, config, commands wiring
      match.py         # path mapping + sweep + resolution
      sync.py          # three-way rating merge + stats mirror
      playlists.py
      collections.py
      scan.py          # auto-scan listeners + scan command
  tests/
  docs/superpowers/specs/
  docs/superpowers/plans/
  pyproject.toml       # deps: beets>=2.12, plexapi, mediafile, mutagen;
                       # hatchling wheel target from the first plugin module on
  README.md
  LICENSE
```

Conventions: conventional commits. CI runs ruff (lint and format) and pytest
via GitHub Actions.

## Delivery: one plugin area per pull request

The first attempt at this design was built as a single branch of 32 commits
and roughly 7,500 lines, then reviewed. That is the wrong order. Three rounds
of review afterwards found about 30 real defects, and two of those were
introduced by fixes from the round before, because a diff that size cannot be
reviewed usefully by a person or a bot.

The work ships as seven pull requests, each closing its own issue and merged
before the next begins:

0. This design and the implementation roadmap (documentation only)
1. Project scaffolding, CI, and test fixtures
2. `ratingtag`: the rating field, its file-tag storage, and
   `rating_is_tagged`
3. `plex` core: plugin skeleton, config, path matching, `status`
4. Rating merge and the statistics mirror
5. Playlists and collections
6. Auto-scan on import, move, copy, link, and remove

`docs/superpowers/plans/2026-07-28-beets-plex-roadmap.md` holds the scope and
exit criteria for each, and each pull request's detailed task plan is written
at its start rather than up front, because pull requests 3 and later depend on
answers that only exist once the code before them runs against a real server.

## Failure-mode catalogue

Every entry below is a defect the first attempt actually shipped and review
later caught. They are recorded as requirements so the reimplementation
designs them in rather than rediscovering them. Each needs a test. Entries
corrected in revision 2 are marked; the rest are unchanged from revision 1 and
have been folded into the sections above.

### Ordering

- A pull must write the file tag **before** advancing the merge base. The
  other order records a sync that never reached the file.
- A push must count as pushed only **after** `track.rate()` returns.
- A playlist rebuild must create the replacement **before** deleting the old
  one, or a failed create leaves the user with nothing.
- Any "leave it alone unless pruning" guard must come **before** any deletion
  in the same function, including duplicate cleanup.
- **Every** event-driven entry point must read config inside its try, not only
  the obvious one.

### Lifecycle and reentrancy

- The stamping suppressor must be a counter, not a flag, so a nested use does
  not re-arm stamping when the inner block exits.
- `flush()` must be idempotent: `cli_exit` can fire after an explicit flush.
- mediafile field registrations are class-level and survive plugin reloads
  (F13), so a style must read config **at use time**. Capturing `popm_email`
  at construction means the first value seen in a process wins forever.
- Re-registering an existing media field must be tolerated, but a field
  registered by a *different* plugin must warn rather than be swallowed.

### Failure paths

- **Corrected in revision 2.** `item.try_write()` returns `True` for a format
  with no applicable rating style: it writes nothing. A pull must verify the
  tag holds the value, or a later `beet update` reads it back as unrated and
  the next sync pushes that phantom clear to Plex. Revision 1 specified the
  exemption as "WMA, AIFF, WAV", which F5 shows is wrong: the POPM style
  covers AIFF, DSF and WAVE, so implementing that list literally would exempt
  files whose tag *was* written and hide real write failures. The exemption is
  computed by `rating_is_tagged(item)` from the field's own styles (F4), never
  from a format list.
- One failing entry must not cancel the entries behind it, in scans,
  playlists, and collections alike.
- Rating pushes must catch Plex and transport errors but not mask programming
  errors.
- Sync failures must reach the exit status.

### Reporting accuracy

- Every command that can mutate must honour `--pretend` on **every** branch
  that mutates, including duplicate cleanup and the "nothing changed" path. A
  dry-run flag that mutates is the worst kind of defect, because users reach
  for it when they do not trust the config.
- Items skipped by `--pull` / `--push` must be counted as deferred.
- A conflict resolved by the `conflict:` policy rather than by recency must be
  reported, and so must a tie inside `clock_skew`.
- A playlist "removed" message must not be logged when no playlist existed.

### Boundaries

- The path prefix check is inclusive of the library root: `beets_dir` itself
  translates to `plex_dir`, so `beet plex scan <beets_dir>` works rather than
  reporting the root as outside the library.

### Destructive operations

- An empty query result must not delete a playlist or collection by default.
- A query that matched items but resolved **none** of them in Plex is a
  misconfiguration, not an empty result, and must be an error.
- A missing `query` key must be rejected.
- Helpers shared between playlists and collections must name the entry type in
  their errors.
- Duplicate remote objects sharing a title must all be handled.

### Data fidelity

- Unrated is `0.0` everywhere. A rated POPM byte must never round down to
  `0.0`.
- **Corrected in revision 2.** The Vorbis legacy-star rule applies to the
  `RATING` comment only, never to MP4, and is now off by default. Revision 1
  described the unrepresentable range as "below 1.0"; it is 0.1-0.5, and only
  in legacy mode.
- **Corrected in revision 2.** Mirror fields must be assigned unconditionally
  *for every matched item*, not only for items whose rating changed. Revision
  1 placed the mirror assignment after "once the action has succeeded, and
  never before", which skipped the statistics pull for every unchanged item.
- plexapi's `rate()` does not reload the object (F11), so after a push the
  track's own `lastRatedAt` is one rating behind and must not be mirrored.
- `rating_updated` must be stamped from the `write` event (F7);
  `database_change` fires after beets clears the dirty set.
- The conflict fallback fires when **either** timestamp is missing, not just
  the beets one; Plex drops `lastRatedAt` when a rating is cleared (D3).

### Test-suite requirements

- Test doubles must be no more forgiving than the real API.
- Sync tests need real files on disk.
- Tests must reset `cached_classproperty.cache`.
- Sort-order tests must use a sort that contradicts beets' default.
- The recency tie-break must be exercised through the database.
- The event wiring itself needs a test.
- `server()` needs coverage of the URL it builds and the token it passes.
- beets' bundled test fixtures are not shipped in the wheel.

## Revision history

**Revision 2 (2026-07-28)** — revision 1 was reviewed against the installed
packages and three of its load-bearing claims were false. Changes:

1. "No per-track reloads ever fire" was wrong (F2, F3). The sweep now
   explicitly suppresses reloads and validates that it got file parts.
2. "Identical declarations do not conflict in beets" was wrong for fresh type
   instances (F1). Both plugins must use the `types.FLOAT` singleton, and a
   test enforces it.
3. The WMA/AIFF/WAV write exemption was keyed on the wrong condition (F5) and
   would have hidden real failures. Replaced by `rating_is_tagged`.
4. The statistics mirror was gated on a rating action, defeating goal 3 for
   unchanged items. Split into an unconditional step.
5. The Vorbis round-trip section contradicted its own scale. Restated, with
   the legacy rule now a config switch that is off by default.
6. Timestamp comparison, previously unspecified, is now defined in epoch
   seconds with a `clock_skew` tie window.
7. Duplicate Plex tracks on one path are now explicitly ambiguous rather than
   silently last-wins.
8. The merge base moved off `plex_userrating` (which keeps its plexsync
   meaning) onto `plex_ratingbase`.
9. Auto-scan gained `item_copied`, `item_linked` and `item_hardlinked` (F9).
10. Added: the named composition interface between the two plugins, a full
    config defaults table, an exit-status rule, `max_scan_dirs` and
    `container_size` as config rather than magic numbers, detection of a
    `types: rating: int` conflict, and the "Verified platform facts" and
    "Open decisions" sections.
11. Revision 1's "record the stored value as the sync base" rule does not
    converge: with Plex at 0.7 the base becomes the clamped value and every
    later run re-pulls and rewrites the file. The Plex value stays
    authoritative and a format-clamped `rating` is treated as unchanged, via
    `tag_image` (this correction was first found in the review that produced
    issue #6 and is adopted here).
12. The test-double rule "the create calls must require `section`
    positionally" is false for `createPlaylist` (F14) and would have made the
    fake stricter than the server.
13. mediafile and mutagen are direct runtime dependencies, because ratingtag
    imports `POPM` and `MP4FreeForm`, which mediafile does not re-export
    (F15).

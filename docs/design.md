# beets-plex: high-level design

Date: 2026-07-28 · Status: for review. Supersedes the archived draft at
`docs/archive/2026-07-28-beets-plex-draft.superseded.md`.

## What this is

A beets plugin package that keeps a beets library in sync with a Plex Media
Server. Beets and Plex index the same files on a shared mount, so an item's
Plex-side path is a fixed rewrite of its beets path — matching is exact, by
path. No fuzzy matching, no discovery, no AI.

## Goals

1. Update Plex when beets imports, moves, or removes files.
2. Two-way rating sync between beets and Plex; a value-based three-way merge,
   genuine conflicts resolved by a configured policy.
3. One-way pull of Plex play statistics into beets fields.
4. One-way push of query-defined playlists from beets to Plex.
5. One-way sync of query-defined track collections from beets to Plex.
6. Ratings stored in the beets database and written to file tags.

## Non-goals

Plex-to-beets playlist import, m3u handling, discovery/AI features;
multi-account sync; album- or artist-typed collections; writing play counts
back to Plex.

## Architecture: two plugins, one package

- `ratingtag` owns the `rating` field and writes it to file tags. No network.
- `plex` does everything Plex: matching, rating and stats sync, playlists,
  collections, scans. It reads and writes the `rating` database field but never
  touches file tags itself.

They compose through beets rather than through each other: when `plex` changes a
rating it writes the beets `rating` database field and stores the item; if
`ratingtag` is enabled, it carries that value into the file's tags the next time
beets writes the file (`beet write`). The beets database is the source of truth,
so `plex` never inspects or confirms file tags — beets can always rewrite them
from the database. There is no import-time dependency in either direction.

## How each part behaves

- **Scan updates.** Import/move/remove trigger targeted partial Plex scans of
  the affected directories, replacing the built-in `plexupdate`'s full-section
  refresh, with a fall-back to a full refresh past a threshold. A scan failure
  degrades to a warning; it never breaks the beets command.
- **Rating sync.** A value-based three-way merge per matched track over a
  last-agreed baseline, the beets rating, and the Plex rating. beets has no
  per-field change timestamp, so time-ordering is impossible: a change on one
  side only is resolved by value against the baseline, and a genuine conflict —
  both sides moved apart from the baseline — is decided by the configured
  `rating_conflict` policy (`plex`, `beets`, or `skip`; default `plex`). The
  baseline is private to this plugin and kept separate from the fields that
  mirror Plex, so a co-installed plugin cannot reinterpret one plugin's value as
  another's.
- **Play statistics.** A one-way pull of Plex counts and timestamps into beets
  fields.
- **Playlists and collections.** One-way, from a beets query to a Plex playlist
  (made to match the query exactly) or a track collection (applied as a diff).

## Configuration

The plugin extends the existing shared `plex:` config section: connection
details, the two path prefixes (beets-side and Plex-side), and switches for
auto-scan, the rating-conflict policy, and whether a query that now matches
nothing may delete its playlist or collection. Field and config names follow
`beets-plexsync`'s where they overlap, to stay compatible with existing data.

## Delivery

The first attempt shipped as one very large branch and took three review rounds
to surface roughly thirty defects — the lesson is about diff size, not any one
bug. This ships instead as a short sequence of small pull requests, each closing
its own issue and merged before the next begins. Those defects cluster in a few
areas — operation ordering, listener robustness, honest dry-run, unrated
semantics, and test doubles that match the real API — and each pull request is
designed and tested against its cluster. The per-PR breakdown is the delivery
roadmap (`docs/roadmap.md`).

## Deferred to implementation

Per-format tag encodings, the exact flexible-attribute names and types, and the
specific beets and plexapi behaviours this design relies on are settled — and
checked against the installed versions — in the pull request that implements
each. They are deliberately not fixed here.

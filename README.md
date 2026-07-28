# beets-plex

Two [beets](https://beets.io/) plugins that can be used together or apart:

- **`ratingtag`** owns a `rating` field on a 0-10 scale and writes it to your
  audio files (POPM for MP3, a `RATING` comment for FLAC/Ogg/Opus, a freeform
  `RATING` atom for MP4). No network access.
- **`plex`** synchronizes a beets library with a Plex music library: two-way
  rating sync, a one-way pull of play statistics, query-defined playlists and
  track collections pushed to Plex, and targeted library scans after imports.

The `plex` plugin matches tracks **by file path only**, so beets and Plex must
index the same files. The two may mount them under different prefixes; the
plugin translates between them.

When both plugins are enabled, ratings synced from Plex are written to your
files automatically: the `plex` plugin updates the `rating` database field and
asks beets to write tags, and `ratingtag` supplies the tag format. Neither
plugin depends on the other.

## Install

```bash
pip install .
```

For development, point beets at the checkout instead:

```yaml
pluginpath:
  - /path/to/beets-plex/beetsplug
```

Then enable the plugins:

```yaml
plugins:
  - ratingtag
  - plex
```

Two changes are needed in an existing configuration:

- **Remove `plexupdate`** from the `plugins:` list. The `plex` plugin replaces
  it and reads the same `plex:` connection settings.
- **Remove any `rating` entry from the `types:` plugin config.** Both plugins
  declare `rating` as a float, and beets raises a conflict error if the `types`
  plugin declares the same field differently.

## Configuration

```yaml
plex:
    host: 192.168.1.10
    port: 32400
    token: YOUR_PLEX_TOKEN     # redacted in `beet config` output
    library_name: 'Music'
    secure: no                 # use https; certificates are always verified

    # Path translation. beets_dir defaults to beets' own `directory`,
    # and plex_dir defaults to beets_dir.
    beets_dir: /mnt/music      # where beets keeps the files
    plex_dir: /mnt/music       # the same files as the Plex server sees them

    auto_scan: yes             # partial scans after import/move/remove
    conflict: plex             # tie-break when both sides changed: plex | beets
    prune: no                  # delete a playlist/collection whose query
                               # now matches nothing (off: leave it alone)

    playlists:
        - name: Top 2000 all
          query: 'top2000_score:1.. top2000_score-'

    collections:
        - name: Top2000
          query: 'top2000_score:1..'

ratingtag:
    popm_email: ''             # POPM identifier; must match your existing tags
```

Playlist and collection queries are ordinary beets queries, including sort
terms (`top2000_score-` above sorts descending). Playlist order in Plex follows
the query's sort order. Every entry needs a `query` key; an empty string means
"the whole library", but a missing key is rejected rather than silently
meaning the same thing.

If a query stops matching anything, the existing playlist or collection is
left in place and a warning is logged, because that is far more often a typo
or a half-imported library than a request to delete. Set `prune: yes` if you
want an empty result to delete the remote object instead.

## Commands

All commands live under `beet plex`:

| Command | What it does |
|---|---|
| `beet plex sync [QUERY]` | Two-way rating sync plus a pull of play statistics |
| `beet plex playlists [NAME...]` | Rebuild the configured playlists in Plex |
| `beet plex collections [NAME...]` | Update the configured track collections in Plex |
| `beet plex scan [PATH...]` | Scan the given beets-side folders |
| `beet plex status` | Connection check and matched/unmatched item counts |

Flags: `--pretend` reports what would change without touching anything (all
commands); `--pull` and `--push` restrict `sync` to one direction; `--full`
makes `scan` refresh the whole library section instead of single folders.

Playlists and collections named on the command line are limited to those
entries; with no names, every configured entry is processed.

## How matching works

Each beets item's path is translated from `beets_dir` to `plex_dir`, then looked
up in a map built from a single sweep of the Plex library, which returns every
track together with its file paths. Items whose translated path is not in Plex
are counted, logged, and skipped; the rest of the run continues normally. The
`plex_ratingkey` field is stored for reference but never used for matching, so
it repairs itself if Plex re-adds a file under a new key.

## Rating semantics

Ratings are floats from 0 to 10, matching Plex's own scale (0-5 stars in half
steps). A rating of `0.0` and an absent field both mean "unrated", and writing
an unrated value removes the tag from the file rather than writing a zero.

`beet plex sync` compares three values per track: the beets `rating`, the Plex
`userRating`, and `plex_userrating`, which records what the two agreed on at
the last sync. If only one side changed, that change propagates. If both
changed, the more recent one wins, comparing beets' `rating_updated` timestamp
against Plex's `lastRatedAt`. If either timestamp is missing, the `conflict:`
setting decides instead (default: Plex wins). Plex drops `lastRatedAt` when a
rating is cleared there, so that case takes this path too.

`rating_updated` is recorded when beets writes a changed rating to a file, so
`beet modify rating=8 <query>` is stamped whenever tag writing is on. It is
not stamped when writing is suppressed, either with `beet modify -W` or for
every command if your config sets `import.write: no`. Such a change falls back
to the `conflict:` policy instead of winning on recency. `beet plex sync`
warns when it resolves conflicts that way, so this is visible rather than
silent.

Play statistics (`plex_viewcount`, `plex_skipcount`, `plex_lastviewedat`) are
pulled from Plex only; the Plex API does not allow writing them.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `rating` | float | Your rating, 0-10 (`ratingtag` writes it to file tags) |
| `plex_userrating` | float | The last rating beets and Plex agreed on |
| `plex_ratingkey` | int | Plex track id, for reference |
| `plex_guid` | string | Plex GUID |
| `plex_lastratedat` | date | When the track was last rated in Plex |
| `plex_viewcount` | int | Play count from Plex |
| `plex_skipcount` | int | Skip count from Plex |
| `plex_lastviewedat` | date | Last played, from Plex |
| `plex_updated` | date | When this item last synced |
| `rating_updated` | date | When the beets rating last changed |

All are queryable, for example `beet ls rating:8.. plex_viewcount:0`.

## Existing rating tags

If your files already carry POPM or `RATING` tags, set `popm_email` to match
what wrote them and run `beet update <query>`; beets re-reads the tags and
populates the `rating` field. No separate import step is needed.

## License

MIT. See `LICENSE`.

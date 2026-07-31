# beets-plex

Beets plugins to synchronize a music library with a Plex Media Server.

Beets and Plex index the same files on a shared mount, so matching is by exact
file path — no fuzzy matching, no discovery. Two plugins ship in one package:

- **`ratingtag`** — stores a rating in the beets database and in file tags.
- **`plex`** — targeted library scans on import/move/remove, two-way rating
  sync, a one-way pull of Plex play statistics, and one-way push of
  query-defined playlists and track collections.

## Install

    pip install beets-plex

Requires Python 3.10–3.14. Then enable and configure the plugins in your beets
config — see [Configuration](#configuration).

For development, from a checkout:

    pip install -e '.[test]'

## Configuration

Enable the plugins and configure them under a shared `plex:` section in your
beets config. `ratingtag` needs no configuration for defaults; `plex` needs at
least a `token` and the `library_name` of your Plex music library.

    plugins: ratingtag plex

    plex:
        # Connection
        host: localhost         # Plex server host
        port: 32400             # Plex server port
        token: ""               # Plex auth token (required)
        library_name: Music     # name of the Plex music library section
        secure: no              # yes connects over https instead of http

        # Path translation (beets and Plex see the same files on a shared mount)
        beets_dir: ""           # beets-side path prefix; defaults to beets' `directory`
        plex_dir: ""            # Plex-side path prefix; defaults to `beets_dir`

        # Rating sync
        rating_conflict: plex   # who wins a genuine conflict: plex | beets | skip

        # Playlists and collections (one-way, beets query -> Plex)
        playlists: []           # list of {name, query} pushed as Plex playlists
        collections: []         # list of {name, query} pushed as Plex collections
        prune_empty: no         # delete a playlist/collection whose query now matches nothing

        # Auto-scan on import/move/remove
        auto_scan: no           # trigger targeted Plex scans from beets operations
        scan_threshold: 100     # above this many touched directories, do one full refresh

`beets_dir`/`plex_dir` are the fixed prefixes that rewrite a beets file path to
its Plex-side path; leave them equal when beets and Plex mount the library at the
same path. `playlists` and `collections` each take a list of mappings, for
example:

    plex:
        playlists:
            - name: Favourites
              query: "rating:8..10"
        collections:
            - name: Recently Rated
              query: "plex_lastratedat:-4w.."

### Replacing `plexupdate`

`plex.auto_scan` replaces beets' built-in `plexupdate` plugin: instead of a full
library refresh, it triggers targeted scans of just the directories an import,
move, or remove touched. To use it, **remove `plexupdate` from your `plugins`
line and set `plex.auto_scan: yes`** — running both would scan twice.

## Usage

    beet plex status                  # connection, library size, match counts
    beet plex stats [QUERY]           # pull Plex play counts/timestamps into beets
    beet plex sync [QUERY]            # two-way rating sync
    beet plex playlists [NAME ...]    # push configured playlists (all, or the named ones)
    beet plex collections [NAME ...]  # push configured collections

Pass `-p`/`--pretend` to any subcommand to print what would change without
writing anything. With no subcommand, `beet plex` runs `status`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md): small pull requests, each closing its
own issue; Conventional Commits; `ruff` and `pytest` green.

## License

MIT — see [`LICENSE`](LICENSE).

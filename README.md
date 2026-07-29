# beets-plex

Beets plugins to synchronize a music library with a Plex Media Server.

Beets and Plex index the same files on a shared mount, so matching is by exact
file path — no fuzzy matching, no discovery. Two plugins ship in one package:

- **`ratingtag`** — stores a rating in the beets database and in file tags.
- **`plex`** — targeted library scans on import/move/remove, two-way rating
  sync, a one-way pull of Plex play statistics, and one-way push of
  query-defined playlists and track collections.

## Status

Early. The design and delivery plan live on `main`:

- [`docs/design.md`](docs/design.md) — high-level design.
- [`docs/roadmap.md`](docs/roadmap.md) — the delivery roadmap. The project is at
  the scaffolding stage; no plugin code yet.

## Install

During development, from a checkout:

    pip install -e '.[test]'

Requires Python 3.10–3.14.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md): small pull requests, each closing its
own issue; Conventional Commits; `ruff` and `pytest` green.

## License

MIT — see [`LICENSE`](LICENSE).

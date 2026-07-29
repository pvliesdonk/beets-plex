# beets-plex: delivery roadmap

Date: 2026-07-28 · Status: for review. Companion to `docs/design.md`.

## Why this exists

The design says what to build. This says in what order, and small enough to
review. The prior attempt failed on delivery, not design: one large branch that
could not be reviewed usefully. So the work ships as a sequence of small pull
requests.

## How it ships

- One pull request at a time, branched off `main`, each closing its own issue,
  merged before the next begins. No stacking.
- Small diffs. The single large branch is the failure this avoids.
- Test-first. Any beets or plexapi behaviour the code relies on is checked
  against the installed version in the pull request that needs it — not assumed
  ahead of time.

## The pull requests

1. Scaffolding: package layout, CI, and shared test fixtures.
2. `ratingtag`: the rating field and its file-tag storage.
3. `plex` core: plugin skeleton, config, path matching, and a `status` command.
4. Rating sync and the play-statistics pull. The riskiest one; expect to split.
5. Playlists and collections.
6. Auto-scan on import, move, and remove.

Each depends on the ones before it and merges before the next starts.

## Regression checklist

The prior attempt shipped ~30 defects, clustered in operation ordering, listener
robustness, honest `--pretend`, unrated-as-zero semantics, and test doubles that
match the real API in both directions. Each pull request designs tests against
its cluster, derived by checking the actual behaviour when the PR is planned.
The archived draft (`docs/archive/2026-07-28-beets-plex-draft.superseded.md`)
holds the prior attempt's fuller catalogue as background only — it is superseded
revision-1 material whose specifics were partly wrong, not a spec to copy tests
from.

# beets-plex — repository guide

A beets plugin package that synchronizes a beets library with a Plex Media
Server. The authoritative design and plan live in `docs/`:

- `docs/design.md` — high-level design (architecture and load-bearing decisions).
- `docs/roadmap.md` — delivery roadmap: six small PRs, each closing its own issue
  and merged before the next.
- `docs/archive/…superseded.md` — the prior over-detailed draft. **Not
  authoritative**; background only, and some of its specifics are wrong. Do not
  build from it.

## Layout

- `beetsplug/` — PEP 420 implicit namespace package (no `__init__.py` at the
  namespace root). Plugin modules (`ratingtag`, `plex`) will live here; none are
  committed yet, so the built package is metadata-only for now.
- `tests/rsrc/` — committed audio fixtures. beets does not ship its own
  (`beets.test._common.RSRC`) in a way a downstream suite can use, so this suite
  carries its own.

## Dev commands

    pip install -e '.[test]'
    ruff check . && ruff format --check .
    pytest -q

The version is derived from the git tag via `hatch-vcs`; `release.yml` publishes
to PyPI via trusted publishing when a GitHub Release is published.

## Conventions

- **Conventional Commits** (`type: summary`) are required, so Python Semantic
  Release can manage versioning and the changelog later.
- Small PRs, one issue each, merged before the next.

## Gotchas (verified against installed beets 2.13 / mediafile 0.17 / plexapi 4.18)

- `mediafile.MP3StorageStyle.formats == ['MP3', 'AIFF', 'DSF', 'WAVE']` —
  AIFF/WAVE/DSF store ratings via ID3/POPM and are **not** tag-less; only
  WMA/ASF is. Decide "can this file hold a rating?" from the format's storage
  style, never from a hardcoded format list.
- `mediafile` has no POPM storage style, so `ratingtag` defines a custom one and
  reaches the mutagen `POPM` class via `mediafile.mutagen` — mutagen is a
  transitive dependency of mediafile, not a direct one. MP4 freeform ratings
  reuse `mediafile.MP4StorageStyle` (route `serialize` through it so the string
  is encoded to a freeform bytes atom).
- plexapi `createPlaylist(section=None)` is optional but `createCollection`
  requires `section` — a test double must mirror that asymmetry, not be stricter.
- `ratingtag` reads the private `mediafile.MediaField._styles` to tell its own
  `rating` field from another plugin's on re-registration (mediafile exposes no
  public introspection). Re-verify it on a mediafile version bump: a rename would
  silently route into the "owned by another plugin" branch.
- `Item._types` is a per-process `cached_classproperty`: a test that reads it
  with no plugins loaded freezes an empty type map (typed-field queries then
  degrade to substring matches). `TestHelper`'s setup/teardown does **not** clear
  it — the shared test harness resets `cached_classproperty.cache` per test (see
  `tests/conftest.py`). Separately, don't call `setup_beets`/`teardown_beets` by
  hand; `TestHelper`'s autouse fixture runs them.

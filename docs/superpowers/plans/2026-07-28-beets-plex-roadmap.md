# beets-plex Implementation Roadmap

> **For agentic workers:** this is the roadmap, not an executable plan. Each
> pull request below gets its own task-level plan document, written at the
> start of that pull request. Execute those with
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans.

**Goal:** Two beets plugins in one package — `ratingtag` (a `rating` field
with file-tag storage) and `plex` (Plex library sync: ratings, play
statistics, playlists, collections, partial scans).

**Architecture:** See `docs/superpowers/specs/2026-07-28-beets-plex-design.md`
revision 2, which is the authority for everything below. `beetsplug/ratingtag.py`
owns the `rating` field and its POPM / Vorbis / MP4 storage;
`beetsplug/plex/` matches beets items to Plex tracks by exact file path and
talks to the server through python-plexapi. The two plugins meet at exactly
one named function, `ratingtag.rating_is_tagged`.

**Tech Stack:** Python >= 3.10, beets >= 2.12, python-plexapi, mediafile,
mutagen, uv, pytest with `beets.test.helper`, ruff, hatchling (from PR 2 on).

## Global Constraints

Copied from the spec; every task in every pull request inherits these.

- Rating scale is canonically float 0-10. **Unrated is 0.0 or an absent field,
  equivalent everywhere.**
- Both plugins declare `rating` with the singleton `beets.dbcore.types.FLOAT`,
  never a fresh `types.Float()` — a fresh instance raises `PluginConflictError`
  (spec F1).
- Nothing in this repository hardcodes a list of "formats that store ratings".
  Applicability is computed from `MediaField.styles()` (spec F4, F5).
- Every command that mutates honours `--pretend` on **every** mutating branch.
- Per-item failures never cancel the items behind them, and they reach the
  process exit status.
- Every event listener wraps its whole body, config reads included, in
  try/except; beets does not guard listeners.
- Every command runs through uv: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`. Never bare pip.
- Conventional commits, scoped `ratingtag` or `plex` where applicable.
- beets plugin logging uses `self._log.debug("found {0}", n)` str.format
  templates, never f-strings in the log call.
- Runtime dependencies are limited to `beets`, `plexapi`, `mediafile`,
  `mutagen`; dev dependencies to `pytest` and `ruff`.
- Every pull request closes at least one issue and is merged by a human before
  the next one starts.

## How this roadmap is executed

Two rules, both of them reactions to how the first two attempts failed.

**One plan per pull request, written at its start.** The first attempt wrote
one 2,800-line plan covering everything, and the tasks for the later pull
requests encoded guesses — about plexapi's sweep behaviour, about what the
fake server would need — that were wrong by the time anyone reached them.
Pull requests 3 and later depend on answers that only exist once the code
before them has run against a real server. Each plan document is therefore
written after its predecessor merges, from the spec plus the repository as it
actually is, and is named
`docs/superpowers/plans/2026-07-28-pr<N>-<slug>.md`.

**Land the smallest increment that stands on its own, verify it, then stop.**
The scaffolding pull request of the second attempt took three review rounds
and ten commits, and several of its defects came from the previous round's
fixes. When a review finds something, fix the class rather than the instance,
sweep for siblings with a command whose output goes in the pull request, and
push once. If a round's findings include ones caused by the previous round,
stop and hand back rather than running another round.

### The plan document each pull request needs

Every per-PR plan opens with the same two things before any implementation
task:

1. **A facts task.** Name the API facts the pull request depends on that are
   *not* already in the spec's "Verified platform facts" table. For each, the
   exact command that establishes it and where the answer gets recorded. No
   implementation task may rely on a recalled signature.
2. **A decisions task**, if the pull request owns an entry in the spec's "Open
   decisions" table. It runs the check, writes the answer into the spec in
   this pull request, and only then unblocks the tasks that depend on it. If
   the check is inconclusive, the documented default is implemented and the
   ledger row is updated to say so.

Then the implementation tasks, each ending in an independently testable
deliverable, each with the failing test written and run before the code.

## Pull requests

| # | Title | Branch | Closes | Plan document |
|---|---|---|---|---|
| 0 | Design revision 2 and roadmap | `docs/design-revision-2` | new issue | this document |
| 1 | Project scaffolding, CI, and audio fixtures | `feat/scaffolding` | new issue | `2026-07-28-pr1-scaffolding.md` |
| 2 | `ratingtag` plugin | `feat/ratingtag` | new issue | written at PR 2 start |
| 3 | `plex` core: config, matching, `status` | `feat/plex-core` | new issue | written at PR 3 start |
| 4 | Rating merge and statistics mirror | `feat/plex-sync` | new issue | written at PR 4 start |
| 5 | Playlists and collections | `feat/plex-playlists` | new issue | written at PR 5 start |
| 6 | Auto-scan | `feat/plex-scan` | new issue | written at PR 6 start |

Issue #2 (the original umbrella) stays open until PR 6 merges and is closed by
it. PR #3 and PR #5 from the abandoned attempts are closed and not reused;
branch `feat/scaffolding` is recreated from `main`.

---

### PR 0 — Design revision 2 and roadmap

**Scope:** documentation only. The revised design document, this roadmap, and
the PR 1 plan. No `beetsplug/`, no `pyproject.toml`, no tests.

**Why it is its own pull request:** revision 1 of the design contained three
claims that are false against the installed packages, and one instruction that
would have introduced a defect if implemented literally. That was found by
checking the document against installed source, which is a review that can
happen on a documentation diff and cannot happen usefully inside a code diff.

**Exit criteria:**

- `docs/superpowers/specs/2026-07-28-beets-plex-design.md` carries revision 2,
  including the "Verified platform facts" and "Open decisions" tables.
- Every claim in the facts table names where it was checked.
- This roadmap and `2026-07-28-pr1-scaffolding.md` are present.
- Review confirms the four unresolved questions are in the ledger with an
  owner and a default, rather than silently assumed.

---

### PR 1 — Project scaffolding, CI, and audio fixtures

**Scope:** `pyproject.toml` as a non-package uv project, ruff and pytest
configuration, `.github/workflows/ci.yml`, `tests/conftest.py` with the beets
harness wiring, and the `tests/rsrc/full.*` audio fixtures with a test that
pins what mediafile makes of each one.

**Explicitly out of scope:** any `beetsplug/` module, and any `[build-system]`
or wheel target. A hatchling wheel target for a directory that does not exist
builds a code-free wheel and reports success, so the build backend arrives in
PR 2 together with the first module it can actually ship.

**Exit criteria:**

- `uv run pytest -q` passes from a clean checkout.
- `uv run ruff check .` and `uv run ruff format --check .` pass.
- CI runs those three commands on pull requests and passes.
- Fixtures exist for MP3, FLAC, M4A, Opus, WMA, WAVE and AIFF, and a test
  asserts the mutagen class name of each, because those names are what
  `MediaField.styles()` matches on in PR 2 (spec F4, F5).

Detailed plan: `docs/superpowers/plans/2026-07-28-pr1-scaffolding.md`.

---

### PR 2 — `ratingtag`

**Scope:** `beetsplug/ratingtag.py` — the `rating` field, the three storage
styles, both halves of the composition interface (`rating_is_tagged` and
`tag_image`), the `types: rating: int` preflight check, the `[build-system]`
and wheel target, and the whole ratingtag contract-edge suite from the spec.

**Depends on:** PR 1's fixtures. Nothing else; this pull request is entirely
offline and needs no Plex.

**Facts to pin before writing code:** `MediaField` / `StorageStyle`
constructor signatures and the `serialize` / `deserialize` contract for each
of the three style base classes; how `MP4StorageStyle` handles `----` freeform
values; what `MediaField.__set__` passes to a style for a `None` value.

**Exit criteria:**

- Round-trip tests over the whole 0-10 range on real fixture files for MP3,
  FLAC and M4A, plus WAVE, which the POPM style covers (spec F5) and which
  revision 1 wrongly listed as storing nothing.
- `rating_is_tagged` is true for MP3/FLAC/M4A/AIFF/WAVE, false for WMA, and
  false when the plugin is not enabled.
- Both the POPM byte-1 clamp and the `vorbis_legacy_stars` switch (default
  off) have tests on both sides of their boundaries.
- `popm_email` is read at use time, not captured at construction, with a test
  that changes the config between two writes in one process.
- `tag_image` is tested by writing to a real fixture and reading back, not by
  reimplementing the clamp in the test.
- `uv build` produces a wheel that actually contains `beetsplug/ratingtag.py`.

---

### PR 3 — `plex` core: config, matching, `status`

**Scope:** `beetsplug/plex/__init__.py` and `match.py`; the config block with
its defaults, the lazy server accessor, the path translation, the section
sweep, the path-to-track map, and `beet plex status`. Plus `tests/fakeplex.py`.

**Owns Open decisions D1 and D4.** This is the first pull request that must
run against the real server, and its first task does exactly that: fetch one
page of `/library/sections/<id>/all?type=10` from the user's server, record
which attributes are present on a rated track, an unrated track and a
never-played track, and whether `Media`/`Part` children are included. That
recording lands in the spec, and it decides both the
`USER_DONT_RELOAD_FOR_KEYS` list and whether the no-parts failure path is
reachable at all.

**Exit criteria:**

- A sweep over the fake server issues no per-track reload, proven by a fake
  that raises if a reload is attempted.
- Path translation covers the library root itself, an item outside
  `beets_dir`, and both prefixes with and without trailing slashes.
- Ambiguous paths (two tracks, one file) are unmatched with one warning.
- A stale `plex_ratingkey` is re-resolved by path and the cache updated.
- `server()` has tests for the URL it builds under `secure: no` and
  `secure: yes`, the token it passes, and the clean `UserError` on a refused
  connection.
- `beet plex status` writes nothing, proven by comparing the library before
  and after.

---

### PR 4 — Rating merge and statistics mirror

**Scope:** `beetsplug/plex/sync.py`, the `beet plex sync` command, the
`write`-event stamping listener with its suspend counter, and the
`rating_updated` field.

**Owns Open decision D3** (whether Plex clears `lastRatedAt` on
`rate(None)`).

**Exit criteria:**

- The merge table is exercised cell by cell through the database, not with
  hand-passed floats, including both clear directions and the `clock_skew`
  tie.
- Statistics are mirrored for an item whose rating changed on neither side —
  the case revision 1 skipped.
- A pull writes the tag before advancing `plex_ratingbase`, proven by a test
  where the write fails and the base is asserted unchanged.
- A pull on the WMA fixture with `ratingtag` enabled is not counted as a
  failure, and a pull on the WAVE fixture *is* verified rather than exempted.
- A failed push leaves the base unchanged and the next run retries.
- `--pull` / `--push` count the other direction as deferred.
- A run with any failure exits non-zero.

---

### PR 5 — Playlists and collections

**Scope:** `beetsplug/plex/playlists.py`, `collections.py`, their commands,
and the shared entry-selection helper that names the entry type in its errors.

**Exit criteria:**

- Every guard in the spec's playlist section has a test, and the same test
  exists for collections. These two files diverged twice during the first
  attempt, each time because a fix landed on one and not the other.
- The prune guard is proven to run before any deletion, including duplicate
  cleanup.
- A query matching beets items but resolving none in Plex is an error, while a
  query matching nothing is a warning that leaves the remote object alone.
- A missing `query` key is rejected at config read.
- `--pretend` is asserted on the create, the update, the delete and the
  duplicate-cleanup branches separately.

---

### PR 6 — Auto-scan

**Scope:** `beetsplug/plex/scan.py`, the six event listeners, the flush at
`cli_exit`, and `beet plex scan`.

**Owns Open decision D2** (partial scan path semantics).

**Exit criteria:**

- A test per event, including `item_copied`, `item_linked` and
  `item_hardlinked`, which revision 1 omitted.
- The `cli_exit` registration itself is tested through a real command run, not
  by calling the flush helper directly.
- `flush()` is idempotent.
- Exceeding `max_scan_dirs` produces exactly one full-section update.
- A listener whose config is malformed logs a warning and does not propagate
  out of `beet import`.
- Issue #2 is closed by this pull request.

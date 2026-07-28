# PR 1: Project scaffolding, CI, and audio fixtures — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A green, lintable, CI-verified Python project with the audio
fixtures and pytest wiring that every later pull request builds on — and no
plugin code whatsoever.

**Architecture:** A uv *virtual* project (`[tool.uv] package = false`): no
build backend and no wheel target yet, because a hatchling wheel target for a
directory that does not exist builds a code-free wheel and reports success.
The build backend arrives in PR 2 with the first module it can ship. Tests
live in `tests/`, audio fixtures in `tests/rsrc/`, and shared pytest fixtures
in `tests/conftest.py`.

**Tech Stack:** Python >= 3.10 (3.14 locally), uv 0.11, pytest, ruff, beets
2.13, mediafile 0.17, mutagen 1.48, plexapi 4.18.

**Spec:** `docs/superpowers/specs/2026-07-28-beets-plex-design.md` revision 2.
Read its "Verified platform facts" table before starting; facts F4, F5, F6,
F15 and F16 are what Task 2 pins in a test.

**Closes:** issue #4.

## Global Constraints

Inherited from `docs/superpowers/plans/2026-07-28-beets-plex-roadmap.md`; the
ones that bite in this pull request:

- Every command runs through uv: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`. Never bare pip.
- Conventional commits.
- Runtime dependencies: `beets>=2.12`, `plexapi`, `mediafile`, `mutagen` —
  mediafile and mutagen are direct, not transitive, because ratingtag imports
  `POPM` and `MP4FreeForm`, which mediafile does not re-export (spec F15).
  Dev dependencies: `pytest`, `ruff`.
- `git ls-files beetsplug` must stay empty for the whole pull request.
- No `[build-system]` table and no `[tool.hatch...]` table in this pull
  request.

## Facts this plan relies on

All were established by running against the installed packages on 2026-07-28,
not recalled. Do not re-derive them; do check them if a step behaves
unexpectedly.

| Fact | Established by |
|---|---|
| `[tool.uv] package = false` needs no build backend, and uv still installs `[project] dependencies` into the environment. | a throwaway project with that table synced and imported successfully |
| `beets.util.cached_classproperty.cache` is a class-level dict; reading `Item._types` adds the key `(Item, "_types")` to it. | `len(cache)` before and after the read: 0 then 1 |
| `beets.test.helper.PluginTestHelper` exists and subclasses `TestHelper`. | `class PluginTestHelper(PluginMixin, TestHelper)` |
| The fixture files yield mutagen classes `MP3`, `AIFF`, `WAVE`, `FLAC`, `OggOpus`, `MP4`, `ASF`. | `mutagen.File(path).__class__.__name__` on all seven |
| `ffmpeg` and `uv` are on PATH; `gh` is authenticated as pvliesdonk. | `which` / `gh auth status` |
| PRs #3 and #5 are closed, so the branch names they used are free. | `gh pr list --state all` |

---

### Task 1: uv project, lint and test configuration

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_environment.py`

**Interfaces:**
- Produces: a synced `.venv` with beets, plexapi, mediafile, mutagen, pytest
  and ruff; `uv run pytest` and `uv run ruff check .` as the project's
  commands. Every later task and pull request uses these.

- [ ] **Step 1: Create the branch**

The abandoned attempt's branch of the same name belongs to closed PR #5.
Archive it, so its audio fixtures stay reachable in Task 2, then take the
name back.

```bash
cd /mnt/code/beets-plex
git fetch origin
git push origin origin/feat/scaffolding:refs/heads/archive/scaffolding-attempt-2
git push origin --delete feat/scaffolding
git checkout main && git pull
git checkout -b feat/scaffolding
```

- [ ] **Step 2: Write the failing test**

`tests/test_environment.py`:

```python
"""Pin the toolchain assumptions the rest of the suite depends on."""

import beets
from beets.test.helper import PluginTestHelper, TestHelper


def test_beets_meets_the_version_floor():
    major, minor = (int(part) for part in beets.__version__.split(".")[:2])
    assert (major, minor) >= (2, 12), beets.__version__


def test_plugin_test_helper_is_available():
    """PluginTestHelper arrived in beets 2.12 and is the whole reason for the
    version floor; the suite has no fallback if it disappears."""
    assert issubclass(PluginTestHelper, TestHelper)
```

Create `tests/__init__.py` as an empty file in the same step.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest -q`
Expected: FAIL — uv reports no `pyproject.toml` in the workspace, because the
project does not exist yet.

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[project]
name = "beets-plex"
version = "0.1.0"
description = "Beets plugins: Plex library sync (plex) and rating file tags (ratingtag)"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "beets>=2.12",
    "plexapi>=4.15",
    "mediafile>=0.13",
    "mutagen>=1.46",
]

# No [build-system] and no wheel target yet: a hatchling wheel target for a
# directory that does not exist builds a code-free wheel and reports success.
# PR 2 adds both together with beetsplug/ratingtag.py.
[tool.uv]
package = false

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]

[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Project metadata that a build backend would validate — `license`,
`classifiers`, `urls` — is deliberately absent until PR 2 introduces the
backend that can check it.

- [ ] **Step 5: Sync and run the tests**

```bash
uv sync
uv run pytest -q
```
Expected: 2 passed. If `uv sync` writes a `uv.lock`, that file is committed.

- [ ] **Step 6: Run the linters**

```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: both clean. If `ruff format --check` objects, run
`uv run ruff format .` and re-run the check.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/test_environment.py
git commit -m "chore: uv project with pytest and ruff"
```

---

### Task 2: Audio fixtures and the storage-style coverage pin

**Files:**
- Create: `tests/rsrc/full.mp3`, `full.flac`, `full.m4a`, `full.opus`,
  `full.wma` (recovered), `full.wav`, `full.aiff` (generated)
- Create: `tests/test_fixtures.py`

**Interfaces:**
- Produces: `tests/rsrc/` as the suite's audio fixture directory. PR 2's
  round-trip tests and PR 4's WMA pull test both read from it.

**Why this task exists at all:** `beets.test._common.RSRC` is not shipped in
the beets wheel, so `create_mediafile_fixture` and `add_album_fixture` raise
in a downstream suite. The repository needs its own fixtures.

**Why the test is not busywork:** revision 1 of the design claimed AIFF and
WAVE store no rating, and PR 2's exemption logic would have been built on
that. `MP3StorageStyle.formats` is `['MP3', 'AIFF', 'DSF', 'WAVE']` (spec F5),
so both do. This test pins the mapping from fixture to mutagen class to
covering style class, and it fails the moment anyone reintroduces a hardcoded
format list that disagrees with the styles.

- [ ] **Step 1: Write the failing test**

`tests/test_fixtures.py`:

```python
"""The audio fixtures, and what mediafile's storage styles make of them.

The style classes' `formats` lists are the single source of truth for which
formats can hold a rating tag (spec F4-F6). Nothing in this repository may
hardcode a parallel list, and this test is what makes a divergence fail.
"""

import mutagen
import pytest
from mediafile import MP3StorageStyle, MP4StorageStyle, StorageStyle

# fixture name -> (mutagen class name, style class that covers it or None)
FIXTURES = {
    "full.mp3": ("MP3", "MP3StorageStyle"),
    "full.aiff": ("AIFF", "MP3StorageStyle"),
    "full.wav": ("WAVE", "MP3StorageStyle"),
    "full.flac": ("FLAC", "StorageStyle"),
    "full.opus": ("OggOpus", "StorageStyle"),
    "full.m4a": ("MP4", "MP4StorageStyle"),
    "full.wma": ("ASF", None),
}

STYLES = {
    "MP3StorageStyle": MP3StorageStyle,
    "StorageStyle": StorageStyle,
    "MP4StorageStyle": MP4StorageStyle,
}


@pytest.mark.parametrize(("name", "expected"), sorted(FIXTURES.items()))
def test_fixture_maps_to_the_expected_storage_style(rsrc, name, expected):
    expected_class_name, expected_style = expected

    path = rsrc / name
    assert path.exists(), f"missing fixture {name}"

    class_name = type(mutagen.File(path)).__name__
    assert class_name == expected_class_name

    covering = [
        style_name
        for style_name, style in STYLES.items()
        if class_name in style.formats
    ]
    assert covering == ([expected_style] if expected_style else [])
```

This depends on an `rsrc` fixture that Task 3 creates. Write the test now,
watch it fail for that reason, and let Task 3 resolve it — the two tasks are
ordered this way so the fixture directory exists before anything needs it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_fixtures.py -q`
Expected: 7 errors, `fixture 'rsrc' not found`.

- [ ] **Step 3: Recover the five existing fixtures**

They were generated during the abandoned attempt and are already known-good
inputs to mediafile.

```bash
mkdir -p tests/rsrc
for ext in mp3 flac m4a opus wma; do
  git show origin/archive/scaffolding-attempt-2:tests/rsrc/full.$ext > tests/rsrc/full.$ext
done
```

- [ ] **Step 4: Generate the two new fixtures**

WAVE and AIFF are new in revision 2 of the design: they are the formats the
POPM style covers but that revision 1 wrongly listed as storing nothing.

```bash
ffmpeg -loglevel error -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 \
  -c:a pcm_s16le -y tests/rsrc/full.wav
ffmpeg -loglevel error -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 \
  -c:a pcm_s16be -y tests/rsrc/full.aiff
```

- [ ] **Step 5: Confirm the fixtures are what the test expects**

```bash
uv run python -c "
import mutagen, glob
for p in sorted(glob.glob('tests/rsrc/full.*')):
    print(p, type(mutagen.File(p)).__name__)
"
```
Expected, in this order: aiff AIFF, flac FLAC, m4a MP4, mp3 MP3, opus
OggOpus, wav WAVE, wma ASF. Anything else means the generated file is not the
container it claims and the step must be fixed before moving on.

- [ ] **Step 6: Commit**

```bash
git add tests/rsrc tests/test_fixtures.py
git commit -m "test: audio fixtures and storage-style coverage pin"
```

The test still fails at this point, because the `rsrc` fixture does not exist
yet. That is expected and Task 3 closes it; do not add a local fixture here to
make it green early.

---

### Task 3: Shared pytest fixtures

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_conftest.py`

**Interfaces:**
- Consumes: `tests/rsrc/` from Task 2.
- Produces: `rsrc` (a `pathlib.Path` to the fixture directory) and an autouse
  cache reset. Every later test module uses `rsrc`; the reset is silent and
  global.

**Why the cache reset:** `Item._types` is a `cached_classproperty` computed
once per process. A test that touches `Item` with no plugins loaded freezes an
empty type map for the rest of the session, and every later typed query
silently degrades to a substring match — with a green suite.

- [ ] **Step 1: Write the failing test**

`tests/test_conftest.py`:

```python
"""The conftest fixtures themselves.

The two tests below run in file order on purpose: the first populates the
per-process cache behind Item._types, the second proves the autouse fixture
emptied it again. Delete the fixture and the second test fails.
"""

from beets.library import Item
from beets.util import cached_classproperty


def test_reading_item_types_populates_the_process_cache():
    assert Item._types is not None
    assert (Item, "_types") in cached_classproperty.cache


def test_the_cache_is_empty_at_the_start_of_the_next_test():
    assert cached_classproperty.cache == {}


def test_rsrc_points_at_the_fixture_directory(rsrc):
    assert rsrc.is_dir()
    assert (rsrc / "full.flac").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_conftest.py -q`
Expected: FAIL — `fixture 'rsrc' not found`, and
`test_the_cache_is_empty_at_the_start_of_the_next_test` fails because nothing
clears the cache between tests.

- [ ] **Step 3: Write the conftest**

`tests/conftest.py`:

```python
"""Fixtures shared by the whole suite."""

from pathlib import Path

import pytest
from beets.util import cached_classproperty

RSRC = Path(__file__).parent / "rsrc"


@pytest.fixture
def rsrc() -> Path:
    """This repository's own audio fixtures.

    beets does not ship beets.test._common.RSRC in its wheel, so its
    create_mediafile_fixture and add_album_fixture helpers raise downstream.
    """
    return RSRC


@pytest.fixture(autouse=True)
def _reset_cached_classproperties():
    """Empty the per-process cache behind Item._types around every test.

    It is computed once per process, so a test that touches Item with no
    plugins loaded would freeze an empty type map for the rest of the
    session and silently downgrade every later typed query to a substring
    match.
    """
    cached_classproperty.cache.clear()
    yield
    cached_classproperty.cache.clear()
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass, including the seven from Task 2.

- [ ] **Step 5: Prove the cache reset is load-bearing**

Do not skip this. A fixture that does nothing passes exactly as well as one
that works.

```bash
# temporarily neuter the autouse fixture
uv run python - <<'EOF'
import pathlib
p = pathlib.Path("tests/conftest.py")
p.write_text(p.read_text().replace("cached_classproperty.cache.clear()", "pass"))
EOF
uv run pytest tests/test_conftest.py -q   # expect: 1 failed
git checkout tests/conftest.py
uv run pytest tests/test_conftest.py -q   # expect: 3 passed
```
Expected: the middle run fails on
`test_the_cache_is_empty_at_the_start_of_the_next_test`. If it passes, the
test is not pinning anything and must be fixed before committing.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_conftest.py
git commit -m "test: shared fixtures for audio resources and the type cache"
```

---

### Task 4: CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: the green baseline every later pull request is measured against.

- [ ] **Step 1: Write the workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --python ${{ matrix.python-version }}
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest -q
```

The matrix covers the declared floor and a current release. `ffmpeg` is not
needed in CI: the fixtures are committed binaries, generated once locally.

- [ ] **Step 2: Run the same commands locally**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```
Expected: all three clean. CI runs nothing that has not passed here first.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run ruff and pytest on pull requests"
```

---

### Task 5: README and the pull request

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the README**

Replace the placeholder with:

```markdown
# beets-plex

Two [beets](https://beets.io) plugins in one package:

- **`ratingtag`** — a `rating` field on items, stored in the beets database
  and in file tags (POPM for MP3/AIFF/WAVE/DSF, a `RATING` comment for FLAC
  and Ogg, a freeform atom for MP4).
- **`plex`** — synchronizes a beets library with a Plex Media Server: two-way
  rating sync, a one-way pull of play statistics, query-defined playlists and
  collections, and partial scans on import, move and remove.

Neither plugin is implemented yet. The design is at
`docs/superpowers/specs/2026-07-28-beets-plex-design.md` and the delivery
roadmap at `docs/superpowers/plans/2026-07-28-beets-plex-roadmap.md`.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```
```

- [ ] **Step 2: Verify the scope boundary held**

```bash
git ls-files beetsplug          # expect: no output
grep -n "build-system" pyproject.toml   # expect: no output
uv run pytest -q                # expect: all green
```

All three must hold. The first two are this pull request's scope boundary and
the reason it can be reviewed at a glance.

- [ ] **Step 3: Commit and push**

```bash
git add README.md
git commit -m "docs: describe the package and the development commands"
git push -u origin feat/scaffolding
```

- [ ] **Step 4: Open the pull request**

```bash
gh pr create --base main --title "chore: project scaffolding, CI, and audio fixtures" --body "$(cat <<'EOF'
Closes #4.

Scaffolding only: a uv virtual project, ruff and pytest configuration, CI, the
audio fixtures, and the shared pytest fixtures. No `beetsplug/` module and no
build backend — a hatchling wheel target for a directory that does not exist
builds a code-free wheel and reports success, so it lands in PR 2 with the
first module it can ship.

The one test worth a reviewer's attention is `tests/test_fixtures.py`, which
pins each fixture to the mediafile storage style that covers it. Revision 1 of
the design claimed AIFF and WAVE store no rating; `MP3StorageStyle.formats` is
`['MP3', 'AIFF', 'DSF', 'WAVE']`, so both do, and PR 2's write-verification
logic depends on getting this right.

## Verification

```
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git ls-files beetsplug   # empty
```

— 🤖 _Automated post by Claude Code (agent) via the account owner's GitHub token; agent analysis/proposal, not a personal directive from the account owner._
EOF
)"
```

- [ ] **Step 5: Stop**

Wait for CI and for review. Do not start PR 2, and do not write PR 2's plan,
until this one is merged.

## Self-review

Checked against the spec and the roadmap after writing:

- **Spec coverage.** This pull request implements the roadmap's PR 1 exit
  criteria only: uv project, lint config, CI, fixtures for all seven formats,
  and the conftest wiring. The spec's "Testing" section names four harness
  hazards; two are addressed here (the missing RSRC, the `_types` cache), one
  is inert until a test class uses the helper (the autouse
  `setup_beets`/`teardown_beets`, recorded in the spec so PR 2 does not call
  them by hand), and one is inert until a test needs terminal capture (beets'
  `io` fixture, which PR 2 or later must define locally).
- **Placeholders.** None: every step has its command or its file content.
- **Type consistency.** The `rsrc` fixture is a `pathlib.Path` in Task 3 and
  is used as one (`/`, `.exists()`, `.is_dir()`) in Tasks 2 and 3.
- **Deliberate red state.** Task 2 ends with a failing test that Task 3 fixes.
  That is the only ordering in the plan where a task does not end green, and
  it is called out in both tasks so nobody "fixes" it locally.

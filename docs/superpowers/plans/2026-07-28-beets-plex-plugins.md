# beets-plex Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two beets plugins in one package: `ratingtag` (rating field + file-tag storage) and `plex` (Plex library sync: ratings, play stats, playlists, collections, partial scans).

**Architecture:** See the approved spec at `docs/superpowers/specs/2026-07-28-beets-plex-design.md`, read it before starting. `beetsplug/ratingtag.py` owns the `rating` field and its POPM/Vorbis/MP4 tag storage; `beetsplug/plex/` is a package (plugin wiring, `match.py`, `sync.py`, `playlists.py`, `collections.py`, `scan.py`) that talks to Plex through python-plexapi and matches tracks by file path only. All Plex tests run against in-memory fakes in `tests/fakeplex.py`; no live server.

**Tech Stack:** Python >= 3.10, beets >= 2.12, python-plexapi, mediafile 0.17 / mutagen (already beets dependencies), hatchling build, uv for env management, pytest with `beets.test.helper`, ruff.

## Global Constraints

- Work on a feature branch created in Task 1: `feat/initial-plugins`.
- Every command runs through uv: `uv run pytest`, `uv run ruff check .`. Never pip.
- Conventional commit messages (`feat:`, `test:`, `chore:`, `docs:`), scope `ratingtag` or `plex` where applicable.
- Rating scale is canonically float 0-10; **unrated is 0.0 or an absent field, equivalent everywhere**. Tags: POPM 0-255 linear (MP3), `RATING` Vorbis comment 0-100 (FLAC/Ogg/Opus; legacy values <= 5 are a 0-5 star scale on read), `----:com.apple.iTunes:RATING` 0-100 (MP4). Writing an unrated value deletes the tag.
- Field names and types must match the spec's field table exactly (`plex_ratingkey` INTEGER, `plex_userrating` FLOAT, dates as `types.DATE` storing epoch floats, etc.).
- Plugin config lives in the shared `plex:` section for the plex plugin and `ratingtag:` for ratingtag. The `token` value is marked `redact = True`.
- Beets plugin logging uses `self._log.debug("found {0}", n)` str.format templates, never f-strings or %-interpolation in log calls.
- No dependencies beyond `beets`, `plexapi`, `mediafile`, `mutagen` (runtime) and `pytest`, `ruff` (dev).
- API facts verified against installed sources (do not re-derive; they are correct for beets 2.12 / mediafile 0.17):
  - `beets.test.helper.PluginTestHelper` exists; class attr `plugin: ClassVar[str]` auto-loads the plugin per test. `TestHelper.add_item(**values)` adds an item to `self.lib`. `RunMixin.run_command(*args)` runs the CLI in-process. beets' bundled fixture dir (RSRC) is NOT shipped in the wheel, use this repo's own `tests/rsrc/` fixtures.
  - `database_change` fires AFTER the dirty set is cleared; the `write` event fires while `item._dirty` is still populated. Rating-change stamping therefore uses the `write` event.
  - `mediafile.MediaField(*styles, out_type=...)` is a descriptor; `MediaField.__get__` returns the first truthy style value passed through `safe_cast` (None stays None). `MediaField.__set__(None)` converts to `_none_value()` (0.0 for float) before calling each style's `set`, so styles receive 0.0, never None.
  - `mediafile.StorageStyle` base handles FLAC + all Ogg formats (`formats` list); `MP3StorageStyle.formats = ["MP3", "AIFF", "DSF", "WAVE"]`; `MP4StorageStyle` serializes `----`-freeform values to bytes inside `serialize()`, always go through `super().set()` for MP4, never `store()` directly with a str.
  - `BeetsPlugin.add_media_field(name, descriptor)` registers the field on `MediaFile` AND adds it to `Item._media_fields`; it raises `ValueError` if the name is already registered, and mediafile class-level registration survives plugin unload, the plugin must tolerate re-registration (catch `ValueError`).
  - `Item.write()` writes only fields present in `dict(item)` intersected with `_media_fields`.
  - plexapi: `track.rate(value)` sets `userRating` and bumps `lastRatedAt`; `rate(None)` clears. `section.update(path=...)` partial-scans one folder. `section.searchTracks(container_size=N)` returns all tracks with `locations`, `userRating`, `lastRatedAt`, `viewCount`, `skipCount`, `lastViewedAt`, `guid` populated (no lazy reloads for these).
  - `ui.decargs` is deprecated, use `args` directly. Queries: `lib.items(args)` accepts a list of query parts; `parse_query_string(s, Item)` returns `(query, sort)`.

---

### Task 1: Package scaffolding, CI, and audio fixtures

**Files:**
- Create: `pyproject.toml`
- Create: `.github/workflows/ci.yml`
- Create: `tests/__init__.py` (empty), `tests/test_scaffolding.py`
- Create: `tests/rsrc/full.mp3`, `tests/rsrc/full.flac`, `tests/rsrc/full.m4a`, `tests/rsrc/full.opus` (generated, committed binaries)

**Interfaces:**
- Produces: an installable package env (`uv sync`), `tests/rsrc/full.<ext>` fixture files used by all ratingtag tests.

- [ ] **Step 1: Create the branch**

```bash
cd /mnt/code/beets-plex && git checkout -b feat/initial-plugins
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "beets-plex"
version = "0.1.0"
description = "Beets plugins: Plex music library sync (plex) and file rating tags (ratingtag)"
readme = "README.md"
license = { file = "LICENSE" }
requires-python = ">=3.10"
dependencies = [
    "beets>=2.12",
    "plexapi>=4.15",
    "mediafile>=0.13",
    "mutagen>=1.46",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]

[tool.hatch.build.targets.wheel]
packages = ["beetsplug"]

[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Write the CI workflow**

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
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest -q
```

- [ ] **Step 4: Generate the audio fixtures**

```bash
mkdir -p tests/rsrc
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 -c:a libmp3lame -q:a 9 -y tests/rsrc/full.mp3
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 -c:a flac -y tests/rsrc/full.flac
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 -c:a aac -y tests/rsrc/full.m4a
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 -c:a libopus -y tests/rsrc/full.opus
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 0.3 -c:a wmav2 -y tests/rsrc/full.wma
```

The `.wma` file is the "format without a rating storage style" fixture (ASF is
in none of the three styles' `formats` lists).

Note: the generated MP3 has no ID3 tag at all (`mutagen.File(...).tags is None`), this is intentional; the POPM code must handle tagless files, and a test covers it.

- [ ] **Step 5: Write a scaffolding test**

`tests/__init__.py` is empty. `tests/test_scaffolding.py`:

```python
from pathlib import Path

import mutagen

RSRC = Path(__file__).parent / "rsrc"


def test_fixtures_are_valid_audio():
    for ext in ("mp3", "flac", "m4a", "opus", "wma"):
        f = mutagen.File(RSRC / f"full.{ext}")
        assert f is not None, ext


def test_beets_and_plexapi_importable():
    import beets
    import plexapi

    assert beets.__version__ >= "2.12"
    assert plexapi.VERSION
```

- [ ] **Step 6: Sync the env and run**

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

Expected: 2 passed, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .github tests
git commit -m "chore: package scaffolding, CI workflow, audio test fixtures"
```

---

### Task 2: ratingtag rating-scale conversions

**Files:**
- Create: `beetsplug/ratingtag.py` (conversions only in this task)
- Create: `tests/test_ratingtag_conversions.py`

**Interfaces:**
- Produces: `rating_from_popm(raw: int | None) -> float | None`, `rating_to_popm(value: float) -> int` (1-255), `rating_from_vorbis(raw) -> float | None`, `rating_to_vorbis(value: float) -> str` ("10".."100"). Canonical values are 0-10 floats rounded to 1 decimal; `None` means unrated on read.

- [ ] **Step 1: Write the failing tests**

`tests/test_ratingtag_conversions.py`:

```python
import pytest

from beetsplug.ratingtag import (
    rating_from_popm,
    rating_from_vorbis,
    rating_to_popm,
    rating_to_vorbis,
)


def half_stars():
    return [n / 2.0 for n in range(2, 21)]  # 1.0 .. 10.0


@pytest.mark.parametrize("value", half_stars())
def test_popm_roundtrip_is_exact_for_half_stars(value):
    assert rating_from_popm(rating_to_popm(value)) == value


@pytest.mark.parametrize("value", half_stars())
def test_vorbis_roundtrip_is_exact_for_half_stars(value):
    assert rating_from_vorbis(rating_to_vorbis(value)) == value


def test_popm_zero_and_none_read_as_unrated():
    assert rating_from_popm(0) is None
    assert rating_from_popm(None) is None


def test_popm_full_scale_endpoints():
    assert rating_to_popm(10.0) == 255
    assert rating_from_popm(255) == 10.0


def test_vorbis_legacy_five_star_scale_on_read():
    assert rating_from_vorbis("3") == 6.0
    assert rating_from_vorbis("4.5") == 9.0
    assert rating_from_vorbis("5") == 10.0


def test_vorbis_mediamonkey_scale_on_read():
    assert rating_from_vorbis("45") == 4.5
    assert rating_from_vorbis("100") == 10.0


def test_vorbis_zero_negative_and_junk_read_as_unrated():
    assert rating_from_vorbis("0") is None
    assert rating_from_vorbis("-3") is None
    assert rating_from_vorbis("abc") is None
    assert rating_from_vorbis(None) is None


def test_vorbis_write_clamps_below_one_to_avoid_legacy_range():
    # Written values must never land in 1..5, which reads as star scale.
    assert rating_to_vorbis(0.5) == "10"
    assert rating_from_vorbis(rating_to_vorbis(0.5)) == 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ratingtag_conversions.py -q`
Expected: FAIL with ImportError (module does not exist).

- [ ] **Step 3: Implement the conversions**

`beetsplug/ratingtag.py`:

```python
"""Store track ratings (0-10) in the beets DB and in file tags.

Tag conventions:
- MP3: POPM frame (0-255 linear), identified by the configured popm_email.
- FLAC/Ogg/Opus: RATING Vorbis comment, 0-100 (MediaMonkey scale); legacy
  values of 5 or less are read as a 0-5 star scale.
- MP4: ----:com.apple.iTunes:RATING freeform atom, 0-100.

Unrated is 0.0 or an absent field; writing an unrated value removes the tag.
"""


def rating_from_popm(raw):
    """POPM byte (0-255) to canonical 0-10 float; 0/None means unrated."""
    if not raw:
        return None
    return round(float(raw) * 10.0 / 255.0, 1)


def rating_to_popm(value):
    """Canonical 0-10 float to POPM byte, minimum 1."""
    return max(1, min(255, int(round(float(value) * 25.5))))


def rating_from_vorbis(raw):
    """RATING comment string to canonical 0-10 float; None when unrated."""
    if raw is None:
        return None
    try:
        num = float(str(raw))
    except ValueError:
        return None
    if num <= 0:
        return None
    if num <= 5:  # legacy 0-5 star scale
        return round(num * 2.0, 1)
    return round(num / 10.0, 1)


def rating_to_vorbis(value):
    """Canonical 0-10 float to a 0-100 integer string.

    Clamped to a minimum of "10" so written values never land in the 1-5
    range, which reads back as the legacy star scale.
    """
    return str(max(10, min(100, int(round(float(value) * 10)))))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_ratingtag_conversions.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add beetsplug/ratingtag.py tests/test_ratingtag_conversions.py
git commit -m "feat(ratingtag): rating scale conversions (POPM, Vorbis/MP4)"
```

---

### Task 3: Vorbis and MP4 storage styles

**Files:**
- Modify: `beetsplug/ratingtag.py`
- Create: `tests/conftest.py`
- Create: `tests/test_ratingtag_styles.py` (Vorbis/MP4 tests in this task)

**Interfaces:**
- Consumes: conversions from Task 2.
- Produces: `VorbisRatingStorageStyle()` and `MP4RatingStorageStyle()` classes with mediafile's `get(mutagen_file)` / `set(mutagen_file, value)` / `delete(mutagen_file)` protocol; `media_path` pytest fixture (copies `tests/rsrc/full.<ext>` to a tmp dir and returns the Path).

- [ ] **Step 1: Write the shared fixture**

`tests/conftest.py`:

```python
import shutil
from pathlib import Path

import pytest

RSRC = Path(__file__).parent / "rsrc"


@pytest.fixture
def media_path(tmp_path):
    """Copy a fixture audio file into tmp and return its path."""

    def _copy(ext):
        dst = tmp_path / f"track.{ext}"
        shutil.copyfile(RSRC / f"full.{ext}", dst)
        return dst

    return _copy
```

- [ ] **Step 2: Write the failing tests**

`tests/test_ratingtag_styles.py`:

```python
import mutagen
import pytest

from beetsplug.ratingtag import (
    MP4RatingStorageStyle,
    VorbisRatingStorageStyle,
)


@pytest.mark.parametrize("ext", ["flac", "opus"])
def test_vorbis_write_read_roundtrip(media_path, ext):
    path = media_path(ext)
    style = VorbisRatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 8.0)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 8.0
    assert f2["RATING"] == ["80"]


def test_vorbis_legacy_value_read(media_path):
    path = media_path("flac")
    f = mutagen.File(path)
    f["RATING"] = ["4"]  # legacy 0-5 stars
    f.save()
    assert VorbisRatingStorageStyle().get(mutagen.File(path)) == 8.0


def test_vorbis_unrated_write_removes_tag(media_path):
    path = media_path("flac")
    style = VorbisRatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 6.0)
    style.set(f, 0.0)
    f.save()
    f2 = mutagen.File(path)
    assert "RATING" not in f2
    assert style.get(f2) is None


def test_mp4_write_read_roundtrip(media_path):
    path = media_path("m4a")
    style = MP4RatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 7.5)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 7.5


def test_mp4_unrated_write_removes_tag(media_path):
    path = media_path("m4a")
    style = MP4RatingStorageStyle()
    f = mutagen.File(path)
    style.set(f, 7.5)
    style.set(f, 0.0)
    f.save()
    assert style.get(mutagen.File(path)) is None
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_ratingtag_styles.py -q`
Expected: FAIL with ImportError (classes not defined).

- [ ] **Step 4: Implement the styles**

Append to `beetsplug/ratingtag.py` (imports go at the top of the file):

```python
import mediafile


class VorbisRatingStorageStyle(mediafile.StorageStyle):
    """RATING Vorbis comment, 0-100; values <= 5 read as 0-5 stars."""

    def __init__(self):
        super().__init__("RATING")

    def get(self, mutagen_file):
        return rating_from_vorbis(self.fetch(mutagen_file))

    def set(self, mutagen_file, value):
        value = float(value or 0)
        if value <= 0:
            self.delete(mutagen_file)
        else:
            super().set(mutagen_file, rating_to_vorbis(value))


class MP4RatingStorageStyle(mediafile.MP4StorageStyle):
    """RATING freeform atom, 0-100 scale (no legacy star handling)."""

    def __init__(self):
        super().__init__("----:com.apple.iTunes:RATING")

    def get(self, mutagen_file):
        raw = self.fetch(mutagen_file)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")
        return rating_from_vorbis(raw)

    def set(self, mutagen_file, value):
        value = float(value or 0)
        if value <= 0:
            self.delete(mutagen_file)
        else:
            super().set(mutagen_file, rating_to_vorbis(value))
```

Implementation notes:
- `StorageStyle.delete` exists on the base class (deletes `self.key`); do not reimplement.
- For MP4, `super().set()` must be used (its `serialize()` encodes freeform values to bytes); calling `store()` with a str corrupts the atom.
- If the base `delete` raises `KeyError` on a missing key (check the mediafile source at `mediafile/storage/base.py` if the unrated test fails), wrap it in try/except KeyError.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_ratingtag_styles.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add beetsplug/ratingtag.py tests/conftest.py tests/test_ratingtag_styles.py
git commit -m "feat(ratingtag): Vorbis and MP4 rating storage styles"
```

---

### Task 4: POPM storage style for MP3

**Files:**
- Modify: `beetsplug/ratingtag.py`
- Modify: `tests/test_ratingtag_styles.py` (append POPM tests)

**Interfaces:**
- Produces: `PopmRatingStorageStyle(email: str)` with the same get/set/delete protocol.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ratingtag_styles.py`:

```python
import mutagen.id3

from beetsplug.ratingtag import PopmRatingStorageStyle


def test_popm_write_read_roundtrip_on_tagless_file(media_path):
    # The fixture MP3 has no ID3 tag at all; set() must create one.
    path = media_path("mp3")
    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    assert f.tags is None
    style.set(f, 8.0)
    f.save()
    f2 = mutagen.File(path)
    assert style.get(f2) == 8.0
    assert f2.tags.getall("POPM")[0].rating == 204


def test_popm_foreign_email_frames_are_ignored_and_preserved(media_path):
    path = media_path("mp3")
    f = mutagen.File(path)
    f.add_tags()
    f.tags.add(mutagen.id3.POPM(email="other@player", rating=100))
    f.save()

    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    assert style.get(f) is None  # only our email counts
    style.set(f, 5.0)
    f.save()

    f2 = mutagen.File(path)
    frames = {frame.email: frame.rating for frame in f2.tags.getall("POPM")}
    assert frames["other@player"] == 100
    assert frames["beets@example.com"] == 128


def test_popm_zero_rating_reads_as_unrated(media_path):
    path = media_path("mp3")
    f = mutagen.File(path)
    f.add_tags()
    f.tags.add(mutagen.id3.POPM(email="beets@example.com", rating=0))
    f.save()
    assert PopmRatingStorageStyle("beets@example.com").get(mutagen.File(path)) is None


def test_popm_unrated_write_removes_only_our_frame(media_path):
    path = media_path("mp3")
    f = mutagen.File(path)
    f.add_tags()
    f.tags.add(mutagen.id3.POPM(email="other@player", rating=100))
    f.tags.add(mutagen.id3.POPM(email="beets@example.com", rating=200))
    f.save()

    style = PopmRatingStorageStyle("beets@example.com")
    f = mutagen.File(path)
    style.set(f, 0.0)
    f.save()

    f2 = mutagen.File(path)
    emails = [frame.email for frame in f2.tags.getall("POPM")]
    assert emails == ["other@player"]


def test_popm_empty_email_config(media_path):
    path = media_path("mp3")
    style = PopmRatingStorageStyle("")
    f = mutagen.File(path)
    style.set(f, 9.0)
    f.save()
    assert style.get(mutagen.File(path)) == 9.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ratingtag_styles.py -q`
Expected: new tests FAIL with ImportError.

- [ ] **Step 3: Implement the style**

Append to `beetsplug/ratingtag.py` (add `import mutagen.id3` at the top):

```python
class PopmRatingStorageStyle(mediafile.MP3StorageStyle):
    """Rating in a POPM frame, linear 0-255, matched by email."""

    def __init__(self, email):
        super().__init__("POPM")
        self.email = email or ""

    def _frame(self, mutagen_file):
        if mutagen_file.tags is None:
            return None
        for frame in mutagen_file.tags.getall("POPM"):
            if (frame.email or "") == self.email:
                return frame
        return None

    def get(self, mutagen_file):
        frame = self._frame(mutagen_file)
        return rating_from_popm(frame.rating) if frame else None

    def set(self, mutagen_file, value):
        value = float(value or 0)
        if value <= 0:
            self.delete(mutagen_file)
            return
        if mutagen_file.tags is None:
            mutagen_file.add_tags()
        frame = self._frame(mutagen_file)
        if frame is None:
            mutagen_file.tags.add(
                mutagen.id3.POPM(email=self.email, rating=rating_to_popm(value))
            )
        else:
            frame.rating = rating_to_popm(value)

    def delete(self, mutagen_file):
        if mutagen_file.tags is None:
            return
        keep = [
            frame
            for frame in mutagen_file.tags.getall("POPM")
            if (frame.email or "") != self.email
        ]
        mutagen_file.tags.setall("POPM", keep)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_ratingtag_styles.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add beetsplug/ratingtag.py tests/test_ratingtag_styles.py
git commit -m "feat(ratingtag): POPM rating storage style for MP3"
```

---

### Task 5: ratingtag plugin class and beets round-trip

**Files:**
- Modify: `beetsplug/ratingtag.py`
- Create: `tests/test_ratingtag_plugin.py`

**Interfaces:**
- Consumes: the three storage styles.
- Produces: `RatingTagPlugin` (BeetsPlugin) declaring `item_types = {"rating": types.FLOAT}` and registering the `rating` media field. After this task, `item["rating"] = x; item.write()` writes tags and `Item.from_path` reads them back.

- [ ] **Step 1: Write the failing tests**

`tests/test_ratingtag_plugin.py`:

```python
import shutil
from pathlib import Path

import pytest
from beets.library import Item
from beets.test.helper import PluginTestHelper

RSRC = Path(__file__).parent / "rsrc"


class TestRatingTagPlugin(PluginTestHelper):
    plugin = "ratingtag"

    def _item_with_file(self, ext, tmp_path):
        dst = tmp_path / f"track.{ext}"
        shutil.copyfile(RSRC / f"full.{ext}", dst)
        item = Item.from_path(bytes(dst))
        item.add(self.lib)
        return item, dst

    @pytest.mark.parametrize("ext", ["mp3", "flac", "m4a", "opus"])
    def test_write_read_roundtrip_through_beets(self, tmp_path, ext):
        item, dst = self._item_with_file(ext, tmp_path)
        item["rating"] = 7.0
        item.write()

        fresh = Item.from_path(bytes(dst))
        assert fresh["rating"] == 7.0

    def test_unrated_file_reads_as_unrated(self, tmp_path):
        item, dst = self._item_with_file("flac", tmp_path)
        fresh = Item.from_path(bytes(dst))
        assert not fresh.get("rating")

    def test_clearing_rating_clears_tag(self, tmp_path):
        item, dst = self._item_with_file("flac", tmp_path)
        item["rating"] = 7.0
        item.write()
        item["rating"] = 0.0
        item.write()
        fresh = Item.from_path(bytes(dst))
        assert not fresh.get("rating")

    def test_rating_is_a_typed_float_field(self):
        item = self.add_item(title="x")
        item["rating"] = 8.0
        item.store()
        results = self.lib.items("rating:7..9")
        assert [i.title for i in results] == ["x"]

    def test_format_without_rating_style_writes_safely(self, tmp_path):
        # ASF/WMA has no rating storage style; write() must succeed and
        # simply not store a rating tag.
        item, dst = self._item_with_file("wma", tmp_path)
        item["rating"] = 7.0
        item.write()
        fresh = Item.from_path(bytes(dst))
        assert not fresh.get("rating")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ratingtag_plugin.py -q`
Expected: FAIL, the module has no BeetsPlugin subclass, so plugin loading errors.

- [ ] **Step 3: Implement the plugin class**

Append to `beetsplug/ratingtag.py` (imports at top: `from typing import ClassVar`, `from beets.dbcore import types`, `from beets.plugins import BeetsPlugin`):

```python
class RatingTagPlugin(BeetsPlugin):
    item_types: ClassVar[dict] = {"rating": types.FLOAT}

    def __init__(self):
        super().__init__()
        self.config.add({"popm_email": ""})
        field = mediafile.MediaField(
            PopmRatingStorageStyle(self.config["popm_email"].as_str()),
            VorbisRatingStorageStyle(),
            MP4RatingStorageStyle(),
            out_type=float,
        )
        try:
            self.add_media_field("rating", field)
        except ValueError:
            # mediafile keeps class-level registrations across plugin
            # reloads in one process (e.g. the test suite).
            pass
```

Implementation notes:
- If `test_unrated_file_reads_as_unrated` fails because `Item.from_path` stores a literal `None`, relax the assertion path in the implementation, not the test: the contract is `not fresh.get("rating")`, which accepts None, 0.0, and absent.
- If `add_item` in `test_rating_is_a_typed_float_field` needs a path value, pass any string path; the item is never written.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_ratingtag_plugin.py -q` then `uv run pytest -q`
Expected: all PASS (full suite).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add beetsplug/ratingtag.py tests/test_ratingtag_plugin.py
git commit -m "feat(ratingtag): plugin class with rating field and media-field registration"
```

---

### Task 6: Fake plexapi layer for tests

**Files:**
- Create: `tests/fakeplex.py`
- Create: `tests/test_fakeplex.py`

**Interfaces:**
- Produces (used by every plex-plugin test):
  - `FakeTrack(ratingKey, locations, title="t", userRating=None, lastRatedAt=None, viewCount=0, skipCount=0, lastViewedAt=None, guid=None)` with `rate(value)` recording into `rate_calls` and bumping `lastRatedAt`.
  - `FakeMusicSection(tracks=(), title="Music", key=1)` with `searchTracks(**kw)`, `update(path=None)` recording into `update_calls`, `collections()`.
  - `FakePlaylist` / `FakeCollection` with the plexapi read/mutate surface used by the plugin.
  - `FakeServer(section)` with `library.section(name)` (raises `plexapi.exceptions.NotFound` for unknown names), `playlists(playlistType=None)`, `createPlaylist(title, items=...)`, `createCollection(title, section=..., items=...)`, `friendlyName`.

- [ ] **Step 1: Write the fake layer**

`tests/fakeplex.py`:

```python
"""In-memory stand-ins for the plexapi objects the plex plugin touches."""

from datetime import datetime

from plexapi.exceptions import NotFound


class FakeTrack:
    def __init__(
        self,
        ratingKey,
        locations,
        title="t",
        userRating=None,
        lastRatedAt=None,
        viewCount=0,
        skipCount=0,
        lastViewedAt=None,
        guid=None,
    ):
        self.ratingKey = ratingKey
        self.locations = list(locations)
        self.title = title
        self.userRating = userRating
        self.lastRatedAt = lastRatedAt
        self.viewCount = viewCount
        self.skipCount = skipCount
        self.lastViewedAt = lastViewedAt
        self.guid = guid or f"plex://track/{ratingKey}"
        self.rate_calls = []

    def rate(self, value):
        self.rate_calls.append(value)
        self.userRating = value
        self.lastRatedAt = datetime.now()


class FakePlaylist:
    def __init__(self, server, title, items, smart=False, playlistType="audio"):
        self._server = server
        self.title = title
        self._items = list(items)
        self.smart = smart
        self.playlistType = playlistType

    def items(self):
        return list(self._items)

    def delete(self):
        self._server._playlists.remove(self)


class FakeCollection:
    def __init__(self, section, title, items, smart=False, subtype="track"):
        self._section = section
        self.title = title
        self._items = list(items)
        self.smart = smart
        self.subtype = subtype
        self.added = []
        self.removed = []

    def items(self):
        return list(self._items)

    def addItems(self, items):
        self.added.append(list(items))
        self._items.extend(items)

    def removeItems(self, items):
        self.removed.append(list(items))
        keys = {t.ratingKey for t in items}
        self._items = [t for t in self._items if t.ratingKey not in keys]

    def delete(self):
        self._section._collections.remove(self)


class FakeMusicSection:
    def __init__(self, tracks=(), title="Music", key=1):
        self.tracks = list(tracks)
        self.title = title
        self.key = key
        self.update_calls = []
        self._collections = []

    def searchTracks(self, container_size=None, **kwargs):
        return list(self.tracks)

    def update(self, path=None):
        self.update_calls.append(path)

    def collections(self):
        return list(self._collections)


class _FakeLibrary:
    def __init__(self, sections):
        self._sections = {s.title: s for s in sections}

    def section(self, name):
        try:
            return self._sections[name]
        except KeyError:
            raise NotFound(name) from None


class FakeServer:
    def __init__(self, section):
        self.library = _FakeLibrary([section])
        self.friendlyName = "fakeplex"
        self._playlists = []
        self._section = section

    def playlists(self, playlistType=None, **kwargs):
        return [
            p
            for p in self._playlists
            if playlistType is None or p.playlistType == playlistType
        ]

    def createPlaylist(self, title, items=None, **kwargs):
        playlist = FakePlaylist(self, title, items or [])
        self._playlists.append(playlist)
        return playlist

    def createCollection(self, title, section=None, items=None, **kwargs):
        section = section or self._section
        collection = FakeCollection(section, title, items or [])
        section._collections.append(collection)
        return collection
```

- [ ] **Step 2: Write smoke tests**

`tests/test_fakeplex.py`:

```python
import pytest
from plexapi.exceptions import NotFound

from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack


def test_rate_records_and_bumps_lastratedat():
    track = FakeTrack(1, ["/music/a.mp3"])
    track.rate(8.0)
    assert track.userRating == 8.0
    assert track.rate_calls == [8.0]
    assert track.lastRatedAt is not None


def test_unknown_section_raises_notfound():
    server = FakeServer(FakeMusicSection())
    with pytest.raises(NotFound):
        server.library.section("nope")


def test_playlist_lifecycle():
    server = FakeServer(FakeMusicSection())
    tracks = [FakeTrack(1, ["/music/a.mp3"]), FakeTrack(2, ["/music/b.mp3"])]
    playlist = server.createPlaylist("mix", items=tracks)
    assert [t.ratingKey for t in playlist.items()] == [1, 2]
    playlist.delete()
    assert server.playlists() == []


def test_collection_diff_surface():
    section = FakeMusicSection()
    server = FakeServer(section)
    a, b = FakeTrack(1, ["/music/a.mp3"]), FakeTrack(2, ["/music/b.mp3"])
    collection = server.createCollection("col", section=section, items=[a])
    collection.addItems([b])
    collection.removeItems([a])
    assert [t.ratingKey for t in collection.items()] == [2]
```

- [ ] **Step 3: Run and commit**

Run: `uv run pytest tests/test_fakeplex.py -q`
Expected: all PASS.

```bash
git add tests/fakeplex.py tests/test_fakeplex.py
git commit -m "test(plex): in-memory fake plexapi layer"
```

---

### Task 7: plex plugin skeleton (config, fields, connection, dispatch)

**Files:**
- Create: `beetsplug/plex/__init__.py`
- Create: `tests/test_plex_plugin.py`

**Interfaces:**
- Produces (used by every later plex task):
  - `PlexPlugin(BeetsPlugin)` with the spec's `item_types` dict.
  - `plugin.server()` -> plexapi `PlexServer` (lazy, cached in `plugin._server`; tests inject fakes by assigning `plugin._server`). Raises `ui.UserError` on connection failure.
  - `plugin.music()` -> the configured library section; `ui.UserError` if missing.
  - `plugin.dirs()` -> `(beets_dir, plex_dir)` strings without trailing separators.
  - `plugin.suspend_stamp()` context manager toggling `plugin._suspend_rating_stamp`.
  - CLI: `beet plex <sub>` dispatching to `plugin.cmd_<sub>(lib, opts, rest_args)`; unknown or missing subcommand raises `ui.UserError`. Options: `--pretend`, `--pull`, `--push`, `--full`.
  - Test helper convention: `plex_plugin()` in `tests/test_plex_plugin.py` fetches the live plugin instance via `beets.plugins.find_plugins()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_plugin.py`:

```python
import pytest
from beets import plugins as plugin_registry
from beets import ui
from beets.test.helper import PluginTestHelper

from tests.fakeplex import FakeMusicSection, FakeServer


def plex_plugin():
    return next(p for p in plugin_registry.find_plugins() if p.name == "plex")


class TestPlexPluginSkeleton(PluginTestHelper):
    plugin = "plex"

    def test_config_defaults(self):
        from beets import config

        assert config["plex"]["port"].get(int) == 32400
        assert config["plex"]["library_name"].as_str() == "Music"
        assert config["plex"]["auto_scan"].get(bool) is True
        assert config["plex"]["conflict"].as_str() == "plex"
        assert config["plex"]["token"].redact

    def test_dirs_default_to_beets_directory(self):
        from beets import config

        config["directory"] = "/music"
        beets_dir, plex_dir = plex_plugin().dirs()
        assert beets_dir == "/music"
        assert plex_dir == "/music"

    def test_dirs_use_configured_prefixes(self):
        from beets import config

        config["plex"]["beets_dir"] = "/mnt/music/"
        config["plex"]["plex_dir"] = "/data/music/"
        assert plex_plugin().dirs() == ("/mnt/music", "/data/music")

    def test_music_reports_missing_library_section(self):
        from beets import config

        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(title="Muziek"))
        config["plex"]["library_name"] = "Does Not Exist"
        with pytest.raises(ui.UserError):
            plugin.music()

    def test_music_finds_section(self):
        from beets import config

        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(title="Muziek"))
        config["plex"]["library_name"] = "Muziek"
        assert plugin.music().title == "Muziek"

    def test_unknown_subcommand_raises(self):
        with pytest.raises(ui.UserError):
            self.run_command("plex", "bogus")

    def test_missing_subcommand_raises(self):
        with pytest.raises(ui.UserError):
            self.run_command("plex")

    def test_dispatch_reaches_handler(self, monkeypatch):
        calls = []
        plugin = plex_plugin()
        monkeypatch.setattr(
            plugin,
            "cmd_status",
            lambda lib, opts, args: calls.append(args),
            raising=False,
        )
        self.run_command("plex", "status", "extra")
        assert calls == [["extra"]]

    def test_suspend_stamp_context(self):
        plugin = plex_plugin()
        assert plugin._suspend_rating_stamp is False
        with plugin.suspend_stamp():
            assert plugin._suspend_rating_stamp is True
        assert plugin._suspend_rating_stamp is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_plugin.py -q`
Expected: FAIL, `beetsplug.plex` does not exist.

- [ ] **Step 3: Implement the skeleton**

`beetsplug/plex/__init__.py`:

```python
"""Synchronize the beets library with a Plex music library."""

from contextlib import contextmanager
from typing import ClassVar

from beets import config, ui
from beets.dbcore import types
from beets.plugins import BeetsPlugin

SUBCOMMANDS = ("sync", "playlists", "collections", "scan", "status")


class PlexPlugin(BeetsPlugin):
    item_types: ClassVar[dict] = {
        "rating": types.FLOAT,
        "plex_userrating": types.FLOAT,
        "plex_ratingkey": types.INTEGER,
        "plex_guid": types.STRING,
        "plex_lastratedat": types.DATE,
        "plex_lastviewedat": types.DATE,
        "plex_viewcount": types.INTEGER,
        "plex_skipcount": types.INTEGER,
        "plex_updated": types.DATE,
        "rating_updated": types.DATE,
    }

    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "host": "localhost",
                "port": 32400,
                "token": "",
                "library_name": "Music",
                "secure": False,
                "beets_dir": None,
                "plex_dir": None,
                "auto_scan": True,
                "conflict": "plex",
                "playlists": [],
                "collections": [],
            }
        )
        self.config["token"].redact = True
        self._server = None
        self._suspend_rating_stamp = False
        self._scan_dirs = set()

    # -- connection ----------------------------------------------------

    def server(self):
        if self._server is None:
            from plexapi.server import PlexServer

            scheme = "https" if self.config["secure"].get(bool) else "http"
            host = self.config["host"].as_str()
            port = self.config["port"].get(int)
            baseurl = f"{scheme}://{host}:{port}"
            # TLS certificates are always verified; plexupdate's
            # ignore_cert_errors is deliberately not supported.
            try:
                self._server = PlexServer(baseurl, self.config["token"].as_str())
            except Exception as exc:
                raise ui.UserError(f"plex: cannot connect to {baseurl}: {exc}")
        return self._server

    def music(self):
        from plexapi.exceptions import NotFound

        name = self.config["library_name"].as_str()
        try:
            return self.server().library.section(name)
        except NotFound:
            raise ui.UserError(f"plex: no library section named {name!r}")

    def dirs(self):
        beets_dir = self.config["beets_dir"].get()
        if not beets_dir:
            beets_dir = config["directory"].as_filename()
        plex_dir = self.config["plex_dir"].get() or beets_dir
        return str(beets_dir).rstrip("/"), str(plex_dir).rstrip("/")

    @contextmanager
    def suspend_stamp(self):
        self._suspend_rating_stamp = True
        try:
            yield
        finally:
            self._suspend_rating_stamp = False

    # -- CLI -----------------------------------------------------------

    def commands(self):
        cmd = ui.Subcommand("plex", help="synchronize with a Plex music library")
        cmd.parser.add_option(
            "--pretend", action="store_true", help="report actions without changes"
        )
        cmd.parser.add_option(
            "--pull", action="store_true", help="sync: only pull changes from Plex"
        )
        cmd.parser.add_option(
            "--push", action="store_true", help="sync: only push changes to Plex"
        )
        cmd.parser.add_option(
            "--full", action="store_true", help="scan: refresh the whole section"
        )
        cmd.func = self._dispatch
        return [cmd]

    def _dispatch(self, lib, opts, args):
        if not args:
            raise ui.UserError("plex: subcommand required: " + ", ".join(SUBCOMMANDS))
        sub, rest = args[0], list(args[1:])
        handler = getattr(self, f"cmd_{sub}", None)
        if sub not in SUBCOMMANDS or handler is None:
            raise ui.UserError(f"plex: unknown subcommand {sub!r}")
        handler(lib, opts, rest)
```

Note: `cmd_*` handler methods are added by later tasks; until then a listed
subcommand without a handler raises the unknown-subcommand `UserError`, which
is the desired behavior mid-build.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_plugin.py -q` then `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add beetsplug/plex tests/test_plex_plugin.py
git commit -m "feat(plex): plugin skeleton with config, fields, connection, dispatch"
```

---

### Task 8: path matching (match.py)

**Files:**
- Create: `beetsplug/plex/match.py`
- Create: `tests/test_plex_match.py`

**Interfaces:**
- Consumes: `FakeTrack`, `FakeMusicSection`.
- Produces:
  - `plex_path(item_path: bytes | str, beets_dir: str, plex_dir: str) -> str | None` (None when outside beets_dir).
  - `build_path_map(music, container_size=1000) -> dict[str, Track]` (every track location maps to its track).
  - `resolve(item, path_map, beets_dir, plex_dir) -> Track | None`, path-map is authoritative; the `plex_ratingkey` DB field is a mirror written by sync, never trusted for resolution.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_match.py`:

```python
from beets.library import Item

from beetsplug.plex import match
from tests.fakeplex import FakeMusicSection, FakeTrack


def test_plex_path_translates_prefix():
    assert (
        match.plex_path(b"/mnt/music/A/b.flac", "/mnt/music", "/data/music")
        == "/data/music/A/b.flac"
    )


def test_plex_path_identity_mapping():
    assert (
        match.plex_path(b"/mnt/music/A/b.flac", "/mnt/music", "/mnt/music")
        == "/mnt/music/A/b.flac"
    )


def test_plex_path_outside_library_is_none():
    assert match.plex_path(b"/elsewhere/x.mp3", "/mnt/music", "/mnt/music") is None


def test_plex_path_rejects_sibling_prefix():
    # /mnt/music2 must not match the /mnt/music prefix
    assert match.plex_path(b"/mnt/music2/x.mp3", "/mnt/music", "/plex") is None


def test_build_path_map_covers_all_locations():
    a = FakeTrack(1, ["/plex/A/a.flac"])
    b = FakeTrack(2, ["/plex/B/b.mp3", "/plex/B/b.flac"])
    music = FakeMusicSection(tracks=[a, b])
    path_map = match.build_path_map(music)
    assert path_map["/plex/A/a.flac"] is a
    assert path_map["/plex/B/b.mp3"] is b
    assert path_map["/plex/B/b.flac"] is b


def test_resolve_by_path_ignores_stale_ratingkey():
    track = FakeTrack(99, ["/plex/A/a.flac"])
    music = FakeMusicSection(tracks=[track])
    path_map = match.build_path_map(music)
    item = Item(path=b"/music/A/a.flac")
    item["plex_ratingkey"] = 12345  # stale; must not matter
    assert match.resolve(item, path_map, "/music", "/plex") is track


def test_resolve_unmatched_returns_none():
    path_map = {}
    item = Item(path=b"/music/A/missing.flac")
    assert match.resolve(item, path_map, "/music", "/plex") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_match.py -q`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement match.py**

`beetsplug/plex/match.py`:

```python
"""Map beets items to Plex tracks by file path."""

import os

from beets import util


def plex_path(item_path, beets_dir, plex_dir):
    """Translate a beets item path to the path the Plex server sees.

    Returns None when the item lies outside beets_dir.
    """
    path = util.displayable_path(item_path)
    base = beets_dir.rstrip(os.sep)
    if not path.startswith(base + os.sep):
        return None
    return plex_dir.rstrip(os.sep) + path[len(base) :]


def build_path_map(music, container_size=1000):
    """One paged sweep of the music section: every file location -> track."""
    path_map = {}
    for track in music.searchTracks(container_size=container_size):
        for location in track.locations:
            path_map[location] = track
    return path_map


def resolve(item, path_map, beets_dir, plex_dir):
    """Find the Plex track for a beets item, or None when unmatched.

    The path map is authoritative; cached ratingKeys in the database are
    mirrors for queries, not identities.
    """
    target = plex_path(item.path, beets_dir, plex_dir)
    if target is None:
        return None
    return path_map.get(target)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_match.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add beetsplug/plex/match.py tests/test_plex_match.py
git commit -m "feat(plex): path-based track matching"
```

---

### Task 9: merge decision logic (sync.decide)

**Files:**
- Create: `beetsplug/plex/sync.py` (decision logic only in this task)
- Create: `tests/test_plex_sync_decide.py`

**Interfaces:**
- Produces:
  - constants `NONE = "none"`, `PULL = "pull"`, `PUSH = "push"`.
  - `normalize(value) -> float` (None -> 0.0, else round(float, 1)).
  - `Decision(action: str, value: float)` dataclass, `value` is always the final agreed rating (what `plex_userrating` becomes after the action).
  - `decide(base, beets_value, plex_value, rating_updated, plex_lastratedat, conflict) -> Decision` where `rating_updated` is an epoch float or None, `plex_lastratedat` a datetime or None, `conflict` is `"plex"` or `"beets"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_sync_decide.py`:

```python
from datetime import datetime, timedelta

import pytest

from beetsplug.plex.sync import NONE, PULL, PUSH, decide, normalize


def test_normalize():
    assert normalize(None) == 0.0
    assert normalize(0) == 0.0
    assert normalize(7.96) == 8.0


def test_no_changes():
    d = decide(8.0, 8.0, 8.0, None, None, "plex")
    assert (d.action, d.value) == (NONE, 8.0)


def test_never_synced_and_unrated_everywhere():
    d = decide(None, None, None, None, None, "plex")
    assert (d.action, d.value) == (NONE, 0.0)


def test_plex_changed_pulls():
    d = decide(6.0, 6.0, 9.0, None, None, "plex")
    assert (d.action, d.value) == (PULL, 9.0)


def test_plex_cleared_pulls_clear():
    d = decide(6.0, 6.0, None, None, None, "plex")
    assert (d.action, d.value) == (PULL, 0.0)


def test_beets_changed_pushes():
    d = decide(6.0, 9.0, 6.0, None, None, "plex")
    assert (d.action, d.value) == (PUSH, 9.0)


def test_beets_cleared_pushes_clear():
    d = decide(6.0, None, 6.0, None, None, "plex")
    assert (d.action, d.value) == (PUSH, 0.0)


def test_first_sync_pull_only_plex_rated():
    # base absent, beets unrated, plex rated -> pull
    d = decide(None, None, 8.0, None, None, "plex")
    assert (d.action, d.value) == (PULL, 8.0)


def test_first_sync_push_only_beets_rated():
    d = decide(None, 8.0, None, None, None, "plex")
    assert (d.action, d.value) == (PUSH, 8.0)


def test_both_changed_to_same_value_needs_no_network_action():
    d = decide(6.0, 9.0, 9.0, None, None, "plex")
    assert (d.action, d.value) == (NONE, 9.0)


def test_both_changed_newest_wins_beets():
    now = datetime.now()
    d = decide(
        6.0,
        9.0,
        4.0,
        rating_updated=now.timestamp(),
        plex_lastratedat=now - timedelta(hours=1),
        conflict="plex",
    )
    assert (d.action, d.value) == (PUSH, 9.0)


def test_both_changed_newest_wins_plex():
    now = datetime.now()
    d = decide(
        6.0,
        9.0,
        4.0,
        rating_updated=(now - timedelta(hours=1)).timestamp(),
        plex_lastratedat=now,
        conflict="beets",
    )
    assert (d.action, d.value) == (PULL, 4.0)


@pytest.mark.parametrize(
    "conflict,action,value",
    [("plex", PULL, 4.0), ("beets", PUSH, 9.0)],
)
def test_both_changed_without_timestamp_uses_conflict_policy(conflict, action, value):
    d = decide(6.0, 9.0, 4.0, None, datetime.now(), conflict)
    assert (d.action, d.value) == (action, value)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_sync_decide.py -q`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement the decision logic**

`beetsplug/plex/sync.py`:

```python
"""Three-way rating merge between beets and Plex."""

from dataclasses import dataclass

NONE = "none"
PULL = "pull"
PUSH = "push"


def normalize(value):
    """Map a rating-ish value onto the canonical scale: 0-10, 0.0 = unrated."""
    if value is None:
        return 0.0
    return round(float(value), 1)


@dataclass
class Decision:
    action: str
    value: float


def decide(base, beets_value, plex_value, rating_updated, plex_lastratedat, conflict):
    """Pick the sync action for one item.

    base: last synced value (plex_userrating), beets_value: the rating field,
    plex_value: Plex userRating. rating_updated is an epoch float or None;
    plex_lastratedat a datetime or None; conflict is "plex" or "beets".
    """
    base = normalize(base)
    beets_val = normalize(beets_value)
    plex_val = normalize(plex_value)
    beets_changed = beets_val != base
    plex_changed = plex_val != base

    if not beets_changed and not plex_changed:
        return Decision(NONE, base)
    if beets_changed and not plex_changed:
        return Decision(PUSH, beets_val)
    if plex_changed and not beets_changed:
        return Decision(PULL, plex_val)
    if beets_val == plex_val:
        return Decision(NONE, beets_val)

    if rating_updated is not None and plex_lastratedat is not None:
        beets_wins = rating_updated > plex_lastratedat.timestamp()
    else:
        beets_wins = conflict == "beets"
    if beets_wins:
        return Decision(PUSH, beets_val)
    return Decision(PULL, plex_val)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_sync_decide.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add beetsplug/plex/sync.py tests/test_plex_sync_decide.py
git commit -m "feat(plex): three-way rating merge decision logic"
```

---

### Task 10: rating_updated stamping via the write event

**Files:**
- Modify: `beetsplug/plex/__init__.py`
- Create: `tests/test_plex_stamp.py`

**Interfaces:**
- Consumes: `plugin.suspend_stamp()` from Task 7.
- Produces: `PlexPlugin.on_write(item, path, tags)` registered for the `write` event; stamps `item.rating_updated = time.time()` when `"rating" in item._dirty` and the guard is off. (The `write` event fires before the store, while the dirty set is populated; `database_change` fires after it is cleared, see the spec.)

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_stamp.py`:

```python
from beets.test.helper import PluginTestHelper

from tests.test_plex_plugin import plex_plugin


class TestRatingStamp(PluginTestHelper):
    plugin = "plex"

    def test_dirty_rating_is_stamped_on_write(self):
        item = self.add_item(title="x")
        item["rating"] = 8.0  # marks the field dirty
        plex_plugin().on_write(item, item.path, {})
        assert item["rating_updated"] > 0

    def test_clean_item_is_not_stamped(self):
        item = self.add_item(title="x")
        item["rating"] = 8.0
        item.store()  # clears the dirty set
        plex_plugin().on_write(item, item.path, {})
        assert not item.get("rating_updated")

    def test_guard_suppresses_stamping(self):
        plugin = plex_plugin()
        item = self.add_item(title="x")
        item["rating"] = 8.0
        with plugin.suspend_stamp():
            plugin.on_write(item, item.path, {})
        assert not item.get("rating_updated")

    def test_stamp_flows_through_the_write_event(self, tmp_path):
        # End to end: the event dispatched by beets reaches the handler.
        from beets import plugins as plugin_registry

        item = self.add_item(title="x")
        item["rating"] = 8.0
        plugin_registry.send("write", item=item, path=item.path, tags={})
        assert item["rating_updated"] > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_stamp.py -q`
Expected: FAIL, `on_write` does not exist.

- [ ] **Step 3: Implement the listener**

In `beetsplug/plex/__init__.py`, add `import time` at the top, register the listener at the end of `__init__`:

```python
        self.register_listener("write", self.on_write)
```

and add the method to `PlexPlugin`:

```python
    def on_write(self, item, path, tags):
        """Stamp rating_updated while the rating change is still dirty.

        Fires on the `write` event, which is dispatched before the store,
        so the dirty set still identifies what changed. Suppressed while
        the sync itself is applying a pull.
        """
        if self._suspend_rating_stamp:
            return
        if "rating" in item._dirty:
            item.rating_updated = time.time()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_stamp.py -q` then `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add beetsplug/plex/__init__.py tests/test_plex_stamp.py
git commit -m "feat(plex): stamp rating_updated from the write event"
```

---

### Task 11: the sync command

**Files:**
- Modify: `beetsplug/plex/sync.py` (add `run` and `_update_mirrors`)
- Modify: `beetsplug/plex/__init__.py` (add `cmd_sync`)
- Create: `tests/test_plex_sync_command.py`

**Interfaces:**
- Consumes: `match.build_path_map`, `match.resolve`, `decide`, `plugin.suspend_stamp()`, `plugin.music()`, `plugin.dirs()`.
- Produces: `sync.run(plugin, lib, opts, args)`; `PlexPlugin.cmd_sync(lib, opts, args)` delegating to it. Item side effects per the spec: mirrors + `plex_userrating` + `plex_updated` stored only after a successful action; pulls call `item.try_write()` under the guard.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_sync_command.py`:

```python
from datetime import datetime

from beets.test.helper import PluginTestHelper

from beetsplug.plex import sync
from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack
from tests.test_plex_plugin import plex_plugin


class SyncBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self, tracks):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        config["plex"]["library_name"] = "Music"
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin

    def add_track_item(self, relpath, **values):
        return self.add_item(path=f"/music/{relpath}", **values)


class TestSyncCommand(SyncBase):
    def test_pull_updates_rating_and_mirrors(self):
        track = FakeTrack(
            7,
            ["/plex/A/a.mp3"],
            userRating=9.0,
            lastRatedAt=datetime(2026, 1, 2),
            viewCount=4,
            skipCount=1,
            lastViewedAt=datetime(2026, 1, 3),
        )
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync")

        item.load()
        assert item["rating"] == 9.0
        assert item["plex_userrating"] == 9.0
        assert item["plex_ratingkey"] == 7
        assert item["plex_viewcount"] == 4
        assert item["plex_skipcount"] == 1
        assert item["plex_updated"] > 0
        assert track.rate_calls == []

    def test_push_rates_track(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0)

        self.run_command("plex", "sync")

        assert track.rate_calls == [8.0]
        item.load()
        assert item["plex_userrating"] == 8.0

    def test_push_clear_sends_none(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=6.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=0.0, plex_userrating=6.0)

        self.run_command("plex", "sync")

        assert track.rate_calls == [None]

    def test_unmatched_item_is_skipped(self):
        self.setup_plex([])
        item = self.add_track_item("A/missing.mp3", rating=8.0)
        self.run_command("plex", "sync")
        item.load()
        assert not item.get("plex_updated")

    def test_pretend_changes_nothing(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync", "--pretend")

        item.load()
        assert not item.get("rating")
        assert not item.get("plex_updated")
        assert track.rate_calls == []

    def test_pull_flag_skips_pushes(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0)

        self.run_command("plex", "sync", "--pull")

        assert track.rate_calls == []
        item.load()
        # The pending push must survive for a later unrestricted run.
        assert not item.get("plex_userrating")

    def test_push_failure_leaves_base_untouched(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=None)

        def broken_rate(value):
            raise RuntimeError("boom")

        track.rate = broken_rate
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3", rating=8.0)

        self.run_command("plex", "sync")

        item.load()
        assert not item.get("plex_userrating")  # retried next run

    def test_pull_does_not_stamp_rating_updated(self):
        track = FakeTrack(7, ["/plex/A/a.mp3"], userRating=9.0)
        self.setup_plex([track])
        item = self.add_track_item("A/a.mp3")

        self.run_command("plex", "sync")

        item.load()
        assert not item.get("rating_updated")

    def test_query_restricts_scope(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"], userRating=9.0)
        b = FakeTrack(2, ["/plex/B/b.mp3"], userRating=9.0)
        self.setup_plex([a, b])
        item_a = self.add_track_item("A/a.mp3", title="aaa")
        item_b = self.add_track_item("B/b.mp3", title="bbb")

        self.run_command("plex", "sync", "title:aaa")

        item_a.load()
        item_b.load()
        assert item_a["rating"] == 9.0
        assert not item_b.get("rating")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_sync_command.py -q`
Expected: FAIL, `cmd_sync` missing, so dispatch raises UserError.

- [ ] **Step 3: Implement the command**

Append to `beetsplug/plex/sync.py` (add imports `import time` and `from . import match` at the top):

```python
def _update_mirrors(item, track, agreed_value):
    item.plex_userrating = agreed_value
    item.plex_ratingkey = track.ratingKey
    item.plex_guid = track.guid or ""
    item.plex_viewcount = track.viewCount or 0
    item.plex_skipcount = track.skipCount or 0
    if track.lastViewedAt:
        item.plex_lastviewedat = track.lastViewedAt.timestamp()
    if track.lastRatedAt:
        item.plex_lastratedat = track.lastRatedAt.timestamp()
    item.plex_updated = time.time()


def run(plugin, lib, opts, args):
    """beet plex sync [QUERY] [--pretend] [--pull|--push]"""
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    conflict = plugin.config["conflict"].as_str()
    pretend = bool(getattr(opts, "pretend", False))
    counts = {"pulled": 0, "pushed": 0, "unchanged": 0, "unmatched": 0}

    for item in lib.items(args):
        track = match.resolve(item, path_map, beets_dir, plex_dir)
        if track is None:
            counts["unmatched"] += 1
            plugin._log.debug("unmatched: {0}", item)
            continue

        decision = decide(
            item.get("plex_userrating"),
            item.get("rating"),
            track.userRating,
            item.get("rating_updated"),
            track.lastRatedAt,
            conflict,
        )
        # A restricted direction leaves the other side's change pending.
        if decision.action == PUSH and getattr(opts, "pull", False):
            continue
        if decision.action == PULL and getattr(opts, "push", False):
            continue

        if decision.action == PUSH:
            counts["pushed"] += 1
            plugin._log.info(
                "plex: push rating {0} for {1}", decision.value or "clear", item
            )
            if pretend:
                continue
            try:
                track.rate(decision.value if decision.value > 0 else None)
            except Exception as exc:
                plugin._log.warning("plex: rating push failed for {0}: {1}", item, exc)
                continue
        elif decision.action == PULL:
            counts["pulled"] += 1
            plugin._log.info(
                "plex: pull rating {0} for {1}", decision.value or "clear", item
            )
            if pretend:
                continue
            item.rating = decision.value
        else:
            counts["unchanged"] += 1
            if pretend:
                continue

        _update_mirrors(item, track, decision.value)
        with plugin.suspend_stamp():
            item.store()
            if decision.action == PULL:
                item.try_write()

    plugin._log.info(
        "plex: sync done: {0} pulled, {1} pushed, {2} unchanged, {3} unmatched",
        counts["pulled"],
        counts["pushed"],
        counts["unchanged"],
        counts["unmatched"],
    )
```

Add to `PlexPlugin` in `beetsplug/plex/__init__.py` (with `from . import sync`, import inside the method to avoid import cycles at module load):

```python
    def cmd_sync(self, lib, opts, args):
        from . import sync

        sync.run(self, lib, opts, args)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_sync_command.py -q` then `uv run pytest -q`
Expected: all PASS. If `add_item(path=...)` stores the path differently than expected (bytes vs str), normalize in the test helper `add_track_item` by passing `path=f"/music/{relpath}".encode()`, beets stores paths as bytes.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add beetsplug/plex tests/test_plex_sync_command.py
git commit -m "feat(plex): two-way rating sync command with play-stat mirrors"
```

---

### Task 12: playlists command

**Files:**
- Create: `beetsplug/plex/playlists.py`
- Modify: `beetsplug/plex/__init__.py` (add `cmd_playlists`)
- Create: `tests/test_plex_playlists.py`

**Interfaces:**
- Consumes: `match`, `plugin.server()`, `plugin.music()`, `plugin.dirs()`.
- Produces: `playlists.configured(plugin) -> list[tuple[str, str]]` (name, query); `playlists.run(plugin, lib, opts, args)`; `PlexPlugin.cmd_playlists`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_playlists.py`:

```python
import pytest
from beets import ui
from beets.test.helper import PluginTestHelper

from tests.fakeplex import (
    FakeMusicSection,
    FakePlaylist,
    FakeServer,
    FakeTrack,
)
from tests.test_plex_plugin import plex_plugin


class PlaylistBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self, tracks, playlists_config):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        config["plex"]["playlists"] = playlists_config
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin


class TestPlaylists(PlaylistBase):
    def test_creates_playlist_in_query_order(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        b = FakeTrack(2, ["/plex/B/b.mp3"])
        plugin = self.setup_plex([a, b], [{"name": "mix", "query": "title:t artist+"}])
        self.add_item(path=b"/music/B/b.mp3", title="t", artist="zz")
        self.add_item(path=b"/music/A/a.mp3", title="t", artist="aa")

        self.run_command("plex", "playlists")

        playlists = plugin._server.playlists()
        assert len(playlists) == 1
        assert [t.ratingKey for t in playlists[0].items()] == [1, 2]

    def test_rebuilds_when_content_differs(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        stale = plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        playlists = plugin._server.playlists()
        assert len(playlists) == 1
        assert playlists[0] is not stale
        assert [t.ratingKey for t in playlists[0].items()] == [1]

    def test_unchanged_playlist_is_left_alone(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")
        existing = plugin._server.createPlaylist("mix", items=[a])

        self.run_command("plex", "playlists")

        assert plugin._server.playlists()[0] is existing

    def test_empty_query_result_deletes_playlist(self):
        plugin = self.setup_plex([], [{"name": "mix", "query": "title:none"}])
        plugin._server.createPlaylist("mix", items=[FakeTrack(9, ["/x"])])

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == []

    def test_non_audio_playlist_with_same_name_is_skipped(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        video = FakePlaylist(plugin._server, "mix", [], playlistType="video")
        plugin._server._playlists.append(video)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [video]

    def test_smart_playlist_is_skipped(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        smart = FakePlaylist(plugin._server, "mix", [], smart=True)
        plugin._server._playlists.append(smart)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists")

        assert plugin._server.playlists() == [smart]

    def test_unmatched_items_are_skipped_not_fatal(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")
        self.add_item(path=b"/music/C/missing.mp3", title="u")

        self.run_command("plex", "playlists")

        assert [t.ratingKey for t in plugin._server.playlists()[0].items()] == [1]

    def test_name_argument_selects_playlist_and_unknown_name_errors(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [{"name": "one", "query": ""}, {"name": "two", "query": "title:none"}],
        )
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists", "one")
        assert [p.title for p in plugin._server.playlists()] == ["one"]

        with pytest.raises(ui.UserError):
            self.run_command("plex", "playlists", "nope")

    def test_pretend_changes_nothing(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "mix", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "playlists", "--pretend")

        assert plugin._server.playlists() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_playlists.py -q`
Expected: FAIL, `cmd_playlists` missing.

- [ ] **Step 3: Implement playlists.py**

`beetsplug/plex/playlists.py`:

```python
"""Push query-defined playlists from beets to Plex."""

from beets import ui
from beets.library import Item, parse_query_string

from . import match


def configured(plugin):
    """Read [(name, query)] from the plex.playlists config list."""
    entries = []
    for node in plugin.config["playlists"].get(list):
        name = node.get("name")
        if not name:
            raise ui.UserError("plex: playlist entry without a name")
        entries.append((str(name), str(node.get("query") or "")))
    return entries


def select(entries, names):
    """Restrict configured entries to the requested names."""
    if not names:
        return entries
    by_name = dict(entries)
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise ui.UserError(f"plex: unknown playlist(s): {', '.join(unknown)}")
    return [(n, by_name[n]) for n in names]


def run(plugin, lib, opts, args):
    """beet plex playlists [NAME...] [--pretend]"""
    server = plugin.server()
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    pretend = bool(getattr(opts, "pretend", False))

    for name, query_string in select(configured(plugin), args):
        query, sort = parse_query_string(query_string, Item)
        tracks = []
        for item in lib.items(query, sort):
            track = match.resolve(item, path_map, beets_dir, plex_dir)
            if track is None:
                plugin._log.warning(
                    "plex: {0} not in Plex, skipped for playlist {1}", item, name
                )
                continue
            tracks.append(track)
        _apply(plugin, server, name, tracks, pretend)


def _apply(plugin, server, name, tracks, pretend):
    same_name = [p for p in server.playlists() if p.title == name]
    for playlist in same_name:
        if playlist.playlistType != "audio":
            plugin._log.warning(
                "plex: {0} exists as a {1} playlist, skipped",
                name,
                playlist.playlistType,
            )
            return
        if getattr(playlist, "smart", False):
            plugin._log.warning("plex: {0} is a smart playlist, skipped", name)
            return

    current = same_name[0] if same_name else None
    desired = [t.ratingKey for t in tracks]
    if current is not None and [t.ratingKey for t in current.items()] == desired:
        plugin._log.info("plex: playlist {0} unchanged", name)
        return

    if pretend:
        ui.print_(f"plex: would rebuild playlist {name} ({len(tracks)} tracks)")
        return
    if current is not None:
        current.delete()
    if tracks:
        server.createPlaylist(name, items=tracks)
        plugin._log.info(
            "plex: playlist {0} rebuilt with {1} tracks", name, len(tracks)
        )
    else:
        plugin._log.warning("plex: playlist {0} removed (query matched nothing)", name)
```

Add to `PlexPlugin`:

```python
    def cmd_playlists(self, lib, opts, args):
        from . import playlists

        playlists.run(self, lib, opts, args)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_playlists.py -q` then `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add beetsplug/plex tests/test_plex_playlists.py
git commit -m "feat(plex): query-defined playlist push"
```

---

### Task 13: collections command

**Files:**
- Create: `beetsplug/plex/collections.py`
- Modify: `beetsplug/plex/__init__.py` (add `cmd_collections`)
- Create: `tests/test_plex_collections.py`

**Interfaces:**
- Consumes: `match`, `playlists.select` (reused for name filtering), `plugin.server()/music()/dirs()`.
- Produces: `collections.configured(plugin)`, `collections.run(plugin, lib, opts, args)`, `PlexPlugin.cmd_collections`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_collections.py`:

```python
from beets.test.helper import PluginTestHelper

from tests.fakeplex import (
    FakeCollection,
    FakeMusicSection,
    FakeServer,
    FakeTrack,
)
from tests.test_plex_plugin import plex_plugin


class CollectionBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self, tracks, collections_config):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        config["plex"]["collections"] = collections_config
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection(tracks=tracks))
        return plugin

    def section(self, plugin):
        return plugin._server._section


class TestCollections(CollectionBase):
    def test_creates_collection(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        cols = self.section(plugin).collections()
        assert len(cols) == 1
        assert [t.ratingKey for t in cols[0].items()] == [1]

    def test_diffs_existing_collection(self):
        keep = FakeTrack(1, ["/plex/A/a.mp3"])
        add = FakeTrack(2, ["/plex/B/b.mp3"])
        drop = FakeTrack(3, ["/plex/C/c.mp3"])
        plugin = self.setup_plex(
            [keep, add, drop], [{"name": "Top2000", "query": "title:t"}]
        )
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [keep, drop])
        section._collections.append(existing)
        self.add_item(path=b"/music/A/a.mp3", title="t")
        self.add_item(path=b"/music/B/b.mp3", title="t")
        self.add_item(path=b"/music/C/c.mp3", title="other")

        self.run_command("plex", "collections")

        assert existing.added == [[add]]
        assert existing.removed == [[drop]]
        assert {t.ratingKey for t in existing.items()} == {1, 2}

    def test_unchanged_collection_makes_no_calls(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [a])
        section._collections.append(existing)
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        assert existing.added == []
        assert existing.removed == []

    def test_empty_query_deletes_collection(self):
        plugin = self.setup_plex([], [{"name": "Top2000", "query": "title:none"}])
        section = self.section(plugin)
        existing = FakeCollection(section, "Top2000", [FakeTrack(9, ["/x"])])
        section._collections.append(existing)

        self.run_command("plex", "collections")

        assert section.collections() == []

    def test_smart_and_foreign_subtype_are_skipped(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex(
            [a],
            [{"name": "Smart", "query": ""}, {"name": "Albums", "query": ""}],
        )
        section = self.section(plugin)
        smart = FakeCollection(section, "Smart", [], smart=True)
        albums = FakeCollection(section, "Albums", [], subtype="album")
        section._collections.extend([smart, albums])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections")

        assert smart.added == [] and albums.added == []
        assert len(section.collections()) == 2  # nothing new, nothing deleted

    def test_pretend_changes_nothing(self):
        a = FakeTrack(1, ["/plex/A/a.mp3"])
        plugin = self.setup_plex([a], [{"name": "Top2000", "query": ""}])
        self.add_item(path=b"/music/A/a.mp3", title="t")

        self.run_command("plex", "collections", "--pretend")

        assert self.section(plugin).collections() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_collections.py -q`
Expected: FAIL, `cmd_collections` missing.

- [ ] **Step 3: Implement collections.py**

`beetsplug/plex/collections.py`:

```python
"""Sync query-defined track collections from beets to Plex."""

from beets import ui
from beets.library import Item, parse_query_string

from . import match
from .playlists import select


def configured(plugin):
    """Read [(name, query)] from the plex.collections config list."""
    entries = []
    for node in plugin.config["collections"].get(list):
        name = node.get("name")
        if not name:
            raise ui.UserError("plex: collection entry without a name")
        entries.append((str(name), str(node.get("query") or "")))
    return entries


def run(plugin, lib, opts, args):
    """beet plex collections [NAME...] [--pretend]"""
    server = plugin.server()
    music = plugin.music()
    beets_dir, plex_dir = plugin.dirs()
    path_map = match.build_path_map(music)
    pretend = bool(getattr(opts, "pretend", False))

    for name, query_string in select(configured(plugin), args):
        query, _ = parse_query_string(query_string, Item)
        tracks = []
        for item in lib.items(query):
            track = match.resolve(item, path_map, beets_dir, plex_dir)
            if track is None:
                plugin._log.warning(
                    "plex: {0} not in Plex, skipped for collection {1}",
                    item,
                    name,
                )
                continue
            tracks.append(track)
        _apply(plugin, server, music, name, tracks, pretend)


def _apply(plugin, server, music, name, tracks, pretend):
    existing = next((c for c in music.collections() if c.title == name), None)
    if existing is not None:
        if getattr(existing, "smart", False):
            plugin._log.warning("plex: {0} is a smart collection, skipped", name)
            return
        if existing.subtype != "track":
            plugin._log.warning(
                "plex: {0} is a {1} collection, skipped", name, existing.subtype
            )
            return

    desired = {t.ratingKey: t for t in tracks}

    if existing is None:
        if not tracks:
            plugin._log.info("plex: collection {0}: nothing to do", name)
            return
        if pretend:
            ui.print_(f"plex: would create collection {name} ({len(tracks)} tracks)")
            return
        server.createCollection(name, section=music, items=tracks)
        plugin._log.info(
            "plex: collection {0} created with {1} tracks", name, len(tracks)
        )
        return

    if not tracks:
        if pretend:
            ui.print_(f"plex: would delete collection {name}")
            return
        existing.delete()
        plugin._log.warning(
            "plex: collection {0} removed (query matched nothing)", name
        )
        return

    current = {t.ratingKey: t for t in existing.items()}
    to_add = [t for key, t in desired.items() if key not in current]
    to_remove = [t for key, t in current.items() if key not in desired]
    if not to_add and not to_remove:
        plugin._log.info("plex: collection {0} unchanged", name)
        return
    if pretend:
        ui.print_(
            f"plex: would update collection {name}: +{len(to_add)} -{len(to_remove)}"
        )
        return
    if to_add:
        existing.addItems(to_add)
    if to_remove:
        existing.removeItems(to_remove)
    plugin._log.info(
        "plex: collection {0} updated: +{1} -{2}",
        name,
        len(to_add),
        len(to_remove),
    )
```

Add to `PlexPlugin`:

```python
    def cmd_collections(self, lib, opts, args):
        from . import collections

        collections.run(self, lib, opts, args)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_collections.py -q` then `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add beetsplug/plex tests/test_plex_collections.py
git commit -m "feat(plex): track collection sync with diff-based updates"
```

---

### Task 14: auto-scan listeners and the scan command

**Files:**
- Create: `beetsplug/plex/scan.py`
- Modify: `beetsplug/plex/__init__.py` (listeners + `cmd_scan`)
- Create: `tests/test_plex_scan.py`

**Interfaces:**
- Consumes: `match.plex_path`, `plugin._scan_dirs`, `plugin.music()`, `plugin.dirs()`.
- Produces: `scan.FULL_SCAN_THRESHOLD = 20`, `scan.flush(plugin)`; plugin listeners for `item_imported`, `album_imported`, `item_moved`, `item_removed`, `cli_exit`; `PlexPlugin.cmd_scan`.

- [ ] **Step 1: Write the failing tests**

`tests/test_plex_scan.py`:

```python
import pytest
from beets import plugins as plugin_registry
from beets import ui
from beets.test.helper import PluginTestHelper

from beetsplug.plex import scan
from tests.fakeplex import FakeMusicSection, FakeServer
from tests.test_plex_plugin import plex_plugin


class ScanBase(PluginTestHelper):
    plugin = "plex"

    def setup_plex(self):
        from beets import config

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        plugin = plex_plugin()
        plugin._server = FakeServer(FakeMusicSection())
        return plugin


class TestAutoScan(ScanBase):
    def test_import_and_remove_events_collect_directories(self):
        plugin = self.setup_plex()
        item = self.add_item(path=b"/music/A/a.mp3")
        plugin_registry.send("item_imported", lib=self.lib, item=item)
        plugin_registry.send("item_removed", item=item)
        assert plugin._scan_dirs == {"/plex/A"}

    def test_move_collects_both_directories(self):
        plugin = self.setup_plex()
        item = self.add_item(path=b"/music/B/b.mp3")
        plugin_registry.send(
            "item_moved",
            item=item,
            source=b"/music/A/b.mp3",
            destination=b"/music/B/b.mp3",
        )
        assert plugin._scan_dirs == {"/plex/A", "/plex/B"}

    def test_flush_scans_each_directory(self):
        plugin = self.setup_plex()
        plugin._scan_dirs = {"/plex/A", "/plex/B"}
        scan.flush(plugin)
        section = plugin._server._section
        assert sorted(section.update_calls) == ["/plex/A", "/plex/B"]
        assert plugin._scan_dirs == set()

    def test_flush_falls_back_to_full_scan_over_threshold(self):
        plugin = self.setup_plex()
        plugin._scan_dirs = {f"/plex/dir{i}" for i in range(25)}
        scan.flush(plugin)
        assert plugin._server._section.update_calls == [None]

    def test_flush_respects_auto_scan_off(self):
        from beets import config

        plugin = self.setup_plex()
        config["plex"]["auto_scan"] = False
        plugin._scan_dirs = {"/plex/A"}
        scan.flush(plugin)
        assert plugin._server._section.update_calls == []

    def test_flush_swallows_connection_errors(self):
        plugin = self.setup_plex()
        plugin._server = None  # forces a real (failing) connection attempt
        plugin._scan_dirs = {"/plex/A"}
        scan.flush(plugin)  # must not raise


class TestScanCommand(ScanBase):
    def test_full_scan(self):
        plugin = self.setup_plex()
        self.run_command("plex", "scan", "--full")
        assert plugin._server._section.update_calls == [None]

    def test_path_scan_translates(self):
        plugin = self.setup_plex()
        self.run_command("plex", "scan", "/music/A")
        assert plugin._server._section.update_calls == ["/plex/A"]

    def test_path_outside_library_errors(self):
        self.setup_plex()
        with pytest.raises(ui.UserError):
            self.run_command("plex", "scan", "/elsewhere/A")

    def test_no_args_without_full_errors(self):
        self.setup_plex()
        with pytest.raises(ui.UserError):
            self.run_command("plex", "scan")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_scan.py -q`
Expected: FAIL, `beetsplug.plex.scan` missing.

- [ ] **Step 3: Implement scan.py and wire the listeners**

`beetsplug/plex/scan.py`:

```python
"""Trigger Plex partial scans for changed directories."""

FULL_SCAN_THRESHOLD = 20


def flush(plugin):
    """Run the queued partial scans; never raise."""
    dirs = sorted(plugin._scan_dirs)
    plugin._scan_dirs.clear()
    if not dirs or not plugin.config["auto_scan"].get(bool):
        return
    try:
        music = plugin.music()
        if len(dirs) > FULL_SCAN_THRESHOLD:
            plugin._log.info(
                "plex: {0} changed directories, full section scan", len(dirs)
            )
            music.update()
        else:
            for directory in dirs:
                plugin._log.info("plex: scanning {0}", directory)
                music.update(path=directory)
    except Exception as exc:
        plugin._log.warning("plex: library scan failed: {0}", exc)
```

In `beetsplug/plex/__init__.py`, add at the top: `import os` and `from . import match`. Register at the end of `__init__`:

```python
        self.register_listener("item_imported", self._on_item_event)
        self.register_listener("album_imported", self._on_album_imported)
        self.register_listener("item_moved", self._on_item_moved)
        self.register_listener("item_removed", self._on_item_event)
        self.register_listener("cli_exit", self._on_cli_exit)
```

Add the methods to `PlexPlugin`:

```python
    # -- auto-scan -----------------------------------------------------

    def _note_path(self, item_path):
        beets_dir, plex_dir = self.dirs()
        target = match.plex_path(item_path, beets_dir, plex_dir)
        if target:
            self._scan_dirs.add(os.path.dirname(target))

    def _on_item_event(self, item, lib=None):
        self._note_path(item.path)

    def _on_album_imported(self, lib, album):
        for item in album.items():
            self._note_path(item.path)

    def _on_item_moved(self, item, source, destination):
        self._note_path(source)
        self._note_path(destination)

    def _on_cli_exit(self, lib):
        from . import scan

        scan.flush(self)

    def cmd_scan(self, lib, opts, args):
        music = self.music()
        if getattr(opts, "full", False):
            music.update()
            ui.print_("plex: full section scan started")
            return
        if not args:
            raise ui.UserError("plex scan: give beets-side PATHs or --full")
        beets_dir, plex_dir = self.dirs()
        for arg in args:
            target = match.plex_path(os.path.abspath(arg), beets_dir, plex_dir)
            if target is None:
                raise ui.UserError(f"plex scan: {arg} is outside the beets directory")
            music.update(path=target)
            ui.print_(f"plex: scan started for {target}")
```

Note on `test_flush_swallows_connection_errors`: with `_server = None`,
`plugin.music()` attempts a real `PlexServer("http://localhost:32400", ...)`
connection, which fails fast with a `UserError` (or connection exception),
and `flush` must catch it. If the environment has something listening on
localhost:32400, set `config["plex"]["port"] = 1` inside the test first.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plex_scan.py -q` then `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add beetsplug/plex tests/test_plex_scan.py
git commit -m "feat(plex): auto partial scans on import/move/remove and scan command"
```

---

### Task 15: status command, README, wrap-up

**Files:**
- Modify: `beetsplug/plex/__init__.py` (add `cmd_status`)
- Modify: `tests/test_plex_plugin.py` (append status test)
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `PlexPlugin.cmd_status`; user-facing README.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plex_plugin.py`:

```python
class TestStatus(PluginTestHelper):
    plugin = "plex"

    def test_status_reports_counts(self):
        from beets import config

        from tests.fakeplex import FakeMusicSection, FakeServer, FakeTrack

        config["plex"]["beets_dir"] = "/music"
        config["plex"]["plex_dir"] = "/plex"
        plugin = plex_plugin()
        plugin._server = FakeServer(
            FakeMusicSection(tracks=[FakeTrack(1, ["/plex/A/a.mp3"])])
        )
        self.add_item(path=b"/music/A/a.mp3", title="hit")
        self.add_item(path=b"/music/B/missing.mp3", title="miss")

        output = self.run_with_output("plex", "status")

        assert "1 matched" in output
        assert "1 unmatched" in output
```

If `run_with_output` is unavailable on `PluginTestHelper` (it lives on
`IOMixin`), change the test class to
`class TestStatus(IOMixin, PluginTestHelper)` with
`from beets.test.helper import IOMixin`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plex_plugin.py -q`
Expected: new test FAILS (`cmd_status` missing → UserError).

- [ ] **Step 3: Implement cmd_status**

Add to `PlexPlugin`:

```python
    def cmd_status(self, lib, opts, args):
        server = self.server()
        music = self.music()
        beets_dir, plex_dir = self.dirs()
        path_map = match.build_path_map(music)
        matched = unmatched = 0
        for item in lib.items(args):
            if match.resolve(item, path_map, beets_dir, plex_dir) is None:
                unmatched += 1
            else:
                matched += 1
        ui.print_(f"server: {server.friendlyName}")
        ui.print_(f"library: {music.title} ({len(path_map)} track files)")
        ui.print_(f"items: {matched} matched, {unmatched} unmatched")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Write the README**

Replace `README.md` with user-facing documentation containing exactly these
sections (prose can be adjusted, structure and facts must match):

1. **What this is**, two beets plugins: `ratingtag` (rating field 0-10,
   written to POPM / Vorbis RATING / MP4 RATING tags) and `plex` (path-based
   sync with a Plex music library: two-way ratings, play-stat pull, playlist
   push, track-collection sync, partial library scans). Files must be shared
   between beets and Plex (same share, possibly different mount prefixes).
2. **Install**, `pip install .` (or add the repo's `beetsplug/` dir to
   `pluginpath` for development), then add `ratingtag` and `plex` to the
   `plugins:` list. Note: remove `plexupdate` from the plugins list and
   remove any `rating` entry from the `types:` plugin config.
3. **Configuration**, the full annotated `plex:` and `ratingtag:` YAML from
   the spec's Config section (copy the keys and defaults verbatim).
4. **Commands**, the five subcommands with one-line descriptions and the
   `--pretend/--pull/--push/--full` flags.
5. **How matching works**, three sentences: path prefix translation,
   one-sweep path map, unmatched items are reported and skipped.
6. **Rating semantics**, 0-10 scale, 0.0/absent = unrated, newest-wins
   conflict resolution with the `conflict:` fallback, the `beet modify -W`
   stamping limitation.

- [ ] **Step 6: Full verification**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Expected: everything green.

- [ ] **Step 7: Commit**

```bash
git add beetsplug/plex tests/test_plex_plugin.py README.md
git commit -m "feat(plex): status command and user documentation"
```

---

## Completion

After all tasks pass: the branch `feat/initial-plugins` contains the full
implementation. Follow the repository owner's PR workflow (an issue must
exist for the PR to close; run the preflight-circus skill before pushing if
available). Manual smoke test against the real server (optional, needs the
user's config): `beet plex status`, then `beet plex sync --pretend`.

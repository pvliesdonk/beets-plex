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

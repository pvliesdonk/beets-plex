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
    from packaging.version import Version

    # Version(), not a string compare: "2.9" >= "2.12" is True as strings.
    assert Version(beets.__version__) >= Version("2.12")
    assert plexapi.VERSION

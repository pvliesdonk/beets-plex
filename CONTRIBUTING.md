# Contributing

## Development setup

Requires Python 3.10–3.14.

    python -m venv .venv
    source .venv/bin/activate
    pip install -e '.[test]'

## Checks

CI runs these on every pull request and on pushes to `main`, across Python
3.10–3.14. Run them locally before pushing:

    ruff check .
    ruff format --check .
    pytest -q

`ruff format .` applies formatting; `ruff check --fix .` applies safe lint fixes.

## Commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/)
(`type: summary`, with types `feat`, `fix`, `docs`, `test`, `build`, `ci`,
`chore`, …). The habit is required so that [Python Semantic
Release](https://python-semantic-release.readthedocs.io/) can derive versions
and generate the changelog automatically once it is wired up: `feat:` implies a
minor release, `fix:` a patch, and a `!` marker or `BREAKING CHANGE:` footer a
major.

## Pull requests

- One pull request at a time off `main`, each closing its own issue, merged
  before the next begins. No stacking.
- Keep diffs small and reviewable — the roadmap sequences the work into small
  PRs on purpose.
- Add or update tests with the change.

## Releases

The version comes from the git tag via `hatch-vcs`. Publishing a GitHub Release
runs `release.yml`, which builds the package and publishes it to PyPI via
trusted publishing (no API token).

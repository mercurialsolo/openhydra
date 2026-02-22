# Contributing to OpenHydra

Thanks for contributing. This project uses a lightweight, test-first workflow and conventional commits.

## Before You Start

- Python `>=3.11`
- [`uv`](https://docs.astral.sh/uv/) installed
- Optional providers/channels as needed for your task

## Local Setup

```bash
# Install package in editable mode (minimal)
uv pip install -e .

# Recommended first-run setup + diagnostics
uv run openhydra onboard
uv run openhydra doctor

# Verify CLI boots
uv run openhydra --help

# Optional: install full provider/channel extras
uv pip install -e ".[all]"
```

## Development Workflow

1. Fork the repo and create a branch from `main`.
2. Implement your change in small, reviewable commits.
3. Add or update tests for behavior changes.
4. Run local checks:

```bash
git ls-files -z | xargs -0 uvx --from detect-secrets detect-secrets-hook --disable-plugin KeywordDetector
uv run ruff check src/ tests/
uv run pytest
```

5. Commit using Conventional Commit subjects:

- `feat: ...`
- `fix: ...`
- `chore: ...`
- `docs: ...`
- `test: ...`

6. Open a pull request using the PR template.

## Pull Request Requirements

- Clear problem statement and rationale
- Tests for bug fixes / new behavior
- Passing CI
- Notes for config/env changes
- No secrets committed

## Coding Guidelines

- Keep the engine interface-agnostic
- Prefer `Protocol` interfaces for adapters
- Use `async`/`await` for I/O
- Keep line length <= 100 (Ruff)
- Follow existing structure under `src/openhydra/`

## Testing Guidance

- Put tests in `tests/test_*.py`
- Add focused regression tests for bug fixes
- Example focused run:

```bash
uv run pytest tests/test_cli.py -k doctor
```

## Issue Submission Guidelines

When opening an issue, include enough detail for quick triage:

1. Use the appropriate GitHub issue form (`Bug report` or `Feature request`).
2. Search existing issues first to avoid duplicates.
3. Keep each issue focused on one problem or proposal.
4. For bugs, include minimal reproduction steps, expected behavior, and actual behavior.
5. Include environment details (`openhydra --version`, Python version, OS).
6. Redact secrets from logs and snippets (API keys, tokens, passwords, credentials).
7. For sensitive security reports, do not open a public issue; follow `SECURITY.md`.

## Security

Do not open public issues for sensitive vulnerabilities. Contact maintainers privately.

## Release Process (PyPI)

PyPI publishing is handled by GitHub Actions (`.github/workflows/publish.yml`) using Trusted
Publishing.

One-time setup in PyPI and TestPyPI:

- Create the `openhydra` project (or claim the name) in each registry.
- Add a Trusted Publisher (GitHub Actions) with owner `mercurialsolo`, repository
  `openhydra`, workflow `publish.yml`, and environment `pypi` (PyPI) or `testpypi`
  (TestPyPI).

Release steps:

1. Bump versions in `pyproject.toml` and `src/openhydra/__init__.py`.
2. Update `CHANGELOG.md`.
3. Validate build locally:

```bash
uvx --from build pyproject-build
uvx --from twine twine check dist/*
```

4. Publish to TestPyPI from GitHub Actions (`Publish` workflow, `repository=testpypi`).
5. Publish to PyPI:

- Either run `Publish` workflow with `repository=pypi`
- Or push a release tag `vX.Y.Z` (must match `pyproject.toml` version)

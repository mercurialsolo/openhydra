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

## Security

Do not open public issues for sensitive vulnerabilities. Contact maintainers privately.

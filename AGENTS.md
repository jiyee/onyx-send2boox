# Repository Guidelines

## Project Structure & Module Organization
This repository is a Python package + CLI for send2boox workflows.

- `src/send2boox/cli.py`: argparse CLI entrypoint (`send2boox` command).
- `src/send2boox/client.py`: high-level workflows (auth, file/book operations).
- `src/send2boox/api.py`: HTTP layer and API request handling.
- `src/send2boox/config.py`: TOML config load/save and defaults.
- `src/send2boox/playwright_*.py`: browser/session debug helpers.
- `tests/`: pytest suite.
- `config.example.toml`: local config template.
- `README.md`, `README_ZH.cn`: user docs.

Prefer keeping business logic in `client.py`/`api.py`; keep `cli.py` focused on argument parsing and orchestration.

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate`: create local virtual environment.
- `pip install -e .[dev]`: install project and development dependencies.
- `send2boox auth login [--email ...|--mobile ...]`: request verification code.
- `send2boox auth code <6_digit_code>`: exchange code for token and persist config.
- `send2boox file send <file1> [file2 ...]`: upload files.
- `send2boox file list [--limit N --offset N]`: list files.
- `send2boox file delete <id1> [id2 ...]`: delete files by id.
- `send2boox book list [--json] [--include-inactive]`: list library books.
- `send2boox book stats|annotations|bookmarks ...`: query reading data.
- `.venv/bin/python -m py_compile src/send2boox/*.py tests/*.py`: syntax sanity check.
- `.venv/bin/python -m pytest`: run automated test suite.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation.
- Use `snake_case` for functions/variables and `CamelCase` for classes (`Send2BooxClient`, `AppConfig`).
- Prefer explicit, small helper methods for each API action.
- Avoid embedding credentials or fixed user-specific endpoints in code; use `config.toml`.

## Testing Guidelines
Automated tests are available in `tests/`. Minimum expectation for changes:

- Run `.venv/bin/python -m py_compile src/send2boox/*.py tests/*.py`.
- Run `.venv/bin/python -m pytest`.
- Add or update focused tests for behavior changes in `tests/test_*.py`.

If adding tests, use `pytest` with files named `tests/test_*.py`, and mock network/API interactions (`requests`, OSS uploads).

## Commit & Pull Request Guidelines
Git history favors short, imperative commit messages with optional scope prefixes, for example:

- `cli: normalize status output to stderr`
- `client: add table formatter for library books`
- `docs: sync README with current book list behavior`

Use one logical change per commit. PRs should include: purpose, key changes, manual test steps/results, config or API impact, and linked issues where applicable.

## Security & Configuration Tips
- Never commit real `email` or `token` values from `config.toml`.
- Treat API tokens as secrets; rotate if exposed.
- If enabling verbose logs, redact user IDs and auth headers before sharing logs.

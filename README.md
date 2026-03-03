# onyx-send2boox

Python CLI for interacting with the send2boox service used by Onyx Boox e-ink devices.

Chinese version: [简体中文](./README_ZH.md)

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp config.example.toml config.toml
```

Fill `config.toml` with your account email and server host (if not using default):

```toml
server = "eur.boox.com"
email = "your_email@example.com"
mobile = ""
```

`email` and `mobile` are both supported; set either one.

## Authentication Flow

```bash
send2boox auth login
send2boox auth code <6_digit_code>
send2boox auth login --mobile 13800138000
send2boox auth code <6_digit_code> --mobile 13800138000
```

The token is saved back to `config.toml`. By default, `auth code` also calls
`users/syncToken` and writes browser cookies to `session-cookies.json` for debugging.
If cookie sync returns no cookies, the command warns and keeps token-only flow available.

## Common Commands

```bash
send2boox file list --limit 24 --offset 0
send2boox file send ./book1.epub ./book2.pdf
send2boox file delete <file_id_1> <file_id_2>
```

List library books without opening browser DevTools. By default, `book list`
prints an ID/Name table. Use `--json` for full metadata (including `unique_id`,
usable as `docIds` for `statistics/readInfoList`):

```bash
send2boox book list
send2boox book list --json
send2boox book list --include-inactive --output ./library-books.json
```

If you only need `unique_id` values:

```bash
send2boox book list --json | jq -r '.[].unique_id' > book-ids.txt
```

Query single-book reading stats (fields from `statistics/readInfoList`):

```bash
send2boox book stats 0138a37b2e77444b9995913cca6a6351
send2boox book stats 0138a37b2e77444b9995913cca6a6351 --output ./read-stats.json
```

Export single-book annotations and bookmarks from `READER_LIBRARY`:

```bash
send2boox book annotations 0138a37b2e77444b9995913cca6a6351 --output ./annotations.json
send2boox book bookmarks 0138a37b2e77444b9995913cca6a6351 --output ./bookmarks.json
```

By default these commands return active records (`status == 0`). Pass
`--include-inactive` to include deleted/archived history records.

## CLI Output Conventions

- `stdout`: structured command data (tables / JSON payloads).
- `stderr`: status and progress messages.
- Status prefixes are standardized:
  - `[OK]`: successful status updates.
  - `[WARN]`: non-fatal warnings and fallbacks.
  - `[ERROR]`: fatal failures (command exits non-zero).

## Project Layout

- `src/send2boox/api.py`: HTTP API layer with timeout/error handling.
- `src/send2boox/client.py`: business logic for auth, list, upload, delete.
- `src/send2boox/config.py`: typed TOML config load/save.
- `src/send2boox/cli.py`: argparse-based CLI entrypoint.
- `tests/`: pytest test suite.
- `.github/workflows/ci.yml`: lint + type-check + test in CI.

## Development Checks

```bash
ruff check .
mypy src
pytest
```

## Security Notes

- `config.toml` may contain sensitive token data and is git-ignored.
- Never commit real credentials.

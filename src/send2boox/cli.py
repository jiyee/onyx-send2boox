"""CLI entrypoint for send2boox."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .client import (
    RemoteFile,
    Send2BooxClient,
    format_files_table,
    format_library_books_table,
)
from .config import AppConfig, load_config, save_config
from .exceptions import ConfigError, Send2BooxError
from .playwright_debug import run_playwright_debug
from .playwright_session import (
    DEFAULT_SESSION_COOKIE_JSON,
    launch_debug_browser_session,
    sync_token_cookies,
)

DELETE_VISIBILITY_RECHECK_ATTEMPTS = 5
DELETE_VISIBILITY_RECHECK_INTERVAL_SECONDS = 0.4


def _print_ok(message: str) -> None:
    print(f"[OK] {message}", file=sys.stderr)


def _print_warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)


def _print_error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="send2boox")
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to TOML config file (default: config.toml)",
    )
    parser.add_argument(
        "--server",
        help="send2boox server host; overrides config server",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Python logging level",
    )

    subparsers = parser.add_subparsers(dest="command_group", required=True)

    auth_parser = subparsers.add_parser("auth", help="Authentication commands")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", required=True)

    request_parser = auth_subparsers.add_parser(
        "login",
        help="Request login code by email or mobile",
    )
    request_parser.set_defaults(command="auth_login")
    request_identity_group = request_parser.add_mutually_exclusive_group()
    request_identity_group.add_argument(
        "--account",
        help="Login account (email or mobile); falls back to config value",
    )
    request_identity_group.add_argument(
        "--email",
        help="Email address; falls back to config email/mobile",
    )
    request_identity_group.add_argument(
        "--mobile",
        help="Mobile number; falls back to config mobile/email",
    )

    token_parser = auth_subparsers.add_parser("code", help="Exchange code for token")
    token_parser.set_defaults(command="auth_code")
    token_parser.add_argument("code", help="6 digit verification code")
    token_identity_group = token_parser.add_mutually_exclusive_group()
    token_identity_group.add_argument(
        "--account",
        help="Login account (email or mobile); falls back to config value",
    )
    token_identity_group.add_argument(
        "--email",
        help="Email address; falls back to config email/mobile",
    )
    token_identity_group.add_argument(
        "--mobile",
        help="Mobile number; falls back to config mobile/email",
    )
    token_parser.add_argument(
        "--cookie-output",
        default=DEFAULT_SESSION_COOKIE_JSON,
        help=f"Path to write auto-synced session cookies (default: {DEFAULT_SESSION_COOKIE_JSON})",
    )
    token_parser.add_argument(
        "--no-cookie-sync",
        action="store_true",
        help="Skip automatic users/syncToken cookie synchronization",
    )

    file_parser = subparsers.add_parser("file", help="Remote file commands")
    file_subparsers = file_parser.add_subparsers(dest="file_command", required=True)

    send_parser = file_subparsers.add_parser("send", help="Send one or more files")
    send_parser.set_defaults(command="file_send")
    send_parser.add_argument("files", nargs="*", help="Local files to upload")

    list_parser = file_subparsers.add_parser("list", help="List remote files")
    list_parser.set_defaults(command="file_list")
    list_parser.add_argument("--limit", type=int, default=24)
    list_parser.add_argument("--offset", type=int, default=0)

    delete_parser = file_subparsers.add_parser("delete", help="Delete remote files by id")
    delete_parser.set_defaults(command="file_delete")
    delete_parser.add_argument("ids", nargs="+", help="Remote file IDs")

    book_parser = subparsers.add_parser("book", help="Book and reading data commands")
    book_subparsers = book_parser.add_subparsers(dest="book_command", required=True)

    dump_book_ids_parser = book_subparsers.add_parser(
        "list",
        help="Fetch library book metadata without browser DevTools",
    )
    dump_book_ids_parser.set_defaults(command="book_list")
    dump_book_ids_parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include books whose status is not 0",
    )
    dump_book_ids_parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON metadata instead of ID/name table",
    )
    dump_book_ids_parser.add_argument(
        "--output",
        help="Optional path to write JSON metadata",
    )

    read_info_parser = book_subparsers.add_parser(
        "stats",
        help="Fetch single-book reading stats via statistics/readInfoList",
    )
    read_info_parser.set_defaults(command="book_stats")
    read_info_parser.add_argument("book_id", help="Book unique id (docId)")
    read_info_parser.add_argument(
        "--output",
        help="Optional path to write JSON reading record",
    )

    annotations_parser = book_subparsers.add_parser(
        "annotations",
        help="Fetch single-book annotations (modeType=1) from READER_LIBRARY",
    )
    annotations_parser.set_defaults(command="book_annotations")
    annotations_parser.add_argument("book_id", help="Book unique id (documentId)")
    annotations_parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include annotation records whose status is not 0",
    )
    annotations_parser.add_argument(
        "--output",
        help="Optional path to write JSON annotations",
    )

    bookmarks_parser = book_subparsers.add_parser(
        "bookmarks",
        help="Fetch single-book bookmarks (modeType=2) from READER_LIBRARY",
    )
    bookmarks_parser.set_defaults(command="book_bookmarks")
    bookmarks_parser.add_argument("book_id", help="Book unique id (documentId)")
    bookmarks_parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include bookmark records whose status is not 0",
    )
    bookmarks_parser.add_argument(
        "--output",
        help="Optional path to write JSON bookmarks",
    )

    debug_parser = subparsers.add_parser(
        "debug-playwright",
        help="Open a page with Playwright and infer API interfaces",
    )
    debug_parser.set_defaults(command="debug_playwright")
    debug_parser.add_argument("url", help="Target URL to inspect")
    debug_parser.add_argument(
        "--headful",
        action="store_true",
        help="Show browser window (default is headless)",
    )
    debug_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Navigation timeout in milliseconds",
    )
    debug_parser.add_argument(
        "--settle-ms",
        type=int,
        default=2_000,
        help="Extra wait time after navigation in milliseconds",
    )
    debug_parser.add_argument(
        "--max-requests",
        type=int,
        default=250,
        help="Maximum number of network responses to capture",
    )
    debug_parser.add_argument(
        "--max-body-chars",
        type=int,
        default=1_200,
        help="Maximum request/response body chars to keep per capture",
    )
    debug_parser.add_argument(
        "--output",
        help="Optional path to write JSON report",
    )

    browser_parser = subparsers.add_parser(
        "debug-browser",
        help="Launch headful Chromium and inject cookies/localStorage token",
    )
    browser_parser.set_defaults(command="debug_browser")
    browser_parser.add_argument("url", help="Target URL to open")
    browser_parser.add_argument(
        "--token",
        help="Token value to inject; defaults to token from config.toml",
    )
    browser_parser.add_argument(
        "--token-key",
        default="token",
        help="Primary localStorage key for token (default: token)",
    )
    browser_parser.add_argument(
        "--extra-token-key",
        action="append",
        default=[],
        help="Additional localStorage keys for token; repeatable",
    )
    browser_parser.add_argument(
        "--cookie-json",
        help="Path to exported browser cookie JSON",
    )
    browser_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30_000,
        help="Navigation timeout in milliseconds",
    )
    browser_parser.add_argument(
        "--devtools",
        action="store_true",
        help="Open Chromium with DevTools",
    )
    browser_parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Exit immediately after injection instead of waiting for Enter",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "command", "")

    logging.basicConfig(level=getattr(logging, args.log_level))

    try:
        def resolve_login_account(config: AppConfig) -> str:
            for raw in (
                getattr(args, "account", ""),
                getattr(args, "mobile", ""),
                getattr(args, "email", ""),
                config.mobile,
                config.email,
            ):
                if isinstance(raw, str):
                    value = raw.strip()
                    if value:
                        return value
            return ""

        def persist_login_account(config: AppConfig, account: str) -> None:
            normalized = account.strip()
            if not normalized:
                return
            if "@" in normalized:
                config.email = normalized
            else:
                config.mobile = normalized

        def sync_cookies_with_fallback(*, cloud: str, token: str, output_path: Path) -> Path | None:
            hosts = [cloud.strip()]
            if cloud.strip().lower() != "send2boox.com":
                hosts.append("send2boox.com")

            for host in hosts:
                cookie_path = sync_token_cookies(
                    cloud=host,
                    token=token,
                    output_path=output_path,
                    raise_on_empty=False,
                )
                if cookie_path is not None:
                    return cookie_path
            return None

        if command == "debug_browser":
            token = (args.token or "").strip()
            cookie_json_path = args.cookie_json
            sync_cloud = args.server.strip() if args.server else ""
            runtime_config = None

            def ensure_runtime_config():
                nonlocal runtime_config, sync_cloud
                if runtime_config is None:
                    runtime_config = load_config(args.config)
                    if args.server:
                        runtime_config.cloud = args.server.strip()
                    sync_cloud = runtime_config.cloud
                return runtime_config

            if not token:
                config = ensure_runtime_config()
                token = config.token.strip()

            if not token:
                raise ConfigError("Token is required. Pass --token or set token in config.toml.")

            if not cookie_json_path:
                default_cookie_path = Path(DEFAULT_SESSION_COOKIE_JSON)
                if default_cookie_path.exists():
                    cookie_json_path = str(default_cookie_path)
                else:
                    if not sync_cloud:
                        sync_cloud = ensure_runtime_config().cloud
                    synced_path = sync_cookies_with_fallback(
                        cloud=sync_cloud,
                        token=token,
                        output_path=default_cookie_path,
                    )
                    if synced_path is not None:
                        cookie_json_path = str(synced_path)
                        _print_ok(f"Session cookies synced to {synced_path}")
                    else:
                        _print_warn(
                            "session cookie sync returned no cookies. "
                            "Continuing with token-only injection."
                        )

            launch_debug_browser_session(
                url=args.url,
                token=token,
                token_key=args.token_key,
                extra_token_keys=args.extra_token_key,
                cookie_json_path=cookie_json_path,
                timeout_ms=args.timeout_ms,
                devtools=args.devtools,
                wait_for_enter=not args.no_wait,
            )
            return 0

        if command == "debug_playwright":
            report = run_playwright_debug(
                url=args.url,
                headless=not args.headful,
                timeout_ms=args.timeout_ms,
                settle_ms=args.settle_ms,
                max_requests=args.max_requests,
                max_body_chars=args.max_body_chars,
            )
            report_json = report.to_json(indent=2)
            if args.output:
                output_path = Path(args.output)
                try:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(report_json, encoding="utf-8")
                except OSError as exc:
                    raise Send2BooxError(f"Failed to write report to {output_path}: {exc}") from exc
                _print_ok(f"Report written to {output_path}")
            print(report_json)
            return 0

        config = load_config(args.config)
        if args.server:
            config.cloud = args.server.strip()
        client = Send2BooxClient(config)

        if command == "auth_login":
            account = resolve_login_account(config)
            if not account:
                raise ConfigError(
                    "Login account is required. Set email/mobile in config.toml "
                    "or pass --account/--email/--mobile."
                )
            client.request_verification_code(account)
            _print_ok("Code requested. Check your mailbox/SMS.")
            return 0

        if command == "auth_code":
            account = resolve_login_account(config)
            if not account:
                raise ConfigError(
                    "Login account is required. Set email/mobile in config.toml "
                    "or pass --account/--email/--mobile."
                )
            token = client.authenticate_with_email_code(account, args.code)
            persist_login_account(config, account)
            save_config(config, args.config)
            _print_ok("Token obtained and saved.")
            _print_ok(f"Token prefix: {token[:8]}...")
            if not args.no_cookie_sync:
                cookie_path = sync_cookies_with_fallback(
                    cloud=config.cloud,
                    token=token,
                    output_path=Path(args.cookie_output),
                )
                if cookie_path is not None:
                    _print_ok(f"Session cookies saved to {cookie_path}")
                else:
                    _print_warn(
                        "session cookie sync returned no cookies. "
                        "Token is saved; browser debugging can continue with token injection."
                    )
            return 0

        if command == "file_send":
            for path in args.files:
                client.send_file(path)
            files = client.list_files()
            print(format_files_table(files))
            return 0

        if command == "file_list":
            files = client.list_files(limit=args.limit, offset=args.offset)
            print(format_files_table(files))
            return 0

        if command == "book_stats":
            normalized_book_id = args.book_id.strip()
            if not normalized_book_id:
                raise ConfigError("book_id is required.")

            preferred_cloud = config.cloud.strip()
            stats_hosts: list[str] = []
            for host in [preferred_cloud, "send2boox.com", "eur.boox.com"]:
                normalized = host.strip()
                if normalized and normalized not in stats_hosts:
                    stats_hosts.append(normalized)

            read_info = None
            active_cloud = preferred_cloud
            stats_last_error: Send2BooxError | None = None

            for host in stats_hosts:
                active_client = client
                if host != preferred_cloud:
                    active_client = Send2BooxClient(
                        AppConfig(
                            email=config.email,
                            token=config.token,
                            cloud=host,
                        )
                    )
                try:
                    read_info = active_client.get_book_read_info(normalized_book_id)
                    active_cloud = host
                    break
                except Send2BooxError as exc:
                    stats_last_error = exc

            if read_info is None:
                if stats_last_error is not None:
                    raise stats_last_error
                raise Send2BooxError("Failed to fetch reading info.")

            read_info_payload = {
                "doc_id": read_info.doc_id,
                "name": read_info.name,
                "total_time": read_info.total_time,
                "avg_time": read_info.avg_time,
                "reading_progress": read_info.reading_progress,
                "token_expired_at": read_info.token_expired_at,
            }
            output_json = json.dumps(read_info_payload, ensure_ascii=False, indent=2)

            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(output_json, encoding="utf-8")
                _print_ok(f"Reading record written to {output_path}")

            print(output_json)

            if active_cloud != preferred_cloud:
                _print_warn(f"failed on {preferred_cloud}; used {active_cloud} fallback.")
            return 0

        if command == "book_list":
            preferred_cloud = config.cloud.strip()
            book_hosts: list[str] = []
            for host in [preferred_cloud, "send2boox.com", "eur.boox.com"]:
                normalized = host.strip()
                if normalized and normalized not in book_hosts:
                    book_hosts.append(normalized)

            books = None
            active_cloud = preferred_cloud
            book_last_error: Send2BooxError | None = None

            for host in book_hosts:
                active_client = client
                if host != preferred_cloud:
                    active_client = Send2BooxClient(
                        AppConfig(
                            email=config.email,
                            token=config.token,
                            cloud=host,
                        )
                    )
                try:
                    books = active_client.list_library_books(
                        include_inactive=args.include_inactive
                    )
                    active_cloud = host
                    break
                except Send2BooxError as exc:
                    book_last_error = exc

            if books is None:
                if book_last_error is not None:
                    raise book_last_error
                raise Send2BooxError("Failed to fetch library books.")

            book_list_payload = [
                {
                    "unique_id": item.unique_id,
                    "name": item.name,
                    "status": item.status,
                    "reading_status": item.reading_status,
                }
                for item in books
            ]

            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(book_list_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                _print_ok(f"Metadata written to {output_path}")

            if args.json:
                print(json.dumps(book_list_payload, ensure_ascii=False, indent=2))
            else:
                print(format_library_books_table(books))

            if active_cloud != preferred_cloud:
                _print_warn(f"failed on {preferred_cloud}; used {active_cloud} fallback.")
            return 0

        if command == "book_annotations":
            normalized_book_id = args.book_id.strip()
            if not normalized_book_id:
                raise ConfigError("book_id is required.")

            preferred_cloud = config.cloud.strip()
            annotation_hosts: list[str] = []
            for host in [preferred_cloud, "send2boox.com", "eur.boox.com"]:
                normalized = host.strip()
                if normalized and normalized not in annotation_hosts:
                    annotation_hosts.append(normalized)

            annotations = None
            active_cloud = preferred_cloud
            annotation_last_error: Send2BooxError | None = None

            for host in annotation_hosts:
                active_client = client
                if host != preferred_cloud:
                    active_client = Send2BooxClient(
                        AppConfig(
                            email=config.email,
                            token=config.token,
                            cloud=host,
                        )
                    )
                try:
                    annotations = active_client.list_book_annotations(
                        normalized_book_id,
                        include_inactive=args.include_inactive,
                    )
                    active_cloud = host
                    break
                except Send2BooxError as exc:
                    annotation_last_error = exc

            if annotations is None:
                if annotation_last_error is not None:
                    raise annotation_last_error
                raise Send2BooxError("Failed to fetch annotations.")

            annotations_payload = [
                {
                    "unique_id": item.unique_id,
                    "document_id": item.document_id,
                    "quote": item.quote,
                    "note": item.note,
                    "chapter": item.chapter,
                    "page_number": item.page_number,
                    "position": item.position,
                    "start_position": item.start_position,
                    "end_position": item.end_position,
                    "color": item.color,
                    "shape": item.shape,
                    "status": item.status,
                    "updated_at": item.updated_at,
                }
                for item in annotations
            ]
            output_json = json.dumps(annotations_payload, ensure_ascii=False, indent=2)

            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(output_json, encoding="utf-8")
                _print_ok(f"Annotations written to {output_path}")

            print(output_json)

            if active_cloud != preferred_cloud:
                _print_warn(f"failed on {preferred_cloud}; used {active_cloud} fallback.")
            return 0

        if command == "book_bookmarks":
            normalized_book_id = args.book_id.strip()
            if not normalized_book_id:
                raise ConfigError("book_id is required.")

            preferred_cloud = config.cloud.strip()
            bookmark_hosts: list[str] = []
            for host in [preferred_cloud, "send2boox.com", "eur.boox.com"]:
                normalized = host.strip()
                if normalized and normalized not in bookmark_hosts:
                    bookmark_hosts.append(normalized)

            bookmarks = None
            active_cloud = preferred_cloud
            bookmark_last_error: Send2BooxError | None = None

            for host in bookmark_hosts:
                active_client = client
                if host != preferred_cloud:
                    active_client = Send2BooxClient(
                        AppConfig(
                            email=config.email,
                            token=config.token,
                            cloud=host,
                        )
                    )
                try:
                    bookmarks = active_client.list_book_bookmarks(
                        normalized_book_id,
                        include_inactive=args.include_inactive,
                    )
                    active_cloud = host
                    break
                except Send2BooxError as exc:
                    bookmark_last_error = exc

            if bookmarks is None:
                if bookmark_last_error is not None:
                    raise bookmark_last_error
                raise Send2BooxError("Failed to fetch bookmarks.")

            bookmarks_payload = [
                {
                    "unique_id": item.unique_id,
                    "document_id": item.document_id,
                    "quote": item.quote,
                    "title": item.title,
                    "page_number": item.page_number,
                    "position": item.position,
                    "xpath": item.xpath,
                    "position_int": item.position_int,
                    "status": item.status,
                    "updated_at": item.updated_at,
                }
                for item in bookmarks
            ]
            output_json = json.dumps(bookmarks_payload, ensure_ascii=False, indent=2)

            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(output_json, encoding="utf-8")
                _print_ok(f"Bookmarks written to {output_path}")

            print(output_json)

            if active_cloud != preferred_cloud:
                _print_warn(f"failed on {preferred_cloud}; used {active_cloud} fallback.")
            return 0

        if command == "file_delete":
            target_ids = [item.strip() for item in args.ids if item.strip()]
            client.delete_files(target_ids)

            files = client.list_files()
            remaining = _find_remaining_target_ids(files=files, target_ids=target_ids)
            if remaining:
                for _ in range(DELETE_VISIBILITY_RECHECK_ATTEMPTS):
                    time.sleep(DELETE_VISIBILITY_RECHECK_INTERVAL_SECONDS)
                    files = client.list_files()
                    remaining = _find_remaining_target_ids(files=files, target_ids=target_ids)
                    if not remaining:
                        break

            if remaining:
                _print_warn(
                    "delete request succeeded but file IDs still visible "
                    f"after refresh window: {', '.join(remaining)}"
                )

            print(format_files_table(files))
            return 0

        parser.error(f"Unknown command: {command}")
        return 2

    except Send2BooxError as exc:
        _print_error(str(exc))
        return 1


def _find_remaining_target_ids(*, files: list[RemoteFile], target_ids: list[str]) -> list[str]:
    target_set = {item for item in target_ids if item}
    if not target_set:
        return []
    remaining = [item.file_id for item in files if item.file_id in target_set]
    remaining.sort()
    return remaining


if __name__ == "__main__":
    raise SystemExit(main())

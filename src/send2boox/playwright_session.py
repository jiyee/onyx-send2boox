"""Headful browser session debugging with injected auth state."""

from __future__ import annotations

import json
from collections.abc import Sequence
from http.cookiejar import CookieJar
from inspect import signature
from pathlib import Path
from typing import Any, cast

from .api import BooxApi, apply_sync_token_payload_to_cookies
from .exceptions import Send2BooxError

DEFAULT_SESSION_COOKIE_JSON = "session-cookies.json"

_SAME_SITE_MAP = {
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
    "no_restriction": "None",
}


def load_exported_cookies(path: str | Path) -> list[dict[str, Any]]:
    """Load browser-exported cookies from a JSON file."""

    cookie_path = Path(path)
    if not cookie_path.exists():
        raise Send2BooxError(f"Cookie JSON file not found: {cookie_path}")

    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Send2BooxError(f"Cookie JSON is invalid: {cookie_path}") from exc

    if not isinstance(data, list):
        raise Send2BooxError("Cookie JSON must be an array.")

    return convert_exported_cookies(data)


def convert_exported_cookies(cookie_records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert browser-export records to Playwright cookie objects."""

    converted: list[dict[str, Any]] = []
    for index, record in enumerate(cookie_records):
        if not isinstance(record, dict):
            raise Send2BooxError(f"Cookie entry #{index} must be an object.")

        name = _required_str(record, "name", index=index)
        value = _required_str(record, "value", index=index)
        domain = _required_str(record, "domain", index=index)
        path = str(record.get("path", "/") or "/")

        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": bool(record.get("secure", False)),
            "httpOnly": bool(record.get("httpOnly", False)),
        }

        same_site = _normalize_same_site(record.get("sameSite"))
        if same_site is not None:
            cookie["sameSite"] = same_site

        expires = _normalize_expires(record)
        if expires is not None:
            cookie["expires"] = expires

        converted.append(cookie)

    return converted


def export_cookie_jar_for_browser(cookie_jar: CookieJar) -> list[dict[str, Any]]:
    """Export cookie jar into Chromium extension-style JSON records."""

    exported: list[dict[str, Any]] = []
    for cookie in cookie_jar:
        record: dict[str, Any] = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": bool(cookie.secure),
            "httpOnly": _cookie_rest_flag(cookie, "httponly"),
            "session": cookie.expires is None,
            "hostOnly": not str(cookie.domain).startswith("."),
        }

        if cookie.expires is not None:
            record["expirationDate"] = int(cookie.expires)

        same_site = _cookie_rest_value(cookie, "samesite")
        if same_site:
            normalized_same_site = same_site.strip().lower()
            if normalized_same_site in {"none", "lax", "strict", "no_restriction"}:
                record["sameSite"] = normalized_same_site

        exported.append(record)

    return exported


def sync_token_cookies(
    *,
    cloud: str,
    token: str,
    output_path: str | Path = DEFAULT_SESSION_COOKIE_JSON,
    raise_on_empty: bool = True,
) -> Path | None:
    """Call users/syncToken and persist returned cookies into JSON."""

    api = BooxApi(cloud=cloud, token=token)
    payload = api.request("users/syncToken")
    apply_sync_token_payload_to_cookies(
        payload=payload,
        cookie_jar=api.session.cookies,
        cloud=cloud,
    )

    records = export_cookie_jar_for_browser(api.session.cookies)
    if not records:
        if raise_on_empty:
            raise Send2BooxError(
                "Cookie sync succeeded but no cookies were returned. "
                "Please verify server domain and account state."
            )
        return None

    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return target_path


def launch_debug_browser_session(
    *,
    url: str,
    token: str,
    token_key: str = "token",
    extra_token_keys: Sequence[str] = (),
    cookie_json_path: str | None = None,
    timeout_ms: int = 30_000,
    devtools: bool = False,
    wait_for_enter: bool = True,
) -> None:
    """Launch headful Chromium, inject cookies/token, and keep page open."""

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local env
        raise Send2BooxError(
            "Playwright is not installed. Install with "
            "`pip install '.[debug]'` and run `playwright install chromium`."
        ) from exc

    token_keys = _build_token_keys(primary=token_key, extra=extra_token_keys)
    cookies = load_exported_cookies(cookie_json_path) if cookie_json_path else []

    try:
        with sync_playwright() as playwright:
            launch_kwargs: dict[str, Any] = {"headless": False}
            if devtools:
                if _supports_keyword_argument(playwright.chromium.launch, "devtools"):
                    launch_kwargs["devtools"] = True
                else:
                    print(
                        "Warning: this Playwright build does not support devtools launch flag. "
                        "Continuing without --devtools."
                    )
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(ignore_https_errors=True)
            if cookies:
                context.add_cookies(cast(Any, cookies))

            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.evaluate(
                "({ token, tokenKeys }) => {"
                "  tokenKeys.forEach((key) => localStorage.setItem(key, token));"
                "}",
                {"token": token, "tokenKeys": token_keys},
            )
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)

            if wait_for_enter:
                print(
                    "Browser launched and auth state injected. "
                    "Press Enter in this terminal to close."
                )
                try:
                    input()
                except EOFError:
                    pass

            context.close()
            browser.close()

    except PlaywrightError as exc:  # pragma: no cover - depends on browser runtime
        raise Send2BooxError(f"Debug browser launch failed: {exc}") from exc


def _required_str(record: dict[str, Any], key: str, *, index: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise Send2BooxError(f"Cookie entry #{index} is missing required string key: {key}")
    return value


def _normalize_same_site(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise Send2BooxError("Cookie sameSite must be a string when provided.")
    normalized = value.strip().lower()
    if not normalized or normalized == "unspecified":
        return None
    mapped = _SAME_SITE_MAP.get(normalized)
    if mapped is None:
        raise Send2BooxError(f"Unsupported sameSite value: {value}")
    return mapped


def _normalize_expires(record: dict[str, Any]) -> int | None:
    if record.get("session") is True:
        return None
    raw = record.get("expirationDate")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    raise Send2BooxError("Cookie expirationDate must be numeric when provided.")


def _build_token_keys(*, primary: str, extra: Sequence[str]) -> list[str]:
    keys = [primary, *extra]
    normalized: list[str] = []
    for key in keys:
        clean = key.strip()
        if clean and clean not in normalized:
            normalized.append(clean)
    if not normalized:
        raise Send2BooxError("At least one token key must be provided.")
    return normalized


def _cookie_rest_value(cookie: Any, key: str) -> str | None:
    rest = getattr(cookie, "_rest", {})
    if not isinstance(rest, dict):
        return None

    lowered_key = key.lower()
    for raw_key, value in rest.items():
        if str(raw_key).strip().lower() != lowered_key:
            continue
        if value is None:
            return "true"
        return str(value)
    return None


def _cookie_rest_flag(cookie: Any, key: str) -> bool:
    value = _cookie_rest_value(cookie, key)
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _supports_keyword_argument(callable_obj: Any, key: str) -> bool:
    try:
        return key in signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False

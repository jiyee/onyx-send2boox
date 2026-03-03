"""Low-level HTTP API access for send2boox."""

from __future__ import annotations

from typing import Any

import requests
from requests.cookies import RequestsCookieJar, create_cookie

from .exceptions import ApiError, ResponseFormatError

DEFAULT_API_PREFIX = "api/1"
DEFAULT_TIMEOUT_SECONDS = 15.0


class BooxApi:
    """Thin HTTP client around send2boox API."""

    def __init__(
        self,
        *,
        cloud: str,
        token: str | None = None,
        api_prefix: str = DEFAULT_API_PREFIX,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self.cloud = cloud
        self.token = token or ""
        self.api_prefix = api_prefix.strip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def set_token(self, token: str) -> None:
        self.token = token

    def request(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        require_auth: bool = True,
    ) -> dict[str, Any]:
        url = f"https://{self.cloud}/{self.api_prefix}/{endpoint.lstrip('/')}"
        return self._request_url(
            url,
            method=method,
            params=params,
            json_data=json_data,
            headers=headers,
            require_auth=require_auth,
        )

    def request_path(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        require_auth: bool = True,
    ) -> dict[str, Any]:
        url = f"https://{self.cloud}/{path.lstrip('/')}"
        return self._request_url(
            url,
            method=method,
            params=params,
            json_data=json_data,
            headers=headers,
            require_auth=require_auth,
        )

    def _request_url(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        require_auth: bool = True,
    ) -> dict[str, Any]:
        request_headers: dict[str, str] = dict(headers or {})

        if require_auth and self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"

        if json_data is not None:
            request_headers.setdefault("Content-Type", "application/json;charset=utf-8")
            method = "POST"

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=request_headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ApiError(
                f"API request failed with HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                payload=_safe_json(exc.response),
                url=url,
            ) from exc
        except requests.RequestException as exc:
            raise ApiError(f"API request failed: {exc}", url=url) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ResponseFormatError(
                "API response is not valid JSON.",
                status_code=response.status_code,
                url=url,
            ) from exc

        if not isinstance(payload, dict):
            raise ResponseFormatError(
                "API response JSON must be an object.",
                status_code=response.status_code,
                payload=payload,
                url=url,
            )

        if payload.get("success") is False:
            raise ApiError(
                "API response reported failure.",
                status_code=response.status_code,
                payload=payload,
                url=url,
            )

        if url.rstrip("/").endswith("/users/syncToken"):
            apply_sync_token_payload_to_cookies(
                payload=payload,
                cookie_jar=self.session.cookies,
                cloud=self.cloud,
            )

        return payload


def _safe_json(response: requests.Response | None) -> Any | None:
    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def apply_sync_token_payload_to_cookies(
    *,
    payload: dict[str, Any],
    cookie_jar: RequestsCookieJar,
    cloud: str,
) -> bool:
    """Inject syncToken cookie into cookie jar when backend returns it in JSON body."""

    session_id_raw = _find_nested_key(payload, ("session_id", "sessionId", "session"))
    if not isinstance(session_id_raw, str):
        return False
    session_id = session_id_raw.strip()
    if not session_id:
        return False

    cookie_name_raw = _find_nested_key(payload, ("cookie_name", "cookieName"))
    cookie_name = "session_id"
    if isinstance(cookie_name_raw, str) and cookie_name_raw.strip():
        cookie_name = cookie_name_raw.strip()

    domain_raw = _find_nested_key(payload, ("cookie_domain", "cookieDomain", "domain"))
    if isinstance(domain_raw, str) and domain_raw.strip():
        domain = domain_raw.strip()
    else:
        domain = cloud.strip()

    path_raw = _find_nested_key(payload, ("cookie_path", "cookiePath", "path"))
    if isinstance(path_raw, str) and path_raw.strip():
        path = path_raw.strip()
    else:
        path = "/"

    secure = True
    secure_raw = _find_nested_key(payload, ("secure", "isSecure"))
    if isinstance(secure_raw, bool):
        secure = secure_raw
    elif isinstance(secure_raw, str):
        normalized = secure_raw.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            secure = False
        elif normalized in {"1", "true", "yes", "on"}:
            secure = True
    elif isinstance(secure_raw, (int, float)):
        secure = bool(secure_raw)

    cookie_names = {cookie_name, "session_id", "SyncGatewaySession"}
    for name in cookie_names:
        cookie_jar.set_cookie(
            create_cookie(
                name=name,
                value=session_id,
                domain=domain,
                path=path,
                secure=secure,
            )
        )
    return True


def _find_nested_key(payload: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    queue: list[dict[str, Any]] = [payload]
    visited: set[int] = set()

    while queue:
        current = queue.pop(0)
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)

        for key in keys:
            if key in current:
                return current[key]

        for value in current.values():
            if isinstance(value, dict):
                queue.append(value)

    return None

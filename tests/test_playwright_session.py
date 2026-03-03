from __future__ import annotations

import json
from pathlib import Path

import pytest
from requests.cookies import RequestsCookieJar, create_cookie

from send2boox.exceptions import Send2BooxError
from send2boox.playwright_session import (
    _supports_keyword_argument,
    convert_exported_cookies,
    export_cookie_jar_for_browser,
    load_exported_cookies,
    sync_token_cookies,
)


def test_convert_exported_cookies_maps_browser_fields() -> None:
    cookies = convert_exported_cookies(
        [
            {
                "domain": ".send2boox.com",
                "expirationDate": 1799726273.91,
                "httpOnly": False,
                "name": "_c_WBKFRo",
                "path": "/",
                "sameSite": "unspecified",
                "secure": False,
                "value": "value-a",
            },
            {
                "domain": ".send2boox.com",
                "httpOnly": False,
                "name": "session_id",
                "path": "/",
                "sameSite": "no_restriction",
                "secure": True,
                "session": True,
                "value": "value-b",
            },
        ]
    )

    assert cookies[0] == {
        "name": "_c_WBKFRo",
        "value": "value-a",
        "domain": ".send2boox.com",
        "path": "/",
        "secure": False,
        "httpOnly": False,
        "expires": 1799726273,
    }
    assert cookies[1] == {
        "name": "session_id",
        "value": "value-b",
        "domain": ".send2boox.com",
        "path": "/",
        "secure": True,
        "httpOnly": False,
        "sameSite": "None",
    }


def test_load_exported_cookies_from_json_file(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps(
            [
                {
                    "domain": ".send2boox.com",
                    "name": "uid",
                    "value": "token-value",
                    "path": "/",
                }
            ]
        )
    )

    cookies = load_exported_cookies(cookie_file)

    assert cookies == [
        {
            "name": "uid",
            "value": "token-value",
            "domain": ".send2boox.com",
            "path": "/",
            "secure": False,
            "httpOnly": False,
        }
    ]


def test_convert_exported_cookies_rejects_missing_fields() -> None:
    with pytest.raises(Send2BooxError):
        convert_exported_cookies(
            [
                {
                    "domain": ".send2boox.com",
                    "path": "/",
                }
            ]
        )


def test_export_cookie_jar_for_browser_maps_cookie_attributes() -> None:
    cookie_jar = RequestsCookieJar()
    cookie_jar.set_cookie(
        create_cookie(
            name="session_id",
            value="abc",
            domain=".send2boox.com",
            path="/",
            secure=True,
            expires=1799726273,
            rest={"HttpOnly": True, "SameSite": "None"},
        )
    )

    records = export_cookie_jar_for_browser(cookie_jar)

    assert records == [
        {
            "name": "session_id",
            "value": "abc",
            "domain": ".send2boox.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "none",
            "session": False,
            "expirationDate": 1799726273,
            "hostOnly": False,
        }
    ]


def test_sync_token_cookies_writes_cookie_file(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    class FakeApi:
        def __init__(self, *, cloud: str, token: str) -> None:
            captured["cloud"] = cloud
            captured["token"] = token
            self.session = type("S", (), {})()
            jar = RequestsCookieJar()
            jar.set_cookie(
                create_cookie(
                    name="uid",
                    value="u-token",
                    domain=".send2boox.com",
                    path="/",
                    secure=True,
                    rest={"SameSite": "Lax"},
                )
            )
            self.session.cookies = jar

        def request(self, endpoint: str, **_: object) -> dict[str, object]:
            captured["endpoint"] = endpoint
            return {"success": True}

    output_path = tmp_path / "cookies.json"
    monkeypatch.setattr("send2boox.playwright_session.BooxApi", FakeApi)

    written_path = sync_token_cookies(
        cloud="send2boox.com",
        token="token-abc",
        output_path=output_path,
    )

    raw = json.loads(output_path.read_text())

    assert written_path == output_path
    assert captured == {
        "cloud": "send2boox.com",
        "token": "token-abc",
        "endpoint": "users/syncToken",
    }
    assert raw[0]["name"] == "uid"
    assert raw[0]["domain"] == ".send2boox.com"


def test_sync_token_cookies_allows_empty_when_disabled(monkeypatch, tmp_path: Path) -> None:
    class FakeApi:
        def __init__(self, *, cloud: str, token: str) -> None:
            _ = (cloud, token)
            self.session = type("S", (), {})()
            self.session.cookies = RequestsCookieJar()

        def request(self, endpoint: str, **_: object) -> dict[str, object]:
            _ = endpoint
            return {"success": True}

    monkeypatch.setattr("send2boox.playwright_session.BooxApi", FakeApi)

    result = sync_token_cookies(
        cloud="send2boox.com",
        token="token-abc",
        output_path=tmp_path / "unused.json",
        raise_on_empty=False,
    )

    assert result is None


def test_sync_token_cookies_reads_session_id_from_payload(monkeypatch, tmp_path: Path) -> None:
    class FakeApi:
        def __init__(self, *, cloud: str, token: str) -> None:
            _ = (cloud, token)
            self.session = type("S", (), {})()
            self.session.cookies = RequestsCookieJar()

        def request(self, endpoint: str, **_: object) -> dict[str, object]:
            _ = endpoint
            return {
                "result_code": 0,
                "data": {
                    "cookie_name": "SyncGatewaySession",
                    "session_id": "payload-session-value",
                },
            }

    monkeypatch.setattr("send2boox.playwright_session.BooxApi", FakeApi)

    output_path = tmp_path / "cookies.json"
    written_path = sync_token_cookies(
        cloud="send2boox.com",
        token="token-abc",
        output_path=output_path,
    )

    assert written_path == output_path
    raw = json.loads(output_path.read_text())
    assert any(item["name"] == "SyncGatewaySession" for item in raw)


def test_supports_keyword_argument_detects_kwarg_presence() -> None:
    def fn_with_devtools(*, devtools: bool = False) -> None:
        _ = devtools

    def fn_without_devtools(*, headless: bool = False) -> None:
        _ = headless

    assert _supports_keyword_argument(fn_with_devtools, "devtools") is True
    assert _supports_keyword_argument(fn_without_devtools, "devtools") is False

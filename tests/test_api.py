import pytest
import requests
import responses

from send2boox.api import BooxApi
from send2boox.exceptions import ApiError, ResponseFormatError


@responses.activate
def test_api_request_success() -> None:
    responses.add(
        responses.GET,
        "https://eur.boox.com/api/1/users/me",
        json={"data": {"uid": "u1"}},
        status=200,
    )

    api = BooxApi(cloud="eur.boox.com", token="token123", session=requests.Session())
    payload = api.request("users/me")

    assert payload["data"]["uid"] == "u1"
    assert responses.calls[0].request.headers["Authorization"] == "Bearer token123"


@responses.activate
def test_api_request_http_error_raises_api_error() -> None:
    responses.add(
        responses.GET,
        "https://eur.boox.com/api/1/users/me",
        json={"error": "server"},
        status=500,
    )

    api = BooxApi(cloud="eur.boox.com", token="token123", session=requests.Session())

    with pytest.raises(ApiError) as exc_info:
        api.request("users/me")

    assert exc_info.value.status_code == 500


@responses.activate
def test_api_request_invalid_json_raises_response_format_error() -> None:
    responses.add(
        responses.GET,
        "https://eur.boox.com/api/1/users/me",
        body="not-json",
        status=200,
        content_type="text/plain",
    )

    api = BooxApi(cloud="eur.boox.com", token="token123", session=requests.Session())

    with pytest.raises(ResponseFormatError):
        api.request("users/me")


@responses.activate
def test_api_request_success_false_payload_raises_api_error() -> None:
    responses.add(
        responses.GET,
        "https://eur.boox.com/api/1/users/me",
        json={"success": False, "message": "bad"},
        status=200,
    )

    api = BooxApi(cloud="eur.boox.com", token="token123", session=requests.Session())

    with pytest.raises(ApiError) as exc_info:
        api.request("users/me")

    assert isinstance(exc_info.value.payload, dict)
    assert exc_info.value.payload.get("success") is False


@responses.activate
def test_api_sync_token_injects_cookie_from_payload_when_set_cookie_missing() -> None:
    responses.add(
        responses.GET,
        "https://send2boox.com/api/1/users/syncToken",
        json={
            "result_code": 0,
            "data": {
                "cookie_name": "SyncGatewaySession",
                "session_id": "session-value-123",
            },
        },
        status=200,
    )

    api = BooxApi(cloud="send2boox.com", token="token123", session=requests.Session())
    payload = api.request("users/syncToken")

    assert payload["result_code"] == 0
    cookies = {(cookie.name, cookie.value) for cookie in api.session.cookies}
    assert ("SyncGatewaySession", "session-value-123") in cookies
    assert ("session_id", "session-value-123") in cookies

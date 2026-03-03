from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from send2boox.client import Send2BooxClient
from send2boox.config import AppConfig
from send2boox.exceptions import ApiError, ResponseFormatError


class FakeApi:
    def __init__(
        self,
        responses: dict[str, Any],
        token: str = "token",
        *,
        path_responses: dict[str, Any] | None = None,
    ) -> None:
        self.responses = responses
        self.token = token
        self.path_responses = path_responses or {}
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "endpoint": endpoint,
                "method": method,
                "params": params,
                "json_data": json_data,
                "headers": headers,
                "require_auth": require_auth,
            }
        )
        response = self.responses.get(endpoint)
        if callable(response):
            return response()
        if isinstance(response, list):
            return response.pop(0)
        if response is None:
            return {}
        return response

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
        self.calls.append(
            {
                "endpoint": path,
                "method": method,
                "params": params,
                "json_data": json_data,
                "headers": headers,
                "require_auth": require_auth,
                "path_request": True,
            }
        )
        response = self.path_responses.get(path)
        if callable(response):
            return response()
        if isinstance(response, list):
            return response.pop(0)
        if response is None:
            return {}
        return response


def test_authenticate_with_email_code_sets_token() -> None:
    api = FakeApi({"users/signupByPhoneOrEmail": {"data": {"token": "abc123"}}}, token="")
    client = Send2BooxClient(AppConfig(email="foo@example.com"), api=api)

    token = client.authenticate_with_email_code("foo@example.com", "654321")

    assert token == "abc123"
    assert client.api.token == "abc123"


def test_authenticate_with_email_code_accepts_mobile_account() -> None:
    api = FakeApi({"users/signupByPhoneOrEmail": {"data": {"token": "abc123"}}}, token="")
    client = Send2BooxClient(AppConfig(mobile="13800138000"), api=api)

    token = client.authenticate_with_email_code("13800138000", "654321")

    assert token == "abc123"
    assert api.calls[0]["json_data"] == {"mobi": "13800138000", "code": "654321"}


def test_request_verification_code_accepts_mobile_account() -> None:
    api = FakeApi({}, token="")
    client = Send2BooxClient(AppConfig(mobile="13800138000"), api=api)

    client.request_verification_code("13800138000")

    assert api.calls[0]["endpoint"] == "users/sendMobileCode"
    assert api.calls[0]["json_data"] == {"mobi": "13800138000"}
    assert api.calls[0]["require_auth"] is False


def test_list_files_parses_response() -> None:
    api = FakeApi(
        {
            "push/message": {
                "list": [
                    {
                        "data": {
                            "args": {
                                "_id": "id1",
                                "name": "book.epub",
                                "formats": ["epub"],
                                "storage": {"epub": {"oss": {"size": "42"}}},
                            }
                        }
                    }
                ]
            }
        }
    )
    client = Send2BooxClient(AppConfig(token="t"), api=api)

    files = client.list_files(limit=12, offset=3)

    assert len(files) == 1
    assert files[0].file_id == "id1"
    assert files[0].name == "book.epub"
    assert files[0].size == 42
    assert api.calls[0]["params"]["where"] == '{"limit": 12, "offset": 3, "parent": 0}'


def test_delete_files_requires_non_empty_ids() -> None:
    api = FakeApi({})
    client = Send2BooxClient(AppConfig(token="t"), api=api)

    with pytest.raises(ValueError):
        client.delete_files([])


def test_delete_files_raises_when_result_code_is_non_zero() -> None:
    api = FakeApi(
        {
            "push/message/batchDelete": {
                "result_code": 40101,
                "message": "DELETE_FAILED",
            }
        },
        token="t",
    )
    client = Send2BooxClient(AppConfig(token="t"), api=api)

    with pytest.raises(ApiError) as exc_info:
        client.delete_files(["id-1"])

    assert "result_code 40101" in str(exc_info.value)


def test_send_file_uploads_and_pushes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    uploaded: dict[str, Any] = {}

    def fake_auth(access_key_id: str, access_key_secret: str) -> tuple[str, str]:
        return (access_key_id, access_key_secret)

    class FakeBucket:
        def __init__(self, auth: Any, endpoint: str, bucket_name: str) -> None:
            self.auth = auth
            self.endpoint = endpoint
            self.bucket_name = bucket_name

    def fake_upload(bucket: Any, remote_name: str, file_path: str, headers: dict[str, str]) -> None:
        uploaded["bucket"] = bucket
        uploaded["remote_name"] = remote_name
        uploaded["file_path"] = file_path
        uploaded["headers"] = headers

    monkeypatch.setattr("send2boox.client.oss2.Auth", fake_auth)
    monkeypatch.setattr("send2boox.client.oss2.Bucket", FakeBucket)
    monkeypatch.setattr("send2boox.client.oss2.resumable_upload", fake_upload)

    api = FakeApi(
        {
            "users/me": {"data": {"uid": "u-1"}},
            "users/getDevice": {},
            "im/getSig": {},
            "config/buckets": {
                "data": {
                    "onyx-cloud": {
                        "bucket": "bucket-a",
                        "aliEndpoint": "oss-cn.example.com",
                    }
                }
            },
            "config/stss": {
                "data": {
                    "AccessKeyId": "ak",
                    "AccessKeySecret": "sk",
                    "SecurityToken": "st",
                }
            },
            "push/saveAndPush": {},
        },
        token="token",
    )

    local_file = tmp_path / "demo.pdf"
    local_file.write_text("hello")

    client = Send2BooxClient(AppConfig(token="token"), api=api)
    client.send_file(local_file)

    assert uploaded["file_path"].endswith("demo.pdf")
    assert uploaded["headers"]["x-oss-security-token"] == "st"
    assert uploaded["remote_name"].startswith("u-1/push/")
    assert uploaded["remote_name"].endswith(".pdf")

    save_call = [c for c in api.calls if c["endpoint"] == "push/saveAndPush"][0]
    data = save_call["json_data"]["data"]
    assert data["name"] == "demo.pdf"
    assert data["resourceType"] == "pdf"


def test_send_file_raises_for_missing_file() -> None:
    api = FakeApi({}, token="token")
    client = Send2BooxClient(AppConfig(token="token"), api=api)

    with pytest.raises(FileNotFoundError):
        client.send_file("/non/existing/file.txt")


def test_list_library_books_filters_mode_type_and_deduplicates() -> None:
    api = FakeApi(
        {
            "users/me": {"data": {"uid": "u-1"}},
            "users/syncToken": {},
        },
        path_responses={
            "neocloud/_changes": [
                {
                    "results": [
                        {
                            "doc": {
                                "modeType": 4,
                                "uniqueId": "book-1",
                                "name": "Alpha",
                                "status": 0,
                            }
                        },
                        {"doc": {"modeType": 1, "uniqueId": "note-1", "status": 0}},
                    ],
                    "last_seq": "10",
                },
                {
                    "results": [
                        {
                            "doc": {
                                "modeType": 4,
                                "uniqueId": "book-1",
                                "name": "Alpha v2",
                                "status": 0,
                            }
                        },
                        {"doc": {"modeType": 4, "uniqueId": "book-2", "name": "Beta", "status": 0}},
                        {
                            "doc": {
                                "modeType": 4,
                                "uniqueId": "book-3",
                                "name": "Archived",
                                "status": 1,
                            }
                        },
                    ],
                    "last_seq": "11",
                },
                {"results": [], "last_seq": "11"},
            ]
        },
    )
    client = Send2BooxClient(AppConfig(token="t", cloud="send2boox.com"), api=api)

    books = client.list_library_books()

    assert [item.unique_id for item in books] == ["book-1", "book-2"]
    assert books[0].name == "Alpha v2"
    path_calls = [call for call in api.calls if call.get("path_request")]
    assert len(path_calls) == 3
    assert path_calls[0]["params"] == {
        "style": "all_docs",
        "filter": "sync_gateway/bychannel",
        "channels": "u-1-READER_LIBRARY",
        "since": "0",
        "limit": 1000,
        "include_docs": "true",
    }
    assert path_calls[0]["require_auth"] is True
    assert path_calls[1]["params"]["since"] == "10"
    assert path_calls[2]["params"]["since"] == "11"


def test_list_library_books_include_inactive_keeps_non_zero_status() -> None:
    api = FakeApi(
        {
            "users/me": {"data": {"uid": "u-1"}},
            "users/syncToken": {},
        },
        path_responses={
            "neocloud/_changes": [
                {
                    "results": [
                        {
                            "doc": {
                                "modeType": 4,
                                "uniqueId": "book-1",
                                "name": "Alpha",
                                "status": 0,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 4,
                                "uniqueId": "book-2",
                                "name": "Archived",
                                "status": 1,
                            }
                        },
                    ],
                    "last_seq": "1",
                },
                {"results": [], "last_seq": "1"},
            ]
        },
    )
    client = Send2BooxClient(AppConfig(token="t", cloud="send2boox.com"), api=api)

    books = client.list_library_books(include_inactive=True)

    assert [item.unique_id for item in books] == ["book-1", "book-2"]


def test_get_book_read_info_parses_statistics_payload() -> None:
    api = FakeApi(
        {
            "statistics/readInfoList": {
                "result_code": 0,
                "data": [
                    {
                        "docId": "book-1",
                        "totalTime": 17880019,
                        "avgTime": 576775,
                        "readingProgress": 67.09,
                        "name": "demo.epub",
                    }
                ],
                "tokenExpiredAt": 1788072864,
            }
        },
        token="token",
    )
    client = Send2BooxClient(AppConfig(token="token"), api=api)

    info = client.get_book_read_info("book-1")

    assert info.doc_id == "book-1"
    assert info.name == "demo.epub"
    assert info.total_time == 17880019
    assert info.avg_time == 576775
    assert info.reading_progress == 67.09
    assert info.token_expired_at == 1788072864
    assert api.calls[0]["endpoint"] == "statistics/readInfoList"
    assert api.calls[0]["json_data"] == {"docIds": ["book-1"]}


def test_get_book_read_info_raises_when_data_is_empty() -> None:
    api = FakeApi(
        {
            "statistics/readInfoList": {
                "result_code": 0,
                "data": [],
            }
        },
        token="token",
    )
    client = Send2BooxClient(AppConfig(token="token"), api=api)

    with pytest.raises(ResponseFormatError):
        client.get_book_read_info("book-1")


def test_list_book_annotations_filters_mode_type_document_and_status() -> None:
    api = FakeApi(
        {
            "users/me": {"data": {"uid": "u-1"}},
            "users/syncToken": {},
        },
        path_responses={
            "neocloud/_changes": [
                {
                    "results": [
                        {
                            "doc": {
                                "modeType": 1,
                                "uniqueId": "ann-1",
                                "documentId": "book-1",
                                "quote": "批注 A",
                                "pageNumber": 12,
                                "status": 0,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 1,
                                "uniqueId": "ann-2",
                                "documentId": "book-1",
                                "quote": "批注 B",
                                "pageNumber": 13,
                                "status": 1,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 1,
                                "uniqueId": "ann-3",
                                "documentId": "book-2",
                                "quote": "其他书",
                                "status": 0,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 2,
                                "uniqueId": "bm-1",
                                "documentId": "book-1",
                                "status": 0,
                            }
                        },
                    ],
                    "last_seq": "1",
                },
                {"results": [], "last_seq": "1"},
            ]
        },
    )
    client = Send2BooxClient(AppConfig(token="t", cloud="send2boox.com"), api=api)

    annotations = client.list_book_annotations("book-1")

    assert [item.unique_id for item in annotations] == ["ann-1"]
    assert annotations[0].document_id == "book-1"
    assert annotations[0].quote == "批注 A"
    assert annotations[0].page_number == 12
    assert annotations[0].status == 0


def test_list_book_bookmarks_filters_mode_type_document_and_status() -> None:
    api = FakeApi(
        {
            "users/me": {"data": {"uid": "u-1"}},
            "users/syncToken": {},
        },
        path_responses={
            "neocloud/_changes": [
                {
                    "results": [
                        {
                            "doc": {
                                "modeType": 2,
                                "uniqueId": "bm-1",
                                "documentId": "book-1",
                                "quote": "书签 A",
                                "pageNumber": 31,
                                "position": "8888",
                                "status": 0,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 2,
                                "uniqueId": "bm-2",
                                "documentId": "book-1",
                                "quote": "书签 B",
                                "pageNumber": 32,
                                "status": 1,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 2,
                                "uniqueId": "bm-3",
                                "documentId": "book-2",
                                "quote": "其他书签",
                                "status": 0,
                            }
                        },
                        {
                            "doc": {
                                "modeType": 1,
                                "uniqueId": "ann-1",
                                "documentId": "book-1",
                                "status": 0,
                            }
                        },
                    ],
                    "last_seq": "1",
                },
                {"results": [], "last_seq": "1"},
            ]
        },
    )
    client = Send2BooxClient(AppConfig(token="t", cloud="send2boox.com"), api=api)

    bookmarks = client.list_book_bookmarks("book-1")

    assert [item.unique_id for item in bookmarks] == ["bm-1"]
    assert bookmarks[0].document_id == "book-1"
    assert bookmarks[0].quote == "书签 A"
    assert bookmarks[0].page_number == 31
    assert bookmarks[0].position == "8888"
    assert bookmarks[0].status == 0

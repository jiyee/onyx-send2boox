"""Business layer for send2boox operations."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

import oss2

from .api import BooxApi
from .config import AppConfig
from .exceptions import ApiError, AuthenticationError, ResponseFormatError, UploadError

T = TypeVar("T")
U = TypeVar("U", bound="_HasUniqueIdAndUpdatedAt")


class _HasUniqueIdAndUpdatedAt(Protocol):
    unique_id: str
    updated_at: int | None


@dataclass(slots=True)
class RemoteFile:
    """Remote file metadata returned by push/message endpoint."""

    file_id: str
    name: str
    size: int


@dataclass(slots=True)
class LibraryBook:
    """Reader library document that can be queried by statistics/readInfoList."""

    unique_id: str
    name: str
    status: int | None = 0
    reading_status: int | None = None


@dataclass(slots=True)
class BookReadInfo:
    """Single-book reading stats returned by statistics/readInfoList."""

    doc_id: str
    name: str
    total_time: int | None
    avg_time: int | None
    reading_progress: float | None
    token_expired_at: int | None


@dataclass(slots=True)
class BookAnnotation:
    """Single annotation record stored in READER_LIBRARY."""

    unique_id: str
    document_id: str
    quote: str
    note: str = ""
    chapter: str = ""
    page_number: int | None = None
    position: str | None = None
    start_position: str | None = None
    end_position: str | None = None
    color: int | None = None
    shape: int | None = None
    status: int | None = 0
    updated_at: int | None = None


@dataclass(slots=True)
class BookBookmark:
    """Single bookmark record stored in READER_LIBRARY."""

    unique_id: str
    document_id: str
    quote: str
    title: str = ""
    page_number: int | None = None
    position: str | None = None
    xpath: str | None = None
    position_int: int | None = None
    status: int | None = 0
    updated_at: int | None = None


class Send2BooxClient:
    """High-level client implementing send2boox workflows."""

    def __init__(self, config: AppConfig, api: BooxApi | None = None) -> None:
        self.config = config
        self.api = api or BooxApi(cloud=config.cloud, token=config.token)
        self.user_id: str | None = None
        self.bucket_name: str | None = None
        self.endpoint: str | None = None

    def set_token(self, token: str) -> None:
        self.config.token = token
        self.api.set_token(token)

    def _require_token(self) -> None:
        if not self.api.token.strip():
            raise AuthenticationError(
                "Token is not configured. Run `auth login` and `auth code` first."
            )

    def authenticate_with_email_code(self, account: str, code: str) -> str:
        payload = self.api.request(
            "users/signupByPhoneOrEmail",
            json_data={"mobi": account, "code": code},
            require_auth=False,
        )
        token = _extract_nested(payload, ("data", "token"), expected_type=str)
        if not token:
            raise AuthenticationError("Token is missing in login response.", payload=payload)
        self.set_token(token)
        return token

    def request_verification_code(self, account: str) -> None:
        self.api.request(
            "users/sendMobileCode",
            json_data={"mobi": account},
            require_auth=False,
        )

    def initialize(self) -> None:
        self._require_token()
        if self.user_id and self.bucket_name and self.endpoint:
            return

        user_payload = self.api.request("users/me")
        self.user_id = _extract_nested(user_payload, ("data", "uid"), expected_type=str)

        # Keep these calls to preserve behavior of the original project.
        self.api.request("users/getDevice")
        self.api.request("im/getSig", params={"user": self.user_id})

        buckets_payload = self.api.request("config/buckets")
        onyx_cloud = _extract_nested(
            buckets_payload,
            ("data", "onyx-cloud"),
            expected_type=dict,
        )
        self.bucket_name = _extract_nested(onyx_cloud, ("bucket",), expected_type=str)
        self.endpoint = _extract_nested(onyx_cloud, ("aliEndpoint",), expected_type=str)

    def list_files(self, *, limit: int = 24, offset: int = 0) -> list[RemoteFile]:
        self._require_token()
        where = f'{{"limit": {limit}, "offset": {offset}, "parent": 0}}'
        payload = self.api.request("push/message", params={"where": where})
        entries = payload.get("list")

        if not isinstance(entries, list):
            raise ResponseFormatError(
                "Expected list field in push/message response.",
                payload=payload,
            )

        result: list[RemoteFile] = []
        for entry in entries:
            try:
                args = entry["data"]["args"]
                fmt = args["formats"][0]
                size = int(args["storage"][fmt]["oss"]["size"])
                result.append(
                    RemoteFile(
                        file_id=str(args["_id"]),
                        name=str(args["name"]),
                        size=size,
                    )
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ResponseFormatError(
                    "Unexpected file entry in push/message response.",
                    payload=entry,
                ) from exc

        return result

    def delete_files(self, file_ids: list[str]) -> None:
        self._require_token()
        if not file_ids:
            raise ValueError("file_ids must not be empty")
        payload = self.api.request("push/message/batchDelete", json_data={"ids": file_ids})
        result_code = _as_int(payload.get("result_code"))
        if result_code not in {None, 0}:
            message = _as_str(payload.get("message")) or "UNKNOWN"
            raise ApiError(
                f"Delete request failed with result_code {result_code}: {message}",
                payload=payload,
            )

    def list_library_books(self, *, include_inactive: bool = False) -> list[LibraryBook]:
        """Fetch book docs from READER_LIBRARY without browser DevTools."""

        docs = self._list_reader_library_docs()
        books_by_id: dict[str, LibraryBook] = {}

        for doc in docs:
            mode_type = _as_int(doc.get("modeType"))
            if mode_type != 4:
                continue

            unique_id = doc.get("uniqueId")
            if not isinstance(unique_id, str) or not unique_id.strip():
                continue

            status = _as_int(doc.get("status"))
            if not include_inactive and status not in {None, 0}:
                continue

            name = doc.get("name")
            if not isinstance(name, str):
                name = ""

            books_by_id[unique_id] = LibraryBook(
                unique_id=unique_id,
                name=name,
                status=status,
                reading_status=_as_int(doc.get("readingStatus")),
            )

        return list(books_by_id.values())

    def list_book_annotations(
        self,
        book_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[BookAnnotation]:
        """Fetch annotation records (modeType=1) for one book."""

        normalized_book_id = book_id.strip()
        if not normalized_book_id:
            raise ValueError("book_id must not be empty")

        docs = self._list_reader_library_docs()
        annotations_by_id: dict[str, BookAnnotation] = {}

        for doc in docs:
            mode_type = _as_int(doc.get("modeType"))
            if mode_type != 1:
                continue

            document_id = doc.get("documentId")
            if not isinstance(document_id, str) or document_id.strip() != normalized_book_id:
                continue

            status = _as_int(doc.get("status"))
            if not include_inactive and status not in {None, 0}:
                continue

            unique_id = _resolve_unique_id(doc)
            if not unique_id:
                continue

            annotation = BookAnnotation(
                unique_id=unique_id,
                document_id=document_id.strip(),
                quote=_as_str(doc.get("quote")) or "",
                note=_as_str(doc.get("note")) or "",
                chapter=_as_str(doc.get("chapter")) or "",
                page_number=_as_int(doc.get("pageNumber")),
                position=_as_str(doc.get("position")),
                start_position=_as_str(doc.get("startPosition")),
                end_position=_as_str(doc.get("endPosition")),
                color=_as_int(doc.get("color")),
                shape=_as_int(doc.get("shape")),
                status=status,
                updated_at=_as_int(doc.get("updatedAt")),
            )
            _keep_latest_by_updated_at(
                item_by_id=annotations_by_id,
                item=annotation,
                updated_at=annotation.updated_at,
            )

        return sorted(
            annotations_by_id.values(),
            key=lambda item: ((item.updated_at or 0), item.unique_id),
        )

    def list_book_bookmarks(
        self,
        book_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[BookBookmark]:
        """Fetch bookmark records (modeType=2) for one book."""

        normalized_book_id = book_id.strip()
        if not normalized_book_id:
            raise ValueError("book_id must not be empty")

        docs = self._list_reader_library_docs()
        bookmarks_by_id: dict[str, BookBookmark] = {}

        for doc in docs:
            mode_type = _as_int(doc.get("modeType"))
            if mode_type != 2:
                continue

            document_id = doc.get("documentId")
            if not isinstance(document_id, str) or document_id.strip() != normalized_book_id:
                continue

            status = _as_int(doc.get("status"))
            if not include_inactive and status not in {None, 0}:
                continue

            unique_id = _resolve_unique_id(doc)
            if not unique_id:
                continue

            bookmark = BookBookmark(
                unique_id=unique_id,
                document_id=document_id.strip(),
                quote=_as_str(doc.get("quote")) or "",
                title=_as_str(doc.get("title")) or "",
                page_number=_as_int(doc.get("pageNumber")),
                position=_as_str(doc.get("position")),
                xpath=_as_str(doc.get("xpath")),
                position_int=_as_int(doc.get("positionInt")),
                status=status,
                updated_at=_as_int(doc.get("updatedAt")),
            )
            _keep_latest_by_updated_at(
                item_by_id=bookmarks_by_id,
                item=bookmark,
                updated_at=bookmark.updated_at,
            )

        return sorted(
            bookmarks_by_id.values(),
            key=lambda item: ((item.updated_at or 0), item.unique_id),
        )

    def get_book_read_info(self, book_id: str) -> BookReadInfo:
        """Fetch reading statistics for a single library book."""

        self._require_token()
        normalized_book_id = book_id.strip()
        if not normalized_book_id:
            raise ValueError("book_id must not be empty")

        payload = self.api.request(
            "statistics/readInfoList",
            json_data={"docIds": [normalized_book_id]},
        )
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ResponseFormatError(
                "Expected non-empty list field in statistics/readInfoList response.",
                payload=payload,
            )

        first = data[0]
        if not isinstance(first, dict):
            raise ResponseFormatError(
                "Expected object entry in statistics/readInfoList data list.",
                payload=payload,
            )

        response_doc_id = first.get("docId")
        if isinstance(response_doc_id, str) and response_doc_id.strip():
            doc_id = response_doc_id.strip()
        else:
            doc_id = normalized_book_id

        name = first.get("name")
        if not isinstance(name, str):
            name = ""

        return BookReadInfo(
            doc_id=doc_id,
            name=name,
            total_time=_as_int(first.get("totalTime")),
            avg_time=_as_int(first.get("avgTime")),
            reading_progress=_as_float(first.get("readingProgress")),
            token_expired_at=_as_int(payload.get("tokenExpiredAt")),
        )

    def _list_reader_library_docs(self) -> list[dict[str, Any]]:
        """Fetch all docs in current user's READER_LIBRARY channel."""

        self._require_token()
        user_payload = self.api.request("users/me")
        user_id = _extract_nested(user_payload, ("data", "uid"), expected_type=str)
        self.api.request("users/syncToken")

        since = "0"
        visited_since: set[str] = set()
        channel = f"{user_id}-READER_LIBRARY"
        docs: list[dict[str, Any]] = []

        while True:
            changes_payload = self.api.request_path(
                "neocloud/_changes",
                params={
                    "style": "all_docs",
                    "filter": "sync_gateway/bychannel",
                    "channels": channel,
                    "since": since,
                    "limit": 1000,
                    "include_docs": "true",
                },
                require_auth=True,
            )

            results = changes_payload.get("results")
            if not isinstance(results, list):
                raise ResponseFormatError(
                    "Expected list field in neocloud/_changes response.",
                    payload=changes_payload,
                )

            for entry in results:
                if not isinstance(entry, dict):
                    continue
                doc = entry.get("doc")
                if isinstance(doc, dict):
                    docs.append(doc)

            if not results:
                break

            last_seq = changes_payload.get("last_seq")
            if last_seq is None:
                break

            next_since = str(last_seq)
            if next_since == since or next_since in visited_since:
                break

            visited_since.add(since)
            since = next_since

        return docs

    def send_file(self, path: str | Path) -> None:
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        self.initialize()
        if self.user_id is None or self.bucket_name is None or self.endpoint is None:
            raise ResponseFormatError("Client is not fully initialized.")

        stss_payload = self.api.request("config/stss")
        access_key_id = _extract_nested(stss_payload, ("data", "AccessKeyId"), expected_type=str)
        access_key_secret = _extract_nested(
            stss_payload,
            ("data", "AccessKeySecret"),
            expected_type=str,
        )
        security_token = _extract_nested(
            stss_payload,
            ("data", "SecurityToken"),
            expected_type=str,
        )

        suffix = file_path.suffix.lstrip(".")
        remote_name = f"{self.user_id}/push/{uuid.uuid4()}"
        if suffix:
            remote_name = f"{remote_name}.{suffix}"

        try:
            auth = oss2.Auth(access_key_id, access_key_secret)
            bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
            oss2.resumable_upload(
                bucket,
                remote_name,
                os.fspath(file_path),
                headers={"x-oss-security-token": security_token},
            )
        except Exception as exc:  # pragma: no cover - third-party exceptions vary
            raise UploadError(f"Failed to upload file {file_path}: {exc}") from exc

        filename = file_path.name
        resource_type = suffix.lower() if suffix else "bin"
        self.api.request(
            "push/saveAndPush",
            json_data={
                "data": {
                    "bucket": self.bucket_name,
                    "name": filename,
                    "parent": None,
                    "resourceDisplayName": filename,
                    "resourceKey": remote_name,
                    "resourceType": resource_type,
                    "title": filename,
                }
            },
        )


def format_files_table(files: list[RemoteFile]) -> str:
    """Format remote files for terminal output."""

    lines = [
        "       File ID           |    Size    | Name",
        "-------------------------|------------|-------------------------------------------------------",
    ]
    for item in files:
        lines.append(f"{item.file_id} | {item.size:>10n} | {item.name}")
    return "\n".join(lines)


def format_library_books_table(books: list[LibraryBook]) -> str:
    """Format library books for terminal output (ID + name only)."""

    lines = [
        "      Book ID            | Name",
        "-------------------------|-------------------------------------------------------",
    ]
    for item in books:
        lines.append(f"{item.unique_id} | {item.name}")
    return "\n".join(lines)


def _extract_nested(
    payload: dict[str, Any],
    path: tuple[str, ...],
    *,
    expected_type: type[T],
) -> T:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            raise ResponseFormatError(
                f"Missing key path: {'/'.join(path)}",
                payload=payload,
            )
        current = current[key]

    if not isinstance(current, expected_type):
        raise ResponseFormatError(
            f"Expected {'/'.join(path)} to be {expected_type.__name__}.",
            payload=payload,
        )

    return current


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        clean = value.strip()
        if clean:
            try:
                return int(clean)
            except ValueError:
                return None
    return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        clean = value.strip()
        if clean:
            try:
                return float(clean)
            except ValueError:
                return None
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _resolve_unique_id(doc: dict[str, Any]) -> str:
    unique_id = doc.get("uniqueId")
    if isinstance(unique_id, str) and unique_id.strip():
        return unique_id.strip()

    doc_id = doc.get("_id")
    if isinstance(doc_id, str) and doc_id.strip():
        return doc_id.strip()

    return ""


def _keep_latest_by_updated_at(
    *,
    item_by_id: dict[str, U],
    item: U,
    updated_at: int | None,
) -> None:
    existing = item_by_id.get(item.unique_id)
    if existing is None:
        item_by_id[item.unique_id] = item
        return

    existing_updated_at = existing.updated_at
    existing_ts = existing_updated_at if isinstance(existing_updated_at, int) else -1
    item_ts = updated_at if isinstance(updated_at, int) else -1
    if item_ts >= existing_ts:
        item_by_id[item.unique_id] = item

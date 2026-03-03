from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from send2boox.cli import main
from send2boox.client import RemoteFile
from send2boox.config import AppConfig
from send2boox.exceptions import Send2BooxError


@dataclass
class DummyClient:
    config: AppConfig

    def request_verification_code(self, email: str) -> None:
        self.config.email = email

    def authenticate_with_email_code(self, email: str, code: str) -> str:
        self.config.email = email
        self.config.token = f"token-{code}"
        return self.config.token

    def list_files(self, limit: int = 24, offset: int = 0) -> list[RemoteFile]:
        _ = (limit, offset)
        return [RemoteFile(file_id="id-1", name="book.epub", size=123)]

    def send_file(self, path: str) -> None:
        _ = path

    def delete_files(self, ids: list[str]) -> None:
        _ = ids

    def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
        _ = include_inactive
        return []

    def get_book_read_info(self, book_id: str) -> DummyReadInfo:
        _ = book_id
        return DummyReadInfo(
            doc_id="book-1",
            name="Alpha",
            total_time=100,
            avg_time=50,
            reading_progress=12.34,
            token_expired_at=999,
        )

    def list_book_annotations(
        self,
        book_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[DummyAnnotation]:
        _ = (book_id, include_inactive)
        return []

    def list_book_bookmarks(
        self,
        book_id: str,
        *,
        include_inactive: bool = False,
    ) -> list[DummyBookmark]:
        _ = (book_id, include_inactive)
        return []


@dataclass
class DummyBook:
    unique_id: str
    name: str
    status: int | None = 0
    reading_status: int | None = 0
    title: str = ""
    authors: str = ""


@dataclass
class DummyReadInfo:
    doc_id: str
    name: str
    total_time: int | None
    avg_time: int | None
    reading_progress: float | None
    token_expired_at: int | None


@dataclass
class DummyAnnotation:
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


@dataclass
class DummyBookmark:
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


@dataclass
class DummyDebugReport:
    payload: str = '{"interfaces":[],"network_requests":0}'

    def to_json(self, *, indent: int = 2) -> str:
        _ = indent
        return self.payload


def test_request_login_code_requires_account(monkeypatch, capsys) -> None:
    monkeypatch.setattr("send2boox.cli.load_config", lambda _: AppConfig(email="", token=""))
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", DummyClient)

    rc = main(["auth", "login"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "[ERROR]" in captured.err
    assert "Login account is required" in captured.err


def test_request_login_code_accepts_mobile(monkeypatch, capsys) -> None:
    captured: dict[str, str] = {}

    class CapturingClient(DummyClient):
        def request_verification_code(self, account: str) -> None:
            captured["account"] = account

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="", token="", mobile=""),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(["auth", "login", "--mobile", "13800138000"])

    captured_io = capsys.readouterr()
    assert rc == 0
    assert captured["account"] == "13800138000"
    assert "[OK] Code requested." in captured_io.err


def test_login_with_code_uses_config_mobile_when_email_empty(monkeypatch, capsys) -> None:
    saved: dict[str, Any] = {}

    def fake_save(config: AppConfig, path: str) -> None:
        saved["config"] = config
        saved["path"] = path

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="", token="", mobile="13800138000", cloud="eur.boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.save_config", fake_save)
    monkeypatch.setattr(
        "send2boox.cli.sync_token_cookies",
        lambda **_kwargs: Path("session-cookies.json"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", DummyClient)

    rc = main(["auth", "code", "123456"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "[OK] Token obtained and saved." in captured.err
    assert "[OK] Token prefix:" in captured.err
    assert isinstance(saved["config"], AppConfig)
    assert saved["config"].token == "token-123456"
    assert saved["config"].mobile == "13800138000"


def test_login_with_code_updates_config_and_calls_save(monkeypatch, capsys) -> None:
    saved: dict[str, Any] = {}
    synced: dict[str, Any] = {}

    def fake_save(config: AppConfig, path: str) -> None:
        saved["config"] = config
        saved["path"] = path

    def fake_sync_token_cookies(
        *,
        cloud: str,
        token: str,
        output_path: str | Path,
        raise_on_empty: bool,
    ) -> Path:
        synced["cloud"] = cloud
        synced["token"] = token
        synced["output_path"] = output_path
        synced["raise_on_empty"] = raise_on_empty
        return Path(output_path)

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="", cloud="eur.boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.save_config", fake_save)
    monkeypatch.setattr("send2boox.cli.sync_token_cookies", fake_sync_token_cookies)
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", DummyClient)

    rc = main(["auth", "code", "123456"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "[OK] Token obtained and saved." in captured.err
    assert "[OK] Session cookies saved to session-cookies.json" in captured.err
    assert isinstance(saved["config"], AppConfig)
    assert saved["config"].token == "token-123456"
    assert synced == {
        "cloud": "eur.boox.com",
        "token": "token-123456",
        "output_path": Path("session-cookies.json"),
        "raise_on_empty": False,
    }


def test_list_files_command_prints_table(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="eur.boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", DummyClient)

    rc = main(["file", "list", "--limit", "10", "--offset", "2"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "ID" in captured.out
    assert "book.epub" in captured.out


def test_file_delete_rechecks_list_until_deleted(monkeypatch, capsys) -> None:
    captured: dict[str, Any] = {"list_calls": 0}

    class CapturingClient(DummyClient):
        def delete_files(self, ids: list[str]) -> None:
            captured["deleted_ids"] = ids

        def list_files(self, limit: int = 24, offset: int = 0) -> list[RemoteFile]:
            _ = (limit, offset)
            captured["list_calls"] += 1
            if captured["list_calls"] == 1:
                return [RemoteFile(file_id="id-1", name="book.epub", size=123)]
            return [RemoteFile(file_id="id-2", name="other.epub", size=456)]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)
    monkeypatch.setattr("send2boox.cli.time.sleep", lambda _seconds: None)

    rc = main(["file", "delete", "id-1"])

    captured_io = capsys.readouterr()
    assert rc == 0
    assert captured["deleted_ids"] == ["id-1"]
    assert captured["list_calls"] >= 2
    assert "id-2" in captured_io.out
    assert "id-1" not in captured_io.out


def test_file_delete_warns_when_target_still_present(monkeypatch, capsys) -> None:
    class CapturingClient(DummyClient):
        def delete_files(self, ids: list[str]) -> None:
            _ = ids

        def list_files(self, limit: int = 24, offset: int = 0) -> list[RemoteFile]:
            _ = (limit, offset)
            return [
                RemoteFile(file_id="id-1", name="book.epub", size=123),
                RemoteFile(file_id="id-2", name="other.epub", size=456),
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)
    monkeypatch.setattr("send2boox.cli.time.sleep", lambda _seconds: None)

    rc = main(["file", "delete", "id-1"])

    captured_io = capsys.readouterr()
    assert rc == 0
    assert "[WARN] delete request succeeded but file IDs still visible" in captured_io.err
    assert "id-1" in captured_io.err


def test_list_books_outputs_table_and_writes_metadata(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    metadata_path = tmp_path / "library-books.json"
    captured: dict[str, Any] = {}

    class CapturingClient(DummyClient):
        def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
            captured["include_inactive"] = include_inactive
            return [
                DummyBook(unique_id="book-1", name="Alpha", status=0, reading_status=1),
                DummyBook(unique_id="book-2", name="Beta", status=1, reading_status=2),
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(
        [
            "book",
            "list",
            "--include-inactive",
            "--output",
            str(metadata_path),
        ]
    )

    captured_io = capsys.readouterr()
    assert rc == 0
    assert captured["include_inactive"] is True
    lines = captured_io.out.splitlines()
    assert "Book ID" in lines[0]
    assert "Name" in lines[0]
    assert "book-1" in captured_io.out
    assert "Alpha" in captured_io.out
    assert "book-2" in captured_io.out
    assert "Beta" in captured_io.out
    assert "status" not in captured_io.out
    assert "reading_status" not in captured_io.out
    expected_metadata = [
        {
            "unique_id": "book-1",
            "name": "Alpha",
            "status": 0,
            "reading_status": 1,
        },
        {
            "unique_id": "book-2",
            "name": "Beta",
            "status": 1,
            "reading_status": 2,
        },
    ]
    metadata = json.loads(metadata_path.read_text())
    assert metadata == expected_metadata


def test_list_books_rejects_removed_full_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["book", "list", "--full"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "unrecognized arguments: --full" in captured.err


def test_list_books_rejects_removed_table_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["book", "list", "--table"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "unrecognized arguments: --table" in captured.err


def test_list_books_json_outputs_full_metadata(monkeypatch, capsys) -> None:
    class CapturingClient(DummyClient):
        def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
            _ = include_inactive
            return [
                DummyBook(unique_id="book-1", name="Alpha", status=0, reading_status=1),
                DummyBook(unique_id="book-2", name="Beta", status=0, reading_status=2),
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(["book", "list", "--json"])

    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload == [
        {
            "unique_id": "book-1",
            "name": "Alpha",
            "status": 0,
            "reading_status": 1,
        },
        {
            "unique_id": "book-2",
            "name": "Beta",
            "status": 0,
            "reading_status": 2,
        },
    ]


def test_list_books_falls_back_to_eur_when_primary_unauthorized(
    monkeypatch,
    capsys,
) -> None:
    attempted_hosts: list[str] = []

    class FallbackClient(DummyClient):
        def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
            _ = include_inactive
            attempted_hosts.append(self.config.cloud)
            if self.config.cloud == "send2boox.com":
                raise Send2BooxError("API request failed with HTTP 401")
            return [DummyBook(unique_id="book-1", name="Alpha", status=0, reading_status=1)]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", FallbackClient)

    rc = main(["book", "list"])

    captured = capsys.readouterr()
    assert rc == 0
    assert attempted_hosts[:2] == ["send2boox.com", "eur.boox.com"]
    lines = captured.out.splitlines()
    assert "Book ID" in lines[0]
    assert "Name" in lines[0]
    assert "book-1" in captured.out
    assert "Alpha" in captured.out
    assert "used eur.boox.com fallback" in captured.err


def test_read_stats_outputs_json_and_writes_file(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "read-stats.json"
    captured: dict[str, str] = {}

    class CapturingClient(DummyClient):
        def get_book_read_info(self, book_id: str) -> DummyReadInfo:
            captured["book_id"] = book_id
            return DummyReadInfo(
                doc_id=book_id,
                name="Alpha",
                total_time=17880019,
                avg_time=576775,
                reading_progress=67.09,
                token_expired_at=1788072864,
            )

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(["book", "stats", "book-1", "--output", str(output_path)])

    captured_io = capsys.readouterr()
    assert rc == 0
    assert captured["book_id"] == "book-1"
    payload = json.loads(captured_io.out)
    assert payload == {
        "doc_id": "book-1",
        "name": "Alpha",
        "total_time": 17880019,
        "avg_time": 576775,
        "reading_progress": 67.09,
        "token_expired_at": 1788072864,
    }
    assert json.loads(output_path.read_text()) == payload


def test_read_stats_falls_back_to_eur_when_primary_unauthorized(monkeypatch, capsys) -> None:
    attempted_hosts: list[str] = []

    class FallbackClient(DummyClient):
        def get_book_read_info(self, book_id: str) -> DummyReadInfo:
            attempted_hosts.append(self.config.cloud)
            if self.config.cloud == "send2boox.com":
                raise Send2BooxError("API request failed with HTTP 401")
            return DummyReadInfo(
                doc_id=book_id,
                name="Alpha",
                total_time=1,
                avg_time=1,
                reading_progress=1.0,
                token_expired_at=1,
            )

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", FallbackClient)

    rc = main(["book", "stats", "book-1"])

    captured = capsys.readouterr()
    assert rc == 0
    assert attempted_hosts[:2] == ["send2boox.com", "eur.boox.com"]
    assert '"doc_id": "book-1"' in captured.out
    assert "used eur.boox.com fallback" in captured.err


def test_read_annotations_outputs_json_and_writes_file(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "annotations.json"
    captured: dict[str, Any] = {}

    class CapturingClient(DummyClient):
        def list_book_annotations(
            self,
            book_id: str,
            *,
            include_inactive: bool = False,
        ) -> list[DummyAnnotation]:
            captured["book_id"] = book_id
            captured["include_inactive"] = include_inactive
            return [
                DummyAnnotation(
                    unique_id="ann-1",
                    document_id=book_id,
                    quote="驴的潇洒与放荡",
                    chapter="第十二章",
                    page_number=199,
                    position='{"chapterIndex":24}',
                    color=-983296,
                    shape=5,
                    status=0,
                    updated_at=1771337927265,
                )
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(
        [
            "book",
            "annotations",
            "book-1",
            "--output",
            str(output_path),
        ]
    )

    captured_io = capsys.readouterr()
    assert rc == 0
    assert captured == {"book_id": "book-1", "include_inactive": False}
    payload = json.loads(captured_io.out)
    assert payload == [
        {
            "unique_id": "ann-1",
            "document_id": "book-1",
            "quote": "驴的潇洒与放荡",
            "note": "",
            "chapter": "第十二章",
            "page_number": 199,
            "position": '{"chapterIndex":24}',
            "start_position": None,
            "end_position": None,
            "color": -983296,
            "shape": 5,
            "status": 0,
            "updated_at": 1771337927265,
        }
    ]
    assert json.loads(output_path.read_text()) == payload


def test_read_bookmarks_outputs_json_and_writes_file(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "bookmarks.json"
    captured: dict[str, Any] = {}

    class CapturingClient(DummyClient):
        def list_book_bookmarks(
            self,
            book_id: str,
            *,
            include_inactive: bool = False,
        ) -> list[DummyBookmark]:
            captured["book_id"] = book_id
            captured["include_inactive"] = include_inactive
            return [
                DummyBookmark(
                    unique_id="bm-1",
                    document_id=book_id,
                    quote="推荐序能力与岗位的匹配",
                    title="推荐序",
                    page_number=1275,
                    position="1616778",
                    xpath="1/3/",
                    position_int=1616778,
                    status=0,
                    updated_at=1693543350299,
                )
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(
        [
            "book",
            "bookmarks",
            "book-1",
            "--output",
            str(output_path),
        ]
    )

    captured_io = capsys.readouterr()
    assert rc == 0
    assert captured == {"book_id": "book-1", "include_inactive": False}
    payload = json.loads(captured_io.out)
    assert payload == [
        {
            "unique_id": "bm-1",
            "document_id": "book-1",
            "quote": "推荐序能力与岗位的匹配",
            "title": "推荐序",
            "page_number": 1275,
            "position": "1616778",
            "xpath": "1/3/",
            "position_int": 1616778,
            "status": 0,
            "updated_at": 1693543350299,
        }
    ]
    assert json.loads(output_path.read_text()) == payload


def test_book_dump_outputs_annotation_txt_template(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "book-annotations.txt"

    class CapturingClient(DummyClient):
        def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
            _ = include_inactive
            return [DummyBook(unique_id="book-1", name="Alpha")]

        def list_book_annotations(
            self,
            book_id: str,
            *,
            include_inactive: bool = False,
        ) -> list[DummyAnnotation]:
            _ = include_inactive
            return [
                DummyAnnotation(
                    unique_id="ann-1",
                    document_id=book_id,
                    chapter="01 Chapter",
                    quote="Quote 1",
                    note="Note 1",
                    page_number=12,
                    updated_at=None,
                ),
                DummyAnnotation(
                    unique_id="ann-2",
                    document_id=book_id,
                    quote="Quote 2",
                    page_number=13,
                    updated_at=None,
                ),
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(
        [
            "book",
            "dump",
            "book-1",
            "--author",
            "Author A",
            "--output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "[OK] Annotation dump written to" in captured.err
    expected = (
        "Reading Notes\xa0|\xa0<<Alpha>>Author A\n"
        "01 Chapter\n"
        "1970-01-01 00:00\xa0\xa0|\xa0\xa0Page No.: 13\n"
        "Quote 1\n"
        "【Annotation】Note 1\n"
        "-------------------\n"
        "1970-01-01 00:00\xa0\xa0|\xa0\xa0Page No.: 14\n"
        "Quote 2\n"
        "-------------------\n"
    )
    assert output_path.read_text(encoding="utf-8") == expected


def test_book_dump_strips_known_extension_from_inferred_title(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "book-annotations.txt"

    class CapturingClient(DummyClient):
        def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
            _ = include_inactive
            return [DummyBook(unique_id="book-1", name="Alpha.epub")]

        def list_book_annotations(
            self,
            book_id: str,
            *,
            include_inactive: bool = False,
        ) -> list[DummyAnnotation]:
            _ = include_inactive
            return [
                DummyAnnotation(
                    unique_id="ann-1",
                    document_id=book_id,
                    quote="Quote 1",
                    page_number=0,
                    updated_at=None,
                )
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(
        [
            "book",
            "dump",
            "book-1",
            "--author",
            "Author A",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert output_path.read_text(encoding="utf-8").startswith(
        "Reading Notes\xa0|\xa0<<Alpha>>Author A\n"
    )


def test_book_dump_uses_book_author_when_author_arg_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "book-annotations.txt"

    class CapturingClient(DummyClient):
        def list_library_books(self, *, include_inactive: bool = False) -> list[DummyBook]:
            _ = include_inactive
            return [DummyBook(unique_id="book-1", name="Alpha", authors="Author A")]

        def list_book_annotations(
            self,
            book_id: str,
            *,
            include_inactive: bool = False,
        ) -> list[DummyAnnotation]:
            _ = include_inactive
            return [
                DummyAnnotation(
                    unique_id="ann-1",
                    document_id=book_id,
                    quote="Quote 1",
                    page_number=0,
                    updated_at=None,
                )
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(
        [
            "book",
            "dump",
            "book-1",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert output_path.read_text(encoding="utf-8").startswith(
        "Reading Notes\xa0|\xa0<<Alpha>>Author A\n"
    )


def test_read_bookmarks_falls_back_to_eur_when_primary_unauthorized(
    monkeypatch,
    capsys,
) -> None:
    attempted_hosts: list[str] = []

    class FallbackClient(DummyClient):
        def list_book_bookmarks(
            self,
            book_id: str,
            *,
            include_inactive: bool = False,
        ) -> list[DummyBookmark]:
            _ = (book_id, include_inactive)
            attempted_hosts.append(self.config.cloud)
            if self.config.cloud == "send2boox.com":
                raise Send2BooxError("API request failed with HTTP 401")
            return [
                DummyBookmark(
                    unique_id="bm-1",
                    document_id="book-1",
                    quote="推荐序能力与岗位的匹配",
                    status=0,
                )
            ]

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="send2boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", FallbackClient)

    rc = main(["book", "bookmarks", "book-1"])

    captured = capsys.readouterr()
    assert rc == 0
    assert attempted_hosts[:2] == ["send2boox.com", "eur.boox.com"]
    assert '"unique_id": "bm-1"' in captured.out
    assert "used eur.boox.com fallback" in captured.err


def test_debug_playwright_command_runs_without_config(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    captured_args: dict[str, Any] = {}
    output_path = tmp_path / "playwright-report.json"

    def fail_load_config(_: str) -> AppConfig:
        raise AssertionError("load_config must not be called for debug-playwright")

    def fake_debug(
        *,
        url: str,
        headless: bool,
        timeout_ms: int,
        settle_ms: int,
        max_requests: int,
        max_body_chars: int,
    ) -> DummyDebugReport:
        captured_args["url"] = url
        captured_args["headless"] = headless
        captured_args["timeout_ms"] = timeout_ms
        captured_args["settle_ms"] = settle_ms
        captured_args["max_requests"] = max_requests
        captured_args["max_body_chars"] = max_body_chars
        return DummyDebugReport()

    monkeypatch.setattr("send2boox.cli.load_config", fail_load_config)
    monkeypatch.setattr("send2boox.cli.run_playwright_debug", fake_debug)

    rc = main(
        [
            "debug-playwright",
            "https://eur.boox.com",
            "--headful",
            "--timeout-ms",
            "11111",
            "--settle-ms",
            "2222",
            "--max-requests",
            "77",
            "--max-body-chars",
            "444",
            "--output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured_args == {
        "url": "https://eur.boox.com",
        "headless": False,
        "timeout_ms": 11111,
        "settle_ms": 2222,
        "max_requests": 77,
        "max_body_chars": 444,
    }
    assert output_path.read_text() == '{"interfaces":[],"network_requests":0}'
    assert "[OK] Report written to" in captured.err


def test_server_option_overrides_config_cloud(monkeypatch, capsys) -> None:
    seen: dict[str, str] = {}

    class CapturingClient:
        def __init__(self, config: AppConfig) -> None:
            seen["cloud"] = config.cloud

        def list_files(self, limit: int = 24, offset: int = 0) -> list[RemoteFile]:
            _ = (limit, offset)
            return []

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="tkn", cloud="eur.boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", CapturingClient)

    rc = main(["--server", "us.boox.com", "file", "list"])

    _ = capsys.readouterr()
    assert rc == 0
    assert seen["cloud"] == "us.boox.com"


def test_debug_browser_command_runs_without_config(monkeypatch, capsys) -> None:
    captured: dict[str, Any] = {}

    def fail_load_config(_: str) -> AppConfig:
        raise AssertionError("load_config must not be called for debug-browser")

    def fake_launch_debug_browser_session(
        *,
        url: str,
        token: str,
        token_key: str,
        extra_token_keys: list[str],
        cookie_json_path: str | None,
        timeout_ms: int,
        devtools: bool,
        wait_for_enter: bool,
    ) -> None:
        captured["url"] = url
        captured["token"] = token
        captured["token_key"] = token_key
        captured["extra_token_keys"] = extra_token_keys
        captured["cookie_json_path"] = cookie_json_path
        captured["timeout_ms"] = timeout_ms
        captured["devtools"] = devtools
        captured["wait_for_enter"] = wait_for_enter

    monkeypatch.setattr("send2boox.cli.load_config", fail_load_config)
    monkeypatch.setattr(
        "send2boox.cli.launch_debug_browser_session",
        fake_launch_debug_browser_session,
    )

    rc = main(
        [
            "debug-browser",
            "https://send2boox.com/#/login",
            "--token",
            "token-abc",
            "--token-key",
            "token",
            "--extra-token-key",
            "access_token",
            "--cookie-json",
            "cookies.json",
            "--timeout-ms",
            "22222",
            "--devtools",
            "--no-wait",
        ]
    )

    _ = capsys.readouterr()
    assert rc == 0
    assert captured == {
        "url": "https://send2boox.com/#/login",
        "token": "token-abc",
        "token_key": "token",
        "extra_token_keys": ["access_token"],
        "cookie_json_path": "cookies.json",
        "timeout_ms": 22222,
        "devtools": True,
        "wait_for_enter": False,
    }


def test_debug_browser_uses_config_token_and_auto_sync_cookie(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    captured: dict[str, Any] = {}
    synced: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="cfg-token", cloud="send2boox.com"),
    )

    def fake_sync_token_cookies(
        *,
        cloud: str,
        token: str,
        output_path: str | Path,
        raise_on_empty: bool,
    ) -> Path:
        synced["cloud"] = cloud
        synced["token"] = token
        synced["output_path"] = output_path
        synced["raise_on_empty"] = raise_on_empty
        return Path(output_path)

    def fake_launch_debug_browser_session(
        *,
        url: str,
        token: str,
        token_key: str,
        extra_token_keys: list[str],
        cookie_json_path: str | None,
        timeout_ms: int,
        devtools: bool,
        wait_for_enter: bool,
    ) -> None:
        captured["url"] = url
        captured["token"] = token
        captured["token_key"] = token_key
        captured["extra_token_keys"] = extra_token_keys
        captured["cookie_json_path"] = cookie_json_path
        captured["timeout_ms"] = timeout_ms
        captured["devtools"] = devtools
        captured["wait_for_enter"] = wait_for_enter

    monkeypatch.setattr("send2boox.cli.sync_token_cookies", fake_sync_token_cookies)
    monkeypatch.setattr(
        "send2boox.cli.launch_debug_browser_session",
        fake_launch_debug_browser_session,
    )

    rc = main(["debug-browser", "https://send2boox.com/#/login"])

    captured_out = capsys.readouterr()
    assert rc == 0
    assert "[OK] Session cookies synced to session-cookies.json" in captured_out.err
    assert synced == {
        "cloud": "send2boox.com",
        "token": "cfg-token",
        "output_path": Path("session-cookies.json"),
        "raise_on_empty": False,
    }
    assert captured == {
        "url": "https://send2boox.com/#/login",
        "token": "cfg-token",
        "token_key": "token",
        "extra_token_keys": [],
        "cookie_json_path": "session-cookies.json",
        "timeout_ms": 30000,
        "devtools": False,
        "wait_for_enter": True,
    }


def test_obtain_token_warns_when_cookie_sync_empty(monkeypatch, capsys) -> None:
    def fake_sync_token_cookies(
        *,
        cloud: str,
        token: str,
        output_path: str | Path,
        raise_on_empty: bool,
    ) -> None:
        _ = (cloud, token, output_path, raise_on_empty)
        return None

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="", cloud="eur.boox.com"),
    )
    monkeypatch.setattr("send2boox.cli.save_config", lambda _config, _path: None)
    monkeypatch.setattr("send2boox.cli.sync_token_cookies", fake_sync_token_cookies)
    monkeypatch.setattr("send2boox.cli.Send2BooxClient", DummyClient)

    rc = main(["auth", "code", "123456"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "[WARN] session cookie sync returned no cookies." in captured.err


def test_debug_browser_continues_when_cookie_sync_empty(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        "send2boox.cli.load_config",
        lambda _: AppConfig(email="user@example.com", token="cfg-token", cloud="eur.boox.com"),
    )

    def fake_sync_token_cookies(
        *,
        cloud: str,
        token: str,
        output_path: str | Path,
        raise_on_empty: bool,
    ) -> None:
        _ = (cloud, token, output_path, raise_on_empty)
        return None

    def fake_launch_debug_browser_session(
        *,
        url: str,
        token: str,
        token_key: str,
        extra_token_keys: list[str],
        cookie_json_path: str | None,
        timeout_ms: int,
        devtools: bool,
        wait_for_enter: bool,
    ) -> None:
        captured["url"] = url
        captured["token"] = token
        captured["token_key"] = token_key
        captured["extra_token_keys"] = extra_token_keys
        captured["cookie_json_path"] = cookie_json_path
        captured["timeout_ms"] = timeout_ms
        captured["devtools"] = devtools
        captured["wait_for_enter"] = wait_for_enter

    monkeypatch.setattr("send2boox.cli.sync_token_cookies", fake_sync_token_cookies)
    monkeypatch.setattr(
        "send2boox.cli.launch_debug_browser_session",
        fake_launch_debug_browser_session,
    )

    rc = main(["debug-browser", "https://send2boox.com/#/login"])

    captured_out = capsys.readouterr()
    assert rc == 0
    assert "[WARN] session cookie sync returned no cookies." in captured_out.err
    assert captured == {
        "url": "https://send2boox.com/#/login",
        "token": "cfg-token",
        "token_key": "token",
        "extra_token_keys": [],
        "cookie_json_path": None,
        "timeout_ms": 30000,
        "devtools": False,
        "wait_for_enter": True,
    }

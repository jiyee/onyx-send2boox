from pathlib import Path

import pytest

from send2boox.config import AppConfig, load_config, save_config
from send2boox.exceptions import ConfigError


def test_load_config_success(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'email = "a@b.com"\n'
        'token = "tkn"\n'
        'cloud = "cloud.example"\n'
    )

    config = load_config(config_path)

    assert config.email == "a@b.com"
    assert config.token == "tkn"
    assert config.cloud == "cloud.example"


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.toml"

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_save_config_roundtrip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    expected = AppConfig(email="test@example.com", token="abc123", cloud="eur.boox.com")

    save_config(expected, config_path)
    loaded = load_config(config_path)

    assert loaded == expected


def test_load_config_prefers_server_over_cloud(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'email = "a@b.com"\n'
        'token = "tkn"\n'
        'server = "us.boox.com"\n'
        'cloud = "eur.boox.com"\n'
    )

    config = load_config(config_path)

    assert config.cloud == "us.boox.com"


def test_save_config_writes_server_and_cloud_alias(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    save_config(
        AppConfig(email="a@b.com", token="tkn", cloud="us.boox.com"),
        config_path,
    )

    raw = config_path.read_text()

    assert 'server = "us.boox.com"' in raw
    assert 'cloud = "us.boox.com"' in raw


def test_load_config_reads_mobile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'mobile = "13800138000"\n'
        'token = "tkn"\n'
        'cloud = "eur.boox.com"\n'
    )

    config = load_config(config_path)

    assert config.mobile == "13800138000"


def test_save_config_writes_mobile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    save_config(
        AppConfig(email="a@b.com", mobile="13800138000", token="tkn", cloud="us.boox.com"),
        config_path,
    )

    raw = config_path.read_text()

    assert 'mobile = "13800138000"' in raw


def test_load_config_invalid_toml_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('email = "a@b.com"\nserver = "send2boox.com"\nbad = [\n')

    with pytest.raises(ConfigError):
        load_config(config_path)

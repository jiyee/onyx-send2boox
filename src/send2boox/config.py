"""Configuration loading and saving."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    _toml_module: Any = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    _toml_module = importlib.import_module("tomli")

from .exceptions import ConfigError

DEFAULT_CLOUD = "send2boox.com"


@dataclass(slots=True)
class AppConfig:
    """Application configuration loaded from TOML file."""

    email: str = ""
    mobile: str = ""
    token: str = ""
    cloud: str = DEFAULT_CLOUD


def load_config(path: str | Path = "config.toml") -> AppConfig:
    """Load config from a TOML file."""

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}. "
            "Create it from config.example.toml."
        )

    try:
        with config_path.open("rb") as config_file:
            payload = _toml_module.load(config_file)
    except _toml_module.TOMLDecodeError as exc:
        raise ConfigError(f"Config file {config_path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read config file {config_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigError(f"Config file {config_path} must contain a TOML table at root.")

    server = _as_str(payload.get("server"))
    cloud = _as_str(payload.get("cloud"))
    resolved_cloud = server or cloud or DEFAULT_CLOUD

    return AppConfig(
        email=_as_str(payload.get("email")),
        mobile=_as_str(payload.get("mobile")),
        token=_as_str(payload.get("token")),
        cloud=resolved_cloud,
    )


def save_config(config: AppConfig, path: str | Path = "config.toml") -> None:
    """Persist config into a TOML file."""

    config_path = Path(path)
    cloud = (config.cloud or DEFAULT_CLOUD).strip() or DEFAULT_CLOUD
    payload = {
        "email": config.email,
        "mobile": config.mobile,
        "token": config.token,
        "server": cloud,
        "cloud": cloud,
    }
    lines = [f"{key} = {_to_toml_str(value)}" for key, value in payload.items()]
    serialized = "\n".join(lines) + "\n"

    try:
        config_path.write_text(serialized, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Failed to write config file {config_path}: {exc}") from exc


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _to_toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)

from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xmuoj_pilot.config import AppConfig, SessionData, get_config_dir


class ConfigStorage:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or get_config_dir()
        self.config_path = self.config_dir / "config.json"
        self._config = self._load()

    @property
    def config(self) -> AppConfig:
        return self._config

    def _load(self) -> AppConfig:
        if not self.config_path.exists():
            return AppConfig()

        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            return AppConfig.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            return AppConfig()

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def update(self, **values: Any) -> AppConfig:
        self._config = self._config.model_copy(update=values)
        self.save()
        return self._config


class SessionStorage:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or get_config_dir()
        self.session_path = self.config_dir / "session.json"
        self._session = self._load()

    @property
    def session(self) -> SessionData:
        return self._session

    def _load(self) -> SessionData:
        if not self.session_path.exists():
            return SessionData()

        try:
            raw = json.loads(self.session_path.read_text(encoding="utf-8"))
            return SessionData.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            return SessionData()

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(
            json.dumps(self._session.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def clear(self) -> None:
        self._session = SessionData()
        if self.session_path.exists():
            self.session_path.unlink()

    def has_session(self) -> bool:
        return bool(self._session.cookies)

    def update_cookies(self, cookies: dict[str, str]) -> None:
        if not cookies:
            return
        merged = dict(self._session.cookies)
        merged.update(cookies)
        csrf_token = self._find_csrf_token(cookies) or self._find_csrf_token(merged)
        self._session = self._session.model_copy(update={"cookies": merged, "csrf_token": csrf_token})
        self.save()

    def set_csrf_token(self, token: str) -> None:
        if token and token != self._session.csrf_token:
            self._session = self._session.model_copy(update={"csrf_token": token})
            self.save()

    def ensure_csrf_token(self) -> str:
        token = self._session.csrf_token or self._find_csrf_token(self._session.cookies)
        if not token:
            alphabet = string.ascii_letters + string.digits
            token = "".join(secrets.choice(alphabet) for _ in range(64))
        cookies = dict(self._session.cookies)
        cookies["csrftoken"] = token
        self._session = self._session.model_copy(update={"cookies": cookies, "csrf_token": token})
        self.save()
        return token

    def mark_login(self) -> None:
        self._session = self._session.model_copy(
            update={"last_login_at": datetime.now(timezone.utc).isoformat()}
        )
        self.save()

    @staticmethod
    def _find_csrf_token(cookies: dict[str, str]) -> str:
        for name in ("csrftoken", "csrf_token", "csrf", "XSRF-TOKEN"):
            if name in cookies:
                return cookies[name]
        return ""

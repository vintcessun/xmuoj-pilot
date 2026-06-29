from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


DEFAULT_BASE_URL = "https://xmuoj.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36 XMUOJ-Pilot/0.1"
)


class AIConfig(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"


class AppConfig(BaseModel):
    base_url: str = DEFAULT_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    debug: bool = False
    verify_ssl: bool = False
    current_contest_id: int | None = None
    current_contest_title: str = ""
    contest_passwords: dict[str, str] = Field(default_factory=dict)
    ai: AIConfig | None = None
    # AC 参考代码库的远程基址（如 GitHub Pages），用于做题时拉取已 AC 代码作参考。
    ac_library_url: str | None = "https://vintcessun.github.io/xmuoj-pilot"


class SessionData(BaseModel):
    base_url: str = DEFAULT_BASE_URL
    cookies: dict[str, str] = Field(default_factory=dict)
    csrf_token: str = ""
    user_agent: str = DEFAULT_USER_AGENT
    last_login_at: str = ""


def get_config_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "xmuoj-pilot"

    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "xmuoj-pilot"

    return Path.home() / ".config" / "xmuoj-pilot"

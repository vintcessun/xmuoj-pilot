from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from xmuoj_pilot.config import DEFAULT_BASE_URL, DEFAULT_USER_AGENT
from xmuoj_pilot.storage import SessionStorage
from xmuoj_pilot.ui.console import console


@dataclass(slots=True)
class APIResponse:
    status_code: int
    headers: dict[str, str]
    data: Any
    text: str
    url: str
    cookies_updated: bool = False
    csrf_updated: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class BaseAPIClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        storage: SessionStorage | None = None,
        *,
        debug: bool = False,
        timeout: float = 20.0,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.storage = storage or SessionStorage()
        self.debug = debug
        self.timeout = timeout
        self.verify_ssl = verify_ssl

    def build_headers(self, referrer: str | None = None) -> dict[str, str]:
        csrf_token = self.storage.session.csrf_token
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "content-type": "application/json;charset=UTF-8",
            "user-agent": self.storage.session.user_agent or DEFAULT_USER_AGENT,
            "origin": self.base_url,
            "referer": referrer or f"{self.base_url}/",
        }
        if csrf_token:
            headers["x-csrftoken"] = csrf_token
        return headers

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        referrer: str | None = None,
        require_json: bool = True,
        raise_for_status: bool = True,
    ) -> APIResponse:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD", "OPTIONS"}:
            self.storage.ensure_csrf_token()

        request_headers = self.build_headers(referrer=referrer)
        if headers:
            request_headers.update(headers)

        before_cookies = dict(self.storage.session.cookies)
        before_csrf = self.storage.session.csrf_token

        async with httpx.AsyncClient(
            base_url=self.base_url,
            cookies=before_cookies,
            follow_redirects=True,
            timeout=httpx.Timeout(self.timeout),
            verify=self.verify_ssl,
        ) as client:
            try:
                response = await client.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=request_headers,
                )
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"请求超时：{method.upper()} {url}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"网络请求失败：{method.upper()} {url}: {exc}") from exc

        response_cookies = {name: value for name, value in response.cookies.items()}
        if response_cookies:
            self.storage.update_cookies(response_cookies)

        csrf_from_cookie = self.storage.session.csrf_token
        csrf_from_header = response.headers.get("x-csrftoken") or response.headers.get("x-csrf-token")
        if csrf_from_header:
            self.storage.set_csrf_token(csrf_from_header)
        elif csrf_from_cookie:
            self.storage.set_csrf_token(csrf_from_cookie)

        text = response.text
        parsed: Any
        try:
            parsed = response.json()
        except ValueError:
            parsed = None
            if require_json and response.status_code < 400:
                console.print("[yellow]响应不是 JSON，已返回文本摘要。[/yellow]")

        api_response = APIResponse(
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items()},
            data=parsed if parsed is not None else text,
            text=text,
            url=str(response.url),
            cookies_updated=before_cookies != self.storage.session.cookies,
            csrf_updated=before_csrf != self.storage.session.csrf_token,
        )

        if self.debug:
            self._print_debug(method.upper(), api_response)

        if response.status_code in (401, 403):
            console.print(
                "[red]请求被拒绝，可能是登录状态过期或权限不足。请尝试重新登录。[/red]"
            )

        if raise_for_status and response.status_code >= 400:
            summary = self._text_summary(api_response.text)
            raise RuntimeError(f"HTTP {response.status_code}: {summary}")

        return api_response

    async def get(self, url: str, **kwargs: Any) -> APIResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> APIResponse:
        return await self.request("POST", url, **kwargs)

    def _print_debug(self, method: str, response: APIResponse) -> None:
        console.print(f"[dim]{method} {response.url} -> {response.status_code}[/dim]")
        console.print(f"[dim]{self._text_summary(response.text)}[/dim]")

    @staticmethod
    def _text_summary(text: str, limit: int = 500) -> str:
        normalized = " ".join(text.split())
        return normalized[:limit] + ("..." if len(normalized) > limit else "")

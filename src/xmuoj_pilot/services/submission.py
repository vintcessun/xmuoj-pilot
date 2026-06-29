from __future__ import annotations

import asyncio
from typing import Any

from xmuoj_pilot.client.xmuoj import XMUOJClient
from xmuoj_pilot.ui.console import console
from xmuoj_pilot.ui.console import extract_items, unwrap_data


class SubmissionService:
    def __init__(self, client: XMUOJClient) -> None:
        self.client = client

    async def submission_exists(self, contest_id: int, internal_problem_id: int) -> Any:
        return (await self.client.submission_exists(contest_id, internal_problem_id)).data

    async def list_contest_submissions(
        self,
        contest_id: int,
        display_problem_id: str,
        *,
        myself: int = 1,
        limit: int = 12,
        offset: int = 0,
    ) -> Any:
        return (
            await self.client.contest_submissions(
                contest_id,
                display_problem_id,
                myself=myself,
                limit=limit,
                offset=offset,
            )
        ).data

    async def fetch_accepted_code(
        self,
        contest_id: int,
        display_problem_id: str,
        *,
        max_pages: int = 3,
        page_size: int = 12,
    ) -> dict[str, Any] | None:
        """查找该题“我自己”的满分/AC 提交并返回其代码与元信息。

        返回 dict：{submission_id, code, language, score, result, create_time}；
        找不到任何满分提交时返回 None。
        """
        best: dict[str, Any] | None = None
        best_score = -1.0
        for page in range(max_pages):
            try:
                data = await self.list_contest_submissions(
                    contest_id,
                    display_problem_id,
                    limit=page_size,
                    offset=page * page_size,
                )
            except RuntimeError:
                break
            items = extract_items(data, preferred_keys=("submissions", "data"))
            if not items:
                break
            for item in items:
                if not _item_accepted(item):
                    continue
                score = _item_score(item)
                if score > best_score:
                    best_score = score
                    best = item
            if len(items) < page_size:
                break

        if best is None:
            return None

        submission_id = str(best.get("id") or best.get("submission_id") or "")
        code = _item_code(best)
        if not code and submission_id:
            try:
                detail = await self.get_submission(submission_id)
            except RuntimeError:
                detail = None
            code = _item_code(unwrap_data(detail)) if detail is not None else ""
        if not code:
            return None
        return {
            "submission_id": submission_id,
            "code": code,
            "language": str(best.get("language") or best.get("lang") or ""),
            "score": best_score if best_score >= 0 else None,
            "result": best.get("result"),
            "create_time": best.get("create_time") or best.get("created_at") or "",
        }

    async def submit_code(
        self,
        contest_id: int,
        internal_problem_id: int,
        language: str,
        code: str,
    ) -> Any:
        return (
            await self.client.submit_code(
                contest_id=contest_id,
                internal_problem_id=internal_problem_id,
                language=language,
                code=code,
            )
        ).data

    async def get_submission(self, submission_id: str) -> Any:
        return (await self.client.submission(submission_id)).data

    async def get_submission_with_retry(
        self,
        submission_id: str,
        *,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
    ) -> Any:
        last_error: RuntimeError | None = None
        for retry in range(max_retries + 1):
            try:
                return await self.get_submission(submission_id)
            except RuntimeError as exc:
                last_error = exc
                if retry >= max_retries:
                    break
                delay = min(max_delay, base_delay * (2**retry))
                console.print(
                    f"[yellow]获取提交结果失败，{delay:.1f}s 后重试 "
                    f"({retry + 1}/{max_retries})：{exc}[/yellow]"
                )
                await asyncio.sleep(delay)
        return {
            "error": "network_retry_exhausted",
            "data": str(last_error) if last_error else "unknown error",
            "submission_id": submission_id,
        }

    async def wait_for_result(
        self,
        submission_id: str,
        *,
        interval_seconds: float = 1.5,
        max_attempts: int = 30,
    ) -> Any:
        latest: Any = None
        for _ in range(max_attempts):
            latest = await self.get_submission_with_retry(submission_id)
            if isinstance(latest, dict) and latest.get("error") == "network_retry_exhausted":
                return latest
            if not _is_pending(latest):
                return latest
            await asyncio.sleep(interval_seconds)
        return latest


def _item_score(item: dict[str, Any]) -> float:
    statistic = item.get("statistic_info")
    if isinstance(statistic, dict) and statistic.get("score") is not None:
        try:
            return float(statistic["score"])
        except (TypeError, ValueError):
            pass
    for key in ("score", "total_score"):
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return -1.0


def _item_accepted(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    # XMUOJ：result == 0 通常代表 Accepted
    if item.get("result") == 0:
        return True
    score = _item_score(item)
    total = item.get("total_score") or 100
    try:
        if score >= float(total):
            return True
    except (TypeError, ValueError):
        pass
    status = str(item.get("status") or item.get("result") or "").lower()
    return status in {"accepted", "ac", "通过", "满分"}


def _item_code(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("code", "source_code", "sourceCode", "source"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _is_pending(data: Any) -> bool:
    payload = data.get("data") if isinstance(data, dict) else data
    if isinstance(payload, dict):
        result = payload.get("result")
        statistic_info = payload.get("statistic_info")
        info = payload.get("info")
        if result == 7:
            return True
        if statistic_info == {} and info == {}:
            return True
        if isinstance(statistic_info, dict) and "score" in statistic_info:
            return False

    text = str(data).lower()
    pending_words = ("pending", "judging", "queue", "running", "compiling", "waiting")
    accepted_terminal = (
        "accepted",
        "wrong answer",
        "compilation error",
        "runtime error",
        "time limit",
        "memory limit",
        "presentation error",
    )
    if any(word in text for word in accepted_terminal):
        return False
    return any(word in text for word in pending_words)

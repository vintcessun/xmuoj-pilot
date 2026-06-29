from __future__ import annotations

from typing import Any

from xmuoj_pilot.client.xmuoj import XMUOJClient


class ContestService:
    def __init__(self, client: XMUOJClient) -> None:
        self.client = client

    async def list_contests(self, offset: int = 0, limit: int = 15) -> Any:
        return (await self.client.contests(offset=offset, limit=limit)).data

    async def get_contest(self, contest_id: int) -> Any:
        return (await self.client.contest(contest_id)).data

    async def check_access(self, contest_id: int) -> Any:
        return (await self.client.contest_access(contest_id)).data

    async def submit_password(self, contest_id: int, password: str) -> Any:
        return (await self.client.submit_contest_password(contest_id, password)).data


from __future__ import annotations

from typing import Any

from xmuoj_pilot.client.xmuoj import XMUOJClient


class ProblemService:
    def __init__(self, client: XMUOJClient) -> None:
        self.client = client

    async def list_problems(self, contest_id: int) -> Any:
        return (await self.client.contest_problems(contest_id)).data

    async def get_problem(self, contest_id: int, display_problem_id: str) -> Any:
        return (await self.client.contest_problem(contest_id, display_problem_id)).data


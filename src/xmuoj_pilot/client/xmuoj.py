from __future__ import annotations

from typing import Any

from xmuoj_pilot.client.base import APIResponse, BaseAPIClient


class XMUOJClient(BaseAPIClient):
    async def warmup(self) -> APIResponse:
        return await self.get("/", require_json=False)

    async def login(self, username: str, password: str) -> APIResponse:
        return await self.post("/api/login", json={"username": username, "password": password})

    async def contests(self, offset: int = 0, limit: int = 15) -> APIResponse:
        return await self.get("/api/contests", params={"offset": offset, "limit": limit})

    async def contest(self, contest_id: int) -> APIResponse:
        return await self.get("/api/contest", params={"id": contest_id})

    async def contest_access(self, contest_id: int) -> APIResponse:
        return await self.get("/api/contest/access", params={"contest_id": contest_id})

    async def submit_contest_password(self, contest_id: int, password: str) -> APIResponse:
        return await self.post(
            "/api/contest/password",
            json={"contest_id": contest_id, "password": password},
        )

    async def contest_problems(self, contest_id: int) -> APIResponse:
        return await self.get("/api/contest/problem", params={"contest_id": contest_id})

    async def contest_problem(self, contest_id: int, display_problem_id: str) -> APIResponse:
        return await self.get(
            "/api/contest/problem",
            params={"contest_id": contest_id, "problem_id": display_problem_id},
        )

    async def submission_exists(self, contest_id: int, internal_problem_id: int) -> APIResponse:
        return await self.get(
            "/api/submission_exists",
            params={"problem_id": internal_problem_id, "contest_id": contest_id},
        )

    async def submit_code(
        self,
        contest_id: int,
        internal_problem_id: int,
        language: str,
        code: str,
    ) -> APIResponse:
        payload: dict[str, Any] = {
            "problem_id": internal_problem_id,
            "language": language,
            "code": code,
            "contest_id": contest_id,
        }
        return await self.post("/api/submission", json=payload)

    async def submission(self, submission_id: str) -> APIResponse:
        return await self.get("/api/submission", params={"id": submission_id})

    async def contest_submissions(
        self,
        contest_id: int,
        display_problem_id: str,
        *,
        myself: int = 1,
        limit: int = 12,
        offset: int = 0,
    ) -> APIResponse:
        return await self.get(
            "/api/contest_submissions",
            params={
                "myself": myself,
                "contest_id": contest_id,
                "problem_id": display_problem_id,
                "limit": limit,
                "offset": offset,
            },
        )


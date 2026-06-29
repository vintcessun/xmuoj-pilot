from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Problem(BaseModel):
    internal_id: int | str | None = None
    display_id: str = ""
    title: str = ""
    score: str = ""
    status: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Problem":
        internal_id = raw.get("id") or raw.get("problem_id") or raw.get("problemId")
        display_id = (
            raw.get("_id")
            or raw.get("display_id")
            or raw.get("displayId")
            or raw.get("number")
            or raw.get("code")
        )
        return cls(
            internal_id=internal_id,
            display_id=str(display_id or internal_id or ""),
            title=str(raw.get("title") or raw.get("name") or raw.get("problem_title") or ""),
            score=str(raw.get("score") or raw.get("total_score") or ""),
            status=str(raw.get("status") or raw.get("result") or ""),
            raw=raw,
        )

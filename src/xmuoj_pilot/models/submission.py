from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Submission(BaseModel):
    id: str = ""
    status: str = ""
    verdict: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Submission":
        return cls(
            id=str(raw.get("id") or raw.get("submission_id") or raw.get("submissionId") or ""),
            status=str(raw.get("status") or raw.get("state") or ""),
            verdict=str(raw.get("verdict") or raw.get("result") or raw.get("judge_result") or ""),
            raw=raw,
        )


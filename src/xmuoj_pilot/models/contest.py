from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Contest(BaseModel):
    id: int | str | None = None
    title: str = ""
    start_time: str = ""
    end_time: str = ""
    status: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "Contest":
        return cls(
            id=raw.get("id") or raw.get("contest_id") or raw.get("pk"),
            title=str(raw.get("title") or raw.get("name") or raw.get("contest_name") or ""),
            start_time=str(raw.get("start_time") or raw.get("startTime") or raw.get("start") or ""),
            end_time=str(raw.get("end_time") or raw.get("endTime") or raw.get("end") or ""),
            status=str(raw.get("status") or raw.get("state") or ""),
            raw=raw,
        )


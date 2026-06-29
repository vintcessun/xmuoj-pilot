from __future__ import annotations

from xmuoj_pilot.client.xmuoj import XMUOJClient
from xmuoj_pilot.storage import SessionStorage


class AuthService:
    def __init__(self, client: XMUOJClient, storage: SessionStorage) -> None:
        self.client = client
        self.storage = storage

    async def login(self, username: str, password: str) -> bool:
        try:
            await self.client.warmup()
        except RuntimeError:
            pass

        response = await self.client.login(username, password)
        if not response.ok:
            return False

        verify = await self.client.contests(offset=0, limit=15)
        if verify.ok:
            self.storage.mark_login()
            return True
        return False

    async def ensure_login(self) -> bool:
        if not self.storage.has_session():
            return False
        try:
            response = await self.client.contests(offset=0, limit=1)
        except RuntimeError:
            return False
        return response.ok


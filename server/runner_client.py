from __future__ import annotations

from typing import Any

import httpx


class RunnerUnavailable(RuntimeError):
    pass


class RunnerClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds

    async def _request(self, path: str, payload: dict | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await (client.get(f"{self.base_url}{path}") if payload is None else client.post(f"{self.base_url}{path}", json=payload))
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RunnerUnavailable("코드 실행 서비스를 사용할 수 없습니다. Docker 실행 상태를 확인하세요.") from exc

    async def health(self) -> dict:
        return await self._request("/health")

    async def execute(self, request: dict) -> dict:
        return await self._request("/execute", request)

    async def script(self, request: dict) -> dict:
        return await self._request("/script", request)

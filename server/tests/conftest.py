from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings


class FakeRunner:
    def __init__(self) -> None:
        self.execute_calls: list[dict] = []
        self.script_calls: list[dict] = []
        self.execute_responses: list[dict] = []
        self.script_responses: list[dict] = []

    async def health(self) -> dict:
        return {"status": "ok", "docker_available": True, "detail": "fake"}

    async def execute(self, request: dict) -> dict:
        self.execute_calls.append(request)
        return self.execute_responses.pop(0)

    async def script(self, request: dict) -> dict:
        self.script_calls.append(request)
        return self.script_responses.pop(0)


class FakeAI:
    def __init__(self) -> None:
        self.analysis = None
        self.bundle = None
        self.repair = None
        self.reply = None
        self.calls: list[tuple[str, dict]] = []

    async def analyze(self, payload: dict):
        self.calls.append(("analyze", payload))
        return self.analysis

    async def generate(self, payload: dict):
        self.calls.append(("generate", payload))
        return self.bundle

    async def repair_output_format(self, payload: dict):
        self.calls.append(("format_repair", payload))
        return self.repair

    async def tutor(self, payload: dict):
        self.calls.append(("tutor", payload))
        return self.reply


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
def client(tmp_path: Path, runner: FakeRunner, ai: FakeAI) -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        runner_url="http://runner.invalid",
        openai_api_key="test-key",
        run_jobs_inline=True,
    )
    with TestClient(create_app(settings=settings, runner=runner, ai=ai)) as value:
        yield value

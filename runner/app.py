from __future__ import annotations

import anyio
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from runner.engine import DockerRunner, DockerUnavailable
from runner.models import ExecuteRequest, REQUEST_LIMIT, ScriptRequest


def create_app(service=None) -> FastAPI:
    app = FastAPI(title="LoopCode Runner", docs_url=None, redoc_url=None)
    runner = service or DockerRunner()

    async def body(request: Request) -> bytes:
        content_length = request.headers.get("content-length")
        try:
            declared_size = int(content_length) if content_length else None
        except ValueError:
            declared_size = REQUEST_LIMIT + 1
        if declared_size is not None and declared_size > REQUEST_LIMIT:
            raise HTTPException(status_code=413, detail="요청 크기는 2MiB 이하여야 합니다.")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > REQUEST_LIMIT:
                raise HTTPException(status_code=413, detail="요청 크기는 2MiB 이하여야 합니다.")
            chunks.append(chunk)
        return b"".join(chunks)

    @app.get("/health")
    async def health():
        return await anyio.to_thread.run_sync(runner.health)

    @app.post("/execute")
    async def execute(request: Request):
        try:
            model = ExecuteRequest.model_validate_json(await body(request))
            return await anyio.to_thread.run_sync(runner.execute, model)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="실행 요청 형식이 올바르지 않습니다.") from exc
        except DockerUnavailable as exc:
            raise HTTPException(status_code=503, detail="Docker 실행 서비스를 사용할 수 없습니다.") from exc

    @app.post("/script")
    async def script(request: Request):
        try:
            model = ScriptRequest.model_validate_json(await body(request))
            return await anyio.to_thread.run_sync(runner.script, model)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="스크립트 요청 형식이 올바르지 않습니다.") from exc
        except DockerUnavailable as exc:
            raise HTTPException(status_code=503, detail="Docker 실행 서비스를 사용할 수 없습니다.") from exc

    return app


app = create_app()

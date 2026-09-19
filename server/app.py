from __future__ import annotations

import asyncio
import base64
import binascii
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.ai_client import AIUnavailable, OpenAIClient
from server.config import Settings, get_settings
from server.db import create_database, initialize_database, session_dependency
from server.models import AIUsage, ChatTurn, CodeDraft, Folder, Job, Problem, TestCase, now
from server.runner_client import RunnerClient, RunnerUnavailable
from server.schemas import (
    AIUsagePublic,
    AnalyzeRequest,
    ChatTurnPublic,
    DraftPublic,
    DraftWrite,
    ExpectedCompute,
    ExpectedResult,
    FolderAssignment,
    FolderPublic,
    FolderWrite,
    GenerationJobPublic,
    HealthPublic,
    JobCreate,
    JobPublic,
    ProblemCreate,
    ProblemPublic,
    ProblemSummary,
    ProblemUpdate,
    Signature,
    TestCaseCreate,
    TestCasePublic,
    TestCaseUpdate,
    TutorRequest,
    TutorResponse,
)
from server.services import execute_job, generate_job
from server.templates import templates_for
from server.validation import DomainValidationError, require_all_true, typed_equal, validate_args, validate_case


SUPPORTED_LANGUAGES = {"python", "cpp", "java", "javascript"}


def _problem_or_404(db: Session, problem_id: str) -> Problem:
    problem = db.get(Problem, problem_id)
    if not problem:
        raise HTTPException(404, "문제를 찾을 수 없습니다.")
    return problem


def _folder_or_404(db: Session, folder_id: str) -> Folder:
    folder = db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "폴더를 찾을 수 없습니다.")
    return folder


def _folder_public(db: Session, folder: Folder) -> FolderPublic:
    count = db.scalar(select(func.count(Problem.id)).where(Problem.folder_id == folder.id)) or 0
    return FolderPublic(id=folder.id, name=folder.name, problem_count=count)


def _folder_conflict() -> HTTPException:
    return HTTPException(409, "같은 이름의 폴더가 이미 있습니다.")


def _ensure_editable(problem: Problem) -> None:
    if problem.status == "generating":
        raise HTTPException(409, "테스트 생성 중에는 문제를 수정할 수 없습니다.")


def _visible_tests(problem: Problem) -> list[TestCase]:
    return sorted((item for item in problem.tests if item.kind in {"public", "user"}), key=lambda item: (item.position, item.id))


def _test_public(item: TestCase) -> TestCasePublic:
    return TestCasePublic(
        id=item.id,
        kind=item.kind,
        position=item.position,
        args=item.args,
        expected=item.expected,
        suite_version=item.suite_version,
    )


def _solved_problem_ids(db: Session, problem_ids: list[str] | None = None) -> set[str]:
    if problem_ids is not None and not problem_ids:
        return set()
    statement = select(Job.problem_id).where(
        Job.kind == "execution",
        Job.mode == "submit",
        Job.status == "completed",
        func.json_type(Job.summary, "$.all_passed") == "true",
        func.json_type(Job.summary, "$.total") == "integer",
        func.json_extract(Job.summary, "$.total") > 0,
    )
    if problem_ids is not None:
        statement = statement.where(Job.problem_id.in_(problem_ids))
    return set(db.scalars(statement.distinct()).all())


def _problem_summary(problem: Problem, *, is_solved: bool = False) -> ProblemSummary:
    return ProblemSummary(
        id=problem.id,
        title=problem.title,
        status=problem.status,
        test_revision=problem.test_revision,
        updated_at=problem.updated_at,
        is_solved=is_solved,
        folder_id=problem.folder_id,
    )


def _problem_public(problem: Problem, *, is_solved: bool = False) -> ProblemPublic:
    return ProblemPublic(
        **_problem_summary(problem, is_solved=is_solved).model_dump(),
        statement=problem.statement,
        example_explanation=problem.example_explanation,
        constraints=problem.constraints,
        signature=problem.signature,
        templates=problem.templates,
        time_limit_ms=problem.time_limit_ms,
        memory_limit_mb=problem.memory_limit_mb,
        tests=[_test_public(item) for item in _visible_tests(problem)],
        latest_generation_job_id=problem.latest_generation_job_id,
        generation_error=problem.generation_error,
        output_format=(problem.generation_meta or {}).get("output_format"),
    )


def _job_public(job: Job) -> JobPublic:
    return JobPublic(
        id=job.id,
        problem_id=job.problem_id,
        mode=job.mode,
        language=job.language,
        source=job.source,
        status=job.status,
        test_revision=job.test_revision,
        results=job.results or [],
        summary=job.summary,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _generation_public(job: Job) -> GenerationJobPublic:
    return GenerationJobPublic(
        id=job.id,
        problem_id=job.problem_id,
        status=job.status,
        test_revision=job.test_revision,
        summary=job.summary,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _domain_http(exc: DomainValidationError) -> HTTPException:
    return HTTPException(422, str(exc))


def _image_matches_mime(data: bytes, mime: str) -> bool:
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


class GenerationRequest(BaseModel):
    seed: int = Field(default=20260917, ge=0, le=2**31 - 1)


def create_app(*, settings: Settings | None = None, runner=None, ai=None) -> FastAPI:
    settings = settings or get_settings()
    engine, session_factory = create_database(settings.database_url)
    runner = runner or RunnerClient(settings.runner_url, settings.runner_timeout_seconds)
    ai = ai or OpenAIClient(settings.openai_api_key, settings.openai_generation_model, settings.openai_tutor_model)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        initialize_database(engine, session_factory)
        application.state.tasks = set()
        application.state.worker_lock = asyncio.Lock()
        yield
        for task in list(application.state.tasks):
            task.cancel()
        engine.dispose()

    app = FastAPI(
        title="LoopCode API",
        version="0.1.0",
        description="루프코드 로컬 코딩 연습 백엔드",
        lifespan=lifespan,
    )
    get_db = session_dependency(session_factory)

    async def validate_constraints(problem: Problem, args: list) -> None:
        if problem.status != "ready":
            return
        if not problem.validator_source:
            raise HTTPException(409, "저장된 제약 검증기가 없습니다. 테스트를 다시 생성하세요.")
        try:
            result = await runner.script(
                {
                    "source": problem.validator_source,
                    "payload": [args],
                    "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 1024},
                }
            )
        except RunnerUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if result.get("status") != "ok":
            raise HTTPException(409, "저장된 제약 검증기를 실행하지 못했습니다. 테스트를 다시 생성하세요.")
        try:
            require_all_true(result.get("value"), 1)
        except DomainValidationError as exc:
            raise _domain_http(exc)

    def claim_test_revision(db: Session, problem: Problem) -> int:
        next_revision = problem.test_revision + 1
        result = db.execute(
            update(Problem)
            .where(
                Problem.id == problem.id,
                Problem.test_revision == problem.test_revision,
                Problem.status == problem.status,
                Problem.status != "generating",
            )
            .values(test_revision=next_revision, updated_at=now())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "문제가 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도하세요.")
        return next_revision

    def schedule(coro):
        async def run_serially():
            async with app.state.worker_lock:
                await coro

        task = asyncio.create_task(run_serially())
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)

    @app.get("/api/health", response_model=HealthPublic, tags=["system"])
    async def health() -> HealthPublic:
        available = False
        detail = "코드 실행 서비스에 연결할 수 없습니다."
        try:
            runner_health = await runner.health()
            available = runner_health.get("status") == "ok" and bool(runner_health.get("docker_available"))
            detail = str(runner_health.get("detail") or ("정상" if available else detail))
        except RunnerUnavailable:
            pass
        except Exception:
            pass
        return HealthPublic(
            status="ok" if available else "degraded",
            database="ok",
            runner_configured=bool(settings.runner_url),
            runner_available=available,
            ai_configured=bool(settings.openai_api_key),
            detail=detail,
        )

    @app.get("/api/problems", response_model=list[ProblemSummary], tags=["problems"])
    def list_problems(db: Session = Depends(get_db)):
        problems = db.scalars(select(Problem).order_by(Problem.updated_at.desc())).all()
        solved = _solved_problem_ids(db, [item.id for item in problems])
        return [_problem_summary(item, is_solved=item.id in solved) for item in problems]

    @app.get("/api/folders", response_model=list[FolderPublic], tags=["folders"])
    def list_folders(db: Session = Depends(get_db)):
        rows = db.execute(
            select(Folder, func.count(Problem.id))
            .outerjoin(Problem, Problem.folder_id == Folder.id)
            .group_by(Folder.id)
            .order_by(Folder.name_key, Folder.id)
        ).all()
        return [FolderPublic(id=folder.id, name=folder.name, problem_count=count) for folder, count in rows]

    @app.post("/api/folders", response_model=FolderPublic, status_code=201, tags=["folders"])
    def create_folder(payload: FolderWrite, db: Session = Depends(get_db)):
        name_key = payload.name.casefold()
        if db.scalar(select(Folder.id).where(Folder.name_key == name_key)):
            raise _folder_conflict()
        folder = Folder(name=payload.name, name_key=name_key)
        db.add(folder)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise _folder_conflict() from exc
        db.refresh(folder)
        return FolderPublic(id=folder.id, name=folder.name, problem_count=0)

    @app.patch("/api/folders/{folder_id}", response_model=FolderPublic, tags=["folders"])
    def update_folder(folder_id: str, payload: FolderWrite, db: Session = Depends(get_db)):
        folder = _folder_or_404(db, folder_id)
        name_key = payload.name.casefold()
        duplicate = db.scalar(
            select(Folder.id).where(Folder.name_key == name_key, Folder.id != folder.id)
        )
        if duplicate:
            raise _folder_conflict()
        folder.name = payload.name
        folder.name_key = name_key
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise _folder_conflict() from exc
        db.refresh(folder)
        return _folder_public(db, folder)

    @app.delete("/api/folders/{folder_id}", status_code=204, tags=["folders"])
    def delete_folder(folder_id: str, db: Session = Depends(get_db)):
        folder = _folder_or_404(db, folder_id)
        db.delete(folder)
        db.commit()
        return Response(status_code=204)

    @app.post("/api/problems", response_model=ProblemPublic, status_code=201, tags=["problems"])
    def create_problem(payload: ProblemCreate, db: Session = Depends(get_db)):
        if payload.folder_id is not None:
            _folder_or_404(db, payload.folder_id)
        signature = payload.signature
        problem = Problem(
            title=payload.title,
            folder_id=payload.folder_id,
            statement=payload.statement,
            example_explanation=payload.example_explanation,
            constraints=payload.constraints,
            signature=signature.model_dump(),
            templates=templates_for(signature),
            source_text=payload.source_text,
            status="draft",
        )
        db.add(problem)
        db.commit()
        db.refresh(problem)
        return _problem_public(problem)

    @app.post("/api/problems/analyze", response_model=ProblemPublic, status_code=201, tags=["ai"])
    async def analyze_new_problem(payload: AnalyzeRequest, db: Session = Depends(get_db)):
        if not settings.openai_api_key:
            raise HTTPException(503, "OPENAI_API_KEY를 설정한 뒤 다시 시도하세요.")
        if payload.folder_id is not None:
            _folder_or_404(db, payload.folder_id)
            db.commit()
        image = None
        if payload.image_base64:
            try:
                image = base64.b64decode(payload.image_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(422, "유효한 base64 이미지가 아닙니다.") from exc
            if len(image) > 10 * 1024 * 1024:
                raise HTTPException(413, "이미지는 10MB 이하여야 합니다.")
            if not _image_matches_mime(image, payload.image_mime):
                raise HTTPException(422, "이미지 내용과 파일 형식이 일치하지 않습니다.")
        try:
            result = await ai.analyze({"text": payload.text, "image": image, "image_mime": payload.image_mime})
            signature_raw = result.get("signature_json", result.get("signature"))
            examples_raw = result.get("examples_json", result.get("examples"))
            signature = Signature.model_validate(json.loads(signature_raw) if isinstance(signature_raw, str) else signature_raw)
            examples = json.loads(examples_raw) if isinstance(examples_raw, str) else examples_raw
            parsed_examples = [TestCaseCreate.model_validate(item) for item in examples]
            for example in parsed_examples:
                validate_case(example.args, example.expected, signature)
            example_explanation = result.get("example_explanation", "")
            if not isinstance(example_explanation, str) or len(example_explanation) > 100_000:
                raise ValueError("입출력 예 설명이 올바르지 않습니다.")
        except AIUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except (ValueError, TypeError, json.JSONDecodeError, DomainValidationError) as exc:
            raise HTTPException(422, "AI 분석 결과의 타입 또는 예제가 올바르지 않습니다.") from exc
        db.expire_all()
        folder_id = payload.folder_id
        if folder_id is not None and db.get(Folder, folder_id) is None:
            folder_id = None

        def persist_analyzed_problem(selected_folder_id: str | None) -> Problem:
            saved = Problem(
                title=result["title"],
                folder_id=selected_folder_id,
                statement=result["statement"],
                example_explanation=example_explanation,
                constraints=result["constraints"],
                signature=signature.model_dump(),
                templates=templates_for(signature),
                source_text=payload.text,
                source_image=image,
                source_image_mime=payload.image_mime,
                status="analyzed",
                original_examples=[{"args": example.args, "expected": example.expected} for example in parsed_examples],
            )
            db.add(saved)
            db.flush()
            for position, example in enumerate(parsed_examples):
                db.add(TestCase(problem_id=saved.id, kind="public", position=position, args=example.args, expected=example.expected, suite_version=1, provenance={"source": "analysis"}))
            db.add(AIUsage(problem_id=saved.id, operation="analyze", model=result["model"], input_tokens=result["input_tokens"], output_tokens=result["output_tokens"]))
            db.commit()
            db.refresh(saved)
            return saved

        try:
            problem = persist_analyzed_problem(folder_id)
        except IntegrityError as exc:
            db.rollback()
            if folder_id is None or db.get(Folder, folder_id) is not None:
                raise HTTPException(409, "폴더 분류 중 충돌이 발생했습니다. 다시 시도하세요.") from exc
            problem = persist_analyzed_problem(None)
        return _problem_public(problem)

    @app.get("/api/problems/{problem_id}", response_model=ProblemPublic, tags=["problems"])
    def get_problem(problem_id: str, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        return _problem_public(problem, is_solved=problem.id in _solved_problem_ids(db, [problem.id]))

    @app.put("/api/problems/{problem_id}/folder", response_model=ProblemPublic, tags=["folders"])
    def move_problem_to_folder(
        problem_id: str, payload: FolderAssignment, db: Session = Depends(get_db)
    ):
        problem = _problem_or_404(db, problem_id)
        if payload.folder_id is not None:
            _folder_or_404(db, payload.folder_id)
        problem.folder_id = payload.folder_id
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(404, "폴더를 찾을 수 없습니다.") from exc
        db.refresh(problem)
        return _problem_public(
            problem, is_solved=problem.id in _solved_problem_ids(db, [problem.id])
        )

    @app.patch("/api/problems/{problem_id}", response_model=ProblemPublic, tags=["problems"])
    def update_problem(problem_id: str, payload: ProblemUpdate, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        _ensure_editable(problem)
        updates = payload.model_dump(exclude_unset=True)
        semantic = any(
            key in updates and updates[key] != getattr(problem, key)
            for key in {"statement", "example_explanation", "constraints", "signature"}
        )
        values = dict(updates)
        signature = None
        if "signature" in values:
            signature = Signature.model_validate(values["signature"])
            values["signature"] = signature.model_dump()
            values["templates"] = templates_for(signature)
        if semantic:
            values.update(
                status="draft",
                reference_source=None,
                brute_source=None,
                validator_source=None,
                generator_source=None,
                generation_meta=None,
                test_revision=problem.test_revision + 1,
            )
        values["updated_at"] = now()
        result = db.execute(
            update(Problem)
            .where(
                Problem.id == problem.id,
                Problem.test_revision == problem.test_revision,
                Problem.status == problem.status,
                Problem.status != "generating",
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "문제가 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도하세요.")
        db.commit()
        db.expire_all()
        problem = _problem_or_404(db, problem_id)
        return _problem_public(problem, is_solved=problem.id in _solved_problem_ids(db, [problem.id]))

    @app.delete("/api/problems/{problem_id}", status_code=204, tags=["problems"])
    def delete_problem(problem_id: str, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        _ensure_editable(problem)
        removed = db.execute(
            delete(Problem).where(
                Problem.id == problem.id,
                Problem.test_revision == problem.test_revision,
                Problem.status == problem.status,
                Problem.status != "generating",
            )
        )
        if removed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "문제가 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도하세요.")
        db.commit()
        return Response(status_code=204)

    @app.post("/api/problems/{problem_id}/tests", response_model=TestCasePublic, status_code=201, tags=["tests"])
    async def create_test(problem_id: str, payload: TestCaseCreate, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        _ensure_editable(problem)
        try:
            validate_case(payload.args, payload.expected, Signature.model_validate(problem.signature))
        except DomainValidationError as exc:
            raise _domain_http(exc)
        await validate_constraints(problem, payload.args)
        next_revision = claim_test_revision(db, problem)
        position = max((item.position for item in problem.tests), default=-1) + 1
        provenance = {"source": "manual-public" if payload.kind == "public" else "manual"}
        item = TestCase(problem_id=problem.id, kind=payload.kind, position=position, args=payload.args, expected=payload.expected, suite_version=next_revision, provenance=provenance)
        db.add(item)
        db.commit()
        db.refresh(item)
        return _test_public(item)

    @app.patch("/api/problems/{problem_id}/tests/{test_id}", response_model=TestCasePublic, tags=["tests"])
    async def update_test(problem_id: str, test_id: str, payload: TestCaseUpdate, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        _ensure_editable(problem)
        item = db.get(TestCase, test_id)
        if not item or item.problem_id != problem.id or item.kind == "hidden":
            raise HTTPException(404, "테스트를 찾을 수 없습니다.")
        args = payload.args if payload.args is not None else item.args
        expected = payload.expected if "expected" in payload.model_fields_set else item.expected
        try:
            validate_case(args, expected, Signature.model_validate(problem.signature))
        except DomainValidationError as exc:
            raise _domain_http(exc)
        await validate_constraints(problem, args)
        next_revision = claim_test_revision(db, problem)
        item.args = args
        item.expected = expected
        item.suite_version = next_revision
        db.commit()
        db.refresh(item)
        return _test_public(item)

    @app.delete("/api/problems/{problem_id}/tests/{test_id}", status_code=204, tags=["tests"])
    def delete_test(problem_id: str, test_id: str, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        _ensure_editable(problem)
        item = db.get(TestCase, test_id)
        if not item or item.problem_id != problem.id or item.kind == "hidden":
            raise HTTPException(404, "테스트를 찾을 수 없습니다.")
        claim_test_revision(db, problem)
        db.delete(item)
        db.commit()
        return Response(status_code=204)

    @app.post("/api/problems/{problem_id}/tests/expected", response_model=ExpectedResult, tags=["tests"])
    async def compute_expected(problem_id: str, payload: ExpectedCompute, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        if not problem.reference_source or not problem.validator_source:
            raise HTTPException(409, "검증된 기준 풀이가 없습니다. 테스트 생성을 먼저 완료하세요.")
        signature = Signature.model_validate(problem.signature)
        try:
            validate_args(payload.args, signature)
            validation = await runner.script({"source": problem.validator_source, "payload": [payload.args], "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 1024}})
            if validation.get("status") != "ok":
                raise DomainValidationError("저장된 제약 검증기 실행에 실패했습니다.")
            require_all_true(validation.get("value"), 1)
            execution = await runner.execute({"language": "python", "source": problem.reference_source, "signature": problem.signature, "cases": [{"id": "case-0", "args": payload.args}], "limits": {"time_ms": problem.time_limit_ms, "memory_mb": problem.memory_limit_mb, "output_kb": 64}})
            result = next((item for item in execution.get("results", []) if item.get("id") == "case-0"), None)
            if not result or result.get("status") != "ok":
                raise DomainValidationError("기준 풀이 실행에 실패했습니다.")
            computed = result.get("value")
            validate_case(payload.args, computed, signature)
        except RunnerUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except DomainValidationError as exc:
            raise _domain_http(exc)
        matches = None if payload.current_expected is None else typed_equal(computed, payload.current_expected, signature.return_type)
        return ExpectedResult(computed=computed, matches_current=matches)

    @app.get("/api/problems/{problem_id}/drafts/{language}", response_model=DraftPublic, tags=["drafts"])
    def get_draft(problem_id: str, language: str, db: Session = Depends(get_db)):
        if language not in SUPPORTED_LANGUAGES:
            raise HTTPException(422, "지원하지 않는 언어입니다.")
        problem = _problem_or_404(db, problem_id)
        draft = db.scalar(select(CodeDraft).where(CodeDraft.problem_id == problem.id, CodeDraft.language == language))
        if draft:
            return DraftPublic(language=language, source=draft.source, updated_at=draft.updated_at)
        return DraftPublic(language=language, source=problem.templates[language], updated_at=problem.updated_at)

    @app.put("/api/problems/{problem_id}/drafts/{language}", response_model=DraftPublic, tags=["drafts"])
    def save_draft(problem_id: str, language: str, payload: DraftWrite, db: Session = Depends(get_db)):
        if language not in SUPPORTED_LANGUAGES:
            raise HTTPException(422, "지원하지 않는 언어입니다.")
        problem = _problem_or_404(db, problem_id)
        draft = db.scalar(select(CodeDraft).where(CodeDraft.problem_id == problem.id, CodeDraft.language == language))
        if draft:
            draft.source = payload.source
            draft.updated_at = datetime.now(timezone.utc)
        else:
            draft = CodeDraft(problem_id=problem.id, language=language, source=payload.source)
            db.add(draft)
        db.commit()
        db.refresh(draft)
        return DraftPublic(language=language, source=draft.source, updated_at=draft.updated_at)

    @app.post("/api/problems/{problem_id}/jobs", response_model=JobPublic, status_code=202, tags=["execution"])
    async def create_execution_job(problem_id: str, payload: JobCreate, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        if len(payload.source.encode("utf-8")) > 256 * 1024:
            raise HTTPException(413, "소스 코드는 256KiB 이하여야 합니다.")
        if payload.mode == "submit" and problem.status != "ready":
            raise HTTPException(409, "테스트 준비가 완료된 문제만 제출할 수 있습니다.")
        selected = [item for item in problem.tests if item.kind in ({"public", "user", "hidden"} if payload.mode == "submit" else {"public", "user"})]
        selected.sort(key=lambda item: (item.position, item.id))
        if not selected:
            raise HTTPException(409, "실행할 테스트가 없습니다.")
        snapshot = [{"id": item.id, "kind": item.kind, "args": item.args, "expected": item.expected} for item in selected]
        job = Job(problem_id=problem.id, kind="execution", mode=payload.mode, language=payload.language, source=payload.source, status="queued", test_revision=problem.test_revision, signature_snapshot=problem.signature, cases_snapshot=snapshot)
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
        if settings.run_jobs_inline:
            await execute_job(session_factory, runner, job_id)
        else:
            schedule(execute_job(session_factory, runner, job_id))
        db.expire_all()
        return _job_public(db.get(Job, job_id))

    @app.get("/api/jobs/{job_id}", response_model=JobPublic, tags=["execution"])
    def get_job(job_id: str, db: Session = Depends(get_db)):
        job = db.get(Job, job_id)
        if not job or job.kind != "execution":
            raise HTTPException(404, "실행 작업을 찾을 수 없습니다.")
        return _job_public(job)

    @app.get("/api/problems/{problem_id}/submissions", response_model=list[JobPublic], tags=["execution"])
    def submissions(problem_id: str, db: Session = Depends(get_db)):
        _problem_or_404(db, problem_id)
        jobs = db.scalars(select(Job).where(Job.problem_id == problem_id, Job.kind == "execution", Job.mode == "submit").order_by(Job.created_at.desc())).all()
        return [_job_public(item) for item in jobs]

    @app.post("/api/problems/{problem_id}/ai/generate", response_model=GenerationJobPublic, status_code=202, tags=["ai"])
    async def create_generation_job(problem_id: str, payload: GenerationRequest, db: Session = Depends(get_db)):
        if not settings.openai_api_key:
            raise HTTPException(503, "OPENAI_API_KEY를 설정한 뒤 다시 시도하세요.")
        problem = _problem_or_404(db, problem_id)
        if problem.status == "generating":
            raise HTTPException(409, "이미 테스트 생성 작업이 진행 중입니다.")
        public_cases = sorted((item for item in problem.tests if item.kind == "public"), key=lambda item: item.position)
        if not public_cases:
            raise HTTPException(409, "원본 공개 예제가 하나 이상 필요합니다.")
        start_revision = problem.test_revision
        job = Job(problem_id=problem.id, kind="generation", status="queued", test_revision=start_revision, signature_snapshot=problem.signature, cases_snapshot=[])
        db.add(job)
        db.flush()
        claimed = db.execute(
            update(Problem)
            .where(
                Problem.id == problem.id,
                Problem.test_revision == start_revision,
                Problem.status == problem.status,
                Problem.status != "generating",
            )
            .values(status="generating", generation_error=None, latest_generation_job_id=job.id, updated_at=now())
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "문제가 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도하세요.")
        visible_cases = db.scalars(
            select(TestCase)
            .where(TestCase.problem_id == problem.id, TestCase.kind.in_(["public", "user"]))
            .order_by(TestCase.position, TestCase.id)
        ).all()
        job.cases_snapshot = [{"id": item.id, "kind": item.kind, "args": item.args, "expected": item.expected} for item in visible_cases]
        db.commit()
        db.refresh(job)
        job_id = job.id
        if settings.run_jobs_inline:
            await generate_job(session_factory, runner, ai, job_id, payload.seed)
        else:
            schedule(generate_job(session_factory, runner, ai, job_id, payload.seed))
        db.expire_all()
        return _generation_public(db.get(Job, job_id))

    @app.get("/api/generation-jobs/{job_id}", response_model=GenerationJobPublic, tags=["ai"])
    def get_generation_job(job_id: str, db: Session = Depends(get_db)):
        job = db.get(Job, job_id)
        if not job or job.kind != "generation":
            raise HTTPException(404, "생성 작업을 찾을 수 없습니다.")
        return _generation_public(job)

    @app.post("/api/problems/{problem_id}/ai/chat", response_model=TutorResponse, tags=["ai"])
    async def chat(problem_id: str, payload: TutorRequest, db: Session = Depends(get_db)):
        if not settings.openai_api_key:
            raise HTTPException(503, "OPENAI_API_KEY를 설정한 뒤 다시 시도하세요.")
        problem = _problem_or_404(db, problem_id)
        previous = db.scalars(select(ChatTurn).where(ChatTurn.problem_id == problem.id).order_by(ChatTurn.created_at.desc()).limit(6)).all()
        history = [{"user": item.user_message, "assistant": item.assistant_message, "mode": item.mode} for item in reversed(previous)]
        ai_payload = {
            "mode": payload.mode,
            "message": payload.message,
            "language": payload.language,
            "source": payload.source,
            "problem": {"title": problem.title, "statement": problem.statement, "example_explanation": problem.example_explanation, "constraints": problem.constraints, "signature": problem.signature, "examples": [{"args": item.args, "expected": item.expected} for item in _visible_tests(problem)]},
            "history": history,
        }
        try:
            result = await ai.tutor(ai_payload)
        except AIUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        turn = ChatTurn(problem_id=problem.id, mode=payload.mode, user_message=payload.message, assistant_message=result["content"], model=result["model"], input_tokens=result["input_tokens"], output_tokens=result["output_tokens"])
        db.add(turn)
        db.add(AIUsage(problem_id=problem.id, operation="tutor", model=result["model"], input_tokens=result["input_tokens"], output_tokens=result["output_tokens"]))
        db.commit()
        return TutorResponse(**result)

    @app.get("/api/problems/{problem_id}/chat", response_model=list[ChatTurnPublic], tags=["ai"])
    def chat_history(problem_id: str, db: Session = Depends(get_db)):
        problem = _problem_or_404(db, problem_id)
        turns = db.scalars(select(ChatTurn).where(ChatTurn.problem_id == problem.id).order_by(ChatTurn.created_at.asc())).all()
        return [
            ChatTurnPublic(
                mode=item.mode,
                user_message=item.user_message,
                assistant_message=item.assistant_message,
                model=item.model,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                created_at=item.created_at,
            )
            for item in turns
        ]

    @app.get("/api/ai/usage", response_model=list[AIUsagePublic], tags=["ai"])
    def ai_usage(db: Session = Depends(get_db)):
        rows = db.scalars(select(AIUsage).order_by(AIUsage.created_at.desc()).limit(500)).all()
        return [AIUsagePublic.model_validate(item, from_attributes=True) for item in rows]

    return app


app = create_app()

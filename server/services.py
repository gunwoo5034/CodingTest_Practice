from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from server.models import AIUsage, Job, Problem, TestCase, now
from server.runner_client import RunnerUnavailable
from server.schemas import Signature
from server.validation import DomainValidationError, require_all_true, typed_equal, validate_args, validate_case


logger = logging.getLogger(__name__)


def _limits(problem: Problem) -> dict:
    return {"time_ms": problem.time_limit_ms, "memory_mb": problem.memory_limit_mb, "output_kb": 64}


def _case_id(index: int) -> str:
    return f"case-{index}"


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, (RunnerUnavailable, DomainValidationError)):
        return str(exc)
    return "작업을 완료하지 못했습니다. 입력과 실행 서비스 상태를 확인하세요."


def partition_generated_cases(public_cases: list[dict], generated: list[tuple[list, Any]]) -> tuple[list[dict], list[tuple[list, Any]]]:
    """Use distinct generated cases to bring the visible examples to three."""
    public = list(public_cases)
    remaining = list(generated)
    while len(public) < 3 and remaining:
        args, expected = remaining.pop(0)
        public.append({"args": args, "expected": expected, "kind": "public", "provenance": {"source": "generated-supplement"}})
    return public, remaining


async def execute_job(factory: sessionmaker[Session], runner, job_id: str) -> None:
    with factory() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = "running"
        db.commit()
        signature = Signature.model_validate(job.signature_snapshot)
        cases = job.cases_snapshot
        problem = db.get(Problem, job.problem_id)
        request = {
            "language": job.language,
            "source": job.source,
            "signature": job.signature_snapshot,
            "cases": [{"id": _case_id(i), "args": item["args"]} for i, item in enumerate(cases)],
            "limits": _limits(problem),
        }
    try:
        response = await runner.execute(request)
        raw_by_id = {item.get("id"): item for item in response.get("results", [])}
        results: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            raw = raw_by_id.get(_case_id(index), {"status": "system_error", "time_ms": 0, "memory_kb": 0})
            runner_status = raw.get("status", "system_error")
            if runner_status == "ok":
                status = "passed" if typed_equal(raw.get("value"), case["expected"], signature.return_type) else "wrong_answer"
            else:
                status = runner_status
            common = {
                "id": case["id"],
                "visibility": case["kind"],
                "status": status,
                "time_ms": float(raw.get("time_ms") or 0),
                "memory_kb": int(raw.get("memory_kb") or 0),
            }
            if case["kind"] != "hidden":
                common.update(
                    expected=case["expected"],
                    actual=raw.get("value"),
                    stdout=str(raw.get("stdout") or ""),
                    stderr=str(raw.get("stderr") or ""),
                )
            results.append(common)
        passed = sum(item["status"] == "passed" for item in results)
        summary = {
            "passed": passed,
            "total": len(results),
            "all_passed": passed == len(results),
            "max_time_ms": max((item["time_ms"] for item in results), default=0),
            "max_memory_kb": max((item["memory_kb"] for item in results), default=0),
        }
        with factory() as db:
            job = db.get(Job, job_id)
            job.status = "completed"
            job.results = results
            job.summary = summary
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as exc:
        logger.exception("execution job failed")
        with factory() as db:
            job = db.get(Job, job_id)
            job.status = "failed"
            job.error = _safe_error(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()


def _require_result_ok(result: dict, label: str) -> Any:
    if result.get("status") != "ok":
        raise DomainValidationError(f"{label} 실행에 실패했습니다.")
    return result.get("value")


def _values_from_execution(response: dict, count: int, label: str) -> list[Any]:
    by_id = {item.get("id"): item for item in response.get("results", [])}
    values = []
    for index in range(count):
        result = by_id.get(_case_id(index))
        if not result or result.get("status") != "ok":
            raise DomainValidationError(f"{label} 실행에 실패했습니다.")
        values.append(result.get("value"))
    return values


async def _execute_sources(runner, problem: Problem, source: str, cases: list[list]) -> list[Any]:
    response = await runner.execute(
        {
            "language": "python",
            "source": source,
            "signature": problem.signature,
            "cases": [{"id": _case_id(i), "args": args} for i, args in enumerate(cases)],
            "limits": _limits(problem),
        }
    )
    return _values_from_execution(response, len(cases), "풀이")


async def _script(runner, source: str, payload: Any) -> Any:
    return _require_result_ok(
        await runner.script(
            {"source": source, "payload": payload, "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 1024}}
        ),
        "검증 스크립트",
    )


async def generate_job(factory: sessionmaker[Session], runner, ai, job_id: str, seed: int) -> None:
    with factory() as db:
        job = db.get(Job, job_id)
        problem = db.get(Problem, job.problem_id) if job else None
        if not job or not problem:
            return
        job.status = "running"
        db.commit()
        public_cases = [item for item in job.cases_snapshot if item["kind"] == "public"]
        ai_payload = {
            "title": problem.title,
            "statement": problem.statement,
            "example_explanation": problem.example_explanation,
            "constraints": problem.constraints,
            "signature": problem.signature,
            "examples": [{"args": item["args"], "expected": item["expected"]} for item in public_cases],
            "seed": seed,
        }
    bundle = None
    try:
        bundle = await ai.generate(ai_payload)
        signature = Signature.model_validate(problem.signature)
        visible_args = [item["args"] for item in job.cases_snapshot]
        original_args = [item["args"] for item in public_cases]
        original_expected = [item["expected"] for item in public_cases]
        visible_validation = await _script(runner, bundle["validator_source"], visible_args)
        require_all_true(visible_validation, len(visible_args))
        reference_examples = await _execute_sources(runner, problem, bundle["reference_source"], original_args)
        brute_examples = await _execute_sources(runner, problem, bundle["brute_source"], original_args)
        for index, expected in enumerate(original_expected):
            if not typed_equal(reference_examples[index], expected, signature.return_type) or not typed_equal(brute_examples[index], expected, signature.return_type):
                raise DomainValidationError("기준 풀이가 원본 예제와 일치하지 않습니다.")

        small_args = await _script(runner, bundle["generator_source"], {"seed": seed, "count": 50, "mode": "small"})
        if not isinstance(small_args, list) or len(small_args) != 50:
            raise DomainValidationError("작은 교차 검증 입력 50개가 필요합니다.")
        valid_small = await _script(runner, bundle["validator_source"], small_args)
        require_all_true(valid_small, 50)
        for args in small_args:
            validate_args(args, signature)
        reference_small = await _execute_sources(runner, problem, bundle["reference_source"], small_args)
        brute_small = await _execute_sources(runner, problem, bundle["brute_source"], small_args)
        if any(not typed_equal(a, b, signature.return_type) for a, b in zip(reference_small, brute_small, strict=True)):
            raise DomainValidationError("기준 풀이와 독립 풀이의 교차 검증 결과가 다릅니다.")

        hidden_args = await _script(runner, bundle["generator_source"], {"seed": seed, "count": 30, "mode": "hidden"})
        if not isinstance(hidden_args, list) or not hidden_args or len(hidden_args) > 30:
            raise DomainValidationError("히든 테스트 생성 결과가 올바르지 않습니다.")
        valid_hidden = await _script(runner, bundle["validator_source"], hidden_args)
        require_all_true(valid_hidden, len(hidden_args))
        for args in hidden_args:
            validate_args(args, signature)
        hidden_expected = await _execute_sources(runner, problem, bundle["reference_source"], hidden_args)
        unique_hidden: list[tuple[list, Any]] = []
        seen = {repr(args) for args in original_args}
        for args, expected in zip(hidden_args, hidden_expected, strict=True):
            validate_case(args, expected, signature)
            marker = repr(args)
            if marker not in seen:
                seen.add(marker)
                unique_hidden.append((args, expected))
        if not unique_hidden:
            raise DomainValidationError("중복이 아닌 히든 테스트가 없습니다.")

        final_public, final_hidden = partition_generated_cases(public_cases, unique_hidden)
        if not final_hidden:
            raise DomainValidationError("공개 예제 보충 후 남은 히든 테스트가 없습니다.")

        with factory() as db:
            job = db.get(Job, job_id)
            problem = db.get(Problem, job.problem_id)
            next_revision = job.test_revision + 1
            installed = db.execute(
                update(Problem)
                .where(
                    Problem.id == problem.id,
                    Problem.status == "generating",
                    Problem.latest_generation_job_id == job.id,
                    Problem.test_revision == job.test_revision,
                )
                .values(
                    reference_source=bundle["reference_source"],
                    brute_source=bundle["brute_source"],
                    validator_source=bundle["validator_source"],
                    generator_source=bundle["generator_source"],
                    generation_meta={"seed": seed, "model": bundle["model"], "notes": bundle["notes"], "small_crosscheck_count": 50, "hidden_count": len(final_hidden)},
                    test_revision=next_revision,
                    status="ready",
                    generation_error=None,
                    updated_at=now(),
                )
                .execution_options(synchronize_session=False)
            )
            if installed.rowcount != 1:
                raise DomainValidationError("생성 중 문제가 변경되어 결과를 설치하지 않았습니다.")
            db.query(TestCase).filter(TestCase.problem_id == problem.id, TestCase.kind.in_(["public", "hidden"])).delete(synchronize_session=False)
            for position, item in enumerate(final_public):
                provenance = item.get("provenance") or {"source": "original"}
                db.add(TestCase(problem_id=problem.id, kind="public", position=position, args=item["args"], expected=item["expected"], suite_version=next_revision, provenance=provenance))
            for offset, (args, expected) in enumerate(final_hidden):
                db.add(TestCase(problem_id=problem.id, kind="hidden", position=len(final_public) + offset, args=args, expected=expected, suite_version=next_revision, provenance={"source": "generated", "seed": seed}))
            job.test_revision = next_revision
            job.status = "completed"
            job.summary = {"small_crosscheck_count": 50, "hidden_count": len(final_hidden), "model": bundle["model"]}
            job.finished_at = datetime.now(timezone.utc)
            db.add(AIUsage(problem_id=problem.id, operation="generate", model=bundle["model"], input_tokens=bundle["input_tokens"], output_tokens=bundle["output_tokens"]))
            db.commit()
    except Exception as exc:
        logger.exception("generation job failed")
        with factory() as db:
            job = db.get(Job, job_id)
            problem = db.get(Problem, job.problem_id) if job else None
            if job:
                job.status = "failed"
                job.error = _safe_error(exc)
                job.finished_at = datetime.now(timezone.utc)
            if problem:
                db.execute(
                    update(Problem)
                    .where(
                        Problem.id == problem.id,
                        Problem.status == "generating",
                        Problem.latest_generation_job_id == job.id,
                    )
                    .values(status="needs_review", generation_error=_safe_error(exc), updated_at=now())
                    .execution_options(synchronize_session=False)
                )
                if bundle:
                    db.add(AIUsage(problem_id=problem.id, operation="generate", model=bundle["model"], input_tokens=bundle["input_tokens"], output_tokens=bundle["output_tokens"]))
            db.commit()

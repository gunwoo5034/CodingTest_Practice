from __future__ import annotations

from sqlalchemy import MetaData, Table
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from server.db import create_database, initialize_database
from server.models import CodeDraft, Job, Problem, TestCase as DBTestCase


class _RestartRunner:
    def __init__(self):
        self.response = None

    async def health(self):
        return {"status": "ok"}

    async def execute(self, _request):
        return self.response


class _NoAI:
    pass


def test_restart_marks_generation_interrupted_and_unlocks_problem(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'restart.db'}")
    initialize_database(engine, factory)
    with factory() as db:
        problem = db.query(Problem).first()
        problem.status = "generating"
        job = Job(
            problem_id=problem.id,
            kind="generation",
            status="running",
            test_revision=problem.test_revision,
            signature_snapshot=problem.signature,
            cases_snapshot=[],
        )
        db.add(job)
        db.flush()
        problem.latest_generation_job_id = job.id
        db.commit()

    initialize_database(engine, factory)
    with factory() as db:
        job = db.query(Job).filter(Job.kind == "generation").one()
        problem = db.get(Problem, job.problem_id)
        assert job.status == "interrupted"
        assert problem.status == "needs_review"
        assert problem.generation_error == "서버가 재시작되어 생성 작업이 중단되었습니다."
    engine.dispose()


def test_initialize_backfills_javascript_and_public_java_templates(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'upgrade.db'}")
    initialize_database(engine, factory)
    with factory() as db:
        problem = db.query(Problem).first()
        problem.templates = {"python": "old", "cpp": "old", "java": "class Solution {}"}
        db.commit()

    initialize_database(engine, factory)
    with factory() as db:
        problem = db.query(Problem).first()
        assert problem.templates["javascript"].startswith("function solution(numbers)")
        assert problem.templates["java"].startswith("public class Solution")
    engine.dispose()


def test_initialize_migrates_legacy_problem_without_losing_related_data(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'legacy.db'}")
    legacy = MetaData()
    problem_table = Table(
        "problems",
        legacy,
        *(column._copy() for column in Problem.__table__.columns if column.name != "example_explanation"),
    )
    test_table = DBTestCase.__table__.to_metadata(legacy)
    draft_table = CodeDraft.__table__.to_metadata(legacy)
    legacy.create_all(engine)
    signature = {
        "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
        "return_type": {"base": "int", "dimensions": 0},
    }
    with engine.begin() as connection:
        connection.execute(
            problem_table.insert().values(
                id="legacy-problem",
                title="기존 문제",
                statement="기존 설명",
                constraints=[],
                signature=signature,
                templates={"python": "def solution(value): return value"},
                status="draft",
                original_examples=[],
                test_revision=2,
                time_limit_ms=2000,
                memory_limit_mb=256,
            )
        )
        connection.execute(
            test_table.insert().values(
                id="legacy-test",
                problem_id="legacy-problem",
                kind="public",
                position=0,
                args=[1],
                expected=1,
                suite_version=2,
            )
        )
        connection.execute(
            draft_table.insert().values(
                id="legacy-draft",
                problem_id="legacy-problem",
                language="python",
                source="def solution(value): return value",
            )
        )

    initialize_database(engine, factory)
    initialize_database(engine, factory)
    with factory() as db:
        problem = db.get(Problem, "legacy-problem")
        assert problem.example_explanation == ""
        assert problem.statement == "기존 설명"
        assert db.get(DBTestCase, "legacy-test").expected == 1
        assert db.get(CodeDraft, "legacy-draft").source.endswith("return value")
    engine.dispose()


def test_solved_state_survives_restart_and_ignores_zero_total_job(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'solved.db'}"
    settings = Settings(database_url=database_url, openai_api_key="", run_jobs_inline=True)
    runner = _RestartRunner()
    with TestClient(create_app(settings=settings, runner=runner, ai=_NoAI())) as client:
        problem = client.get("/api/problems").json()[0]
        runner.response = {
            "results": [
                {"id": f"case-{index}", "status": "ok", "value": value, "time_ms": 1, "memory_kb": 1}
                for index, value in enumerate([6, 0, 12, 9, -5])
            ]
        }
        client.post(
            f"/api/problems/{problem['id']}/jobs",
            json={"mode": "submit", "language": "python", "source": "def solution(numbers): return sum(numbers)"},
        )
        problem_id = problem["id"]
        empty_problem_id = client.post(
            "/api/problems",
            json={
                "title": "빈 제출 기록",
                "signature": {
                    "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
                    "return_type": {"base": "int", "dimensions": 0},
                },
            },
        ).json()["id"]

    engine, factory = create_database(database_url)
    with factory() as db:
        saved = db.get(Problem, empty_problem_id)
        db.add(
            Job(
                problem_id=empty_problem_id,
                kind="execution",
                mode="submit",
                language="python",
                source="def solution(numbers): return 0",
                status="completed",
                test_revision=saved.test_revision,
                signature_snapshot=saved.signature,
                cases_snapshot=[],
                summary={"passed": 0, "total": 0, "all_passed": True, "max_time_ms": 0, "max_memory_kb": 0},
            )
        )
        db.add(
            Job(
                problem_id=empty_problem_id,
                kind="execution",
                mode="submit",
                language="python",
                source="def solution(value): return value",
                status="running",
                test_revision=saved.test_revision,
                signature_snapshot=saved.signature,
                cases_snapshot=[{"id": "pending", "kind": "public", "args": [1], "expected": 1}],
                summary={"passed": 1, "total": 1, "all_passed": True, "max_time_ms": 0, "max_memory_kb": 0},
            )
        )
        db.add(
            Job(
                problem_id=empty_problem_id,
                kind="execution",
                mode="submit",
                language="python",
                source="def solution(value): return value",
                status="completed",
                test_revision=saved.test_revision,
                signature_snapshot=saved.signature,
                cases_snapshot=[{"id": "invalid-bool", "kind": "public", "args": [1], "expected": 1}],
                summary={"passed": 1, "total": 1, "all_passed": 1, "max_time_ms": 0, "max_memory_kb": 0},
            )
        )
        db.commit()
    engine.dispose()

    with TestClient(create_app(settings=settings, runner=_RestartRunner(), ai=_NoAI())) as client:
        detail = client.get(f"/api/problems/{problem_id}").json()
        listed = {item["id"]: item for item in client.get("/api/problems").json()}
        assert detail["is_solved"] is True
        assert listed[problem_id]["is_solved"] is True
        assert listed[empty_problem_id]["is_solved"] is False

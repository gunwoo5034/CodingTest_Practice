from __future__ import annotations

from server.db import create_database, initialize_database
from server.models import Job, Problem


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

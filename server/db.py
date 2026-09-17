from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from server.models import Base, Job, Problem, TestCase


def create_database(url: str):
    if url.startswith("sqlite"):
        database = make_url(url).database
        if database and database != ":memory:":
            Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize_database(engine, session_factory: sessionmaker[Session]) -> None:
    Base.metadata.create_all(engine)
    with session_factory() as db:
        interrupted_generations = db.scalars(
            select(Job).where(Job.kind == "generation", Job.status.in_(["queued", "running"]))
        ).all()
        db.execute(
            update(Job).where(Job.status.in_(["queued", "running"])).values(status="interrupted", error="서버가 재시작되어 작업이 중단되었습니다.")
        )
        for job in interrupted_generations:
            problem = db.get(Problem, job.problem_id)
            if problem:
                problem.status = "needs_review"
                problem.latest_generation_job_id = job.id
                problem.generation_error = "서버가 재시작되어 생성 작업이 중단되었습니다."
        if db.query(Problem).count() == 0:
            _seed_demo(db)
        db.commit()


def _seed_demo(db: Session) -> None:
    signature = {
        "parameters": [{"name": "numbers", "type": {"base": "int", "dimensions": 1}}],
        "return_type": {"base": "int", "dimensions": 0},
    }
    problem = Problem(
        title="정수 배열의 합",
        statement="정수 배열 numbers가 주어지면 모든 원소의 합을 반환하세요.",
        constraints=["0 ≤ numbers의 길이 ≤ 100", "-1,000 ≤ 각 원소 ≤ 1,000"],
        signature=signature,
        templates={
            "python": "def solution(numbers):\n    return sum(numbers)\n",
            "cpp": "int solution(vector<int> numbers) {\n    int answer = 0;\n    for (int n : numbers) answer += n;\n    return answer;\n}\n",
            "java": "class Solution {\n    public int solution(int[] numbers) {\n        int answer = 0;\n        for (int n : numbers) answer += n;\n        return answer;\n    }\n}\n",
        },
        status="ready",
        reference_source="def solution(numbers):\n    return sum(numbers)\n",
        validator_source="def main(payload):\n    return [isinstance(a, list) and len(a)==1 and isinstance(a[0], list) for a in payload]\n",
        test_revision=1,
        generation_meta={"origin": "built-in", "seed": 20260917},
        original_examples=[{"args": [[1, 2, 3]], "expected": 6}, {"args": [[]], "expected": 0}, {"args": [[5, -2, 9]], "expected": 12}],
    )
    db.add(problem)
    db.flush()
    cases = [
        ("public", [[1, 2, 3]], 6),
        ("public", [[]], 0),
        ("public", [[5, -2, 9]], 12),
        ("hidden", [[4, 5]], 9),
        ("hidden", [[-10, 5]], -5),
    ]
    for position, (kind, args, expected) in enumerate(cases):
        db.add(TestCase(problem_id=problem.id, kind=kind, position=position, args=args, expected=expected, suite_version=1))


def session_dependency(factory: sessionmaker[Session]):
    def get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    return get_db

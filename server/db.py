from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from server.models import Base, Job, Problem, TestCase
from server.schemas import Signature
from server.templates import templates_for


DEMO_VALIDATOR_SOURCE = (
    "def main(payload):\n"
    "    results = []\n"
    "    for args in payload:\n"
    "        valid = isinstance(args, list) and len(args) == 1 and isinstance(args[0], list)\n"
    "        if valid:\n"
    "            valid = len(args[0]) <= 100 and all(type(value) is int and -1000 <= value <= 1000 for value in args[0])\n"
    "        results.append(valid)\n"
    "    return results\n"
)


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
        _upgrade_templates(db)
        db.commit()


def _upgrade_templates(db: Session) -> None:
    for problem in db.scalars(select(Problem)).all():
        generated = templates_for(Signature.model_validate(problem.signature))
        current = dict(problem.templates or {})
        changed = False
        for language, source in generated.items():
            if language not in current:
                current[language] = source
                changed = True
        java = current.get("java", "")
        if java.startswith("class Solution"):
            current["java"] = f"public {java}"
            changed = True
        if changed:
            problem.templates = current
        if (problem.generation_meta or {}).get("origin") == "built-in" and problem.status == "ready":
            problem.validator_source = DEMO_VALIDATOR_SOURCE


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
            "java": "public class Solution {\n    public int solution(int[] numbers) {\n        int answer = 0;\n        for (int n : numbers) answer += n;\n        return answer;\n    }\n}\n",
            "javascript": "function solution(numbers) {\n    return numbers.reduce((sum, number) => sum + number, 0);\n}\n\nmodule.exports = { solution };\n",
        },
        status="ready",
        reference_source="def solution(numbers):\n    return sum(numbers)\n",
        validator_source=DEMO_VALIDATOR_SOURCE,
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

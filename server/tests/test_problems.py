from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading


def test_seed_problem_is_public_and_redacted(client):
    response = client.get("/api/problems")
    assert response.status_code == 200
    [problem] = response.json()
    assert problem["title"] == "정수 배열의 합"

    detail = client.get(f"/api/problems/{problem['id']}").json()
    assert detail["status"] == "ready"
    assert len(detail["tests"]) == 3
    serialized = str(detail).lower()
    assert "reference" not in serialized
    assert "hidden" not in serialized


def test_semantic_edit_invalidates_generated_material(client):
    problem = client.get("/api/problems").json()[0]
    response = client.patch(
        f"/api/problems/{problem['id']}",
        json={"statement": "배열 원소를 모두 더해 반환하세요. (수정됨)"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "draft"


def test_title_or_unchanged_semantic_fields_keep_ready_status(client):
    problem = client.get("/api/problems").json()[0]
    detail = client.get(f"/api/problems/{problem['id']}").json()
    response = client.patch(
        f"/api/problems/{problem['id']}",
        json={
            "title": "새 제목",
            "statement": detail["statement"],
            "constraints": detail["constraints"],
            "signature": detail["signature"],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["test_revision"] == detail["test_revision"]


def test_visible_test_change_increments_revision(client, runner):
    problem = client.get("/api/problems").json()[0]
    before = problem["test_revision"]
    runner.script_responses.append(
        {"status": "ok", "value": [True], "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 100}
    )
    created = client.post(
        f"/api/problems/{problem['id']}/tests",
        json={"args": [[10, -3]], "expected": 7},
    )
    assert created.status_code == 201
    assert created.json()["kind"] == "user"
    after = client.get(f"/api/problems/{problem['id']}").json()
    assert after["test_revision"] == before + 1


def test_manual_public_case_is_accepted_but_hidden_is_rejected(client):
    created_problem = client.post(
        "/api/problems",
        json={
            "title": "수동 문제",
            "statement": "값을 그대로 반환하세요.",
            "constraints": [],
            "signature": {
                "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
                "return_type": {"base": "int", "dimensions": 0},
            },
        },
    ).json()
    public = client.post(
        f"/api/problems/{created_problem['id']}/tests",
        json={"kind": "public", "args": [1], "expected": 1},
    )
    hidden = client.post(
        f"/api/problems/{created_problem['id']}/tests",
        json={"kind": "hidden", "args": [2], "expected": 2},
    )
    assert public.status_code == 201
    assert public.json()["kind"] == "public"
    assert hidden.status_code == 422


def test_concurrent_validated_test_writes_use_one_revision(client, runner):
    problem = client.get("/api/problems").json()[0]
    start_revision = problem["test_revision"]
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0

    async def barrier_script(request):
        nonlocal calls
        runner.script_calls.append(request)
        with lock:
            calls += 1
            if calls == 2:
                entered.set()
        await asyncio.to_thread(release.wait)
        return {"status": "ok", "value": [True], "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 10}

    runner.script = barrier_script

    def create(value):
        return client.post(
            f"/api/problems/{problem['id']}/tests",
            json={"args": [[value]], "expected": value},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create, 21), pool.submit(create, 22)]
        assert entered.wait(timeout=5)
        release.set()
        responses = [future.result(timeout=5) for future in futures]

    assert sorted(response.status_code for response in responses) == [201, 409]
    detail = client.get(f"/api/problems/{problem['id']}").json()
    assert detail["test_revision"] == start_revision + 1
    assert len([item for item in detail["tests"] if item["kind"] == "user"]) == 1


def test_semantic_patch_wins_against_test_write_waiting_on_validation(client, runner):
    problem = client.get("/api/problems").json()[0]
    entered = threading.Event()
    release = threading.Event()

    async def blocked_script(request):
        runner.script_calls.append(request)
        entered.set()
        await asyncio.to_thread(release.wait)
        return {"status": "ok", "value": [True], "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 10}

    runner.script = blocked_script

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post,
            f"/api/problems/{problem['id']}/tests",
            json={"args": [[31]], "expected": 31},
        )
        assert entered.wait(timeout=5)
        patch = client.patch(
            f"/api/problems/{problem['id']}",
            json={"statement": "의미가 바뀐 설명"},
        )
        release.set()
        write = future.result(timeout=5)

    assert patch.status_code == 200
    assert patch.json()["status"] == "draft"
    assert write.status_code == 409
    detail = client.get(f"/api/problems/{problem['id']}").json()
    assert all(item["args"] != [[31]] for item in detail["tests"])


def test_ready_problem_rejects_manual_input_that_validator_rejects(client, runner):
    problem = client.get("/api/problems").json()[0]
    runner.script_responses.append(
        {"status": "ok", "value": [False], "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 100}
    )
    response = client.post(
        f"/api/problems/{problem['id']}/tests",
        json={"args": [[1001]], "expected": 1001},
    )
    assert response.status_code == 422
    assert "제한사항" in response.json()["detail"]


def test_ready_problem_rejects_test_update_that_validator_rejects(client, runner):
    problem = client.get("/api/problems").json()[0]
    test_id = client.get(f"/api/problems/{problem['id']}").json()["tests"][0]["id"]
    runner.script_responses.append(
        {"status": "ok", "value": [False], "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 100}
    )
    response = client.patch(
        f"/api/problems/{problem['id']}/tests/{test_id}",
        json={"args": [[1001]]},
    )
    assert response.status_code == 422


def test_draft_problem_uses_type_validation_without_runner(client, runner):
    problem = client.get("/api/problems").json()[0]
    client.patch(f"/api/problems/{problem['id']}", json={"statement": "수정"})
    response = client.post(
        f"/api/problems/{problem['id']}/tests",
        json={"args": [[1001]], "expected": 1001},
    )
    assert response.status_code == 201
    assert runner.script_calls == []


def test_problem_patch_rejects_explicit_null(client):
    problem = client.get("/api/problems").json()[0]
    response = client.patch(f"/api/problems/{problem['id']}", json={"title": None})
    assert response.status_code == 422


def test_problem_patch_schema_is_optional_but_not_nullable(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ProblemUpdate"]
    assert "required" not in schema
    for field in ("title", "statement", "constraints", "signature", "time_limit_ms", "memory_limit_mb"):
        assert "null" not in str(schema["properties"][field]).lower()
    assert schema["properties"]["constraints"]["maxItems"] == 100
    assert schema["properties"]["time_limit_ms"]["minimum"] == 100


def test_sqlite_public_timestamps_are_explicit_utc(client):
    problem = client.get("/api/problems").json()[0]
    assert problem["updated_at"].endswith("Z") or problem["updated_at"].endswith("+00:00")
    draft = client.get(f"/api/problems/{problem['id']}/drafts/python").json()
    assert draft["updated_at"].endswith("Z") or draft["updated_at"].endswith("+00:00")


def test_problem_templates_include_javascript_and_public_java(client):
    problem = client.get("/api/problems").json()[0]
    detail = client.get(f"/api/problems/{problem['id']}").json()
    assert detail["templates"]["javascript"].startswith("function solution(numbers)")
    assert "module.exports = { solution }" in detail["templates"]["javascript"]
    assert detail["templates"]["java"].startswith("public class Solution")

    draft = client.get(f"/api/problems/{problem['id']}/drafts/javascript")
    assert draft.status_code == 200
    assert draft.json()["language"] == "javascript"

    created = client.post(
        "/api/problems",
        json={
            "title": "큰 수",
            "statement": "큰 수를 반환합니다.",
            "constraints": [],
            "signature": {
                "parameters": [{"name": "value", "type": {"base": "long", "dimensions": 0}}],
                "return_type": {"base": "long", "dimensions": 0},
            },
        },
    ).json()
    assert "BigInt" in created["templates"]["javascript"]

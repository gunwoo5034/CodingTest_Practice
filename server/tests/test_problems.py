from __future__ import annotations


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

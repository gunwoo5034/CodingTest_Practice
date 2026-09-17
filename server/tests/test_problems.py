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


def test_visible_test_change_increments_revision(client):
    problem = client.get("/api/problems").json()[0]
    before = problem["test_revision"]
    created = client.post(
        f"/api/problems/{problem['id']}/tests",
        json={"args": [[10, -3]], "expected": 7},
    )
    assert created.status_code == 201
    assert created.json()["kind"] == "user"
    after = client.get(f"/api/problems/{problem['id']}").json()
    assert after["test_revision"] == before + 1

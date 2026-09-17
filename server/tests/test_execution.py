from __future__ import annotations


def _ok(case_id: str, value, *, stdout: str = "") -> dict:
    return {
        "id": case_id,
        "status": "ok",
        "value": value,
        "stdout": stdout,
        "stderr": "",
        "time_ms": 1.25,
        "memory_kb": 2048,
    }


def test_run_uses_only_visible_tests_and_does_not_call_ai(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    runner.execute_responses.append(
        {"results": [_ok(f"case-{i}", value) for i, value in enumerate([6, 0, 12])]}
    )

    response = client.post(
        f"/api/problems/{problem['id']}/jobs",
        json={"mode": "run", "language": "python", "source": "def solution(numbers): return sum(numbers)"},
    )
    assert response.status_code == 202
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "completed"
    assert job["summary"]["passed"] == 3
    assert len(runner.execute_calls[0]["cases"]) == 3
    assert ai.calls == []


def test_submit_redacts_hidden_case_data_and_preserves_snapshot(client, runner):
    problem = client.get("/api/problems").json()[0]
    runner.execute_responses.append(
        {"results": [_ok(f"case-{i}", value, stdout="secret log") for i, value in enumerate([6, 0, 12, 9, -5])]}
    )
    response = client.post(
        f"/api/problems/{problem['id']}/jobs",
        json={"mode": "submit", "language": "python", "source": "def solution(numbers): return sum(numbers)"},
    )
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["test_revision"] == problem["test_revision"]
    assert len(job["results"]) == 5
    hidden = [result for result in job["results"] if result["visibility"] == "hidden"]
    assert len(hidden) == 2
    assert all(set(item) == {"id", "visibility", "status", "time_ms", "memory_kb"} for item in hidden)
    assert "secret log" not in str(hidden)


def test_submit_requires_ready_problem(client, runner):
    problem = client.get("/api/problems").json()[0]
    client.patch(f"/api/problems/{problem['id']}", json={"statement": "changed"})
    response = client.post(
        f"/api/problems/{problem['id']}/jobs",
        json={"mode": "submit", "language": "python", "source": "def solution(numbers): return 0"},
    )
    assert response.status_code == 409
    assert runner.execute_calls == []

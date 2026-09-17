from __future__ import annotations


def _script(value):
    return {"status": "ok", "value": value, "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 100}


def _results(values):
    return {
        "results": [
            {"id": f"case-{i}", "status": "ok", "value": value, "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 100}
            for i, value in enumerate(values)
        ]
    }


def test_generation_crosschecks_and_atomically_installs_tests(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): return sum(numbers)",
        "brute_source": "def solution(numbers):\n total=0\n for n in numbers: total+=n\n return total",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "independent loop",
        "model": "fake-generation",
        "input_tokens": 100,
        "output_tokens": 200,
    }
    small = [[[i, -i]] for i in range(50)]
    hidden = [[[i, i + 1]] for i in range(30)]
    public_expected = [6, 0, 12]
    small_expected = [0] * 50
    hidden_expected = [2 * i + 1 for i in range(30)]
    runner.script_responses.extend([_script(small), _script([True] * 50), _script(hidden), _script([True] * 30)])
    runner.execute_responses.extend(
        [
            _results(public_expected),
            _results(public_expected),
            _results(small_expected),
            _results(small_expected),
            _results(hidden_expected),
        ]
    )

    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 42})
    assert response.status_code == 202
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "completed"
    updated = client.get(f"/api/problems/{problem['id']}").json()
    assert updated["status"] == "ready"
    assert updated["latest_generation_job_id"] == job["id"]
    assert updated["generation_error"] is None
    assert updated["test_revision"] == problem["test_revision"] + 1
    assert len(updated["tests"]) == 3
    assert all("expected" not in call for call in runner.execute_calls)


def test_expected_value_is_computed_locally_without_overwriting(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    runner.script_responses.append(_script([True]))
    runner.execute_responses.append(_results([7]))
    response = client.post(
        f"/api/problems/{problem['id']}/tests/expected",
        json={"args": [[3, 4]], "current_expected": 8},
    )
    assert response.status_code == 200
    assert response.json() == {"computed": 7, "matches_current": False}
    assert ai.calls == []


def test_generation_failure_keeps_existing_tests(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    before = client.get(f"/api/problems/{problem['id']}").json()["tests"]
    ai.bundle = {
        "reference_source": "def solution(numbers): return 0",
        "brute_source": "def solution(numbers): return 1",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "bad",
        "model": "fake",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    runner.execute_responses.extend([_results([0, 0, 0]), _results([1, 1, 1])])
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 1})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    updated = client.get(f"/api/problems/{problem['id']}").json()
    assert updated["status"] == "needs_review"
    assert updated["generation_error"]
    assert updated["tests"] == before


def test_generation_supplements_public_examples_up_to_three():
    from server.services import partition_generated_cases

    public = [{"args": [[1]], "expected": 1}]
    generated = [([[2]], 2), ([[3]], 3), ([[4]], 4)]
    supplemented, hidden = partition_generated_cases(public, generated)
    assert [item["args"] for item in supplemented] == [[[1]], [[2]], [[3]]]
    assert hidden == [([[4]], 4)]

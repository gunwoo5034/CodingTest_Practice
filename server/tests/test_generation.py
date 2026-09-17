from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading


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
    runner.script_responses.append(_script([True]))
    added = client.post(
        f"/api/problems/{problem['id']}/tests",
        json={"args": [[10]], "expected": 10},
    )
    assert added.status_code == 201
    revision_before_generation = client.get(f"/api/problems/{problem['id']}").json()["test_revision"]
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
    runner.script_responses.extend([_script([True] * 4), _script(small), _script([True] * 50), _script(hidden), _script([True] * 30)])
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
    assert updated["test_revision"] == revision_before_generation + 1
    assert len(updated["tests"]) == 4
    assert all("expected" not in call for call in runner.execute_calls)
    assert runner.script_calls[1]["payload"] == [[[1, 2, 3]], [[]], [[5, -2, 9]], [[10]]]


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
    runner.script_responses.append(_script([True] * 3))
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 1})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    updated = client.get(f"/api/problems/{problem['id']}").json()
    assert updated["status"] == "needs_review"
    assert updated["generation_error"]
    assert updated["tests"] == before


def test_generation_rejects_non_boolean_public_validation(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): return sum(numbers)",
        "brute_source": "def solution(numbers): return sum(numbers)",
        "validator_source": "def main(payload): return [1 for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "bad validator",
        "model": "fake",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    runner.script_responses.append(_script([1, 1, 1]))
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 2})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert runner.execute_calls == []


def test_generation_supplements_public_examples_up_to_three():
    from server.services import partition_generated_cases

    public = [{"args": [[1]], "expected": 1}]
    generated = [([[2]], 2), ([[3]], 3), ([[4]], 4)]
    supplemented, hidden = partition_generated_cases(public, generated)
    assert [item["args"] for item in supplemented] == [[[1]], [[2]], [[3]]]
    assert hidden == [([[4]], 4)]


def test_manual_draft_public_example_can_complete_generation(client, runner, ai):
    problem = client.post(
        "/api/problems",
        json={
            "title": "항등 함수",
            "statement": "정수를 그대로 반환하세요.",
            "constraints": ["-100 ≤ value ≤ 100"],
            "signature": {
                "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
                "return_type": {"base": "int", "dimensions": 0},
            },
        },
    ).json()
    created = client.post(
        f"/api/problems/{problem['id']}/tests",
        json={"kind": "public", "args": [7], "expected": 7},
    )
    assert created.status_code == 201
    ai.bundle = {
        "reference_source": "def solution(value): return value",
        "brute_source": "def solution(value):\n result = 0\n result += value\n return result",
        "validator_source": "def main(payload): return [len(args) == 1 and type(args[0]) is int and -100 <= args[0] <= 100 for args in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "identity",
        "model": "fake-generation",
        "input_tokens": 10,
        "output_tokens": 20,
    }
    small = [[index - 25] for index in range(50)]
    hidden = [[index - 15] for index in range(30)]
    runner.script_responses.extend(
        [_script([True]), _script(small), _script([True] * 50), _script(hidden), _script([True] * 30)]
    )
    runner.execute_responses.extend(
        [_results([7]), _results([7]), _results([item[0] for item in small]), _results([item[0] for item in small]), _results([item[0] for item in hidden])]
    )
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 9})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    detail = client.get(f"/api/problems/{problem['id']}").json()
    assert job["status"] == "completed"
    assert detail["status"] == "ready"
    assert len([item for item in detail["tests"] if item["kind"] == "public"]) == 3


def test_generation_start_wins_against_test_write_waiting_on_validation(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    validation_entered = threading.Event()
    release_validation = threading.Event()
    generation_entered = threading.Event()
    release_generation = threading.Event()
    original_script = runner.script
    script_count = 0

    async def blocked_first_script(request):
        nonlocal script_count
        script_count += 1
        if script_count == 1:
            runner.script_calls.append(request)
            validation_entered.set()
            await asyncio.to_thread(release_validation.wait)
            return _script([True])
        return await original_script(request)

    bundle = {
        "reference_source": "def solution(numbers): return sum(numbers)",
        "brute_source": "def solution(numbers):\n total=0\n for n in numbers: total+=n\n return total",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "race",
        "model": "fake-generation",
        "input_tokens": 1,
        "output_tokens": 1,
    }

    async def blocked_generate(payload):
        ai.calls.append(("generate", payload))
        generation_entered.set()
        await asyncio.to_thread(release_generation.wait)
        return bundle

    runner.script = blocked_first_script
    ai.generate = blocked_generate
    small = [[[index, -index]] for index in range(50)]
    hidden = [[[index, index + 1]] for index in range(30)]
    runner.script_responses.extend(
        [_script([True] * 3), _script(small), _script([True] * 50), _script(hidden), _script([True] * 30)]
    )
    runner.execute_responses.extend(
        [_results([6, 0, 12]), _results([6, 0, 12]), _results([0] * 50), _results([0] * 50), _results([2 * i + 1 for i in range(30)])]
    )

    def write_test():
        return client.post(
            f"/api/problems/{problem['id']}/tests",
            json={"args": [[99]], "expected": 99},
        )

    def generate():
        return client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 10})

    with ThreadPoolExecutor(max_workers=2) as pool:
        test_future = pool.submit(write_test)
        assert validation_entered.wait(timeout=5)
        generation_future = pool.submit(generate)
        assert generation_entered.wait(timeout=5)
        release_validation.set()
        test_response = test_future.result(timeout=5)
        release_generation.set()
        generation_response = generation_future.result(timeout=10)

    assert test_response.status_code == 409
    assert generation_response.status_code == 202
    detail = client.get(f"/api/problems/{problem['id']}").json()
    assert detail["status"] == "ready"
    assert all(item["args"] != [[99]] for item in detail["tests"])

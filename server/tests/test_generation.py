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


def _return_type_results(count):
    return {
        "results": [
            {
                "id": f"case-{index}",
                "status": "runtime_error",
                "failure_kind": "return_type",
                "value": None,
                "stdout": "",
                "stderr": "",
                "time_ms": 1,
                "memory_kb": 100,
            }
            for index in range(count)
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
    generation_payload = next(payload for operation, payload in ai.calls if operation == "generate")
    assert generation_payload["example_explanation"]


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


def test_generation_repairs_shared_output_format_once_and_records_usage(client, runner, ai):
    created = client.post(
        "/api/problems",
        json={
            "title": "방문 순서",
            "statement": "방문 순서를 하나의 정수로 반환하세요.",
            "constraints": [],
            "signature": {
                "parameters": [{"name": "nodes", "type": {"base": "int", "dimensions": 1}}],
                "return_type": {"base": "int", "dimensions": 0},
            },
        },
    ).json()
    public = client.post(
        f"/api/problems/{created['id']}/tests",
        json={"kind": "public", "args": [[1]], "expected": 32231},
    )
    assert public.status_code == 201
    ai.bundle = {
        "reference_source": "def solution(nodes): return [3, 2, 2, 3, 1]",
        "brute_source": "def solution(nodes):\n result = [3, 2, 2, 3, 1]\n return result",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "visit order",
        "model": "fake-generation",
        "input_tokens": 100,
        "output_tokens": 200,
    }
    ai.repair = {
        "output_format": "concat_decimal",
        "reason": "정수 방문 순서를 이어 붙입니다.",
        "model": "fake-generation",
        "input_tokens": 11,
        "output_tokens": 7,
    }
    small = [[[index]] for index in range(50)]
    hidden = [[[index + 100]] for index in range(30)]
    runner.script_responses.extend(
        [_script([True]), _script([True]), _script(small), _script([True] * 50), _script(hidden), _script([True] * 30)]
    )
    runner.execute_responses.extend(
        [
            _return_type_results(1),
            _return_type_results(1),
            _results([32231]),
            _results([32231]),
            _results([int(f"{index}{index}") if index else 0 for index in range(50)]),
            _results([int(f"{index}{index}") if index else 0 for index in range(50)]),
            _results([int(f"{index + 100}{index + 100}") for index in range(30)]),
        ]
    )

    response = client.post(f"/api/problems/{created['id']}/ai/generate", json={"seed": 44})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    problem = client.get(f"/api/problems/{created['id']}").json()
    assert job["status"] == "completed"
    assert job["summary"]["output_format"] == "concat_decimal"
    assert job["summary"]["format_repair_attempted"] is True
    assert problem["output_format"] == "concat_decimal"
    repair_calls = [payload for operation, payload in ai.calls if operation == "format_repair"]
    assert len(repair_calls) == 1
    assert repair_calls[0]["examples"] == [{"args": [[1]], "expected": 32231}]
    assert all("expected" not in call for call in runner.execute_calls)
    repaired_sources = [call["source"] for call in runner.execute_calls[2:4]]
    assert all("_loopcode_original_namespace" in source for source in repaired_sources)
    usage = client.get("/api/ai/usage").json()
    assert any(item["operation"] == "format_repair" and item["input_tokens"] == 11 for item in usage)


def test_generation_does_not_request_format_repair_for_timeout(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): return sum(numbers)",
        "brute_source": "def solution(numbers): return sum(numbers)",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "timeout",
        "model": "fake-generation",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    runner.script_responses.append(_script([True] * 3))
    runner.execute_responses.append(
        {"results": [{"id": "case-0", "status": "time_limit", "time_ms": 2000, "memory_kb": 10}]}
    )
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 45})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert [operation for operation, _ in ai.calls] == ["generate"]


def test_generation_does_not_request_format_repair_for_generic_runtime_error(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): raise ValueError('algorithm bug')",
        "brute_source": "def solution(numbers): return sum(numbers)",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "runtime bug",
        "model": "fake-generation",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    runner.script_responses.append(_script([True] * 3))
    runner.execute_responses.append(
        {"results": [{"id": "case-0", "status": "runtime_error", "time_ms": 1, "memory_kb": 10}]}
    )
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 47})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert [operation for operation, _ in ai.calls] == ["generate"]


def test_nonrepairable_failure_wins_over_other_example_mismatch(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): return 0",
        "brute_source": "def solution(numbers):\n while True: pass",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "mixed failure",
        "model": "fake-generation",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    runner.script_responses.append(_script([True] * 3))
    runner.execute_responses.extend(
        [
            _results([0, 0, 0]),
            {"results": [{"id": "case-0", "status": "time_limit", "time_ms": 2000, "memory_kb": 10}]},
        ]
    )
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 49})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert [operation for operation, _ in ai.calls] == ["generate"]


def test_failed_repair_is_not_retried_and_usage_is_recorded(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): return [6]",
        "brute_source": "def solution(numbers): return [6]",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "wrong repair",
        "model": "fake-generation",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    ai.repair = {
        "output_format": "none",
        "reason": "변환 없음",
        "model": "fake-generation",
        "input_tokens": 4,
        "output_tokens": 2,
    }
    runner.script_responses.append(_script([True] * 3))
    runner.execute_responses.extend([_results([[6], [0], [12]]), _results([[6], [0], [12]])])
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 46})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert [operation for operation, _ in ai.calls].count("format_repair") == 1
    usage = client.get("/api/ai/usage").json()
    assert any(item["operation"] == "format_repair" and item["output_tokens"] == 2 for item in usage)


def test_generation_rejects_wrong_values_after_one_format_repair(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    ai.bundle = {
        "reference_source": "def solution(numbers): return [sum(numbers)]",
        "brute_source": "def solution(numbers): return [sum(numbers)]",
        "validator_source": "def main(payload): return [True for _ in payload]",
        "generator_source": "def main(payload): return []",
        "notes": "still wrong",
        "model": "fake-generation",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    ai.repair = {
        "output_format": "concat_decimal",
        "reason": "정수 목록 연결",
        "model": "fake-generation",
        "input_tokens": 4,
        "output_tokens": 2,
    }
    runner.script_responses.extend([_script([True] * 3), _script([True] * 3)])
    runner.execute_responses.extend(
        [
            _return_type_results(3),
            _return_type_results(3),
            _results([999, 999, 999]),
            _results([999, 999, 999]),
        ]
    )
    response = client.post(f"/api/problems/{problem['id']}/ai/generate", json={"seed": 48})
    job = client.get(f"/api/generation-jobs/{response.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["error"] == "출력 표현을 보정했지만 공개 예제의 기대값과 일치하지 않습니다. 예제 또는 문제 설명을 확인한 뒤 다시 준비하세요."
    assert [operation for operation, _ in ai.calls].count("format_repair") == 1


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
    assert [operation for operation, _ in ai.calls] == ["generate"]


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

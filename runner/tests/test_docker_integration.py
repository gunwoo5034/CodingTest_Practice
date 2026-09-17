from __future__ import annotations

import os
import threading
import time

import docker
import pytest

from runner.engine import DockerRunner
from runner.models import ExecuteRequest, ScriptRequest


pytestmark = pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="set RUN_DOCKER_TESTS=1 after building sandbox images")


@pytest.fixture(scope="module")
def runner():
    client = docker.from_env(timeout=15)
    client.ping()
    return DockerRunner(client)


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("python", "def solution(values): return sum(values)"),
        ("cpp", "long long solution(vector<long long> values) { long long total=0; for(auto v:values) total+=v; return total; }"),
        ("java", "public class Solution { public long solution(long[] values) { long total=0; for(long v:values) total+=v; return total; } }"),
        ("javascript", "function solution(values) { return values.reduce((a, b) => a + b, 0n); }"),
    ],
)
def test_all_languages_execute_int64_arrays_in_isolated_containers(runner, language, source):
    model = ExecuteRequest.model_validate(
        {
            "language": language,
            "source": source,
            "signature": {"parameters": [{"name": "values", "type": {"base": "long", "dimensions": 1}}], "return_type": {"base": "long", "dimensions": 0}},
            "cases": [{"id": "a", "args": [["9223372036854775800", "7"]]}, {"id": "b", "args": [["-8", "9"]]}],
            "limits": {"time_ms": 4000 if language == "java" else 2000, "memory_mb": 512 if language == "java" else 256, "output_kb": 64},
        }
    )
    response = runner.execute(model)
    assert [(item["status"], item["value"]) for item in response["results"]] == [("ok", "9223372036854775807"), ("ok", "1")]
    assert all(item["time_ms"] >= 0 and item["memory_kb"] > 0 for item in response["results"])


def test_each_case_gets_clean_python_process_and_script_runs_in_sandbox(runner):
    execute = ExecuteRequest.model_validate(
        {
            "language": "python",
            "source": "counter = 0\ndef solution(value):\n    global counter\n    counter += 1\n    return counter",
            "signature": {"parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}], "return_type": {"base": "int", "dimensions": 0}},
            "cases": [{"id": "one", "args": [1]}, {"id": "two", "args": [2]}],
            "limits": {"time_ms": 2000, "memory_mb": 256, "output_kb": 64},
        }
    )
    assert [item["value"] for item in runner.execute(execute)["results"]] == [1, 1]

    script = ScriptRequest.model_validate({"source": "def main(payload): return {'count': len(payload)}", "payload": [1, 2, 3], "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 64}})
    assert runner.script(script)["value"] == {"count": 3}


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("python", "def solution(numbers, labels, flags): return flags"),
        ("cpp", "vector<vector<bool>> solution(vector<vector<int>> numbers, vector<string> labels, vector<vector<bool>> flags) { return flags; }"),
        ("java", "public class Solution { public boolean[][] solution(int[][] numbers, String[] labels, boolean[][] flags) { return flags; } }"),
        ("javascript", "function solution(numbers, labels, flags) { return flags; }"),
    ],
)
def test_all_languages_preserve_strings_bool_and_jagged_two_dimensional_arrays(runner, language, source):
    model = ExecuteRequest.model_validate(
        {
            "language": language,
            "source": source,
            "signature": {
                "parameters": [
                    {"name": "numbers", "type": {"base": "int", "dimensions": 2}},
                    {"name": "labels", "type": {"base": "string", "dimensions": 1}},
                    {"name": "flags", "type": {"base": "bool", "dimensions": 2}},
                ],
                "return_type": {"base": "bool", "dimensions": 2},
            },
            "cases": [{"id": "typed", "args": [[[1, -2], []], ["한글", ""], [[True, False], []]]}],
            "limits": {"time_ms": 4000 if language == "java" else 2000, "memory_mb": 512 if language == "java" else 256, "output_kb": 64},
        }
    )
    result = runner.execute(model)["results"][0]
    assert (result["status"], result["value"]) == ("ok", [[True, False], []])


def test_runtime_limits_are_reported_and_containers_are_cleaned(runner):
    request = ExecuteRequest.model_validate(
        {
            "language": "python",
            "source": "def solution(value):\n    while True: print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')",
            "signature": {"parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}], "return_type": {"base": "int", "dimensions": 0}},
            "cases": [{"id": "spam", "args": [1]}],
            "limits": {"time_ms": 2000, "memory_mb": 256, "output_kb": 1},
        }
    )
    result = runner.execute(request)["results"][0]
    assert result["status"] == "output_limit"
    assert len(result["stdout"].encode()) <= 1024
    assert not runner._docker().containers.list(all=True, filters={"label": "com.loopcode.sandbox=true"})


def test_compile_and_time_failures_have_distinct_statuses(runner):
    base = {
        "language": "python",
        "signature": {"parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}], "return_type": {"base": "int", "dimensions": 0}},
        "cases": [{"id": "case", "args": [1]}],
        "limits": {"time_ms": 100, "memory_mb": 256, "output_kb": 64},
    }
    compile_error = runner.execute(ExecuteRequest.model_validate({**base, "source": "def solution(:"}))["results"][0]
    time_limit = runner.execute(ExecuteRequest.model_validate({**base, "source": "def solution(value):\n    while True: pass"}))["results"][0]
    assert compile_error["status"] == "compile_error"
    assert time_limit["status"] == "time_limit"


def test_runtime_cannot_write_root_or_see_network_socket_or_secret(runner):
    source = '''import os, socket
def solution(value):
    checks = []
    try:
        open('/forbidden', 'w').write('x')
        checks.append(False)
    except OSError:
        checks.append(True)
    checks.append(not os.path.exists('/var/run/docker.sock'))
    checks.append('OPENAI_API_KEY' not in os.environ)
    net = socket.socket()
    net.settimeout(0.2)
    try:
        net.connect(('1.1.1.1', 53))
        checks.append(False)
    except OSError:
        checks.append(True)
    return checks
'''
    request = ExecuteRequest.model_validate(
        {
            "language": "python",
            "source": source,
            "signature": {"parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}], "return_type": {"base": "bool", "dimensions": 1}},
            "cases": [{"id": "isolated", "args": [1]}],
            "limits": {"time_ms": 2000, "memory_mb": 256, "output_kb": 64},
        }
    )
    result = runner.execute(request)["results"][0]
    assert (result["status"], result["value"]) == ("ok", [True, True, True, True])


def test_result_frame_does_not_consume_user_output_budget(runner):
    returned = "y" * 100_000
    request = ExecuteRequest.model_validate(
        {
            "language": "python",
            "source": "def solution(value):\n    print('x' * 1000)\n    return 'y' * 100000",
            "signature": {"parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}], "return_type": {"base": "string", "dimensions": 0}},
            "cases": [{"id": "large-result", "args": [1]}],
            "limits": {"time_ms": 2000, "memory_mb": 256, "output_kb": 1},
        }
    )
    result = runner.execute(request)["results"][0]
    assert (result["status"], result["value"]) == ("ok", returned)
    assert result["stdout"] == "x" * 1000 + "\n"


def test_java_heap_exhaustion_is_memory_limit(runner):
    request = ExecuteRequest.model_validate(
        {
            "language": "java",
            "source": "public class Solution { public int solution(int value) { int[] data = new int[60000000]; return data.length; } }",
            "signature": {"parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}], "return_type": {"base": "int", "dimensions": 0}},
            "cases": [{"id": "heap", "args": [1]}],
            "limits": {"time_ms": 4000, "memory_mb": 128, "output_kb": 64},
        }
    )
    result = runner.execute(request)["results"][0]
    assert result["status"] == "memory_limit"
    assert "OutOfMemoryError" in result["stderr"]


def test_large_unread_stdin_cannot_block_wall_deadline(runner):
    request = ExecuteRequest.model_validate(
        {
            "language": "javascript",
            "source": "while (true) {}\nfunction solution(value) { return value.length; }",
            "signature": {"parameters": [{"name": "value", "type": {"base": "string", "dimensions": 0}}], "return_type": {"base": "int", "dimensions": 0}},
            "cases": [{"id": "blocked-stdin", "args": ["x" * (32 * 1024 * 1024)]}],
            "limits": {"time_ms": 100, "memory_mb": 256, "output_kb": 64},
        }
    )
    values: list[dict] = []
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            values.append(runner.execute(request))
        except BaseException as exc:
            errors.append(exc)

    started = time.monotonic()
    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    thread.join(5)
    if thread.is_alive():
        for container in runner._docker().containers.list(all=True, filters={"label": "com.loopcode.sandbox=true"}):
            container.remove(force=True)
        thread.join(2)
    assert not thread.is_alive(), "runner remained blocked writing stdin after its deadline"
    assert not errors
    assert values[0]["results"][0]["status"] == "time_limit"
    assert time.monotonic() - started < 5


def test_unread_stdin_within_public_request_budget_obeys_deadline(runner):
    request = ExecuteRequest.model_validate(
        {
            "language": "javascript",
            "source": "while (true) {}\nfunction solution(value) { return value.length; }",
            "signature": {"parameters": [{"name": "value", "type": {"base": "string", "dimensions": 0}}], "return_type": {"base": "int", "dimensions": 0}},
            "cases": [{"id": "public-budget", "args": ["x" * 1_500_000]}],
            "limits": {"time_ms": 100, "memory_mb": 256, "output_kb": 64},
        }
    )
    assert len(request.model_dump_json().encode()) < 2 * 1024 * 1024
    started = time.monotonic()
    result = runner.execute(request)["results"][0]
    assert result["status"] == "time_limit"
    assert time.monotonic() - started < 5

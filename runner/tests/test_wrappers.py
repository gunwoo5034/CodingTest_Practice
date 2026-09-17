from __future__ import annotations

import json

from runner.models import ExecuteRequest, ScriptRequest
from runner.wrappers import build_execute_bundle, build_script_bundle, parse_control_frame

from .test_models import request


def test_python_wrapper_round_trips_long_values_at_every_depth():
    model = ExecuteRequest.model_validate(
        request(
            source="def solution(values): return values",
            signature={
                "parameters": [{"name": "values", "type": {"base": "long", "dimensions": 2}}],
                "return_type": {"base": "long", "dimensions": 2},
            },
            cases=[{"id": "case-1", "args": [[["-9223372036854775808"], ["0", "9223372036854775807"]]]}],
        )
    )
    bundle = build_execute_bundle(model)
    assert bundle.compile_command == ["python", "-m", "py_compile", "/job/solution.py", "/job/harness.py"]
    assert bundle.runtime_command == ["python", "/job/harness.py"]
    compile(bundle.files["harness.py"], "harness.py", "exec")


def test_python_wrapper_reports_only_return_encoding_type_errors_as_private_failure():
    model = ExecuteRequest.model_validate(request(source="def solution(*args): return [3, 2, 2, 3, 1]"))
    harness = build_execute_bundle(model).files["harness.py"]
    assert b"except TypeError:" in harness
    assert b"'failure': 'return_type'" in harness
    assert b"result = solution.solution" in harness
    assert harness.index(b"result = solution.solution") < harness.index(b"try:\n    encoded = _encode")


def test_cpp_and_java_wrappers_call_the_contract_entrypoints_with_native_types():
    cpp = build_execute_bundle(ExecuteRequest.model_validate(request(language="cpp")))
    java = build_execute_bundle(ExecuteRequest.model_validate(request(language="java", limits={"time_ms": 4000, "memory_mb": 512, "output_kb": 64})))

    assert b"long long solution(int, vector<long long>, vector<vector<bool>>);" in cpp.files["harness.cpp"]
    assert b"solution(arg0, arg1, arg2)" in cpp.files["harness.cpp"]
    assert b"new Solution().solution(arg0, arg1, arg2)" in java.files["Harness.java"]
    assert b"catch (OutOfMemoryError error)" in java.files["Harness.java"]
    assert b'{\\"failure\\":\\"memory_limit\\"}' in java.files["Harness.java"]
    assert java.runtime_command[:3] == ["java", "-Xmx384m", "-cp"]


def test_script_bundle_calls_main_and_returns_untyped_json():
    model = ScriptRequest.model_validate({"source": "def main(payload): return payload", "payload": [1], "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 10}})
    bundle = build_script_bundle(model)
    assert b"solution.main(message['payload'])" in bundle.files["harness.py"]


def test_javascript_wrapper_uses_bigint_and_commonjs_solution_export():
    model = ExecuteRequest.model_validate(
        request(
            language="javascript",
            source="function solution(values) { return values; }",
            signature={
                "parameters": [{"name": "values", "type": {"base": "long", "dimensions": 2}}],
                "return_type": {"base": "long", "dimensions": 2},
            },
            cases=[{"id": "case-1", "args": [[["-9223372036854775808", "9223372036854775807"]]]}],
        )
    )
    bundle = build_execute_bundle(model)
    assert bundle.image == "loopcode-sandbox-javascript:latest"
    assert bundle.compile_command == ["sh", "-c", "node --check /job/solution.js && node --check /job/harness.js"]
    assert b"module.exports = { solution };" in bundle.files["solution.js"]
    assert b"BigInt(value)" in bundle.files["harness.js"]
    assert b"process.resourceUsage().maxRSS" in bundle.files["harness.js"]


def test_control_frame_is_removed_without_changing_user_logs():
    token = "abc123"
    control = {"value": ["9"], "time_ms": 1.25, "memory_kb": 321}
    stdout = b"user output without newline"
    stderr = b"warning" + f"\n__LOOPCODE_RESULT__{token}:".encode() + json.dumps(control).encode() + b"\n"

    parsed, clean_stdout, clean_stderr = parse_control_frame(stdout, stderr, token)

    assert parsed == control
    assert clean_stdout == stdout
    assert clean_stderr == b"warning"

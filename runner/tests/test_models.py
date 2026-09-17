from __future__ import annotations

import pytest
from pydantic import ValidationError

from runner.models import ExecuteRequest, ScriptRequest


SIGNATURE = {
    "parameters": [
        {"name": "count", "type": {"base": "int", "dimensions": 0}},
        {"name": "large", "type": {"base": "long", "dimensions": 1}},
        {"name": "flags", "type": {"base": "bool", "dimensions": 2}},
    ],
    "return_type": {"base": "long", "dimensions": 0},
}


def request(**overrides):
    value = {
        "language": "python",
        "source": "def solution(count, large, flags): return 0",
        "signature": SIGNATURE,
        "cases": [{"id": "case-1", "args": [1, ["0", "9223372036854775807"], [[True], []]]}],
        "limits": {"time_ms": 2000, "memory_mb": 256, "output_kb": 64},
    }
    value.update(overrides)
    return value


def test_execute_request_accepts_canonical_typed_values():
    parsed = ExecuteRequest.model_validate(request())
    assert parsed.cases[0].args[1] == ["0", "9223372036854775807"]


@pytest.mark.parametrize(
    "args",
    [
        [True, ["0"], [[True]]],
        [1, [0], [[True]]],
        [1, ["01"], [[True]]],
        [1, ["9223372036854775808"], [[True]]],
        [1, ["0"], [[1]]],
    ],
)
def test_execute_request_rejects_values_that_only_look_like_declared_types(args):
    with pytest.raises(ValidationError):
        ExecuteRequest.model_validate(request(cases=[{"id": "case-1", "args": args}]))


def test_execute_request_rejects_duplicate_case_ids_and_reserved_parameter_names():
    duplicate = request(cases=[{"id": "same", "args": [1, ["0"], [[True]]]}, {"id": "same", "args": [2, [], []]}])
    with pytest.raises(ValidationError):
        ExecuteRequest.model_validate(duplicate)

    bad_signature = {**SIGNATURE, "parameters": [{"name": "class", "type": {"base": "int", "dimensions": 0}}]}
    with pytest.raises(ValidationError):
        ExecuteRequest.model_validate(request(signature=bad_signature, cases=[{"id": "case-1", "args": [1]}]))


def test_language_limits_are_bounded_and_java_has_a_higher_memory_floor():
    with pytest.raises(ValidationError):
        ExecuteRequest.model_validate(request(limits={"time_ms": 49, "memory_mb": 256, "output_kb": 64}))
    with pytest.raises(ValidationError):
        ExecuteRequest.model_validate(request(language="java", limits={"time_ms": 2000, "memory_mb": 127, "output_kb": 64}))


def test_script_request_enforces_source_bytes_and_payload_budget():
    ScriptRequest.model_validate({"source": "def main(payload): return payload", "payload": {"한글": True}, "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 1024}})
    with pytest.raises(ValidationError):
        ScriptRequest.model_validate({"source": "가" * 100_000, "payload": None, "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 1}})

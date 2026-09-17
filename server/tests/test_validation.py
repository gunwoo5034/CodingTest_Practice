from __future__ import annotations

import pytest

from server.schemas import Signature
from server.validation import DomainValidationError, typed_equal, validate_args


def test_bool_is_not_accepted_as_int_and_long_requires_decimal_string():
    signature = Signature.model_validate(
        {
            "parameters": [
                {"name": "number", "type": {"base": "int", "dimensions": 0}},
                {"name": "large", "type": {"base": "long", "dimensions": 1}},
            ],
            "return_type": {"base": "bool", "dimensions": 0},
        }
    )
    with pytest.raises(DomainValidationError):
        validate_args([True, ["1"]], signature)
    with pytest.raises(DomainValidationError):
        validate_args([1, [1]], signature)
    validate_args([1, ["9223372036854775807", "-2"]], signature)
    assert not typed_equal(True, 1, signature.return_type)


def test_execution_runner_failure_is_a_failed_job(client, runner):
    from server.runner_client import RunnerUnavailable

    problem = client.get("/api/problems").json()[0]

    async def unavailable(_request):
        raise RunnerUnavailable("코드 실행 서비스를 사용할 수 없습니다. Docker 실행 상태를 확인하세요.")

    runner.execute = unavailable
    response = client.post(
        f"/api/problems/{problem['id']}/jobs",
        json={"mode": "run", "language": "python", "source": "def solution(numbers): return 0"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert "Docker" in response.json()["error"]


def test_openapi_public_models_do_not_expose_hidden_payload_fields(client):
    schema = client.get("/openapi.json").json()
    hidden = schema["components"]["schemas"]["HiddenResult"]
    assert set(hidden["properties"]) == {"id", "visibility", "status", "time_ms", "memory_kb"}
    problem = schema["components"]["schemas"]["ProblemPublic"]
    assert "reference_source" not in problem["properties"]
    assert "source_image" not in problem["properties"]

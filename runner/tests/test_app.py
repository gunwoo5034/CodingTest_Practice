from __future__ import annotations

from fastapi.testclient import TestClient

from runner.app import create_app
from runner.engine import DockerUnavailable

from .test_models import request


class FakeRunner:
    def health(self):
        return {"status": "ok", "docker_available": True, "detail": "Docker is available."}

    def execute(self, model):
        return {"results": [{"id": model.cases[0].id, "status": "ok", "value": "1", "stdout": "", "stderr": "", "time_ms": 1.0, "memory_kb": 10}]}

    def script(self, model):
        return {"status": "ok", "value": model.payload, "stdout": "", "stderr": "", "time_ms": 1.0, "memory_kb": 10}


def test_http_contract_has_execute_envelope_and_direct_script_result():
    client = TestClient(create_app(FakeRunner()))
    response = client.post("/execute", json=request())
    assert response.status_code == 200
    assert response.json()["results"][0]["id"] == "case-1"

    script = client.post("/script", json={"source": "def main(payload): return payload", "payload": [1], "limits": {"time_ms": 5000, "memory_mb": 256, "output_kb": 64}})
    assert script.status_code == 200
    assert script.json() == {"status": "ok", "value": [1], "stdout": "", "stderr": "", "time_ms": 1.0, "memory_kb": 10}


def test_oversized_request_is_rejected_before_runner_and_docker_failure_is_503():
    class BrokenRunner(FakeRunner):
        def execute(self, model):
            raise DockerUnavailable("socket unavailable")

    client = TestClient(create_app(BrokenRunner()))
    assert client.post("/execute", content=b"{" + b" " * (2 * 1024 * 1024), headers={"content-type": "application/json"}).status_code == 413
    response = client.post("/execute", json=request())
    assert response.status_code == 503
    assert "socket" not in response.json()["detail"].lower()

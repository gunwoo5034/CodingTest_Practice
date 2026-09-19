from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading


def _folder(client, name="그래프"):
    response = client.post("/api/folders", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _ok(case_id: str, value) -> dict:
    return {"id": case_id, "status": "ok", "value": value, "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 1}


def test_folder_crud_trims_names_counts_problems_and_rejects_duplicates(client):
    assert client.get("/api/folders").json() == []
    folder = _folder(client, "  Graph  ")
    assert folder == {"id": folder["id"], "name": "Graph", "problem_count": 0}
    assert client.post("/api/folders", json={"name": "graph"}).status_code == 409
    assert client.post("/api/folders", json={"name": "   "}).status_code == 422
    assert client.post("/api/folders", json={"name": "가" * 61}).status_code == 422
    other = _folder(client, "동적 계획법")
    assert client.patch(f"/api/folders/{other['id']}", json={"name": "gRaPh"}).status_code == 409

    problem = client.post(
        "/api/problems",
        json={
            "title": "폴더 문제",
            "folder_id": folder["id"],
            "signature": {
                "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
                "return_type": {"base": "int", "dimensions": 0},
            },
        },
    )
    assert problem.status_code == 201
    assert problem.json()["folder_id"] == folder["id"]
    assert client.get("/api/folders").json()[0]["problem_count"] == 1
    missing_problem = client.post(
        "/api/problems",
        json={
            "title": "없는 폴더",
            "folder_id": "missing",
            "signature": {
                "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
                "return_type": {"base": "int", "dimensions": 0},
            },
        },
    )
    assert missing_problem.status_code == 404

    renamed = client.patch(f"/api/folders/{folder['id']}", json={"name": "  탐색  "})
    assert renamed.status_code == 200
    assert renamed.json() == {"id": folder["id"], "name": "탐색", "problem_count": 1}
    assert client.patch("/api/folders/missing", json={"name": "없음"}).status_code == 404
    assert client.delete("/api/folders/missing").status_code == 404


def test_concurrent_casefold_duplicate_folder_creation_returns_conflict(client):
    entered = threading.Barrier(2)

    def create(name):
        entered.wait(timeout=5)
        return client.post("/api/folders", json={"name": name})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = [future.result(timeout=5) for future in [pool.submit(create, "DP"), pool.submit(create, "dp")]]

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert len(client.get("/api/folders").json()) == 1


def test_move_and_delete_folder_preserve_problem_data_and_completion(client, runner, ai):
    problem = client.get("/api/problems").json()[0]
    folder = _folder(client)
    before = client.get(f"/api/problems/{problem['id']}").json()
    draft = client.put(
        f"/api/problems/{problem['id']}/drafts/python",
        json={"source": "def solution(numbers): return sum(numbers)"},
    ).json()
    runner.execute_responses.append(
        {"results": [_ok(f"case-{index}", value) for index, value in enumerate([6, 0, 12, 9, -5])]}
    )
    client.post(
        f"/api/problems/{problem['id']}/jobs",
        json={"mode": "submit", "language": "python", "source": draft["source"]},
    )

    moved = client.put(f"/api/problems/{problem['id']}/folder", json={"folder_id": folder["id"]})
    assert moved.status_code == 200
    assert moved.json()["folder_id"] == folder["id"]
    assert moved.json()["status"] == before["status"]
    assert moved.json()["test_revision"] == before["test_revision"]
    assert moved.json()["tests"] == before["tests"]
    assert moved.json()["is_solved"] is True
    assert ai.calls == []
    assert client.get(f"/api/problems/{problem['id']}/drafts/python").json()["source"] == draft["source"]
    assert len(client.get(f"/api/problems/{problem['id']}/submissions").json()) == 1
    runner.script_responses.append(
        {"status": "ok", "value": [True], "stdout": "", "stderr": "", "time_ms": 1, "memory_kb": 1}
    )
    runner.execute_responses.append({"results": [_ok("case-0", 7)]})
    expected = client.post(
        f"/api/problems/{problem['id']}/tests/expected",
        json={"args": [[3, 4]], "current_expected": 0},
    )
    assert expected.json() == {"computed": 7, "matches_current": False}

    assert client.delete(f"/api/folders/{folder['id']}").status_code == 204
    after = client.get(f"/api/problems/{problem['id']}").json()
    assert after["folder_id"] is None
    assert after["status"] == before["status"]
    assert after["test_revision"] == before["test_revision"]
    assert after["tests"] == before["tests"]
    assert after["is_solved"] is True
    assert client.get(f"/api/problems/{problem['id']}/drafts/python").json()["source"] == draft["source"]
    assert len(client.get(f"/api/problems/{problem['id']}/submissions").json()) == 1


def test_folder_move_allows_null_rejects_missing_and_does_not_touch_generation(client, ai):
    problem = client.get("/api/problems").json()[0]
    folder = _folder(client)
    entered = threading.Event()
    release = threading.Event()

    async def blocked_generate(payload):
        ai.calls.append(("generate", payload))
        entered.set()
        await asyncio.to_thread(release.wait)
        raise RuntimeError("stop after move")

    ai.generate = blocked_generate
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"/api/problems/{problem['id']}/ai/generate", json={"seed": 77})
        assert entered.wait(timeout=5)
        generating = client.get(f"/api/problems/{problem['id']}").json()
        moved = client.put(f"/api/problems/{problem['id']}/folder", json={"folder_id": folder["id"]})
        assert moved.status_code == 200
        assert moved.json()["status"] == "generating"
        assert moved.json()["test_revision"] == generating["test_revision"]
        assert moved.json()["latest_generation_job_id"] == generating["latest_generation_job_id"]
        release.set()
        assert future.result(timeout=5).status_code == 202

    assert client.put(f"/api/problems/{problem['id']}/folder", json={"folder_id": "missing"}).status_code == 404
    cleared = client.put(f"/api/problems/{problem['id']}/folder", json={"folder_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["folder_id"] is None


def test_analyze_validates_folder_before_ai_and_survives_deletion_during_await(client, ai):
    missing = client.post("/api/problems/analyze", json={"text": "문제", "folder_id": "missing"})
    assert missing.status_code == 404
    assert ai.calls == []

    folder = _folder(client, "분석")
    ai.analysis = {
        "title": "분석 문제",
        "statement": "값을 반환하세요.",
        "constraints": [],
        "signature": {
            "parameters": [{"name": "value", "type": {"base": "int", "dimensions": 0}}],
            "return_type": {"base": "int", "dimensions": 0},
        },
        "examples": [{"args": [1], "expected": 1}],
        "model": "fake-analysis",
        "input_tokens": 1,
        "output_tokens": 1,
    }
    assigned = client.post(
        "/api/problems/analyze",
        json={"text": "값을 반환하세요.", "folder_id": folder["id"]},
    )
    assert assigned.status_code == 201
    assert assigned.json()["folder_id"] == folder["id"]
    assert ai.calls[-1][1] == {"text": "값을 반환하세요.", "image": None, "image_mime": None}

    deleted_folder = _folder(client, "삭제될 폴더")
    entered = threading.Event()
    release = threading.Event()
    original_analyze = ai.analyze

    async def blocked_analyze(payload):
        entered.set()
        await asyncio.to_thread(release.wait)
        return await original_analyze(payload)

    ai.analyze = blocked_analyze
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.post,
            "/api/problems/analyze",
            json={"text": "값을 반환하세요.", "folder_id": deleted_folder["id"]},
        )
        assert entered.wait(timeout=5)
        assert client.delete(f"/api/folders/{deleted_folder['id']}").status_code == 204
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 201
    assert response.json()["folder_id"] is None
    assert ai.calls[-1][1] == {"text": "값을 반환하세요.", "image": None, "image_mime": None}

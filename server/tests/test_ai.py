from __future__ import annotations


def test_missing_api_key_only_blocks_explicit_ai_route(tmp_path):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'no-key.db'}", openai_api_key="", run_jobs_inline=True)
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/api/problems").status_code == 200
        problem = client.get("/api/problems").json()[0]
        response = client.post(f"/api/problems/{problem['id']}/ai/chat", json={"mode": "hint", "message": "힌트"})
        assert response.status_code == 503
        assert "OPENAI_API_KEY" in response.json()["detail"]


def test_tutor_context_excludes_hidden_and_reference(client, ai):
    problem = client.get("/api/problems").json()[0]
    ai.reply = {"content": "누적합부터 생각해 보세요.", "input_tokens": 30, "output_tokens": 12, "model": "fake"}
    response = client.post(
        f"/api/problems/{problem['id']}/ai/chat",
        json={"mode": "hint", "message": "어떻게 시작하나요?", "language": "python", "source": "def solution(numbers): pass"},
    )
    assert response.status_code == 200
    payload = ai.calls[0][1]
    serialized = str(payload).lower()
    assert "hidden" not in serialized
    assert "reference" not in serialized
    assert len(payload["history"]) <= 6

    history = client.get(f"/api/problems/{problem['id']}/chat").json()
    assert history == [
        {
            "mode": "hint",
            "user_message": "어떻게 시작하나요?",
            "assistant_message": "누적합부터 생각해 보세요.",
            "model": "fake",
            "input_tokens": 30,
            "output_tokens": 12,
            "created_at": history[0]["created_at"],
        }
    ]

from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.ai_client import AIUnavailableWithUsage, OpenAIClient
from server.schemas import AIAnalysisOutput, AIFormatRepairOutput, AIGenerationOutput, AITutorOutput


class FakeResponses:
    def __init__(self, owner):
        self.owner = owner
        self.calls = owner.calls

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["text_format"]
        if schema is AIAnalysisOutput:
            parsed = schema(
                title="문제",
                statement="설명",
                example_explanation="1을 입력하면 1입니다.",
                constraints=[],
                signature_json='{"parameters":[{"name":"a","type":{"base":"long","dimensions":0}}],"return_type":{"base":"long","dimensions":0}}',
                examples_json='[{"args":["1"],"expected":"1"}]',
            )
        elif schema is AIGenerationOutput:
            parsed = schema(
                reference_source="def solution(a): return a",
                brute_source="def solution(a): return a",
                validator_source="def main(payload): return [True] * len(payload)",
                generator_source="def main(payload): return []",
                notes="test",
            )
        elif schema is AIFormatRepairOutput:
            parsed = schema(output_format="concat_decimal", reason="배열의 정수를 이어 붙입니다.")
        else:
            parsed = AITutorOutput(content="답변")
        return SimpleNamespace(
            output_parsed=None if schema is AIFormatRepairOutput and self.owner.incomplete_repair else parsed,
            usage=SimpleNamespace(input_tokens=2, output_tokens=3),
            model="fake-model",
        )


class FakeSDK:
    def __init__(self, owner):
        self.owner = owner
        self.responses = FakeResponses(owner)

    async def __aenter__(self):
        self.owner.entered += 1
        return self

    async def __aexit__(self, *_args):
        self.owner.exited += 1


class FakeFactory:
    def __init__(self):
        self.created = 0
        self.entered = 0
        self.exited = 0
        self.calls = []
        self.incomplete_repair = False

    def __call__(self, **_kwargs):
        self.created += 1
        return FakeSDK(self)


@pytest.mark.asyncio
async def test_openai_client_uses_request_scoped_sdk_and_explicit_generation_contract():
    factory = FakeFactory()
    client = OpenAIClient("key", "generation-model", "tutor-model", client_factory=factory)
    payload = {"signature": {"parameters": [], "return_type": {"base": "long", "dimensions": 0}}}
    await client.analyze({"text": "문제", "image": None, "image_mime": None})
    await client.generate(payload)
    repaired = await client.repair_output_format(
        {
            "signature": payload["signature"],
            "reference_source": "def solution(a): return [a]",
            "brute_source": "def solution(a): return [a]",
            "examples": [{"args": [[3, 2, 2, 3, 1]], "expected": 32231}],
        }
    )
    await client.tutor({"mode": "hint"})

    assert (factory.created, factory.entered, factory.exited) == (4, 4, 4)
    analysis_prompt = factory.calls[0]["input"][0]["content"]
    generation_prompt = factory.calls[1]["input"][0]["content"]
    repair_prompt = factory.calls[2]["input"][0]["content"]
    assert "examples_json" in analysis_prompt
    assert "10진 문자열" in analysis_prompt
    assert '"parameters"' in analysis_prompt
    assert '"name"' in analysis_prompt
    assert '"base"' in analysis_prompt
    assert '"dimensions"' in analysis_prompt
    assert "지원하지 않는" in analysis_prompt
    assert "추측" in analysis_prompt
    assert "example_explanation" in analysis_prompt
    assert "statement에는 문제 본문만" in analysis_prompt
    assert "해설이 없으면 빈 문자열" in analysis_prompt
    assert "seed/count/mode" in generation_prompt
    assert "정확한 bool 목록" in generation_prompt
    assert "10진 문자열" in generation_prompt
    assert "독립" in generation_prompt
    assert "경계" in generation_prompt
    assert "인자 배열" in generation_prompt
    assert "공개 예제" in generation_prompt
    assert "표현 규칙" in repair_prompt
    assert "알고리즘" in repair_prompt
    assert repaired["output_format"] == "concat_decimal"
    assert all(call["store"] is False for call in factory.calls)

    tutor_prompt = factory.calls[3]["input"][0]["content"]
    assert "hint" in tutor_prompt and "단계" in tutor_prompt
    assert "question" in tutor_prompt and "전체 풀이" in tutor_prompt
    assert "solution" in tutor_prompt and "정답 코드" in tutor_prompt
    tutor_payload = factory.calls[3]["input"][1]["content"]
    assert '"mode": "hint"' in tutor_payload


@pytest.mark.asyncio
async def test_incomplete_format_repair_carries_response_usage():
    factory = FakeFactory()
    factory.incomplete_repair = True
    client = OpenAIClient("key", "generation-model", "tutor-model", client_factory=factory)

    with pytest.raises(AIUnavailableWithUsage) as raised:
        await client.repair_output_format({"signature": {}, "examples": []})

    assert raised.value.usage == {
        "model": "fake-model",
        "input_tokens": 2,
        "output_tokens": 3,
    }

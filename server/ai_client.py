from __future__ import annotations

import base64
import json
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from server.schemas import AIAnalysisOutput, AIFormatRepairOutput, AIGenerationOutput, AITutorOutput


class AIUnavailable(RuntimeError):
    pass


class AIUnavailableWithUsage(AIUnavailable):
    def __init__(self, message: str, usage: dict) -> None:
        super().__init__(message)
        self.usage = usage


def _usage(response) -> dict:
    usage = response.usage
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
        "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
        "model": response.model,
    }


class OpenAIClient:
    def __init__(self, api_key: str, generation_model: str, tutor_model: str, client_factory=AsyncOpenAI) -> None:
        self.api_key = api_key
        self.generation_model = generation_model
        self.tutor_model = tutor_model
        self.client_factory = client_factory

    def _client(self):
        if not self.api_key:
            raise AIUnavailable("OPENAI_API_KEY를 설정한 뒤 다시 시도하세요.")
        return self.client_factory(api_key=self.api_key, max_retries=0, timeout=90)

    async def analyze(self, payload: dict) -> dict:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": payload.get("text") or "이미지의 문제를 분석하세요."}]
        if payload.get("image"):
            encoded = base64.b64encode(payload["image"]).decode()
            content.append({"type": "input_image", "image_url": f"data:{payload['image_mime']};base64,{encoded}", "detail": "high"})
        try:
            async with self._client() as client:
                response = await client.responses.parse(
                    model=self.generation_model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "한국어 함수 반환형 코딩 문제를 제공된 텍스트와 이미지에 실제로 보이는 내용에서만 추출하세요. 보이지 않는 제한사항, 예제, 함수 이름을 추측하지 마세요. "
                                "지원 타입은 int,long,string,bool 및 2차원 이하 배열입니다. 지원하지 않는 그 밖의 타입, 실수 오차, 다중 정답, 표준 입출력 문제라면 지원되는 문제인 것처럼 변환하지 말고 응답을 거부하세요. "
                                "signature_json의 구조 예시는 {\"parameters\":[{\"name\":\"numbers\",\"type\":{\"base\":\"int\",\"dimensions\":1}}],\"return_type\":{\"base\":\"int\",\"dimensions\":0}} 입니다. "
                                "이 예시의 이름과 타입을 복사하지 말고 실제 문제와 예제에 맞춰 name, base, dimensions를 선택하세요. 각 parameter에는 name과 type이 필요하고, type에는 base와 dimensions가 필요합니다. examples_json은 [{\"args\": [...], \"expected\": 값}] 배열 JSON 문자열이어야 합니다. "
                                "statement에는 문제 본문만 넣고 제한사항, 입출력 예 표, 입출력 예 설명을 중복해서 넣지 마세요. constraints에는 제한사항만, examples_json에는 입출력 예 표의 입력과 결과만 넣으세요. "
                                "example_explanation에는 원문에 명시된 입출력 예 설명만 Markdown으로 옮기세요. 해설이 없으면 빈 문자열을 반환하고 새 해설을 만들지 마세요. "
                                "long은 API 경계에서 배열 내부까지 정규 10진 문자열로 표현하고, int와 bool을 구분하세요. JSON 문자열 필드는 유효한 JSON만 반환하세요."
                            ),
                        },
                        {"role": "user", "content": content},
                    ],
                    text_format=AIAnalysisOutput,
                    store=False,
                    max_output_tokens=5000,
                )
        except OpenAIError as exc:
            raise AIUnavailable("OpenAI 문제 분석 요청에 실패했습니다.") from exc
        if response.output_parsed is None:
            raise AIUnavailable("AI가 분석 결과를 완성하지 못했습니다.")
        return {**response.output_parsed.model_dump(), **_usage(response)}

    async def generate(self, payload: dict) -> dict:
        try:
            async with self._client() as client:
                response = await client.responses.parse(
                    model=self.generation_model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "Python 함수 반환형 문제의 검증 자산을 작성하세요. reference_source와 brute_source는 solution 함수를 정의하며 runner가 변환한 네이티브 인자를 받습니다. "
                                "payload.signature의 각 parameter 순서와 차원을 정확히 따르세요. payload.examples의 각 args는 항상 순서 있는 인자 배열이므로 매개변수가 하나이고 그 값이 배열인 경우에도 [[...]] 형태입니다. "
                                "payload.examples의 공개 예제 기대값 표현과 반환 타입을 기준으로 두 풀이, validator, generator가 같은 입출력 계약을 지키게 하세요. "
                                "brute_source는 reference_source와 독립적인 작은 입력용 단순 알고리즘이어야 하며 같은 구현을 복사하거나 위임하면 안 됩니다. "
                                "validator_source는 main(payload)를 정의하고 payload로 순서 있는 인자 배열들의 목록을 받아 각 입력의 제한사항 충족 여부를 정확한 bool 목록으로 같은 길이에 맞춰 반환합니다. "
                                "generator_source는 main(payload)를 정의하며 payload는 seed/count/mode 키를 갖고, count개의 순서 있는 인자 배열 목록을 반환합니다. mode는 small 또는 hidden입니다. "
                                "small은 독립 풀이 교차 검증에 적합한 다양한 작은 입력을 만들고, hidden은 최소·최대 경계, 빈 값, 중복, 특수 조건, 무작위와 가능한 큰 입력을 문제 제한 안에서 다양하게 포함해야 합니다. "
                                "생성기와 검증기의 long 값은 중첩 배열에서도 API 경계 규칙에 따라 정규 10진 문자열이어야 하며 solution 안에서는 Python int입니다. "
                                "외부 패키지, 파일, 네트워크를 사용하지 마세요."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    text_format=AIGenerationOutput,
                    store=False,
                    max_output_tokens=12000,
                )
        except OpenAIError as exc:
            raise AIUnavailable("OpenAI 테스트 생성 요청에 실패했습니다.") from exc
        if response.output_parsed is None:
            raise AIUnavailable("AI가 테스트 생성 결과를 완성하지 못했습니다.")
        return {**response.output_parsed.model_dump(), **_usage(response)}

    async def repair_output_format(self, payload: dict) -> dict:
        try:
            async with self._client() as client:
                response = await client.responses.parse(
                    model=self.generation_model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "두 독립 풀이의 계산 알고리즘이나 소스를 고치지 말고, 모든 공개 예제에 공통으로 적용되는 반환 표현 규칙 하나만 선택하세요. "
                                "상수 반환이나 기대값 하드코딩을 유도하지 마세요. 허용 규칙은 none, concat_decimal, space_separated, comma_separated, json_array뿐입니다. "
                                "계산 결과가 1차원 정수 목록 또는 튜플일 때만 표현 변환이 가능합니다. 이미 선언된 scalar 타입이면 원값을 유지합니다. "
                                "concat_decimal은 int, long, string scalar에만, 나머지 구분 규칙은 string scalar에만 맞습니다. bool, float, 중첩 배열은 변환할 수 없습니다. "
                                "소스와 공개 예제 전체로 한 규칙을 확신할 수 없거나 계산 자체가 틀렸다면 none을 선택하세요. reason은 짧게 작성하세요."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    text_format=AIFormatRepairOutput,
                    store=False,
                    max_output_tokens=600,
                )
        except OpenAIError as exc:
            raise AIUnavailable("OpenAI 출력 형식 진단 요청에 실패했습니다.") from exc
        if response.output_parsed is None:
            raise AIUnavailableWithUsage("AI가 출력 형식 진단을 완성하지 못했습니다.", _usage(response))
        return {**response.output_parsed.model_dump(), **_usage(response)}

    async def tutor(self, payload: dict) -> dict:
        try:
            async with self._client() as client:
                response = await client.responses.parse(
                    model=self.tutor_model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "당신은 한국어 코딩 연습 도우미입니다. payload의 현재 language와 source를 기준으로 답하세요. "
                                "mode=hint이면 한 번에 다음 단계만 생각하도록 점진적 힌트를 주고 전체 풀이 또는 정답 코드를 먼저 제공하지 마세요. "
                                "mode=question이면 사용자가 선택한 질문 주제에 직접 답하되 요청하지 않은 전체 풀이와 정답 코드를 제공하지 마세요. "
                                "mode=solution일 때만 완전한 풀이 설명과 현재 언어의 정답 코드를 제공하세요. "
                                "어떤 모드에서도 숨겨진 테스트나 저장된 기준 풀이를 추측하거나 언급하지 마세요."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    text_format=AITutorOutput,
                    store=False,
                    max_output_tokens=4000,
                )
        except OpenAIError as exc:
            raise AIUnavailable("OpenAI 도우미 요청에 실패했습니다.") from exc
        if response.output_parsed is None:
            raise AIUnavailable("AI가 답변을 완성하지 못했습니다.")
        return {**response.output_parsed.model_dump(), **_usage(response)}

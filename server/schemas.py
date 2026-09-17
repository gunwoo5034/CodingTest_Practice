from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator
from pydantic.json_schema import SkipJsonSchema


Language = Literal["python", "cpp", "java", "javascript"]
BaseType = Literal["int", "long", "string", "bool"]
OutputFormat = Literal["none", "concat_decimal", "space_separated", "comma_separated", "json_array"]


def _as_utc(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, BeforeValidator(_as_utc)]
OmittableTitle = Annotated[str, Field(min_length=1, max_length=200)] | SkipJsonSchema[None]
OmittableStatement = Annotated[str, Field(max_length=100_000)] | SkipJsonSchema[None]
OmittableExampleExplanation = Annotated[str, Field(max_length=100_000)] | SkipJsonSchema[None]
OmittableConstraints = Annotated[list[str], Field(max_length=100)] | SkipJsonSchema[None]
OmittableTimeLimit = Annotated[int, Field(ge=100, le=10_000)] | SkipJsonSchema[None]
OmittableMemoryLimit = Annotated[int, Field(ge=32, le=1024)] | SkipJsonSchema[None]


class TypeDescriptor(BaseModel):
    base: BaseType
    dimensions: Literal[0, 1, 2]


class Parameter(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: TypeDescriptor


class Signature(BaseModel):
    parameters: list[Parameter] = Field(min_length=1, max_length=12)
    return_type: TypeDescriptor

    @model_validator(mode="after")
    def unique_parameters(self):
        names = [item.name for item in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("매개변수 이름은 중복될 수 없습니다.")
        return self


class TestCasePublic(BaseModel):
    id: str
    kind: Literal["public", "user"]
    position: int
    args: list[Any]
    expected: Any
    suite_version: int


class ProblemSummary(BaseModel):
    id: str
    title: str
    status: Literal["draft", "analyzed", "generating", "ready", "needs_review"]
    test_revision: int
    updated_at: UTCDateTime
    is_solved: bool = False


class ProblemPublic(ProblemSummary):
    statement: str
    example_explanation: str = Field(max_length=100_000)
    constraints: list[str]
    signature: Signature
    templates: dict[Language, str]
    time_limit_ms: int
    memory_limit_mb: int
    tests: list[TestCasePublic]
    latest_generation_job_id: str | None = None
    generation_error: str | None = None
    output_format: OutputFormat | None


class ProblemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(default="", max_length=100_000)
    example_explanation: str = Field(default="", max_length=100_000)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    signature: Signature
    source_text: str | None = Field(default=None, max_length=100_000)


class ProblemUpdate(BaseModel):
    title: OmittableTitle = None
    statement: OmittableStatement = None
    example_explanation: OmittableExampleExplanation = None
    constraints: OmittableConstraints = None
    signature: Signature | SkipJsonSchema[None] = None
    time_limit_ms: OmittableTimeLimit = None
    memory_limit_mb: OmittableMemoryLimit = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if isinstance(value, dict):
            null_fields = [name for name, item in value.items() if name in cls.model_fields and item is None]
            if null_fields:
                raise ValueError(f"명시적인 null은 허용되지 않습니다: {', '.join(null_fields)}")
        return value


class TestCaseCreate(BaseModel):
    kind: Literal["public", "user"] = "user"
    args: list[Any]
    expected: Any


class TestCaseUpdate(BaseModel):
    args: list[Any] | None = None
    expected: Any | None = None


class DraftWrite(BaseModel):
    source: str = Field(max_length=262_144)


class DraftPublic(BaseModel):
    language: Language
    source: str
    updated_at: UTCDateTime


class JobCreate(BaseModel):
    mode: Literal["run", "submit"]
    language: Language
    source: str = Field(min_length=1, max_length=262_144)


class VisibleResult(BaseModel):
    id: str
    visibility: Literal["public", "user"]
    status: Literal["passed", "wrong_answer", "compile_error", "runtime_error", "time_limit", "memory_limit", "output_limit", "system_error"]
    expected: Any = None
    actual: Any = None
    stdout: str = ""
    stderr: str = ""
    time_ms: float = 0
    memory_kb: int = 0


class HiddenResult(BaseModel):
    id: str
    visibility: Literal["hidden"]
    status: Literal["passed", "wrong_answer", "compile_error", "runtime_error", "time_limit", "memory_limit", "output_limit", "system_error"]
    time_ms: float = 0
    memory_kb: int = 0


class ExecutionSummary(BaseModel):
    passed: int
    total: int
    all_passed: bool
    max_time_ms: float
    max_memory_kb: int


class JobPublic(BaseModel):
    id: str
    problem_id: str
    mode: Literal["run", "submit"]
    language: Language
    source: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    test_revision: int
    results: list[VisibleResult | HiddenResult] = Field(default_factory=list)
    summary: ExecutionSummary | None = None
    error: str | None = None
    created_at: UTCDateTime
    finished_at: UTCDateTime | None = None


class ExpectedCompute(BaseModel):
    args: list[Any]
    current_expected: Any | None = None


class ExpectedResult(BaseModel):
    computed: Any
    matches_current: bool | None


class AnalyzeRequest(BaseModel):
    text: str | None = Field(default=None, max_length=100_000)
    image_base64: str | None = Field(default=None, max_length=14_000_000)
    image_mime: Literal["image/png", "image/jpeg", "image/webp"] | None = None

    @model_validator(mode="after")
    def has_input(self):
        if not self.text and not self.image_base64:
            raise ValueError("문제 텍스트 또는 이미지를 입력하세요.")
        if bool(self.image_base64) != bool(self.image_mime):
            raise ValueError("이미지와 이미지 형식을 함께 입력하세요.")
        return self


class GenerationSummary(BaseModel):
    small_crosscheck_count: int
    hidden_count: int
    model: str
    output_format: OutputFormat | None = None
    format_repair_attempted: bool = False


class GenerationJobPublic(BaseModel):
    id: str
    problem_id: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    test_revision: int
    summary: GenerationSummary | None = None
    error: str | None = None
    created_at: UTCDateTime
    finished_at: UTCDateTime | None = None


class TutorRequest(BaseModel):
    mode: Literal["hint", "question", "solution"]
    message: str = Field(min_length=1, max_length=10_000)
    language: Language | None = None
    source: str | None = Field(default=None, max_length=262_144)


class TutorResponse(BaseModel):
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class ChatTurnPublic(BaseModel):
    mode: Literal["hint", "question", "solution"]
    user_message: str
    assistant_message: str
    model: str
    input_tokens: int
    output_tokens: int
    created_at: UTCDateTime


class AIUsagePublic(BaseModel):
    operation: Literal["analyze", "generate", "format_repair", "tutor"]
    model: str
    input_tokens: int
    output_tokens: int
    created_at: UTCDateTime


class HealthPublic(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok"]
    runner_configured: bool
    runner_available: bool
    ai_configured: bool
    detail: str


# Strict structured-output models use JSON strings for domain values because
# OpenAI strict schemas cannot express signature-dependent JSON values.
class AIAnalysisOutput(BaseModel):
    title: str
    statement: str
    example_explanation: str = Field(max_length=100_000)
    constraints: list[str]
    signature_json: str
    examples_json: str


class AIGenerationOutput(BaseModel):
    reference_source: str
    brute_source: str
    validator_source: str
    generator_source: str
    notes: str


class AIFormatRepairOutput(BaseModel):
    output_format: OutputFormat
    reason: str = Field(max_length=500)


class AITutorOutput(BaseModel):
    content: str

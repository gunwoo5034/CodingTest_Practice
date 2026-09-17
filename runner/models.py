from __future__ import annotations

import json
import keyword
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator


SOURCE_LIMIT = 256 * 1024
REQUEST_LIMIT = 2 * 1024 * 1024
ARTIFACT_LIMIT = 32 * 1024 * 1024

BaseType = Literal["int", "long", "string", "bool"]
Language = Literal["python", "cpp", "java", "javascript"]
Status = Literal["ok", "compile_error", "runtime_error", "time_limit", "memory_limit", "output_limit", "system_error"]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = set(keyword.kwlist) | {
    "alignas", "alignof", "and", "asm", "auto", "bitand", "bitor", "break", "case", "catch", "char",
    "class", "compl", "concept", "const", "consteval", "constexpr", "constinit", "const_cast", "continue",
    "co_await", "co_return", "co_yield", "decltype", "default", "delete", "do", "double", "dynamic_cast",
    "else", "enum", "explicit", "export", "extern", "false", "final", "float", "for", "friend", "goto",
    "if", "implements", "import", "instanceof", "interface", "long", "module", "mutable", "namespace", "native",
    "new", "noexcept", "not", "nullptr", "operator", "or", "override", "package", "private", "protected",
    "public", "record", "register", "reinterpret_cast", "requires", "return", "sealed", "short", "signed",
    "sizeof", "static", "static_assert", "static_cast", "strictfp", "struct", "super", "switch", "synchronized",
    "template", "this", "thread_local", "throw", "throws", "transient", "true", "try", "typedef", "typeid",
    "typename", "union", "unsigned", "using", "var", "virtual", "void", "volatile", "while", "with", "xor",
    "yield", "arguments", "await", "debugger", "eval", "extends", "let", "of",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TypeDescriptor(StrictModel):
    base: BaseType
    dimensions: Literal[0, 1, 2]


class Parameter(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=80)
    type: TypeDescriptor

    @field_validator("name")
    @classmethod
    def portable_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value) or value in _RESERVED:
            raise ValueError("parameter name must be a portable non-reserved identifier")
        return value


class Signature(StrictModel):
    parameters: list[Parameter] = Field(min_length=1, max_length=12)
    return_type: TypeDescriptor

    @model_validator(mode="after")
    def unique_names(self):
        names = [item.name for item in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        return self


class Limits(StrictModel):
    time_ms: StrictInt = Field(ge=50, le=10_000)
    memory_mb: StrictInt = Field(ge=32, le=1024)
    output_kb: StrictInt = Field(ge=1, le=1024)


class ExecuteCase(StrictModel):
    id: StrictStr = Field(min_length=1, max_length=200)
    args: list[Any]


class ExecuteRequest(StrictModel):
    language: Language
    source: StrictStr = Field(min_length=1)
    signature: Signature
    cases: list[ExecuteCase] = Field(min_length=1, max_length=100)
    limits: Limits

    @field_validator("source")
    @classmethod
    def source_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > SOURCE_LIMIT:
            raise ValueError("source exceeds 256KiB")
        return value

    @model_validator(mode="after")
    def contract_checks(self):
        if self.language == "java" and self.limits.memory_mb < 128:
            raise ValueError("Java requires at least 128MB")
        ids = [item.id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique")
        for case in self.cases:
            if len(case.args) != len(self.signature.parameters):
                raise ValueError("case argument count does not match signature")
            for value, parameter in zip(case.args, self.signature.parameters, strict=True):
                validate_wire_value(value, parameter.type)
        return self


class ScriptRequest(StrictModel):
    source: StrictStr = Field(min_length=1)
    payload: Any
    limits: Limits

    @model_validator(mode="after")
    def size_checks(self):
        if len(self.source.encode("utf-8")) > SOURCE_LIMIT:
            raise ValueError("source exceeds 256KiB")
        encoded = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > REQUEST_LIMIT:
            raise ValueError("payload exceeds 2MiB")
        return self


class ExecutionResult(StrictModel):
    id: str | None = None
    status: Status
    value: Any = None
    stdout: str = ""
    stderr: str = ""
    time_ms: float = 0.0
    memory_kb: int = 0


def validate_wire_value(value: Any, descriptor: TypeDescriptor) -> None:
    if descriptor.dimensions:
        if type(value) is not list:
            raise ValueError("array value required")
        child = TypeDescriptor(base=descriptor.base, dimensions=descriptor.dimensions - 1)
        for item in value:
            validate_wire_value(item, child)
        return
    if descriptor.base == "bool":
        valid = type(value) is bool
    elif descriptor.base == "string":
        valid = type(value) is str
    elif descriptor.base == "int":
        valid = type(value) is int and -(2**31) <= value < 2**31
    else:
        valid = type(value) is str and _canonical_long(value)
    if not valid:
        raise ValueError(f"invalid {descriptor.base} value")


def _canonical_long(value: str) -> bool:
    try:
        parsed = int(value)
    except ValueError:
        return False
    return str(parsed) == value and -(2**63) <= parsed < 2**63

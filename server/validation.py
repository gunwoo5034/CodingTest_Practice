from __future__ import annotations

from typing import Any

from server.schemas import Signature, TypeDescriptor


class DomainValidationError(ValueError):
    pass


def require_all_true(value: Any, expected_length: int) -> None:
    if not isinstance(value, list) or len(value) != expected_length:
        raise DomainValidationError("검증기가 입력 개수와 같은 불리언 목록을 반환해야 합니다.")
    if any(type(item) is not bool or item is not True for item in value):
        raise DomainValidationError("문제 제한사항을 만족하지 않는 입력이 있습니다.")


def validate_value(value: Any, descriptor: TypeDescriptor, path: str = "값") -> None:
    if descriptor.dimensions:
        if not isinstance(value, list):
            raise DomainValidationError(f"{path}: 배열이어야 합니다.")
        nested = TypeDescriptor(base=descriptor.base, dimensions=descriptor.dimensions - 1)
        for index, item in enumerate(value):
            validate_value(item, nested, f"{path}[{index}]")
        return
    if descriptor.base == "bool":
        valid = isinstance(value, bool)
    elif descriptor.base == "string":
        valid = isinstance(value, str)
    elif descriptor.base == "int":
        valid = isinstance(value, int) and not isinstance(value, bool) and -(2**31) <= value < 2**31
    else:
        valid = isinstance(value, str) and _is_long(value)
    if not valid:
        expectation = {"bool": "불리언", "string": "문자열", "int": "32비트 정수", "long": "문자열로 인코딩한 64비트 정수"}[descriptor.base]
        raise DomainValidationError(f"{path}: {expectation} 형식이 아닙니다.")


def _is_long(value: str) -> bool:
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        return False
    return str(parsed) == value and -(2**63) <= parsed < 2**63


def validate_args(args: list[Any], signature: Signature) -> None:
    if len(args) != len(signature.parameters):
        raise DomainValidationError(f"인자 개수는 {len(signature.parameters)}개여야 합니다.")
    for value, parameter in zip(args, signature.parameters, strict=True):
        validate_value(value, parameter.type, parameter.name)


def validate_case(args: list[Any], expected: Any, signature: Signature) -> None:
    validate_args(args, signature)
    validate_value(expected, signature.return_type, "기대값")


def typed_equal(left: Any, right: Any, descriptor: TypeDescriptor) -> bool:
    try:
        validate_value(left, descriptor)
        validate_value(right, descriptor)
    except DomainValidationError:
        return False
    if descriptor.dimensions:
        if len(left) != len(right):
            return False
        nested = TypeDescriptor(base=descriptor.base, dimensions=descriptor.dimensions - 1)
        return all(typed_equal(a, b, nested) for a, b in zip(left, right, strict=True))
    return type(left) is type(right) and left == right

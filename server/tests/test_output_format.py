from __future__ import annotations

import pytest

from server.output_format import build_output_format_wrapper


def _solution(source: str, rule: str, return_base: str):
    namespace: dict = {}
    exec(build_output_format_wrapper(source, rule, return_base), namespace)
    return namespace["solution"]


def test_concat_decimal_formats_integer_sequence_and_preserves_matching_scalar():
    sequence = _solution("def solution(): return [3, 2, 2, 3, 1]", "concat_decimal", "int")
    scalar = _solution("def solution(): return 32231", "concat_decimal", "int")
    assert sequence() == 32231
    assert scalar() == 32231


def test_concat_decimal_handles_two_digit_zero_and_long_or_string_targets():
    source = "def solution(): return [12, 0, 3]"
    assert _solution(source, "concat_decimal", "int")() == 1203
    assert _solution(source, "concat_decimal", "long")() == 1203
    assert _solution("def solution(): return [0, 2]", "concat_decimal", "string")() == "02"


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("space_separated", "3 2 2 3 1"),
        ("comma_separated", "3,2,2,3,1"),
        ("json_array", "[3,2,2,3,1]"),
    ],
)
def test_string_format_rules(rule, expected):
    solution = _solution("def solution(): return (3, 2, 2, 3, 1)", rule, "string")
    assert solution() == expected


def test_wrapper_keeps_original_namespace_for_recursive_solution():
    source = (
        "def flatten(values):\n"
        "    if not values: return []\n"
        "    return [values[0]] + flatten(values[1:])\n"
        "def solution(values): return flatten(values)\n"
    )
    assert _solution(source, "concat_decimal", "int")([3, 2, 2, 3, 1]) == 32231


@pytest.mark.parametrize(
    ("source", "rule", "return_base"),
    [
        ("def solution(): return [True, 2]", "concat_decimal", "int"),
        ("def solution(): return [1.5, 2]", "concat_decimal", "int"),
        ("def solution(): return [[1], [2]]", "concat_decimal", "int"),
        ("def solution(): return [1, 2]", "space_separated", "int"),
        ("def solution(): return [1, -2]", "concat_decimal", "int"),
    ],
)
def test_wrapper_rejects_unsafe_or_incompatible_coercion(source, rule, return_base):
    with pytest.raises((TypeError, ValueError)):
        _solution(source, rule, return_base)()


def test_none_rule_is_not_a_wrapper():
    with pytest.raises(ValueError, match="none"):
        build_output_format_wrapper("def solution(): return [1]", "none", "int")

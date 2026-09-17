from __future__ import annotations

from typing import Literal


OutputFormat = Literal["none", "concat_decimal", "space_separated", "comma_separated", "json_array"]


def build_output_format_wrapper(source: str, output_format: OutputFormat, return_base: str) -> str:
    """Build trusted adapter code; the returned source is executed only by the runner."""
    if output_format == "none":
        raise ValueError("none 출력 형식은 반환값을 보정하지 않습니다.")
    if return_base not in {"int", "long", "string"}:
        raise ValueError("이 반환 타입에는 출력 형식 보정을 적용할 수 없습니다.")
    if output_format != "concat_decimal" and return_base != "string":
        raise ValueError("선택한 출력 형식은 문자열 반환 문제에만 사용할 수 있습니다.")

    return f'''import json as _loopcode_json

_loopcode_original_namespace = {{"__name__": "_loopcode_original_solution"}}
exec({source!r}, _loopcode_original_namespace)
_loopcode_original_solution = _loopcode_original_namespace.get("solution")
if not callable(_loopcode_original_solution):
    raise TypeError("solution function required")

def _loopcode_format_result(value):
    if {return_base!r} == "string" and type(value) is str:
        return value
    if {return_base!r} in {{"int", "long"}} and type(value) is int:
        return value
    if type(value) not in {{list, tuple}} or not value:
        raise TypeError("output format repair requires a non-empty integer sequence")
    if any(type(item) is not int for item in value):
        raise TypeError("output format repair accepts only a one-dimensional integer sequence")
    if {output_format!r} == "concat_decimal":
        rendered = "".join(str(item) for item in value)
    elif {output_format!r} == "space_separated":
        rendered = " ".join(str(item) for item in value)
    elif {output_format!r} == "comma_separated":
        rendered = ",".join(str(item) for item in value)
    elif {output_format!r} == "json_array":
        rendered = _loopcode_json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        raise TypeError("unsupported output format repair")
    return int(rendered) if {return_base!r} in {{"int", "long"}} else rendered

def solution(*args):
    return _loopcode_format_result(_loopcode_original_solution(*args))
'''

from __future__ import annotations

from server.schemas import Signature, TypeDescriptor


def _cpp_type(item: TypeDescriptor) -> str:
    base = {"int": "int", "long": "long long", "string": "string", "bool": "bool"}[item.base]
    for _ in range(item.dimensions):
        base = f"vector<{base}>"
    return base


def _java_type(item: TypeDescriptor) -> str:
    base = {"int": "int", "long": "long", "string": "String", "bool": "boolean"}[item.base]
    return base + "[]" * item.dimensions


def templates_for(signature: Signature) -> dict[str, str]:
    py_params = ", ".join(item.name for item in signature.parameters)
    cpp_params = ", ".join(f"{_cpp_type(item.type)} {item.name}" for item in signature.parameters)
    java_params = ", ".join(f"{_java_type(item.type)} {item.name}" for item in signature.parameters)
    return {
        "python": f"def solution({py_params}):\n    pass\n",
        "cpp": f"{_cpp_type(signature.return_type)} solution({cpp_params}) {{\n    // 코드를 작성하세요.\n}}\n",
        "java": f"class Solution {{\n    public {_java_type(signature.return_type)} solution({java_params}) {{\n        // 코드를 작성하세요.\n    }}\n}}\n",
    }

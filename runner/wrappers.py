from __future__ import annotations

import json
from dataclasses import dataclass

from runner.models import ExecuteRequest, ScriptRequest, TypeDescriptor


CONTROL_PREFIX = "__LOOPCODE_RESULT__"


@dataclass(frozen=True)
class Bundle:
    image: str
    files: dict[str, bytes]
    compile_command: list[str]
    runtime_command: list[str]


def build_execute_bundle(request: ExecuteRequest) -> Bundle:
    if request.language == "python":
        descriptors = {
            "parameters": [item.type.model_dump() for item in request.signature.parameters],
            "return_type": request.signature.return_type.model_dump(),
        }
        return Bundle(
            image="loopcode-sandbox-python:latest",
            files={"solution.py": request.source.encode(), "harness.py": _python_harness(descriptors, script=False).encode()},
            compile_command=["python", "-m", "py_compile", "/job/solution.py", "/job/harness.py"],
            runtime_command=["python", "/job/harness.py"],
        )
    if request.language == "cpp":
        return Bundle(
            image="loopcode-sandbox-cpp:latest",
            files={"solution.cpp": ("#include <bits/stdc++.h>\nusing namespace std;\n" + request.source).encode(), "harness.cpp": _cpp_harness(request).encode()},
            compile_command=["g++", "-std=c++17", "-O2", "-pipe", "/job/solution.cpp", "/job/harness.cpp", "-o", "/job/program"],
            runtime_command=["/job/program"],
        )
    if request.language == "javascript":
        descriptors = {
            "parameters": [item.type.model_dump() for item in request.signature.parameters],
            "return_type": request.signature.return_type.model_dump(),
        }
        source = request.source + "\nmodule.exports = { solution };\n"
        return Bundle(
            image="loopcode-sandbox-javascript:latest",
            files={"solution.js": source.encode(), "harness.js": _javascript_harness(descriptors).encode()},
            compile_command=["sh", "-c", "node --check /job/solution.js && node --check /job/harness.js"],
            runtime_command=["node", "/job/harness.js"],
        )
    memory = max(32, request.limits.memory_mb * 3 // 4)
    return Bundle(
        image="loopcode-sandbox-java:latest",
        files={"Solution.java": request.source.encode(), "Harness.java": _java_harness(request).encode()},
        compile_command=["javac", "-cp", "/usr/share/java/gson.jar", "/job/Solution.java", "/job/Harness.java"],
        runtime_command=["java", f"-Xmx{memory}m", "-cp", "/job:/usr/share/java/gson.jar", "Harness"],
    )


def build_script_bundle(request: ScriptRequest) -> Bundle:
    return Bundle(
        image="loopcode-sandbox-python:latest",
        files={"solution.py": request.source.encode(), "harness.py": _python_harness(None, script=True).encode()},
        compile_command=["python", "-m", "py_compile", "/job/solution.py", "/job/harness.py"],
        runtime_command=["python", "/job/harness.py"],
    )


def parse_control_frame(stdout: bytes, stderr: bytes, token: str) -> tuple[dict | None, bytes, bytes]:
    marker = ("\n" + CONTROL_PREFIX + token + ":").encode()
    index = stderr.rfind(marker)
    if index < 0:
        return None, stdout, stderr
    end = stderr.find(b"\n", index + len(marker))
    if end < 0:
        return None, stdout, stderr
    try:
        value = json.loads(stderr[index + len(marker) : end])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, stdout, stderr
    if not isinstance(value, dict):
        return None, stdout, stderr
    return value, stdout, stderr[:index] + stderr[end + 1 :]


def _python_harness(descriptors: dict | None, *, script: bool) -> str:
    descriptor_json = repr(descriptors)
    invocation = "solution.main(message['payload'])" if script else "solution.solution(*[_decode(v, d) for v, d in zip(message['args'], DESCRIPTORS['parameters'], strict=True)])"
    encoding = "result" if script else "_encode(result, DESCRIPTORS['return_type'])"
    return f'''import importlib.util
import json
import resource
import sys
import time

DESCRIPTORS = {descriptor_json}

def _decode(value, descriptor):
    dimensions = descriptor['dimensions']
    if dimensions:
        if type(value) is not list:
            raise TypeError('array required')
        nested = {{'base': descriptor['base'], 'dimensions': dimensions - 1}}
        return [_decode(item, nested) for item in value]
    base = descriptor['base']
    if base == 'long':
        return int(value)
    return value

def _encode(value, descriptor):
    dimensions = descriptor['dimensions']
    if dimensions:
        if type(value) is not list:
            raise TypeError('solution returned a non-list array value')
        nested = {{'base': descriptor['base'], 'dimensions': dimensions - 1}}
        return [_encode(item, nested) for item in value]
    base = descriptor['base']
    if base == 'bool':
        if type(value) is not bool: raise TypeError('bool return required')
    elif base == 'string':
        if type(value) is not str: raise TypeError('string return required')
    elif base == 'int':
        if type(value) is not int or not -(2**31) <= value < 2**31: raise TypeError('int32 return required')
    elif base == 'long':
        if type(value) is not int or not -(2**63) <= value < 2**63: raise TypeError('int64 return required')
        return str(value)
    return value

message = json.loads(sys.stdin.readline())
spec = importlib.util.spec_from_file_location('user_solution', '/job/solution.py')
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)
started = time.monotonic_ns()
result = {invocation}
elapsed_ms = (time.monotonic_ns() - started) / 1_000_000
try:
    encoded = {encoding}
except TypeError as error:
    sys.stderr.write("Return type error: " + str(error) + '\\n')
    control = {{'failure': 'return_type'}}
    sys.stderr.write('\\n{CONTROL_PREFIX}' + message['token'] + ':' + json.dumps(control, separators=(',', ':')) + '\\n')
    sys.stderr.flush()
    sys.exit(1)
json.dumps(encoded, ensure_ascii=False, allow_nan=False)
control = {{'value': encoded, 'time_ms': elapsed_ms, 'memory_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}
sys.stderr.write('\\n{CONTROL_PREFIX}' + message['token'] + ':' + json.dumps(control, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\\n')
sys.stderr.flush()
'''


def _cpp_type(descriptor: TypeDescriptor) -> str:
    value = {"int": "int", "long": "long long", "string": "string", "bool": "bool"}[descriptor.base]
    for _ in range(descriptor.dimensions):
        value = f"vector<{value}>"
    return value


def _cpp_decode(descriptor: TypeDescriptor, expression: str) -> str:
    if descriptor.dimensions == 0:
        return f"decode_{descriptor.base}({expression})"
    child = TypeDescriptor(base=descriptor.base, dimensions=descriptor.dimensions - 1)
    return f"decode_array<{_cpp_type(child)}>({expression}, [](const json& item) {{ return {_cpp_decode(child, 'item')}; }})"


def _cpp_encode(descriptor: TypeDescriptor, expression: str) -> str:
    if descriptor.dimensions == 0:
        return f"encode_{descriptor.base}({expression})"
    child = TypeDescriptor(base=descriptor.base, dimensions=descriptor.dimensions - 1)
    return f"encode_array({expression}, [](auto item) {{ return {_cpp_encode(child, 'item')}; }})"


def _cpp_harness(request: ExecuteRequest) -> str:
    declaration = ", ".join(_cpp_type(item.type) for item in request.signature.parameters)
    arguments = []
    for index, parameter in enumerate(request.signature.parameters):
        arguments.append(f"    auto arg{index} = {_cpp_decode(parameter.type, f'args.at({index})')};")
    call_args = ", ".join(f"arg{index}" for index in range(len(arguments)))
    return_type = _cpp_type(request.signature.return_type)
    encoded = _cpp_encode(request.signature.return_type, "result")
    return f'''#include <bits/stdc++.h>
#include <sys/resource.h>
#include <nlohmann/json.hpp>
using namespace std;
using json = nlohmann::json;

{return_type} solution({declaration});

int decode_int(const json& v) {{ if (!v.is_number_integer() || v.is_boolean()) throw runtime_error("int required"); long long n=v.get<long long>(); if(n<INT_MIN||n>INT_MAX) throw runtime_error("int range"); return (int)n; }}
long long decode_long(const json& v) {{ if(!v.is_string()) throw runtime_error("long string required"); string s=v.get<string>(); size_t p=0; long long n=stoll(s,&p); if(p!=s.size() || to_string(n)!=s) throw runtime_error("canonical long required"); return n; }}
string decode_string(const json& v) {{ if(!v.is_string()) throw runtime_error("string required"); return v.get<string>(); }}
bool decode_bool(const json& v) {{ if(!v.is_boolean()) throw runtime_error("bool required"); return v.get<bool>(); }}
template<class T, class F> vector<T> decode_array(const json& v, F decoder) {{ if(!v.is_array()) throw runtime_error("array required"); vector<T> out; out.reserve(v.size()); for(const auto& item:v) out.push_back(decoder(item)); return out; }}
json encode_int(int v) {{ return v; }}
json encode_long(long long v) {{ return to_string(v); }}
json encode_string(const string& v) {{ return v; }}
json encode_bool(bool v) {{ return v; }}
template<class T, class F> json encode_array(const vector<T>& v, F encoder) {{ json out=json::array(); for(auto item:v) out.push_back(encoder(item)); return out; }}

int main() {{
  try {{
    string inputLine; getline(cin, inputLine); json message = json::parse(inputLine);
    const auto& args = message.at("args");
{chr(10).join(arguments)}
    auto started = chrono::steady_clock::now();
    auto result = solution({call_args});
    double elapsed = chrono::duration<double, milli>(chrono::steady_clock::now()-started).count();
    struct rusage usage{{}}; getrusage(RUSAGE_SELF, &usage);
    json control={{{{"value", {encoded}}}, {{"time_ms", elapsed}}, {{"memory_kb", usage.ru_maxrss}}}};
    cerr << "\\n{CONTROL_PREFIX}" << message.at("token").get<string>() << ":" << control.dump() << "\\n";
    return 0;
  }} catch(const exception& error) {{ cerr << error.what() << "\\n"; return 1; }}
}}
'''


def _java_type(descriptor: TypeDescriptor) -> str:
    return {"int": "int", "long": "long", "string": "String", "bool": "boolean"}[descriptor.base] + "[]" * descriptor.dimensions


def _java_method(descriptor: TypeDescriptor, prefix: str) -> str:
    return prefix + descriptor.base.capitalize() + str(descriptor.dimensions)


def _java_harness(request: ExecuteRequest) -> str:
    arg_lines = []
    for index, parameter in enumerate(request.signature.parameters):
        arg_lines.append(f"    {_java_type(parameter.type)} arg{index} = {_java_method(parameter.type, 'decode')}(args.get({index}));")
    call_args = ", ".join(f"arg{i}" for i in range(len(arg_lines)))
    return_type = _java_type(request.signature.return_type)
    encoder = _java_method(request.signature.return_type, "encode")
    return f'''import com.google.gson.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

public class Harness {{
  static int decodeInt0(JsonElement v) {{ if(!v.isJsonPrimitive() || !v.getAsJsonPrimitive().isNumber()) throw new IllegalArgumentException("int required"); long n=v.getAsLong(); if(n<Integer.MIN_VALUE||n>Integer.MAX_VALUE) throw new IllegalArgumentException("int range"); return (int)n; }}
  static long decodeLong0(JsonElement v) {{ String s=v.getAsString(); long n=Long.parseLong(s); if(!Long.toString(n).equals(s)) throw new IllegalArgumentException("canonical long required"); return n; }}
  static String decodeString0(JsonElement v) {{ if(!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isString()) throw new IllegalArgumentException("string required"); return v.getAsString(); }}
  static boolean decodeBool0(JsonElement v) {{ if(!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isBoolean()) throw new IllegalArgumentException("bool required"); return v.getAsBoolean(); }}
  static int[] decodeInt1(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); int[] o=new int[a.size()]; for(int i=0;i<o.length;i++)o[i]=decodeInt0(a.get(i)); return o; }}
  static int[][] decodeInt2(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); int[][] o=new int[a.size()][]; for(int i=0;i<o.length;i++)o[i]=decodeInt1(a.get(i)); return o; }}
  static long[] decodeLong1(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); long[] o=new long[a.size()]; for(int i=0;i<o.length;i++)o[i]=decodeLong0(a.get(i)); return o; }}
  static long[][] decodeLong2(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); long[][] o=new long[a.size()][]; for(int i=0;i<o.length;i++)o[i]=decodeLong1(a.get(i)); return o; }}
  static String[] decodeString1(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); String[] o=new String[a.size()]; for(int i=0;i<o.length;i++)o[i]=decodeString0(a.get(i)); return o; }}
  static String[][] decodeString2(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); String[][] o=new String[a.size()][]; for(int i=0;i<o.length;i++)o[i]=decodeString1(a.get(i)); return o; }}
  static boolean[] decodeBool1(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); boolean[] o=new boolean[a.size()]; for(int i=0;i<o.length;i++)o[i]=decodeBool0(a.get(i)); return o; }}
  static boolean[][] decodeBool2(JsonElement v) {{ JsonArray a=v.getAsJsonArray(); boolean[][] o=new boolean[a.size()][]; for(int i=0;i<o.length;i++)o[i]=decodeBool1(a.get(i)); return o; }}
  static JsonElement encodeInt0(int v) {{ return new JsonPrimitive(v); }}
  static JsonElement encodeLong0(long v) {{ return new JsonPrimitive(Long.toString(v)); }}
  static JsonElement encodeString0(String v) {{ if(v==null)throw new IllegalArgumentException("null string"); return new JsonPrimitive(v); }}
  static JsonElement encodeBool0(boolean v) {{ return new JsonPrimitive(v); }}
  static JsonElement encodeInt1(int[] v) {{ JsonArray a=new JsonArray(); for(int x:v)a.add(encodeInt0(x)); return a; }}
  static JsonElement encodeInt2(int[][] v) {{ JsonArray a=new JsonArray(); for(int[] x:v)a.add(encodeInt1(x)); return a; }}
  static JsonElement encodeLong1(long[] v) {{ JsonArray a=new JsonArray(); for(long x:v)a.add(encodeLong0(x)); return a; }}
  static JsonElement encodeLong2(long[][] v) {{ JsonArray a=new JsonArray(); for(long[] x:v)a.add(encodeLong1(x)); return a; }}
  static JsonElement encodeString1(String[] v) {{ JsonArray a=new JsonArray(); for(String x:v)a.add(encodeString0(x)); return a; }}
  static JsonElement encodeString2(String[][] v) {{ JsonArray a=new JsonArray(); for(String[] x:v)a.add(encodeString1(x)); return a; }}
  static JsonElement encodeBool1(boolean[] v) {{ JsonArray a=new JsonArray(); for(boolean x:v)a.add(encodeBool0(x)); return a; }}
  static JsonElement encodeBool2(boolean[][] v) {{ JsonArray a=new JsonArray(); for(boolean[] x:v)a.add(encodeBool1(x)); return a; }}
  static long peakRssKb() throws IOException {{ for(String line:Files.readAllLines(Path.of("/proc/self/status"))) if(line.startsWith("VmHWM:")) return Long.parseLong(line.trim().split("\\\\s+")[1]); return 0; }}
  public static void main(String[] ignored) throws Exception {{
    String inputLine = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8)).readLine();
    JsonObject message = JsonParser.parseString(inputLine).getAsJsonObject();
    String token = message.get("token").getAsString();
    try {{
      JsonArray args = message.getAsJsonArray("args");
{chr(10).join(arg_lines)}
      long started = System.nanoTime();
      {return_type} result = new Solution().solution({call_args});
      double elapsed = (System.nanoTime()-started)/1_000_000.0;
      JsonObject control = new JsonObject(); control.add("value", {encoder}(result)); control.addProperty("time_ms",elapsed); control.addProperty("memory_kb",peakRssKb());
      System.err.print("\\n{CONTROL_PREFIX}" + token + ":" + control + "\\n");
    }} catch (OutOfMemoryError error) {{
      System.err.print("\\n{CONTROL_PREFIX}" + token + ":{{\\\"failure\\\":\\\"memory_limit\\\"}}\\n");
      error.printStackTrace(System.err);
      System.exit(1);
    }}
  }}
}}
'''


def _javascript_harness(descriptors: dict) -> str:
    descriptor_json = json.dumps(descriptors, ensure_ascii=True)
    return f'''"use strict";
const fs = require("fs");
const {{ solution }} = require("/job/solution.js");
const DESCRIPTORS = {descriptor_json};
const LONG_MIN = -(1n << 63n);
const LONG_MAX = (1n << 63n) - 1n;

function decode(value, descriptor) {{
  if (descriptor.dimensions > 0) {{
    if (!Array.isArray(value)) throw new TypeError("array required");
    return value.map(item => decode(item, {{base: descriptor.base, dimensions: descriptor.dimensions - 1}}));
  }}
  if (descriptor.base === "long") {{
    if (typeof value !== "string") throw new TypeError("long string required");
    const parsed = BigInt(value);
    if (parsed < LONG_MIN || parsed > LONG_MAX || parsed.toString() !== value) throw new TypeError("canonical int64 required");
    return parsed;
  }}
  return value;
}}

function encode(value, descriptor) {{
  if (descriptor.dimensions > 0) {{
    if (!Array.isArray(value)) throw new TypeError("array return required");
    return value.map(item => encode(item, {{base: descriptor.base, dimensions: descriptor.dimensions - 1}}));
  }}
  if (descriptor.base === "long") {{
    if (typeof value !== "bigint" || value < LONG_MIN || value > LONG_MAX) throw new TypeError("int64 return required");
    return value.toString();
  }}
  if (descriptor.base === "int" && (typeof value !== "number" || !Number.isInteger(value) || value < -2147483648 || value > 2147483647)) throw new TypeError("int32 return required");
  if (descriptor.base === "string" && typeof value !== "string") throw new TypeError("string return required");
  if (descriptor.base === "bool" && typeof value !== "boolean") throw new TypeError("bool return required");
  return value;
}}

function readMessage() {{
  const chunks = [];
  while (true) {{
    const buffer = Buffer.allocUnsafe(65536);
    const count = fs.readSync(0, buffer, 0, buffer.length, null);
    if (count === 0) break;
    const chunk = buffer.subarray(0, count);
    const newline = chunk.indexOf(10);
    chunks.push(newline < 0 ? chunk : chunk.subarray(0, newline));
    if (newline >= 0) break;
  }}
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}}
const message = readMessage();
const args = message.args.map((value, index) => decode(value, DESCRIPTORS.parameters[index]));
const started = process.hrtime.bigint();
const result = solution(...args);
const elapsed = Number(process.hrtime.bigint() - started) / 1e6;
const encoded = encode(result, DESCRIPTORS.return_type);
const control = {{value: encoded, time_ms: elapsed, memory_kb: process.resourceUsage().maxRSS}};
process.stderr.write("\\n{CONTROL_PREFIX}" + message.token + ":" + JSON.stringify(control) + "\\n");
'''

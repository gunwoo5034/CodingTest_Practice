# Implementation contracts

These decisions complete PLAN.md for v1. Root coordinator owns changes to this file. Product name: **LoopCode / 루프코드**. Korean UI. Demo problems are original examples, not copied site content.

## Ownership and runtime

- Backend: `server/`, root `pyproject.toml`, Python lockfile, `.env.example`, API OpenAPI export.
- Runner: `runner/`, `compose.yaml`, Dockerfiles for runner images, runner tests.
- Frontend: `web/`, web Dockerfile and nginx config.
- Root: docs, integration, review coordination. One writer at a time; no nested agents.
- Python 3.12; root `uv` project imports packages `server` and `runner`. pytest tests live under each package. Backend binds internally at 8000; runner at 8001. Web at 127.0.0.1:8080 proxies /api to backend. Dev web Vite proxy to 127.0.0.1:8000.
- SQLAlchemy SQLite database uses named volume /data. Only server has DB and OPENAI_API_KEY. Manager has Docker socket, internal network only. No host fallback to execute arbitrary code.

## Types and invocation

- Language IDs: `python`, `cpp`, `java`, `javascript` (user-added fourth language).
- Type descriptor: `{ "base": "int" | "long" | "string" | "bool", "dimensions": 0 | 1 | 2 }`.
- Signature: `{ "parameters": [{"name": "numbers", "type": {"base":"int","dimensions":1}}], "return_type": {"base":"int","dimensions":0} }`.
- Every case `args` is an ordered array of argument values, e.g. `[[1,2,3]]`. int is 32-bit; long is signed 64-bit encoded as decimal STRING at API/storage boundary, including nested arrays. Native wrappers decode/encode. Bool must not compare equal to int.
- C++ free function solution, Python def solution, Java public class Solution with public instance method solution, JavaScript Node22 plain synchronous function solution. Templates derive deterministically from signature. JavaScript native long is BigInt, recursively string-encoded at JSON boundaries; int is Number restricted to int32.
- Public problem response excludes reference sources, validation code, hidden cases, raw generator results. Default seeded example is sum of integers with public 3 and hidden cases.

## Internal runner HTTP interface (authoritative)

`GET /health`: `{ "status":"ok"|"unavailable", "docker_available":bool, "detail":string }`.

`POST /execute` request:

```json
{"language":"python","source":"def solution(a): return a", "signature":{"parameters":[{"name":"a","type":{"base":"int","dimensions":0}}],"return_type":{"base":"int","dimensions":0}}, "cases":[{"id":"case-1","args":[1]}], "limits":{"time_ms":2000,"memory_mb":256,"output_kb":64}}
```

Response: `{ "results": [{"id":"case-1","status":"ok"|"compile_error"|"runtime_error"|"time_limit"|"memory_limit"|"output_limit"|"system_error", "value":<typed JSON or null>, "stdout":"", "stderr":"", "time_ms":0.0, "memory_kb":0}] }`.

- Expected answers never enter runner. Failure to reach Docker returns service error (503); never fake execution. API client timeout must accommodate per-case work (up to 600s default).
- Each case starts a clean process/container; compile artifact may be reused for a request. Compile timeout 30s, 1024MB; runtime defaults Python/C++/JavaScript 2000ms 256MB, Java 4000ms 512MB. pids 64 (Java 128), cpu 1. Caller limits validated and capped. Output bound applies while collecting, not only after completion.
- Bounds: source 256KiB; total request/payload 2MiB; 1..100 unique case IDs; time 50..10000ms, memory 32..1024MB (Java minimum 128), output 1..1024KiB combined stdout+stderr. Reject oversized artifacts above 32MiB. Mid-request Docker transport failure returns whole-request 503.
- Archive handling: use a restricted writable compile/staging container, copy bounded source archive in, compile, then commit to a temporary job image. Each runtime container derives from that image with read-only root and per-case stdin; cleanup image and containers in finally. Do not rely on put_archive into a read-only container or on tmpfs surviving exit. Compile staging contains no host mounts/secrets/expected values, has network/CPU/PID/memory/time limits, and is removed after image creation.
- Measure runtime with monotonic clock and Linux peak RSS or container metrics; identify measurements accurately. Cleanup in finally, including kill, failed compile, disconnect/error paths. No secrets, expected values, API keys, docker socket or host directory mounts in sandbox.

`POST /script`: `{ "source": "...Python...", "payload": <JSON>, "limits":{"time_ms":5000,"memory_mb":256,"output_kb":1024} }`. Generated Python defines `main(payload)` and returns a JSON value. Return same result fields except id. Use Python sandbox, never eval in backend. This endpoint supports input generation and constraint validation only. Size-limit source/input/output and validate response.

## Public backend conventions

- Base /api; JSON error detail must be user-safe. Health reports runner/API configured separately, never keys.
- Problem CRUD; visible tests CRUD; draft read/write per language; execution job creation with mode run/submit; jobs polling; submission history; AI analyze/generate/chat; expected-value compute through reference and runner; all use typed response models. Backend freezes concrete routes in exported OpenAPI for frontend.
- Background jobs persisted to SQLite, in-process single-worker executor (not Redis). On restart mark unfinished jobs interrupted; no silent reexecution/API calls. One active generation per problem; snapshot code and test version at execution request. Do not allow editing the active problem during generation. Submit requires ready tests. Run may use visible examples while unready.
- AI analysis returns editable draft with signature, examples, constraints. Store source image as local data only, enforce 10MB limit, PNG/JPEG/WebP. No image re-send after extraction.
- OpenAI official Python SDK Responses structured parsing, `store=False`, `max_retries=0`, bounded outputs; model env OPENAI_GENERATION_MODEL and OPENAI_TUTOR_MODEL default gpt-5-mini. Only explicit analyze/generate/chat routes call API. No key: clear setup message, rest of site works.
- Generation: create Python reference solution, independent brute force, validator (`main` receives list of args and returns list of booleans), generator (`main` receives seed/count/mode and returns list of argument lists); execute only via runner. Verify preserved original examples, 50 small cases differential, then 30 hidden candidates including edge/large cases. Validate all inputs; reject contradictions. Deduplicate cases. Retain original examples and supplement up to 3. Store provenance, seed, sources, report, version atomically after success. Store failed generation as needs_review, never mark ready. Existing tests retained if regeneration fails; submission disabled until repaired. Special comparison unsupported.
- Manual expected value uses stored reference and validator; never overwrites user's expected value silently. Visible test changes increment a test-suite revision; past jobs keep snapshots. Semantic problem edits invalidate ready status and references.
- Chat mode hint/question/solution; keep last 6 turns. No reference/hidden in context, even solution mode can derive solution from problem. No tool-using autonomous tutor.
- Metrics reflect observed runtime, not official score. Hidden result redacts args, expected, actual, stdout, stderr and per-input diagnostics; only status/time/memory/id remain.

## UI direction

Professional dark navy workspace, restrained mint accent, legible Korean system font, no external fonts or decorative assets. Left global navigation, problem list landing, workspace with resizable statement/code split, bottom tabs tests/results/history, collapsible tutor. Status/difficulty chips, intentional empty/error/loading states. Responsive desktop-first; stack panels on narrow screens. Keyboard accessible buttons/dialogs. All core actions functional; setup errors actionable.

## Acceptance

pytest meaningful backend and runner tests; generated wrappers tested on original fixtures, Docker integration tests opt-in. Frontend typecheck/build, Vitest behavior tests, browser smoke via Playwright if available. Real Docker and Windows validation may be unavailable; disclose separately, never use unsafe host fallback to make tests pass. Live OpenAI calls are not required for automated tests.

## Integration clarification: manually entered public examples

`TestCaseCreate` adds optional `kind: "public" | "user"` (default `"user"`). The existing test-create route accepts only these visible kinds. Problem setup uses `"public"` to register original examples after manual entry; the workspace custom-case editor omits it or uses `"user"`. Hidden test creation stays internal to validated generation. All visible writes share constraint validation, generation edit locks, and revision semantics.

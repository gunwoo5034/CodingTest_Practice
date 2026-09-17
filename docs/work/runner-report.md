# Runner implementation report

## Status

Implemented the internal runner service for Python 3.12, C++17, Java 21, and JavaScript on Node.js 22. The manager compiles source in a restricted writable staging container, commits a temporary job image, and creates a fresh read-only runtime container for every case. `/script` uses the same Python sandbox path.

## Security and lifecycle

- Sandbox containers use no network, bind mount, Docker socket, database, expected answer, or inherited secret environment.
- Runtime containers use a non-root UID, read-only root filesystem, capability drop, `no-new-privileges`, PID/CPU/memory limits, and a bounded `/tmp` tmpfs.
- Source is copied with a deterministic in-memory tar archive. No Docker Desktop host path is used.
- stdout and stderr are collected together against the configured limit while the process runs. Limit and timeout events kill the container.
- Staging containers, runtime containers, and temporary images are removed in `finally` paths. A post-test Docker query found zero labeled sandbox containers and zero temporary job images.
- Successful time is the language harness's monotonic solution-call duration. Memory is Linux process peak RSS: `getrusage` for Python/C++, `/proc/self/status` VmHWM for Java, and Node `resourceUsage().maxRSS` for JavaScript. Timeout timing uses manager monotonic elapsed time.

## Validation performed

- `.tools/uv run pytest runner/tests -q`: unit suite passes with Docker integration tests skipped by default.
- `RUN_DOCKER_TESTS=1 DOCKER_HOST=unix:///Users/gunwoo/.docker/run/docker.sock .tools/uv run pytest runner/tests -q`: 37 passed on Docker Desktop 29.8.0, Linux arm64 containers.
- Real Docker coverage includes all four languages, signed 64-bit decimal boundary encoding, int/string/bool, empty and jagged 2D arrays, Unicode, clean state between cases, `/script`, compile error, timeout, live combined-output cutoff, read-only root, disabled network, and absence of Docker socket/API key.
- `docker compose build sandbox-python sandbox-cpp sandbox-java sandbox-javascript`: all sandbox images built successfully.
- `docker compose build runner server`: both service images built successfully.
- `docker compose up -d --no-build runner`: helper image services completed, runner became reachable, `/health` reported Docker available, and an in-container HTTP `/script` request returned the expected JSON value.
- `docker compose config --quiet`, `git diff --check`, and Python compileall completed successfully.

## Remaining validation

Windows Docker Desktop was not available and is unverified. Full browser-to-backend Compose startup awaits the frontend Dockerfile. Live OpenAI calls were outside this task and were not performed.

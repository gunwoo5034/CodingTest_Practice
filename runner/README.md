# LoopCode runner

The runner accepts only the internal `/execute` and `/script` contracts. It compiles source in a restricted staging container, commits a temporary job image, and starts a new read-only container for every case. Sandbox containers have no network, host bind mount, secret environment, database, expected answer, or Docker socket.

From the repository root, `docker compose up --build` builds all four sandbox images before starting the runner and server. The helper sandbox services exit successfully after ensuring their images exist. The final web service is exposed only at `127.0.0.1:8080` through the frontend network.

Run unit tests with `uv run pytest runner/tests -q`. After Docker Desktop is running and sandbox images are built, run the opt-in integration suite with `RUN_DOCKER_TESTS=1 DOCKER_HOST=unix:///Users/$USER/.docker/run/docker.sock uv run pytest runner/tests/test_docker_integration.py -q` on macOS. Windows and Linux should set `DOCKER_HOST` only when their Docker client requires it.

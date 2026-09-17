# Implementation ledger

- User authorized implementation; no public deployment or live paid API test requested.
- Initial workspace contained only PLAN.md, AGENTS.md, CLAUDE.md; initialized local Git repository. No existing code or tests to preserve, so work in place rather than creating a redundant worktree.
- Host: macOS arm64, system Python 3.9.6; Node, uv and Docker initially absent. Project-local tools will be used; Docker isolation tests require Docker Desktop.
- Contract: docs/CONTRACT.md. Root owns contract changes, one implementation writer at a time.
- Pending: backend → runner → frontend → integration/review.
- Project-local Node 22 and uv installed; uv Python 3.12 provisioned. Playwright Chromium headless installed for browser validation.
- Runner design reviewed: restricted writable compile stage → temporary image → per-case read-only runtime, no host bind mount; bounded stdout/stderr collection, no AI judging.
- Backend commit 8ec4401: 16 tests passed, compileall/OpenAPI export/diff check passed. Root started API on127.0.0.1:8000 and observed health200(database ok, runner absent) and demo problems200. Live OpenAI was not called.
- Runner implementation started; independent backend review in progress. Frontend compared frozen OpenAPI and found no remaining integration blocker.
- Docker Desktop ready:29.8.0 Linux aarch64, Compose5.5.1. Root ran network-disabled Alpine container and verified Docker socket bind works. CLI available at /Applications/Docker.app/Contents/Resources/bin/docker; host SDK uses unix:///Users/gunwoo/.docker/run/docker.sock.
- Backend review findings confirmed: validate original examples and user test constraints; require strict bool validator output; reject explicit-null PATCH fields; return submitted source in history; public Java class template. Backend fix scheduled after runner writer slot, before frontend. Draft problems without validator allow type-only edits; generation must validate all retained visible inputs.
- User added JavaScript(Node22) solution language during implementation. All owners notified; contracts/docs updated. Backend schema/templates and frontend selector must include `javascript`; runner uses native BigInt for long.

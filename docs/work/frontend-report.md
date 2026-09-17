# Frontend implementation report

## Status

Implemented the LoopCode React/Vite frontend under `web/`. It is a Korean, desktop-first dark navy workspace with mint accents and responsive stacked layouts for narrow screens.

## User flows

- Problem library with search, status filters, edit/delete actions, loading, empty, and error states.
- Text/image registration with paste, drop, and file upload validation for PNG/JPEG/WebP up to 10 MiB. AI analysis only runs after an explicit click; manual drafts remain available without an API key.
- Editable problem content, constraints, typed function signature, public examples, limits, generation start, generation polling, reload recovery, and failure display.
- Resizable problem/Monaco workspace with Python 3.12, C++17, Java 21, and JavaScript/Node.js 22. Drafts save after an 800 ms debounce, before language changes, and when leaving the workspace. Language switching locks the selector/editor until save and load finish.
- Editable visible tests, user test creation, local reference expected-value calculation, and explicit application of the computed value.
- Run and submit job polling, public/user diagnostics, redacted hidden results, typed summaries, and persistent submission history with submitted source viewing.
- Persistent on-demand tutor with hint/question/full-solution modes. Full solution requires explicit confirmation. Merely opening, typing, running, submitting, or saving never calls AI.
- Health/settings drawer separates database, runner, and AI configuration with actionable setup information.

The API client uses types generated from `docs/openapi.json` by `openapi-typescript`. Markdown uses `react-markdown` without unsafe HTML. Monaco and its workers are bundled locally; a browser network check observed no external requests.

## Verification

```text
npm test -- --reporter=basic
3 test files, 8 tests passed

npm run typecheck
exit 0

npm run build
exit 0

npm audit --omit=dev
found 0 vulnerabilities
```

Playwright browser smoke against the real backend confirmed the library and workspace load without console/page errors, the Monaco background uses the LoopCode dark theme, and no CDN requests occur. A real JavaScript execution request reached the runner; the first automation input was malformed by the test's Monaco keystroke method, so that result is not treated as a product execution verification. Backend/runner integration is recorded separately by the coordinator.

The Docker image build was also run. nginx accepts 16 MiB request bodies, proxies `/api` to `server:8000`, uses 120-second proxy timeouts, and serves SPA routes through `index.html`.

## Pending contract hookup

Manual problem creation currently cannot add a public example because the frozen `TestCaseCreate` contract creates user cases. The coordinator approved an upcoming optional `kind: public | user` field, defaulting to `user`. After the backend and OpenAPI update, `EditProblemPage` must send `kind: "public"` from its “예제 추가” action and regenerate `src/api/schema.d.ts`. No other frontend API gap remains.

Live OpenAI analysis/chat were not invoked because no API key is configured. Windows browser behavior was not tested.

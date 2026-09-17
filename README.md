# LoopCode · 루프코드

문제를 이미지·텍스트로 등록하고, 로컬에서 코딩테스트를 연습하는 개인용 웹앱입니다. C++17, Python 3.12, Java 21, JavaScript(Node.js 22)의 함수 반환값을 채점합니다.

## AI가 사용되는 곳

OpenAI API는 문제 분석·테스트 준비와 사용자가 요청한 질문·힌트·정답 설명에만 사용합니다. **코드 실행·제출 채점·시간 및 메모리 측정에는 AI를 호출하지 않습니다.** 생성한 테스트를 저장하므로 반복 연습에는 API 연결이 필요하지 않습니다.

개발용 서브에이전트의 모델 배정은 웹사이트 API 설정과 별개입니다. 웹사이트의 기본 API 모델은 `gpt-5-mini`이며 문제 생성용과 도우미용을 각각 바꿀 수 있습니다.

## Docker로 실행

macOS 또는 Windows에 Docker Desktop을 설치하고 실행합니다. Windows에서는 Linux 컨테이너를 사용합니다. 처음 이미지를 빌드할 때는 인터넷 연결이 필요합니다.

1. 이 저장소를 내려받고 프로젝트 폴더에서 터미널을 엽니다.
2. `.env.example`을 `.env`로 복사합니다.
   - macOS: `cp .env.example .env`
   - Windows PowerShell: `Copy-Item .env.example .env`
3. AI 기능을 사용할 때만 `.env`의 `OPENAI_API_KEY`를 채웁니다. 키가 없어도 저장된 예제와 실행 기능을 사용할 수 있습니다.
4. 다음 명령으로 실행합니다.

```sh
docker compose up --build -d
```

브라우저에서 <http://localhost:8080>을 엽니다. 최초 빌드에는 언어별 실행 이미지 준비 시간이 포함됩니다.

실행 중에 `.env`의 API 키나 모델을 바꿨다면 다음 명령으로 서버 설정을 다시 적용합니다.

```sh
docker compose up -d --no-deps --force-recreate server
```

macOS에서 `docker: command not found`가 나오면 현재 터미널에서 다음을 실행한 뒤 다시 시도합니다.

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

```sh
# 상태 확인
docker compose ps

# 종료: 저장된 데이터 유지
docker compose down
```

DB는 Docker 볼륨에 저장합니다. `docker compose down -v`는 볼륨 데이터를 지우므로 보존하려는 문제가 있을 때 사용하지 마세요.

## 사용 흐름

1. 기본 예제를 열거나 새 문제를 이미지·텍스트로 등록합니다.
2. AI가 읽은 설명, 함수 입력·반환 타입, 예제를 확인하고 수정합니다. 문제 편집 화면의 **입출력 예 설명**에는 예제 해설을 Markdown으로 입력할 수 있으며 표도 표시합니다.
3. 테스트 생성을 요청합니다. 검증에 실패하면 이유를 확인하고 문제를 수정하거나 다시 생성합니다.
4. 언어를 선택해 `solution` 함수를 작성합니다. Java는 `Solution` 클래스의 메서드입니다.
5. **실행**은 공개·사용자 테스트, **제출**은 히든을 포함한 전체 테스트를 검사합니다.
6. 질문이 있을 때만 AI 도우미를 호출합니다. 기본은 힌트이며 전체 정답은 명시적인 요청에 제공합니다.

사용자 테스트는 입력 인자 목록과 기대 반환값을 JSON으로 편집합니다. 매개변수가 정수 배열 하나라면 입력은 `[[1, 2, 3]]`입니다. 64비트 정수(`long`)는 정밀도 보존을 위해 `"9223372036854775807"`처럼 문자열로 입력합니다.

JavaScript의 `long` 매개변수·반환값은 코드 안에서 `BigInt`를 사용합니다. 예를 들어 `return n + 1n;`처럼 작성하며, 채점 경계에서는 자동으로 문자열로 변환합니다.

## 현재 지원 범위

- 함수의 매개변수와 반환값을 사용하는 프로그래머스 형식.
- 32·64비트 정수, 문자열, 불리언 및 해당 타입의 1·2차원 배열.
- 문제 목록·등록·수정, 언어별 코드 저장, 사용자 테스트, 제출 기록, 요청형 AI 도우미.
- 기대 반환값이 하나로 정해지는 문제. 실수 오차, 복수 정답, 사용자 정의 자료형, 표준 입출력형 문제는 첫 버전에서 제외합니다.

테스트 전체 통과는 이 앱이 준비한 테스트의 통과를 뜻합니다. 원래 사이트의 공식 채점 결과를 재현하는 것은 아닙니다. 측정 시간과 메모리는 실행 환경에 따라 달라집니다.

## 개발 환경

Python 3.12와 uv, Node.js 22 이상, Docker Desktop을 사용합니다. 웹과 API만 별도로 실행할 수 있으며, 실제 코드 실행에는 Docker 실행기가 필요합니다. 사용자 코드를 호스트에서 실행하는 대체 모드는 제공하지 않습니다.

```sh
uv sync
```

macOS/Linux의 API 개발 서버:

```sh
LOOPCODE_DATABASE_URL=sqlite:///./data/loopcode.db \
LOOPCODE_RUNNER_URL=http://127.0.0.1:8001 \
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000
```

프런트엔드는 `web` 폴더에서 `npm ci`, `npm run dev`로 실행합니다. API 명세는 `/openapi.json`과 `docs/openapi.json`에서 확인합니다.

API 키와 문제 이미지·원문·개인 DB·제출 기록은 저장소에 커밋하지 않습니다. `.env`는 백엔드 설정이며 프런트엔드나 채점 컨테이너에 전달하지 않습니다.

## 검증 범위

2026-09-17 기준 macOS Apple Silicon의 Docker Desktop에서 네 언어의 정답·오답 판정, 실행 제한, 히든 결과 비공개, 서버 재생성 후 DB 보존을 확인했습니다. 테스트 생성 파이프라인은 AI 모의 응답과 실제 Docker 실행을 연결해 검증했습니다.

실제 OpenAI API 호출과 Windows 실기기 실행은 아직 검증하지 않았습니다. Windows용 설정은 Docker Desktop의 Linux 컨테이너를 기준으로 제공합니다.

## 프로젝트 문서

- [PLAN.md](PLAN.md): 제품 설계, 구현 단계, 인수 기준.
- [AGENTS.md](AGENTS.md): 개발팀의 모델·역할·위임·검토 규칙.
- [CLAUDE.md](CLAUDE.md): Claude용 진입 안내.
- [docs/CONTRACT.md](docs/CONTRACT.md): 내부 API와 실행기 계약.
- [docs/PROGRESS.md](docs/PROGRESS.md): 실제 작업과 검증 기록.

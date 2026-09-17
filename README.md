# LoopCode · 루프코드

문제를 이미지나 텍스트로 등록하면 AI가 문제를 분석하고 테스트 케이스를 생성해 주는 **로컬 코딩테스트 연습 웹앱**입니다. Docker로 실행하며, 문제와 풀이 기록은 로컬 DB에 저장됩니다.

- **지원 언어:** C++17, Python 3.12, Java 21, JavaScript(Node.js 22)
- **테스트:** AI가 기본·히든 테스트를 생성하며, 사용자 테스트도 직접 추가할 수 있습니다.
- **실행과 제출:** 실행은 기본·사용자 테스트를, 제출은 히든을 포함한 전체 테스트를 채점합니다. 전체 테스트를 통과하면 풀이 완료로 표시됩니다.
- **AI 도우미:** 사용자가 요청할 때 질문에 답하거나 힌트와 풀이 방법을 제공합니다.

프로그래머스 형식의 함수 반환값을 채점합니다. AI는 문제 분석·테스트 준비·요청한 풀이 도움에 사용하며, 코드 실행과 제출 채점에는 사용하지 않습니다.

## 실행 방법

### 1. 준비

Git과 Docker Desktop을 설치하고 Docker Desktop을 실행합니다. Windows에서는 Linux 컨테이너 모드를 사용합니다. 최초 빌드에는 인터넷 연결이 필요합니다.

```sh
git clone https://github.com/gunwoo5034/CodingTest_Practice.git
cd CodingTest_Practice
```

### 2. 환경 설정

macOS 터미널:

```sh
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

AI 기능을 사용하려면 `.env` 파일의 `OPENAI_API_KEY`에 본인의 OpenAI API 키를 입력합니다. AI 요청에는 API 사용 요금이 발생합니다. 키 없이도 기본 예제와 이미 준비된 문제의 코드 실행·제출은 가능합니다.

### 3. 실행

프로젝트 폴더에서 다음 명령을 실행합니다.

```sh
docker compose up --build -d
```

최초 빌드가 끝나면 브라우저에서 **http://localhost:8080**에 접속합니다.

실행 중 API 키 등 `.env` 설정을 변경했다면 다음 명령으로 적용합니다.

```sh
docker compose up -d --no-deps --force-recreate server
```

### 4. 종료 및 재실행

종료:

```sh
docker compose down
```

문제와 풀이 기록은 Docker 볼륨에 유지됩니다. 다시 실행할 때는 다음 명령을 사용합니다.

```sh
docker compose up -d
```

2026년도 공공데이터 활용 경진대회

# 올팍 포토캐스트

올림픽공원 포토 스팟을 고르고 날짜·시간을 정하면, 그때의 **예상 배경 이미지**와 **혼잡도**를 보여 준다.

- 프론트엔드: Vite + React + TS (`src/`)
- AI 예상 이미지 서버: FastAPI + forecast 패키지 + Gemini 이미지 편집 (`server/`)
- 서버 없이도 프론트는 돈다(자리표시 이미지). 혼잡도는 아직 `src/data/mock.ts`의 계산을 쓴다.

## 구조

```mermaid
flowchart LR
  subgraph 브라우저
    UI[ResultScreen] -->|getForecast| API[src/data/api.ts]
    API -->|혼잡도| MOCK[mock.ts crowd]
  end
  API -->|GET /api/forecast<br/>spot, datetime| SRV[server/app.py<br/>FastAPI]
  SRV -->|있으면 즉시| CACHE[(server/cache/<br/>이미지 + result.json)]
  SRV --> COND[forecast.conditions<br/>태양 pvlib · 날씨 · 대기질 · 수목 달력]
  COND --> W[Open-Meteo 예보 / 기상청 단기예보<br/>CAMS 대기질 / 에어코리아]
  COND --> STATE[forecast.scene<br/>장면 상태표 L·D·H]
  STATE --> PROMPT[forecast.prompt<br/>config/templates.yaml]
  PROMPT --> GEN[forecast.generate<br/>Gemini Nano Banana 2.1]
  GEN -->|기준 사진 public/images/스팟.jpg 편집| CACHE
  SRV -->|image_url · summary_ko · conditions| API
```

API 실패·하루 한도 초과면 프론트는 자리표시 이미지를 보여 주고 사유를 안내문에 띄운다.

## 실행

### 1) 서버

```bash
cd olpark_photocast
python3 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.txt

# 키 설정: server/.env (커밋 금지, .gitignore에 있음)
# (주석은 줄 끝이 아니라 따로 한 줄로 — 줄 끝에 쓰면 값에 섞인다)
cat > server/.env <<'EOF'
# Google AI Studio에서 발급
GEMINI_API_KEY=...
# (선택) 공공데이터포털 기상청 단기예보 조회서비스 / 에어코리아 대기오염정보
KMA_SERVICE_KEY=
AIRKOREA_SERVICE_KEY=
# 하루 최대 생성 장수 (넘으면 429)
DAILY_LIMIT=30
EOF
chmod 600 server/.env

server/.venv/bin/uvicorn server.app:app --reload --port 8000
# 확인: curl http://localhost:8000/api/health
```

- `GET /api/forecast?spot=naholo&datetime=2026-11-22T12:00` (한국 시간, 정시, 오늘~7일 뒤)
- 생성에 10~20초, 장당 약 $0.034. 같은 (스팟, 시각, 템플릿 버전, 모델)은 `server/cache/`에서 즉시 반환하고 다시 만들지 않는다.
- 같은 요청이 동시에 와도 한 번만 생성한다.
- 선택 키가 없으면 Open-Meteo(예보·대기질)로 대신한다.

### 2) 프론트

```bash
npm install
cp .env.example .env.local     # VITE_API_BASE= (빈 값 → 개발 서버 프록시 /api → localhost:8000)
npm run dev                    # http://localhost:5173
```

- `.env.local`이 없으면(VITE_API_BASE 미설정) 서버를 부르지 않고 예전처럼 자리표시 이미지만 쓴다.
- 배포 시에는 `VITE_API_BASE=https://<서버 주소>`로 빌드한다(`npm run build`). 서버 CORS는 지금 localhost:5173만 허용하므로 배포 주소를 `server/app.py`에 추가해야 한다.

## 스팟 설정

`server/forecast/spots/{rose,wild,gyeong4,naholo}.yaml` — 좌표·카메라 방위는 2026-11-22 현장 실측, 화각은 아이폰 1x 세로(50°/65°).
기준 시각은 기준 사진 EXIF, 기준 날씨는 그 시각의 실제 값(Open-Meteo). 수목 단계는 `server/forecast/config/phenology.yaml`(11/22 관찰로 보정).
4경 이름은 확정 전(임시 '4경'). 프롬프트 문장은 `server/forecast/config/templates.yaml`, 판단 규칙은 `rules.yaml`·`delta_rules.yaml`.

## 프롬프트 실험실 (진행 중)

두 사람이 프롬프트 템플릿을 fork해 고쳐 보며 결과 이미지를 비교하는 곳. 사용법은 **[LAB_GUIDE.md](LAB_GUIDE.md)**.

- API: `server/lab/` (`/api/lab/...`, 공용 비밀번호 `LAB_PASSCODE` + 사용자 `LAB_USERS`), 저장 `server/lab.db` + `server/lab_data/`(커밋 안 함)
- 지금은 `http://localhost:8000/docs` 에서 실험한다. 전용 화면(`#/lab`)은 만드는 중.
- 기본 모델: Nano Banana Pro(`gemini-3-pro-image`, 장당 $0.134). 사용자별 하루 20장(`LAB_DAILY_LIMIT`).
- 공개 화면 예측은 현재 shared 템플릿 + 아래 기준 사진을 쓴다. 캐시 키에 모델 id와 기준 사진 해시가 들어간다.

## 기준 사진 (2026-11-22 답사)

`server/base_photos/{rose,wild,gyeong4,naholo}.jpg` — 아이폰 원본에서 만든 전송용 사본(긴 변 1536px, 촬영 시각 EXIF만 남기고 GPS 제거).
원본을 새로 찍으면 `~/skyfinder/basephotos/`에 넣고 `server/.venv/bin/python -u scripts/import_basephotos.py` (촬영 순서 9경·8경·4경·6경).
스팟 좌표·방위는 `server/forecast/spots/*.yaml` (현장 실측).

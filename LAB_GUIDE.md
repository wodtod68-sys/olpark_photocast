# 프롬프트 실험실 사용법 (임시판)

> 실험실 전용 화면(`#/lab`)은 아직 만드는 중이다. 그 전까지는 서버가 자동으로 만들어 주는
> **API 화면(`/docs`)** 에서 버튼을 눌러 실험한다. 기능(조건 조회·프롬프트 미리보기·생성·점수·템플릿 fork/diff·그리드·실제 사진 채점)은 다 들어 있다.

## 0. 처음 한 번: 내 컴퓨터에서 띄우기

```bash
git clone https://github.com/wodtod68-sys/olpark_photocast.git
cd olpark_photocast
git checkout feature/ai-forecast

python3 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.txt
npm install
```

`server/.env` 파일을 만든다(**절대 커밋하지 말 것** — .gitignore에 있음). 값은 세환에게 메신저로 따로 받는다.

```
GEMINI_API_KEY=(세환에게 받거나 Google AI Studio에서 직접 발급)
LAB_PASSCODE=(공용 비밀번호, 세환에게 받기)
LAB_USERS=세환,친구
LAB_DAILY_LIMIT=20
DAILY_LIMIT=30
```

실행:

```bash
server/.venv/bin/uvicorn server.app:app --reload --port 8000     # 서버
npm run dev                                                      # 공개 화면 (선택, .env.local에 VITE_API_BASE= 한 줄)
```

- 공개 화면: http://localhost:5173 — 스팟 4곳(4경 추가), 기본 모델 Nano Banana Pro
- **실험 화면: http://localhost:8000/docs**

> 각자 자기 컴퓨터에서 띄우면 실험 기록(DB)은 각자 따로 쌓인다. 둘이 같은 기록을 보려면
> 세환 맥에서 띄운 서버에 터널 주소로 접속하는 방식을 쓴다(세환이 주소를 보내 줌).

## 1. 비용과 한도 (먼저 읽기)

| 모델 | 장당 | 비고 |
|---|---|---|
| Nano Banana Pro (`pro`, 기본) | **$0.134** | 생성에 15~20초 |
| Nano Banana 2.1 (`nb2.1`) | $0.034 | 비교용 |

- 사람마다 하루 **20장**(한국 시간 자정 초기화). 같은 프롬프트·기준 사진·모델·샘플 번호는 캐시라 다시 눌러도 0원.
- **미리보기(`/prompt`, `/conditions`)는 무료**. 문장을 충분히 다듬고 나서 생성한다.
- 그리드 한 번 = 20장 = $2.68 = 하루 한도 전부. 둘이 상의하고 돌린다.

## 2. /docs 쓰는 법

각 API를 펼쳐 **Try it out → 값 입력 → Execute**. 결과는 아래 Response body에 나온다.

1. **입장** — `POST /api/lab/login`
   `{"passcode": "공용비번", "user": "친구"}` → 브라우저에 로그인 쿠키가 저장되어 나머지 API가 열린다.
2. **조건 보기** — `GET /api/lab/conditions` (spot=`naholo`, datetime=`2026-11-23T16:30`)
   - `summary_ko`: 한 줄 요약, `data_state`: 데이터로 계산한 상태표, `raw`: 날씨 원데이터
   - `block_keys`: 이번 조건에서 **실제로 쓰인 템플릿 문장의 경로**, `key_values`: 그 문장들
3. **내 템플릿 만들기** — `POST /api/lab/templates/1/fork` `{"name": "친구 실험 1"}` → 응답의 `id`(예: 3)를 기억
4. **문장 고치며 미리보기(무료)** — `POST /api/lab/prompt`
   ```json
   {"spot": "naholo", "datetime": "2026-11-23T16:30", "template_id": 3,
    "overrides": {"assume": "clear"},
    "edits": {"lighting.sun": "Sun position: low, about {elev} degrees, {where}, {frame}. Earlier it was {base_cmp}."}}
   ```
   `edits`의 키는 2번의 `block_keys`에 나온 경로를 그대로 쓴다. `{elev}` 같은 중괄호 자리는 지우지 말 것.
5. **저장** — `PUT /api/lab/templates/3` `{"edits": {...같은 내용...}, "note": "해 위치 문장 짧게"}`
   (YAML 문법·필수 키를 검사한다. shared와 남의 템플릿은 저장 불가 → fork해서 쓴다)
6. **shared와 차이 보기** — `POST /api/lab/templates/diff` `{"a": 3}`
7. **생성** — `POST /api/lab/generate` (4번 본문 + `"model": "pro", "n": 1`)
   → `images[0].url`을 브라우저 주소창에 `http://localhost:8000` 뒤에 붙여 열면 이미지가 보인다.
   기준 사진은 `http://localhost:8000/api/lab/files/base/naholo.jpg`.
8. **점수 남기기** — `POST /api/lab/images/{id}/score`
   `{"scores": {"cond": 4, "struct": 5, "nobeauty": 3}, "note": "그림자 방향 맞음, 하늘이 너무 진함"}`
   - cond = 조건 반영, struct = 구조 보존(나무·건물 그대로인지), nobeauty = 미화 억제(과장 안 했는지), 각 1~5
9. **기록 보기** — `GET /api/lab/experiments` (user·spot·template_id로 거르기)

### 덮어쓰기(overrides) — 날씨를 일부러 바꿔 보기

| 키 | 값 |
|---|---|
| `assume` | `"clear"` — 예보 대신 맑은 날로 가정 (날짜가 달라도 같은 조건으로 비교) |
| `direct_sun` | `D0`(햇빛 없음) ~ `D3`(쨍함) |
| `haze` | `H0`(맑은 공기) ~ `H4`(안개) |
| `sky` | `clear, partly, high, low_many, overcast, golden, twilight, night, rain, fog` |
| `precip` | `none`, `rain:light`, `rain:moderate`, `rain:heavy`, `snow:light` … |
| `ground` | `["wet"]`, `["snow"]`, `["frost"]`, `["leaves"]` 조합 |
| `trees` | `{"lawn": "green", "maple": "bare"}` — 단계 이름은 `server/forecast/config/phenology.yaml` |

예: 흐린 날 → `{"assume": "clear", "direct_sun": "D0", "sky": "overcast"}`,
비 오는 날 → `{"assume": "clear", "precip": "rain:moderate", "ground": ["wet"]}`

## 3. 추천 실험 순서

1. **한 조건 고정**: 스팟 하나 + 시각 하나 + `assume: clear`로 shared 템플릿 결과를 1장 만든다(기준점).
2. **문장 하나만 바꾼다**: 내 템플릿에서 블록 하나(예: `consequences`, `exposure`, `sky.*`)만 고쳐 미리보기 → 생성.
3. **점수와 메모**를 남긴다. 무엇을 바꿨고 무엇이 나아졌는지 한 줄로.
4. 괜찮으면 다른 스팟·시각(07시 / 12시 / 16:30 / 흐림 / 비)에서도 확인한다.
5. 두 사람 모두 납득하면 그리드(`POST /api/lab/grid`, 먼저 `confirm: false`로 비용 확인 → `confirm: true`)로 4곳×5조건을 돌려 shared와 비교.
6. 확실히 낫다면 `POST /api/lab/templates/{id}/promote` (`confirm: false`로 diff 확인 → `true`) — **공개 화면 기본값이 바뀌니 둘이 합의 후에**.

## 4. 실제 사진으로 채점

같은 자리에서 찍은 사진을 `POST /api/lab/real-photo`로 올린다(폰 원본 HEIC 그대로 가능).
- 사진의 EXIF 촬영 시각으로 ±30분 안의 예측(덮어쓰기 없는 것)을 찾아 정렬·채점한다. 시각이 없으면 `taken_at`에 `2026-11-23T16:30`.
- `generate_missing=true`면 없는 예측을 shared + 고른 템플릿으로 새로 만든다(장당 $0.134).
- 결과: 지면 ΔE(낮을수록 좋음)와 "기준 사진 그대로 뒀을 때" ΔE 비교, 비교 패널 이미지.
- `GET /api/lab/leaderboard`: 템플릿별 평균 ΔE 순위.

## 5. 템플릿 문장 구조 한눈에

`server/forecast/config/templates.yaml` (shared v1의 원본). 블록 순서:
시간 변화 → 보존 → 태양·날씨 → 결과(빛·그림자) → 노출 → 하늘·대기 → 수목 → 지면 → 미화 금지.
조건에 따라 쓰이는 문장이 달라지므로, 고치기 전에 2번(`block_keys`)으로 지금 어떤 문장이 쓰이는지 먼저 본다.

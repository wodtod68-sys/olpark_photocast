# forecast — 조건 데이터 → 프롬프트 → Gemini 예측 이미지

기준 사진 한 장에 "그 시각의 태양·날씨·대기·수목 조건"을 문장으로 묘사해서 Gemini 이미지 편집으로 예측 사진을 만든다.
학습형 변환기(`translator/`)는 보존만 하고 이 방식으로 전환했다.

```
조건 계산(conditions.py) → 장면 상태표(scene.py) → 프롬프트(prompt.py + config/templates.yaml) → 생성(generate.py) → 채점(verify.py)
```

## 1. 준비

```bash
cd ~/skyfinder/photocast_sky
.venv/bin/pip install -r requirements.txt      # pyyaml, google-genai 포함
cp .env.example .env                           # 키 채우기 (.env는 .gitignore)
```

| 키 | 용도 | 발급처 |
|---|---|---|
| `GEMINI_API_KEY` | 이미지 생성 | Google AI Studio (aistudio.google.com → Get API key) |
| `KMA_SERVICE_KEY` | 기상청 단기예보 조회서비스(getVilageFcst) | 공공데이터포털 data.go.kr "기상청_단기예보 조회서비스" 활용신청 → 일반 인증키(Decoding) |
| `AIRKOREA_SERVICE_KEY` | 에어코리아 대기오염정보(실시간·예보) | 공공데이터포털 "한국환경공단_에어코리아_대기오염정보" 활용신청 |

키가 없는 소스는 건너뛰고 로그에 남긴다. 기상청이 없으면 Open-Meteo 예보, 에어코리아가 없으면 Open-Meteo 대기질
(그것도 없으면 스팟의 `typical_pm25`)을 쓴다. 출처는 `scene_state.json`의 `source`에 기록된다.

## 2. 실행 예시 (모든 실행은 `python -u`)

```bash
# 상태표와 프롬프트만 (API 호출 없음)
.venv/bin/python -u -m forecast.predict --spot spots/sample_21510.yaml --datetime "2013-02-15 16:02" --dry-run

# 1장 생성 (기본 Nano Banana 2.1, 장당 $0.034). --model pro 는 Nano Banana Pro ($0.134)
.venv/bin/python -u -m forecast.predict --spot spots/sample_21510.yaml --datetime "2013-02-15 16:02" --n 1

# 참조 사진을 두 번째 이미지로 첨부
.venv/bin/python -u -m forecast.predict --spot spots/sample_21510.yaml --datetime "2013-02-15 16:02" --ref path/to/ref.jpg

# 같은 날 시각만 바꿔 여러 장 + 비교 스트립 (호출 수가 --max-calls(기본 5)를 넘으면 실행 안 함)
.venv/bin/python -u -m forecast.sweep --spot spots/sample_21510.yaml --date 2013-02-15 --times "07:30,12:00,16:02,17:32" --dry-run

# 채점: 예측 폴더 vs 실제 사진 (폰 사진도 기준 사진에 자동 정렬)
.venv/bin/python -u -m forecast.verify --pred outputs/forecast/sample_21510/20130215_1602 --real ~/skyfinder/21510/20130215_220215.jpg

# 계정에서 보이는 이미지 모델 ID 확인
.venv/bin/python -u -m forecast.generate --list-models
```

`--spot`은 현재 폴더, `photocast_sky/`, `forecast/` 순서로 찾는다. `--datetime`은 스팟 현지 시각.

## 3. 저장

`outputs/forecast/<spot>/<YYYYMMDD_HHMM>/`
- `scene_state.json` 기준·목표 상태표(단계값 + 원값 + 소스)와 노출 변화량
- `prompt.txt`
- `gen_<i>.png` (1K, Gemini 원본), `gen_<i>_orig.png` (기준 사진 크기)
- `meta.json` 모델, 호출 수, 비용, 데이터 소스, 템플릿·규칙 버전, 생성 시각
- `verify_<실제>_<gen>.jpg` 채점 패널

sweep: `outputs/forecast/<spot>/sweep_<YYYYMMDD>/<HHMM>/` + `prompts.md`(이웃 시각과 달라진 문장 diff) + `strip.jpg`
채점 누적: `outputs/forecast/validation_log.csv` (스팟, 시각, 조건 단계, 지표, 템플릿 버전)

## 4. 고치는 곳

| 파일 | 내용 |
|---|---|
| `config/templates.yaml` | **모든 프롬프트 문장**과 블록 순서(`order`). 문장을 바꾸면 `version`을 올린다 |
| `config/delta_rules.yaml` | 노출 변화 계수(★ 보정 전). 조합별 직접 문장은 `overrides` |
| `config/rules.yaml` | 빛 L·직사광 D·연무 H 단계 임계값, 화면 기준 위치 경계, 가시성 모델, 소스 범위 |
| `config/phenology.yaml` | 서울 수종별 평년 단계 달력(★ 추정치) |
| `spots/*.yaml` | 스팟 설정. `template_olympicpark.yaml`의 체크리스트 참고 |

lighting 블록 우선순위: 강수 > 안개 > 밤 > 박명 > 흐림 > 태양 방향. 흐림 이상이면 태양 위치·그림자 문장 대신 균일한 빛 문장.

## 5. 지표 읽는 법 (verify)

- 지면 ΔE: 예측 vs 실제 픽셀 ΔE76 평균. **같은 패널의 "base(no change)" 값과 비교**한다(측정 방식이 다르면 절대값은 달라진다).
- 하늘 ΔE: 하늘 평균색 차이(구름 모양은 맞힐 수 없으므로 픽셀 비교 안 함).
- 대비 = 지면 L 95%−5% 폭, 채도 = 평균 sqrt(a²+b²), 색온도 = 평균 b*(+면 따뜻함).
- 윤곽선 SSIM(예측 vs 기준): 1에 가까울수록 구조가 보존됨. 생성 모델이 건물을 바꿨는지 감시용.

# 올림픽공원 시간별 혼잡도 예측 엔진

올팍 포토캐스트 웹이 읽을 혼잡도 점수(정적 JSON)를 만든다.
데이터: 한국체육산업개발 「올림픽공원 2025 차량입출차, 공연, 날씨정보 등 연계 데이터」 (KCISA API_CPM_009)

## 한눈에

1. **지표**: 2025년 공원 주차대수에서 그날 새벽 대수를 빼고, 기관의 차량당 인원(평일 3, 주말·공휴일 5)을 곱한다. 이것을 혼잡 지표로 쓴다.
2. **모델**: 이 지표를 (평일 / 주말·일반공휴일 / 명절) × 시간으로 평균 내고, 공연 관람객 수에 비례하는 증가분을 더한다(baseline).
3. **점수**: 미래 날짜·공휴일·공연 일정에 2번을 적용해 2025년 분포의 백분위(0~100점)로 바꾼다. 여기서 4단계 등급과 근거 문구가 나온다.
4. **스팟 차이**: 스팟별 차이는 공연 동선 보정 하나뿐이다. 공연장 가까운 스팟만 공연 시간 전후로 등급을 한 단계 올린다.

공원 전체 단위 지표라서, 공연 보정이 없는 스팟들은 점수가 서로 같다.

## 준비

```bash
cd web/crowd
python -m venv .venv          # Python 3.12에서 확인
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # CULTURE_API_KEY 값을 넣는다 (KCISA 문화공공데이터 인증키)
```

`.env`와 `data/`는 커밋하지 않는다 (`.gitignore`). 레포를 새로 받았다면 처음 한 번은 데이터를 만들어야 한다. 키가 필요하고, 수집에 15분쯤 걸린다.

```bash
python -m src.fetch && python -m src.parse && python -m src.prepare
```

## 공연 일정·스팟만 바꿀 때 (자주 하는 일)

1. 바꿀 파일을 고친다.
   - 공연 일정: `config/events_manual.csv`
   - 공연장 가까운 스팟: `config/spots.json`의 `near_venues`
2. 아래 두 줄을 실행한다.
   ```bash
   python -m src.events    # 공연 일정 검증 → config/upcoming_events_hourly.csv
   python -m src.export    # out/crowd_forecast.json + 웹 사본 ../public/crowd_forecast.json
   ```
3. 바뀐 `public/crowd_forecast.json`을 커밋한다. 웹은 새로고침하면 반영된다.

웹에 새 스팟을 추가하면 `config/spots.json`에도 **웹과 같은 id**로 넣어야 한다. 넣지 않으면 그 스팟은 웹에서 mock 점수가 나온다.

## 전체 실행 순서 (처음부터 다시 만들 때)

| 단계 | 명령 | 하는 일 | 결과 |
|---|---|---|---|
| 1 | `python -m src.fetch` | API 전체 페이지 수집, LOCAL_ID 중복 제거, 시간순 정렬 | `data/raw/olpark_2025_raw.csv` |
| 1 | `python -m src.parse` | TITLE·DESCRIPTION을 컬럼으로 파싱, 결측·공연·휴일 점검 출력 | `data/processed/olpark_2025.csv` |
| 2 | `python -m src.prepare` | target·feature 생성, 아래 기간 제외, 비교 그래프 | `data/processed/olpark_2025_features.csv`, `reports/target_compare.png` |
| 3 | `python -m src.train` | baseline·LightGBM 학습(1~7월)·평가(10~12월), baseline 개선 전후 비교, 12/13 예측 확인 | `reports/test_actual_vs_pred.png`, `reports/feature_importance.png`, 해석은 `reports/model_comparison.md` |
| 4 | `python -m src.score` | 배포용 baseline(248일 전체), 백분위 점수·등급·근거 문구, 경계 후보 비교 | (출력만) |
| 5 | `python -m src.spot_adjust` | `config/` 공연장 이름 검증, 스팟 보정 예시 | (출력만) |
| 6 | `python -m src.events` | 미래 공연(손으로 정리)을 검증하고 2025 데이터와 같은 시간별 형식으로 펼침 | `config/upcoming_events_hourly.csv` |
| 6 | `python -m src.export` | 2026-12-01 ~ 2027-02-28, 06~22시, `spots.json`의 스팟별 점수·등급·근거. 06시는 웹 선택기에 맞춰 넣었고, 점수 기준 분포는 운영시간(07~22시) 그대로 | `out/crowd_forecast.json`, 웹 사본 `../public/crowd_forecast.json` |

### 점수와 등급

- **등급 경계**: 30 / 75 / 85점(여유 / 보통 / 약간 붐빔 / 붐빔). 점수는 248일 운영시간 분포에서의 백분위다.
- **평일 07~10시**: 체육시설·업무 이용 시간대라 등급 상한이 "보통"이다. 점수도 74점에서 자른다.
- **날씨**: 점수와 근거 문구 모두에 쓰지 않는다. 이유는 `reports/limitations.md`에 있다.
- **분석 정리**: 데이터에서 확인한 사실은 `reports/findings.md`, 한계는 `reports/limitations.md`에 있다.

### 설정 파일 (`config/`)

| 파일 | 내용 |
|---|---|
| `venues.json` | 공연장 이름 → 좌석 수. 아래 파일들의 공연장 이름은 이 목록과 정확히 같아야 하고, 다르면 실행이 멈춘다 |
| `spots.json` | 스팟별 `near_venues`(공연장 이름 리스트). 비어 있으면 그 스팟은 공연 보정을 하지 않는다 |
| `events_manual.csv` | 손으로 정리한 미래 공연. 1행 = 공연 1회. 열은 `date,start,venue,title,audience,source_url`. `audience`가 빈칸이면 좌석 수 × 0.9 |
| `upcoming_events_hourly.csv` | `src.events`가 만드는 시간별 공연 정보. 열은 `datetime,event_name,event_audience,venues`이고, 2025 데이터와 같은 형식 |

### 공연 반영 규칙 (6단계)

- **검증**: `events_manual.csv`의 공연장 이름, 날짜·시각 형식, (date, start, venue) 중복을 확인하고, 틀린 행이 있으면 행 번호와 함께 멈춘다.
- **공원 전체 점수**: 공연 1회는 [시작 시각이 속한 시간 − 1시간]부터 **5시간** 동안 관람객수에 잡힌다. 18:00 공연은 17~21시, 19:30 공연은 18~22시다.
  - 5시간은 2025 데이터의 중앙값이다. 관람객수가 처음 기록된 시각부터 연속으로 기록된 시간을 쟀다.
  - 시작 1시간 전부터 기록된다는 점은 2025-12-06 god 공연(18:00 시작, 17~21시 기록)으로 확인했다.
  - 같은 칸에 공연이 여러 개면 관람객수는 더하고, 공연명·공연장은 " + "로 잇는다.
- **스팟 보정**: [시작 −90분, 관람객 기록이 끝나는 시각 + 30분]과 겹치는 칸에서, 공연장이 그 스팟의 `near_venues`에 있으면 등급을 한 단계 올린다. 18:00 공연이면 16:30~22:30이다.
  - 시작 시각이 분 단위로 필요해서 시간별 파일이 아니라 `events_manual.csv`의 공연 단위 행으로 계산한다.
  - 점수는 올라간 등급의 하한까지 끌어올린다.
  - 근거 문구 뒤에 ` · {공연장} 공연 동선 ({시작} 시작)`을 붙인다.
- **적용 범위**: 2025 데이터에는 공연장 정보가 없다. 그래서 스팟 보정은 내보내기에만 적용하고, 2025 평가 지표는 보정 전 기준이다.

배포 모델은 **baseline**이다: (평일 / 주말·일반공휴일 / 명절) × 시간 평균에 시간대별 계수 × 공연 관람객 수를 더한다. LightGBM은 비교 실험으로만 남겼다.

API가 429(호출 빈도 제한)를 자주 돌려줘서 수집에 15분 정도 걸린다.

## target

`crowd = (parked_cars − 그날 03~05시 최솟값) × 환산 계수`

환산 계수는 기관의 차량당 인원이다. 평일은 3, 주말·공휴일은 5이며, 데이터의 `방문객 / 주차대수`와 모든 행에서 일치한다.

## 학습·테스트에서 뺀 데이터와 이유

| 대상 | 이유 |
|---|---|
| 2025-08-01 ~ 09-30 | 하루 모양은 정상이지만 크기가 평소의 약 1/4(하루 최대 약 590대, 평소 약 2,370대). 7/30 → 8/1, 9/30 → 10/1에 갑자기 바뀌어서 집계하는 주차장 범위가 달라진 것으로 판단 |
| 03~05시 값이 없는 날 (37일, 11~12월) | 기준선(그날 새벽 최솟값)을 계산할 수 없음 |
| 입차가 기록되지 않은 날 (12일: 매월 말일, 11/7, 12/8 등) | 하루 종일 주차대수가 줄기만 함. 운영시간 증가분의 중앙값이 0 이하인 날로 판별 |

남은 데이터는 248일이다(1~7월, 10월, 11/1~6, 12/1~7). 한계는 [reports/limitations.md](reports/limitations.md)에 정리했다.

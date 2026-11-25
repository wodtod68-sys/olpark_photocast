"""4단계: baseline 예측값을 0~100점·4단계 등급·근거 문구로 바꾼다.

실행: python -m src.score   (분포·경계 후보 비교·예시 출력)
배포용 baseline과 점수 분포는 2단계에서 남은 248일 전체(운영시간)로 계산한다.
"""
import numpy as np
import pandas as pd

from src.prepare import OPEN_HOURS
from src.train import (COMMUTE_HOURS, FEAT_PATH, TEST_MONTHS, TRAIN_MONTHS, fit_baseline,
                       predict_baseline, score_dist)

LEVELS = ["여유", "보통", "약간 붐빔", "붐빔"]
BOUNDS = [30, 75, 85]  # 확정: 여유 <30 ≤ 보통 <75 ≤ 약간 붐빔 <85 ≤ 붐빔 (후보 비교는 compare_bounds)
CANDIDATES = [[30, 60, 85], [30, 75, 85]]
WEEKDAYS = "월화수목금토일"
SERVE_HOURS = range(6, 23)  # 내보내는 시간: 웹 선택기(06~21시) + 운영시간(07~22시)
COMMUTE_REASON = "체육시설·업무 이용 시간대"


def fit_deploy() -> tuple[dict, np.ndarray]:
    """248일 전체로 배포용 baseline(SERVE_HOURS)과 점수 기준 분포(운영시간, 평일 07~10시 제외 실제값)를 만든다."""
    df = pd.read_csv(FEAT_PATH, parse_dates=["datetime"])
    return fit_baseline(df[df.hour.isin(SERVE_HOURS)]), score_dist(df[df.hour.isin(OPEN_HOURS)])


def is_commute(day_type, hour) -> np.ndarray:
    return (np.asarray(day_type) == "평일") & np.isin(hour, list(COMMUTE_HOURS))


def to_score(pred, dist: np.ndarray, commute, bounds=BOUNDS) -> np.ndarray:
    """2025년 분포에서의 백분위(0~100, 정수). 평일 07~10시는 '보통' 구간 상단에서 자른다."""
    s = np.clip(np.round(np.searchsorted(dist, pred, side="right") / len(dist) * 100), 0, 100)
    return np.where(commute, np.minimum(s, bounds[1] - 1), s).astype(int)


def level_index(score, bounds=BOUNDS) -> np.ndarray:
    return np.digitize(score, bounds)


def _part_of_day(hour: int) -> str:
    return "오전" if hour < 12 else "오후" if hour < 18 else "저녁"


def _audience(a: float) -> str:
    if a >= 10000:
        return f"공연 관람객 약 {round(a / 10000, 1):g}만 명"
    return f"공연 관람객 약 {max(1, round(a / 1000)):d}천 명"


def reason(row) -> str:
    """규칙으로 가장 큰 요인 1~2개를 고른다. row: datetime, day_type, holiday_name, event_audience."""
    t, hour = row.datetime, row.datetime.hour
    if row.day_type == "평일" and hour in COMMUTE_HOURS:
        return COMMUTE_REASON
    parts = []
    if row.day_type == "명절":
        parts.append(("추석" if "추석" in str(row.holiday_name) else "설") + " 연휴")
    elif isinstance(row.holiday_name, str):
        parts.append(f"공휴일 {_part_of_day(hour)}")
    else:
        day = "평일" if row.day_type == "평일" else f"{WEEKDAYS[t.day_of_week]}요일"
        parts.append(f"{day} {_part_of_day(hour)}")
    if row.event_audience >= 1000:
        parts.append(_audience(row.event_audience))
    return " · ".join(parts)


def compare_bounds(df: pd.DataFrame, model: dict, dist: np.ndarray):
    """경계 후보별 요일 유형·시간대 등급 비율과 테스트 일치율."""
    commute = is_commute(df.day_type, df.hour)
    pred = predict_baseline(model, df)
    groups = {
        "평일 전체": df.day_type.eq("평일"),
        "평일 오후 12~17시": df.day_type.eq("평일") & df.hour.between(12, 17),
        "주말·일반공휴일 전체": df.day_type.eq("주말·일반공휴일"),
        "주말·일반공휴일 오후 12~17시": df.day_type.eq("주말·일반공휴일") & df.hour.between(12, 17),
        "명절 전체": df.day_type.eq("명절"),
    }
    train, test = df.month.isin(TRAIN_MONTHS), df.month.isin(TEST_MONTHS)
    m, d = fit_baseline(df[train]), score_dist(df[train])
    tc = commute[test.to_numpy()]
    for bounds in CANDIDATES:
        lv = pd.Series(level_index(to_score(pred, dist, commute, bounds), bounds), index=df.index)
        print(f"\n[경계 {bounds}] 248일 예측 등급 비율")
        table = pd.DataFrame({g: lv[mask].value_counts(normalize=True).reindex(range(4), fill_value=0)
                              for g, mask in groups.items()}).T
        table.columns = LEVELS
        print((table * 100).round(0).astype(int).astype(str).add("%").to_string())
        a = level_index(to_score(df[test].crowd, d, tc, bounds), bounds)
        p = level_index(to_score(predict_baseline(m, df[test]), d, tc, bounds), bounds)
        print(f"  테스트 등급 일치율: 정확 {(a == p).mean():.1%}, ±1 이내 {(abs(a - p) <= 1).mean():.1%}")


def main():
    model, dist = fit_deploy()
    print(f"[점수 기준 분포] 248일 운영시간, 평일 07~10시 제외: {len(dist)}행")
    print("  백분위 → 명:", {q: int(np.percentile(dist, q)) for q in [10, 30, 50, 60, 70, 75, 80, 85, 90, 95]})

    df = pd.read_csv(FEAT_PATH, parse_dates=["datetime"])
    df = df[df.hour.isin(OPEN_HOURS)].copy()
    compare_bounds(df, model, dist)

    print(f"\n[예시, 경계 {BOUNDS}]")
    raw = pd.read_csv(FEAT_PATH.parent / "olpark_2025.csv", parse_dates=["datetime"])[["datetime", "holiday_name"]]
    ex = df.merge(raw, on="datetime", how="left")
    picks = ["2025-10-15 10:00", "2025-10-15 14:00", "2025-10-18 15:00", "2025-10-18 20:00",
             "2025-11-01 18:00", "2025-10-06 14:00", "2025-10-03 14:00", "2025-12-03 19:00"]
    ex = ex[ex.datetime.isin(pd.to_datetime(picks))].copy()
    ex["score"] = to_score(predict_baseline(model, ex), dist, is_commute(ex.day_type, ex.hour))
    for r in ex.itertuples():
        lv = LEVELS[level_index(r.score)]
        print(f"  {r.datetime:%m-%d %H시} {WEEKDAYS[r.datetime.day_of_week]} | {r.score:>3}점 {lv:<5} | {reason(r)}")


if __name__ == "__main__":
    main()

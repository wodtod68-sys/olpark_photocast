"""6단계: 웹이 읽을 정적 JSON을 만든다 (baseline, 248일 재학습, 경계 30/75/85).

실행: python -m src.events  →  python -m src.export
입력: config/upcoming_events_hourly.csv(공원 전체 공연 관람객수), config/events_manual.csv(스팟 보정용 공연 단위),
      config/spots.json, config/venues.json
결과: out/crowd_forecast.json — 2026-12-01 ~ 2027-02-28, 06~22시 (점수 기준 분포는 운영시간 07~22시)
"""
import json
from datetime import timedelta
from pathlib import Path

import holidays
import pandas as pd

from src.events import END, START, load_events, load_hourly
from src.prepare import day_type, holiday_type
from src.score import LEVELS, SERVE_HOURS, fit_deploy, is_commute, level_index, reason, to_score
from src.spot_adjust import adjust, load_spots, load_venues
from src.train import predict_baseline

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "out" / "crowd_forecast.json"
WEB_PATH = ROOT.parent / "public" / "crowd_forecast.json"  # 웹이 읽는 사본 (web/public/)


def build_hours(hourly: pd.DataFrame) -> pd.DataFrame:
    """배포 기간의 운영시간 칸마다 baseline 입력(요일 유형, 시간, 공연 관람객수)을 만든다."""
    dates = pd.date_range(START, END, freq="D")
    df = pd.DataFrame({"datetime": [d + timedelta(hours=h) for d in dates for h in SERVE_HOURS]})
    kr = holidays.KR(years=sorted({d.year for d in dates}))
    df["holiday_name"] = df.datetime.dt.date.map(kr.get)
    df["hour"] = df.datetime.dt.hour
    df["month"] = df.datetime.dt.month
    df["is_weekend"] = (df.datetime.dt.day_of_week >= 5).astype(int)
    df["holiday_type"] = holiday_type(df.holiday_name)
    df["day_type"] = day_type(df.is_weekend, df.holiday_type)
    df = df.merge(hourly[["datetime", "event_audience"]], on="datetime", how="left")
    df["event_audience"] = df.event_audience.fillna(0).astype(int)
    df["has_event"] = (df.event_audience > 0).astype(int)
    return df


def main():
    venues = load_venues()
    spots = load_spots(venues)
    placeholders = [sid for sid, s in spots.items() if not s.get("name")]
    if placeholders:
        print(f"이름이 비어 있는 자리 스팟 {placeholders} → 내보내기에서 제외")
    spots = {sid: s for sid, s in spots.items() if s.get("name")}
    events = load_events(venues)  # 스팟 보정 구간에 시작 시각(분 단위)이 필요해서 공연 단위 행을 쓴다
    hourly = load_hourly()
    if hourly.event_audience.sum() == 0:
        print("경고: config/upcoming_events_hourly.csv에 공연이 없음 → 공연 없음으로 계산")
    model, dist = fit_deploy()

    df = build_hours(hourly)
    df["score"] = to_score(predict_baseline(model, df), dist, is_commute(df.day_type, df.hour))
    df["level"] = level_index(df.score)
    df["reason"] = [reason(r) for r in df.itertuples()]

    records = []
    for sid, spot in spots.items():
        for r in df.itertuples():
            score, level, why = adjust(spot, r.datetime, int(r.score), int(r.level), r.reason, events)
            records.append({"spot_id": sid, "datetime": f"{r.datetime:%Y-%m-%dT%H:%M}",
                            "crowd_score": score, "crowd_level": LEVELS[level], "reason": why})

    text = "[\n" + ",\n".join(json.dumps(x, ensure_ascii=False) for x in records) + "\n]\n"
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8")
    WEB_PATH.write_text(text, encoding="utf-8")
    print(f"웹 사본: {WEB_PATH}")

    out = pd.DataFrame(records)
    print(f"\n저장: {OUT_PATH} ({len(out)}건 = {df.datetime.dt.date.nunique()}일 × "
          f"{len(SERVE_HOURS)}시간 × 스팟 {len(spots)}개)")
    print("공휴일:", {f"{d:%m-%d}": n for d, n in df.groupby(df.datetime.dt.date).holiday_name.first().dropna().items()})
    print("공연 있는 운영시간 칸:", int(df.has_event.sum()))
    print("등급 비율(%):", (out.crowd_level.value_counts(normalize=True) * 100).reindex(LEVELS).round(1).to_dict())
    print("요일 유형별 평균 점수:", df.groupby("day_type").score.mean().round(0).to_dict())
    print("공연 보정된 칸:", int((out.reason.str.contains("공연 입장|공연 퇴장")).sum()))


if __name__ == "__main__":
    main()

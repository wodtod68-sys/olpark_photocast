"""미래 공연: 손으로 정리한 공연 일정(1행 = 공연 1회)을 2025 데이터와 같은 시간별 형식으로 바꾼다.

실행: python -m src.events
입력: config/events_manual.csv (date, start, venue, title, audience, source_url), config/venues.json
결과: config/upcoming_events_hourly.csv (datetime, event_name, event_audience, venues)
"""
import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.spot_adjust import load_venues

ROOT = Path(__file__).resolve().parent.parent
MANUAL_PATH = ROOT / "config" / "events_manual.csv"
HOURLY_PATH = ROOT / "config" / "upcoming_events_hourly.csv"
RAW_2025 = ROOT / "data" / "processed" / "olpark_2025.csv"
START, END = "2026-12-01", "2027-02-28"  # 내보내기 기간
EVENT_HOURS = 5  # 공연 1회가 관람객수에 잡히는 시간 수 (2025 데이터 중앙값, measure_event_hours)
# 2025 데이터는 시작 1시간 전부터 기록했다 (god 2025-12-06 18:00 시작 → 17~21시 기록)
LEAD_HOURS = 1
OCCUPANCY = 0.9  # 관람객 수 빈칸 → 좌석 수 × 점유율 (가정)
JOIN = " + "


def measure_event_hours() -> pd.Series:
    """2025 공연이 있는 날마다, 관람객수가 처음 기록된 시각부터 연속으로 기록된 시간 수."""
    df = pd.read_csv(RAW_2025, parse_dates=["datetime"])
    on = set(df[df.event_audience > 0].datetime)
    first = df[df.event_audience > 0].groupby(df.datetime.dt.date).datetime.min()
    runs = {}
    for date, t in first.items():
        n = 0
        while t + timedelta(hours=n) in on:
            n += 1
        runs[date] = n
    return pd.Series(runs)


def load_events(venues: dict) -> pd.DataFrame:
    """공연 단위 행을 검증해서 돌려준다. 틀린 행이 있으면 행 번호와 함께 출력하고 멈춘다.
    결과 열: start, venue, title, audience."""
    ev = pd.read_csv(MANUAL_PATH, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    errors = []
    for i, r in ev.iterrows():
        line = i + 2  # 파일의 줄 번호 (1줄은 제목)
        if r.venue not in venues:
            errors.append(f"{line}행: venue '{r.venue}'이 config/venues.json에 없음 (허용: {list(venues)})")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.date) or pd.isna(pd.to_datetime(r.date, errors="coerce")):
            errors.append(f"{line}행: date '{r.date}' 형식 오류 (YYYY-MM-DD)")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", r.start):
            errors.append(f"{line}행: start '{r.start}' 형식 오류 (HH:MM)")
        if r.audience.strip() and not r.audience.strip().isdigit():
            errors.append(f"{line}행: audience '{r.audience}'는 숫자여야 함")
    dup = ev[ev.duplicated(["date", "start", "venue"], keep=False)]
    for key, g in dup.groupby(["date", "start", "venue"]):
        errors.append(f"{', '.join(str(i + 2) for i in g.index)}행: 같은 (date, start, venue) 중복 {key}")
    if errors:
        print("\n".join(errors))
        sys.exit(f"config/events_manual.csv에 틀린 행 {len(errors)}건 → 고친 뒤 다시 실행하세요")

    out = pd.DataFrame({"start": pd.to_datetime(ev.date + " " + ev.start), "venue": ev.venue, "title": ev.title})
    seats = ev.venue.map(lambda v: venues[v]["seats"])
    out["audience"] = [int(a) if a.strip() else round(s * OCCUPANCY) for a, s in zip(ev.audience, seats)]
    outside = out[(out.start < START) | (out.start >= pd.Timestamp(END) + timedelta(days=1))]
    if len(outside):
        print(f"경고: 내보내기 기간({START}~{END}) 밖의 공연 {len(outside)}건은 시간별 파일에서 빠짐")
    return out


def to_hourly(events: pd.DataFrame) -> pd.DataFrame:
    """공연 1회를 [floor(start) − LEAD_HOURS]부터 EVENT_HOURS개 칸으로 펼치고(18:00 → 17~21시, 19:30 → 18~22시),
    같은 칸끼리 합친다. 이름·공연장은 " + "로 잇고(같은 이름은 한 번만), 관람객수는 더한다."""
    rows = []
    for e in events.itertuples():
        first = e.start.floor("h") - timedelta(hours=LEAD_HOURS)
        for k in range(EVENT_HOURS):
            rows.append((first + timedelta(hours=k), e.title, e.audience, e.venue))
    spread = pd.DataFrame(rows, columns=["datetime", "title", "audience", "venue"])
    agg = spread.groupby("datetime").agg(
        event_name=("title", lambda s: JOIN.join(dict.fromkeys(s))),
        event_audience=("audience", "sum"),
        venues=("venue", lambda s: JOIN.join(dict.fromkeys(s))))
    hours = pd.DataFrame({"datetime": pd.date_range(START, f"{END} 23:00", freq="h")})
    out = hours.merge(agg, on="datetime", how="left")
    out["event_audience"] = out.event_audience.fillna(0).astype(int)
    return out  # 공연 없는 시간: event_name·venues 빈칸, event_audience 0


def load_hourly() -> pd.DataFrame:
    if not HOURLY_PATH.exists():
        sys.exit("config/upcoming_events_hourly.csv가 없습니다. 먼저 python -m src.events 를 실행하세요")
    return pd.read_csv(HOURLY_PATH, parse_dates=["datetime"], encoding="utf-8-sig")


def main():
    runs = measure_event_hours()
    print(f"[2025 공연 1회 길이] 공연 있는 날 {len(runs)}일, 처음 기록 시각부터 연속 기록 시간 수 "
          f"중앙값 {runs.median():.0f}시간 (사용 값 EVENT_HOURS={EVENT_HOURS})")
    print("  분포:", runs.value_counts().sort_index().to_dict())

    venues = load_venues()
    events = load_events(venues)
    filled = (pd.read_csv(MANUAL_PATH, dtype=str, keep_default_na=False).audience.str.strip() == "").sum()
    print(f"\n[미래 공연] {len(events)}회 ({events.start.min():%Y-%m-%d} ~ {events.start.max():%Y-%m-%d}), "
          f"audience 빈칸 {filled}건 → 좌석 수 × {OCCUPANCY}")
    print("  공연장별 회차·1회 관람객:",
          events.groupby("venue").audience.agg(["size", "first"]).rename(columns={"size": "회차", "first": "1회"}).to_dict("index"))

    hourly = to_hourly(events)
    hourly.to_csv(HOURLY_PATH, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")
    print(f"저장: {HOURLY_PATH.relative_to(ROOT)} ({len(hourly)}행, 공연 있는 시간 {(hourly.event_audience > 0).sum()}개)")

    per_day = events.groupby(events.start.dt.date).size()
    day_max = hourly.groupby(hourly.datetime.dt.date).event_audience.max()
    top = pd.DataFrame({"공연 수": per_day, "하루 최대 event_audience": day_max}).dropna()
    top = top.sort_values("하루 최대 event_audience", ascending=False).head(10)
    top.index = [f"{pd.Timestamp(d):%m-%d}({'월화수목금토일'[pd.Timestamp(d).day_of_week]})" for d in top.index]
    print("\n[하루 최대 event_audience 상위 10일]")
    print(top.astype(int).to_string())


if __name__ == "__main__":
    main()

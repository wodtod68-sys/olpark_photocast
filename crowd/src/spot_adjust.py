"""5단계: 스팟 공연 보정. 공연의 입장·퇴장 시간대와 겹치는 1시간 칸에서,
그 공연장(venue)이 스팟의 near_venues에 있으면 등급을 한 단계 올린다. 공연 중에는 올리지 않는다.

입장·퇴장 시간대는 2025 데이터에서 공연 날의 시간당 주차대수 변화를 공연 없는 날과 비교해 정했다
(measure_flows). 18:00 공연이면 도착이 14~17시(정점 15시대), 퇴장이 20~21시에 몰렸다.
  입장: [floor(시작) − 4시간, 시작)            18:00 → 14:00~18:00, 19:30 → 15:00~19:30
  퇴장: [floor(시작) + 2시간, floor(시작) + 4시간)   18:00 → 20:00~22:00

2025 데이터에는 공연장 정보가 없어서, 이 보정은 6단계 내보내기에만 적용한다 (2025 평가는 보정 전 기준).
실행: python -m src.spot_adjust   (config 검증 + 2025 입장·퇴장 측정 + 예시 출력)
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.score import BOUNDS, LEVELS

ROOT = Path(__file__).resolve().parent.parent
VENUES_PATH = ROOT / "config" / "venues.json"
SPOTS_PATH = ROOT / "config" / "spots.json"
FEAT_PATH = ROOT / "data" / "processed" / "olpark_2025_features.csv"
SLOT = timedelta(hours=1)
ARRIVE_FROM = timedelta(hours=4)  # 입장: floor(시작) − 4시간부터 시작 시각까지
EXIT_FROM, EXIT_TO = timedelta(hours=2), timedelta(hours=4)  # 퇴장: floor(시작) + 2시간 ~ + 4시간


def load_venues() -> dict:
    """공연장 이름 → {"seats": 좌석 수}."""
    return json.loads(VENUES_PATH.read_text(encoding="utf-8"))


def check_venues(names, where: str, venues: dict):
    """허용 목록(config/venues.json)에 없는 공연장 이름이 있으면 멈춘다."""
    bad = sorted(set(names) - set(venues))
    if bad:
        sys.exit(f"{where}의 공연장 이름 {bad}이 config/venues.json에 없습니다. 허용: {sorted(venues)}")


def load_spots(venues: dict) -> dict:
    spots = json.loads(SPOTS_PATH.read_text(encoding="utf-8"))
    for sid, s in spots.items():
        check_venues(s["near_venues"], f"config/spots.json의 {sid}", venues)
    empty = [sid for sid, s in spots.items() if not s["near_venues"]]
    if empty:
        print(f"경고: near_venues가 비어 있는 스팟 {empty} → 공연 보정 안 함")
    return spots


def phases(start) -> list[tuple[str, pd.Timestamp, pd.Timestamp]]:
    f = start.floor("h")
    return [("입장", f - ARRIVE_FROM, start), ("퇴장", f + EXIT_FROM, f + EXIT_TO)]


def matching_event(spot: dict, slot_start, events: pd.DataFrame):
    """이 칸이 공연장이 near_venues에 있는 공연의 입장·퇴장 시간대와 겹치면 (공연, '입장'|'퇴장'). 없으면 None.
    events: start(datetime), venue."""
    for e in events.sort_values("start", kind="stable").itertuples():  # 같은 시작이면 입력 파일 순서
        if e.venue not in spot["near_venues"]:
            continue
        for name, a, b in phases(e.start):
            if slot_start < b and slot_start + SLOT > a:
                return e, name
    return None


def adjust(spot: dict, slot_start, score: int, level: int, reason: str, events: pd.DataFrame):
    """보정 대상이면 등급 +1(최대 '붐빔'), 점수를 올라간 등급의 하한까지 끌어올리고 근거 문구를 덧붙인다."""
    hit = matching_event(spot, slot_start, events)
    if hit is None:
        return score, level, reason
    e, name = hit
    level = min(level + 1, len(BOUNDS))
    return max(score, BOUNDS[level - 1]), level, f"{reason} · {e.venue} 공연 {name} ({e.start:%H:%M} 시작)"


def measure_flows() -> pd.DataFrame:
    """2025 공연 날(관람객 기록이 연속 5시간인 날), 공연 없는 날의 같은 요일 유형·시각보다
    시간당 주차대수 변화(× 환산 계수, 명)가 얼마나 큰지. 칸은 floor(시작) 기준 (기록 시작 = 시작 − 1시간)."""
    df = pd.read_csv(FEAT_PATH, parse_dates=["datetime"]).sort_values("datetime")
    # 칸 h의 흐름 = h+1시 주차대수 − h시 주차대수 (그 1시간 동안 들어오고 나간 차)
    df["flow"] = (df.parked_cars.shift(-1) - df.parked_cars) * df.factor
    df.loc[df.datetime.shift(-1) - df.datetime != SLOT, "flow"] = np.nan
    event_day = df.groupby("date").has_event.transform("max") == 1
    normal = df[~event_day].groupby(["day_type", "hour"]).flow.mean()
    rows = []
    for _, g in df[event_day].groupby("date"):
        hrs = g[g.has_event == 1].hour.tolist()
        if len(hrs) != 5 or hrs != list(range(hrs[0], hrs[0] + 5)):
            continue
        start_hour = hrs[0] + 1
        for r in g.itertuples():
            if (r.day_type, r.hour) in normal.index and -5 <= r.hour - start_hour <= 5:
                rows.append({"rel": r.hour - start_hour, "excess": r.flow - normal[(r.day_type, r.hour)]})
    out = pd.DataFrame(rows).groupby("rel").excess.agg(["size", "mean", "median"]).round(0)
    out.index = [f"시작{i:+d}h" for i in out.index]
    return out


def main():
    venues = load_venues()
    spots = load_spots(venues)
    print("허용 공연장:", sorted(venues))
    print("스팟:", {k: (v["name"], v["near_venues"]) for k, v in spots.items()})

    print("\n[2025 공연 날 초과 유입(+)·유출(−), 명/시간] 칸 = floor(시작) 기준")
    print(measure_flows().to_string())

    demo_spot = {"near_venues": ["KSPO DOME"]}
    events = pd.DataFrame({"start": [pd.Timestamp("2026-12-05 18:00")], "venue": ["KSPO DOME"]})
    print(f"\n[예시] KSPO DOME 18:00 공연, 70점 '{LEVELS[1]}' 칸 (경계 {BOUNDS})")
    for h in range(13, 23):
        s, lv, r = adjust(demo_spot, pd.Timestamp(f"2026-12-05 {h:02d}:00"), 70, 1, "토요일", events)
        print(f"  {h}시 칸 → {s}점 {LEVELS[lv]} | {r}")


if __name__ == "__main__":
    main()

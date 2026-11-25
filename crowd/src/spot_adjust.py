"""5단계: 스팟 공연 보정. 공연이 [시작 −90분, 종료 +30분]과 겹치는 1시간 칸에서,
그 공연장(venue)이 스팟의 near_venues에 있으면 등급을 한 단계 올린다.
종료 = 관람객 기록이 끝나는 시각(src.events.load_events의 end, 18:00 시작 → 22:00).

2025 데이터에는 공연장 정보가 없어서, 이 보정은 6단계 내보내기에만 적용한다 (2025 평가는 보정 전 기준).
실행: python -m src.spot_adjust   (config 검증 + 예시 출력)
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.score import BOUNDS, LEVELS

ROOT = Path(__file__).resolve().parent.parent
VENUES_PATH = ROOT / "config" / "venues.json"
SPOTS_PATH = ROOT / "config" / "spots.json"
BEFORE, AFTER = timedelta(minutes=90), timedelta(minutes=30)
SLOT = timedelta(hours=1)


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


def matching_event(spot: dict, slot_start, events: pd.DataFrame):
    """이 칸이 [시작 −90분, 종료 +30분]과 겹치고 공연장이 near_venues에 있는 첫 공연. 없으면 None.
    events: start, end(datetime), venue."""
    for e in events.sort_values("start").itertuples():
        if e.venue in spot["near_venues"] and slot_start < e.end + AFTER and slot_start + SLOT > e.start - BEFORE:
            return e
    return None


def adjust(spot: dict, slot_start, score: int, level: int, reason: str, events: pd.DataFrame):
    """보정 대상이면 등급 +1(최대 '붐빔'), 점수를 올라간 등급의 하한까지 끌어올리고 근거 문구를 덧붙인다."""
    e = matching_event(spot, slot_start, events)
    if e is None:
        return score, level, reason
    level = min(level + 1, len(BOUNDS))
    return max(score, BOUNDS[level - 1]), level, f"{reason} · {e.venue} 공연 동선 ({e.start:%H:%M} 시작)"


def main():
    venues = load_venues()
    spots = load_spots(venues)
    print("허용 공연장:", sorted(venues))
    print("스팟:", {k: (v["name"], v["near_venues"]) for k, v in spots.items()})

    # 예시: near_venues에 KSPO DOME이 있다고 가정한 스팟, 18:00~21:00 공연
    demo_spot = {"near_venues": ["KSPO DOME"]}
    events = pd.DataFrame({"start": [pd.Timestamp("2026-12-05 18:00")], "end": [pd.Timestamp("2026-12-05 21:00")],
                           "venue": ["KSPO DOME"]})
    print(f"\n[예시] KSPO DOME 18:00~21:00 공연 → 보정 구간 16:30~21:30, 70점 '{LEVELS[1]}' 칸 (경계 {BOUNDS})")
    for h in [15, 16, 17, 21, 22]:
        s, lv, r = adjust(demo_spot, pd.Timestamp(f"2026-12-05 {h:02d}:00"), 70, 1, "토요일 오후", events)
        print(f"  {h}시 칸 → {s}점 {LEVELS[lv]} | {r}")


if __name__ == "__main__":
    main()

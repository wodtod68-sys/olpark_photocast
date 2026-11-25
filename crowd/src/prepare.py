"""2단계: 혼잡 target과 feature를 만들고, target 정의를 원래 parked_cars와 비교한다.

실행: python -m src.prepare
입력: data/processed/olpark_2025.csv
결과: data/processed/olpark_2025_features.csv, reports/target_compare.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_PATH = ROOT / "data" / "processed" / "olpark_2025.csv"
OUT_PATH = ROOT / "data" / "processed" / "olpark_2025_features.csv"
FIG_PATH = ROOT / "reports" / "target_compare.png"

FEATURES = ["hour", "dow", "is_weekend", "holiday_type", "month", "has_event", "event_audience",
            "temp", "is_rain", "humidity", "wind_speed"]
OPEN_HOURS = range(7, 23)  # 운영시간 07~22시
HOLIDAY_TYPES = {"none": 0, "public": 1, "major": 2}
MAJOR_RE = r"구정|설날|추석"  # 설·추석 연휴(대체공휴일 포함)
# 집계 범위가 바뀐 것으로 보이는 기간(하루 최대가 평소의 약 1/4). 학습·테스트에서 뺀다
EXCLUDE = ("2025-08-01", "2025-09-30")
DAY_TYPES = ["평일", "주말·일반공휴일", "명절"]


def holiday_type(names: pd.Series) -> pd.Series:
    """휴일명 → 0(none) / 1(public) / 2(major). 6단계에서 미래 공휴일에도 같은 규칙을 쓴다."""
    out = names.notna().astype(int) * HOLIDAY_TYPES["public"]
    out[names.fillna("").str.contains(MAJOR_RE)] = HOLIDAY_TYPES["major"]
    return out


def day_type(is_weekend: pd.Series, htype: pd.Series) -> pd.Series:
    """baseline 그룹: 명절 > 주말·일반공휴일 > 평일."""
    out = pd.Series("평일", index=is_weekend.index)
    out[(is_weekend == 1) | (htype == HOLIDAY_TYPES["public"])] = "주말·일반공휴일"
    out[htype == HOLIDAY_TYPES["major"]] = "명절"
    return out


def people_factor(is_weekend: pd.Series, htype: pd.Series) -> pd.Series:
    """기관의 차량→인원 환산 계수: 평일 3, 주말·공휴일 5."""
    return ((is_weekend == 1) | (htype > 0)).map({True: 5, False: 3})


def build(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = df.datetime.dt.date
    df["hour"] = df.datetime.dt.hour
    df["dow"] = df.datetime.dt.day_of_week  # 월=0 … 일=6
    df["is_weekend"] = (df.dow >= 5).astype(int)
    df["holiday_type"] = holiday_type(df.holiday_name)
    df["day_type"] = day_type(df.is_weekend, df.holiday_type)
    df["month"] = df.datetime.dt.month
    df["has_event"] = (df.event_audience > 0).astype(int)
    df["is_rain"] = (df.precip > 0).astype(int)

    excluded = df.datetime.between(EXCLUDE[0], EXCLUDE[1] + " 23:59")
    print(f"집계 범위가 달라 뺀 기간 {EXCLUDE[0]}~{EXCLUDE[1]}: {excluded.sum()}행")
    df = df[~excluded]

    # 그날 03~05시 최솟값(밤샘·장기 주차) 대비 증가분. 03~05시 값이 없는 날은 뺀다
    night_min = df[df.hour.between(3, 5)].groupby("date").parked_cars.min().rename("night_min")
    df = df.join(night_min, on="date")
    dropped = df[df.night_min.isna()]
    print(f"03~05시 값이 없어 뺀 날: {dropped.date.nunique()}일, {len(dropped)}행 "
          f"(월별 {dropped.month.value_counts().sort_index().to_dict()})")
    df = df[df.night_min.notna()].copy()
    df["increase"] = df.parked_cars - df.night_min

    # 입차가 기록되지 않고 출차만 빠지는 날(말일, 11/7~, 12/8~ 등): 운영시간에도 새벽보다 낮다
    open_median = df[df.hour.isin(OPEN_HOURS)].groupby("date").increase.median()
    broken = open_median[open_median <= 0].index
    print(f"입차가 기록되지 않은 것으로 보여 뺀 날: {len(broken)}일 "
          f"(월별 {pd.Series(pd.to_datetime(broken).month).value_counts().sort_index().to_dict()})")
    df = df[~df.date.isin(broken)].copy()

    # target: 증가분 × 기관 환산 계수 (차량 → 인원)
    df["factor"] = people_factor(df.is_weekend, df.holiday_type)
    mismatch = (df.factor != (df.visitors / df.parked_cars).round()).sum()
    print(f"환산 계수 규칙이 데이터의 visitors/parked_cars와 다른 행: {mismatch}")
    df["crowd"] = df.increase * df.factor
    return df


def effect_table(df: pd.DataFrame) -> pd.DataFrame:
    """운영시간 기준, 각 지표에서 요일 유형·공연 효과가 시간별 흔들림 대비 얼마나 큰지."""
    d = df[df.hour.isin(OPEN_HOURS)]
    event_day = d.groupby("date").has_event.transform("max").eq(1)
    rows = []
    for col in ["parked_cars", "increase", "crowd"]:
        base = d[d.day_type.eq("평일") & ~event_day][col]  # 기준: 평일, 공연 없는 날
        for name, grp in [("평일, 공연 있음", d[d.day_type.eq("평일") & event_day][col]),
                          ("주말·일반공휴일", d[d.day_type.eq("주말·일반공휴일")][col]),
                          ("명절", d[d.day_type.eq("명절")][col])]:
            pooled = ((base.var() + grp.var()) / 2) ** 0.5
            rows.append({"지표": col, "비교": name, "기준 평균": base.mean(), "비교 평균": grp.mean(),
                         "표준화 차이(d)": (grp.mean() - base.mean()) / pooled})
    return pd.DataFrame(rows).round(2)


def plot(df: pd.DataFrame):
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    event_day = df.groupby("date").has_event.transform("max").eq(1)
    groups = [("평일, 공연 없음", df.day_type.eq("평일") & ~event_day, "#2a78d6"),
              ("평일, 공연 있음", df.day_type.eq("평일") & event_day, "#1baf7a"),
              ("주말·일반공휴일", df.day_type.eq("주말·일반공휴일"), "#eb6834"),
              ("명절", df.day_type.eq("명절"), "#eda100")]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, col, title, unit in [
            (axes[0], "parked_cars", "원래 값: parked_cars (재차 대수)", "대"),
            (axes[1], "crowd", "target: (parked_cars - 03~05시 최솟값) × 환산 계수(3/5)", "명")]:
        for label, mask, color in groups:
            s = df[mask].groupby("hour")[col].mean()
            ax.plot(s.index, s.values, color=color, lw=2, label=f"{label} ({df[mask].date.nunique()}일)")
        ax.axvspan(7, 22, color="#000", alpha=0.04, lw=0)
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_xlabel("시각 (음영: 운영시간 07~22시)")
        ax.set_ylabel(f"시간대별 평균 ({unit})")
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlim(0, 23)
        ax.grid(axis="y", color="#ddd", lw=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].legend(fontsize=8, frameon=False, loc="upper left")
    fig.suptitle("요일 유형·공연 효과: 원래 주차대수 vs target (2025, 8~9월·고장일 제외)",
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PATH, dpi=150)
    print(f"저장: {FIG_PATH.relative_to(ROOT)}")


def main():
    df = build(pd.read_csv(IN_PATH, parse_dates=["datetime"]))

    night = df.groupby("date").night_min.first()
    print(f"\n[03~05시 최솟값] 평균 {night.mean():.0f}, 최소 {night.min():.0f}, 최대 {night.max():.0f}")
    print(f"  증가분이 음수인 행: {(df.increase < 0).sum()} (03~05시 최솟값보다 낮아지는 시간, 그대로 둠)")
    print("  holiday_type별 날 수:", df.groupby("holiday_type").date.nunique().to_dict())
    print("  명절로 분류된 휴일명:", sorted(df[df.holiday_type == 2].holiday_name.unique()))

    print("\n[효과 크기 비교 — 운영시간, 기준: 평일·공연 없는 날]")
    print(effect_table(df).to_string(index=False))

    plot(df)
    cols = ["datetime", "date", "crowd", "increase", "parked_cars", "factor", "day_type"] + FEATURES
    df[cols].to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT_PATH.relative_to(ROOT)} ({len(df)}행, {df.date.nunique()}일)")
    print("  월별 날 수:", df.groupby("month").date.nunique().to_dict())
    print("[feature 결측]", df[FEATURES].isna().sum()[lambda s: s > 0].to_dict())


if __name__ == "__main__":
    main()

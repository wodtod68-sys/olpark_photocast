"""3단계: baseline과 LightGBM을 1~7월로 학습하고 10~12월로 평가한다 (8~9월은 2단계에서 제외).

실행: python -m src.train
입력: data/processed/olpark_2025_features.csv, data/processed/olpark_2025.csv(12/13 예측용 날씨)
결과: reports/test_actual_vs_pred.png, reports/feature_importance.png
"""
from pathlib import Path

import lightgbm as lgb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.prepare import FEATURES, OPEN_HOURS, day_type, holiday_type

ROOT = Path(__file__).resolve().parent.parent
FEAT_PATH = ROOT / "data" / "processed" / "olpark_2025_features.csv"
RAW_PATH = ROOT / "data" / "processed" / "olpark_2025.csv"
REPORTS = ROOT / "reports"

TRAIN_MONTHS = range(1, 8)  # 1~7월 (8~9월은 제외된 기간)
TEST_MONTHS = range(10, 13)
TEMP_BOUNDS = [30, 55, 75]  # 등급 경계(임시: 웹의 현재 값). 4단계에서 분포를 보고 정한다
LEVELS = ["여유", "보통", "약간 붐빔", "붐빔"]
COMMUTE_HOURS = range(7, 11)  # 평일 07~10시: 체육시설·업무 이용 시간대


# ---------- baseline: (요일 유형 × 시간 [× 계절]) 평균 + 공연 시간대 증가분 ----------
EVENT_LINEAR = True  # A: 공연 증가분 = 시간대별 계수 × event_audience (False면 시간대별 고정값)
USE_SEASON = False   # B: 그룹에 계절 추가 — 테스트 MAE가 나빠져서 끔
SEASON_MIN_N = 10    # (요일 유형 × 시간 × 계절) 칸의 관측 수가 이보다 적으면 계절 무시
SEASONS = {12: "겨울", 1: "겨울", 2: "겨울", 10: "가을", 11: "가을"}  # 나머지(3~9월)는 봄·여름


def season(month: pd.Series) -> pd.Series:
    return month.map(SEASONS).fillna("봄·여름")


def _cell_means(rows: pd.DataFrame, keys: list) -> pd.DataFrame:
    """공연 없는 시간의 평균(없으면 전체 평균)과 그 관측 수."""
    stats = rows[rows.has_event == 0].groupby(keys).crowd.agg(["mean", "size"])
    return stats.combine_first(rows.groupby(keys).crowd.agg(["mean", "size"]))


def _base(model: dict, df: pd.DataFrame) -> np.ndarray:
    g2 = model["group"]["mean"]
    out = np.array([g2.get((d, h), np.nan) for d, h in zip(df.day_type, df.hour)])
    if model["season_group"] is not None:
        g3 = model["season_group"]
        s3 = [g3.get((d, h, s), np.nan) for d, h, s in zip(df.day_type, df.hour, season(df.month))]
        out = np.where(np.isnan(s3), out, s3)
    return out


def fit_baseline(train: pd.DataFrame, event_linear=EVENT_LINEAR, use_season=USE_SEASON) -> dict:
    model = {"group": _cell_means(train, ["day_type", "hour"]), "season_group": None,
             "event_linear": event_linear}
    if use_season:
        g3 = _cell_means(train.assign(season=season(train.month)), ["day_type", "hour", "season"])
        model["season_group"] = g3[g3["size"] >= SEASON_MIN_N]["mean"]

    ev = train[train.has_event == 1]
    resid = ev.crowd - _base(model, ev)
    if event_linear:
        # 시간대별로 원점을 지나는 최소제곱: 증가분 = b_h × 관람객수
        a = ev.event_audience
        model["event_inc"] = (resid * a).groupby(ev.hour).sum() / (a ** 2).groupby(ev.hour).sum()
        model["event_inc_default"] = (resid * a).sum() / (a ** 2).sum()
    else:
        model["event_inc"] = resid.groupby(ev.hour).mean()
        model["event_inc_default"] = resid.mean()
    return model


def predict_baseline(model: dict, df: pd.DataFrame) -> np.ndarray:
    inc = df.hour.map(model["event_inc"]).fillna(model["event_inc_default"]).to_numpy()
    scale = df.event_audience.to_numpy() if model["event_linear"] else df.has_event.to_numpy()
    return _base(model, df) + scale * inc


# ---------- LightGBM (기본 하이퍼파라미터) ----------
def fit_lgbm(train: pd.DataFrame, features=FEATURES) -> lgb.Booster:
    # 기본 API(scikit-learn 불필요). 하이퍼파라미터는 기본값, 반복 100회도 기본값
    params = {"objective": "regression", "seed": 0, "verbose": -1}
    return lgb.train(params, lgb.Dataset(train[features], train.crowd))


# ---------- 점수·등급 (임시, 4단계에서 확정) ----------
def score_dist(train: pd.DataFrame) -> np.ndarray:
    """백분위 기준 분포: 운영시간에서 평일 07~10시를 뺀 실제값."""
    commute = (train.day_type == "평일") & train.hour.isin(COMMUTE_HOURS)
    return np.sort(train[~commute].crowd.to_numpy())


def to_score(values, dist: np.ndarray) -> np.ndarray:
    return np.clip(np.searchsorted(dist, values, side="right") / len(dist) * 100, 0, 100)


def to_level(score) -> np.ndarray:
    return np.digitize(score, TEMP_BOUNDS)


def evaluate(name, actual, pred, dist, commute_mask) -> dict:
    lv_a, lv_p = to_level(to_score(actual, dist)), to_level(to_score(pred, dist))
    return {"모델": name, "MAE(명)": np.abs(actual - pred).mean().round(0),
            "등급 일치율": (lv_a == lv_p).mean().round(3),
            "등급 일치율(평일 07~10시 제외)": (lv_a == lv_p)[~commute_mask].mean().round(3),
            "등급 ±1 이내": (np.abs(lv_a - lv_p) <= 1).mean().round(3)}


# ---------- 12/13 (공연 없는 주말, 주차 데이터는 고장) ----------
def dec13_frame() -> pd.DataFrame:
    raw = pd.read_csv(RAW_PATH, parse_dates=["datetime"])
    hours = pd.DataFrame({"datetime": pd.date_range("2025-12-13 07:00", "2025-12-13 22:00", freq="h")})
    df = hours.merge(raw, on="datetime", how="left")  # 빠진 시간은 날씨 NaN (LightGBM이 처리)
    df["hour"] = df.datetime.dt.hour
    df["dow"] = df.datetime.dt.day_of_week
    df["is_weekend"] = (df.dow >= 5).astype(int)
    df["holiday_type"] = holiday_type(df.holiday_name)
    df["day_type"] = day_type(df.is_weekend, df.holiday_type)
    df["month"] = 12
    df["event_audience"] = df.event_audience.fillna(0)
    df["has_event"] = (df.event_audience > 0).astype(int)
    df["is_rain"] = (df.precip.fillna(0) > 0).astype(int)
    return df


def plot_test(test: pd.DataFrame):
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    periods = [("10월", test.month == 10), ("11/1~6", test.month == 11), ("12/1~7", test.month == 12)]
    fig = plt.figure(figsize=(14, 7))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], width_ratios=[6, 7])
    axes = [fig.add_subplot(gs[0, :]), fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])]
    series = [("실제", "actual", "#333333", 1.6), ("baseline", "pred_base", "#2a78d6", 1.2),
              ("LightGBM", "pred_lgbm", "#eb6834", 1.2)]
    for ax, (title, mask) in zip(axes, periods):
        d = test[mask].reset_index(drop=True)
        x = np.arange(len(d))
        for label, col, color, lw in series:
            ax.plot(x, d[col], color=color, lw=lw, label=label)
        starts = d.index[d.datetime.dt.date != d.datetime.dt.date.shift()]
        ax.set_xticks(starts)
        ax.set_xticklabels([f"{t:%d}\n{'월화수목금토일'[t.day_of_week]}" for t in d.datetime[starts]], fontsize=7)
        for s in starts:
            ax.axvline(s, color="#eee", lw=0.6, zorder=0)
        ax.set_title(f"{title} (운영시간 07~22시만 이어 붙임)", fontsize=10, loc="left")
        ax.set_ylabel("혼잡 target (명)")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].legend(fontsize=8, frameon=False, ncol=3, loc="upper right")
    fig.suptitle("테스트 기간 실제 vs 예측 (학습 1~7월)", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(REPORTS / "test_actual_vs_pred.png", dpi=150)


def plot_importance(model: lgb.Booster):
    imp = pd.Series(model.feature_importance("gain"), index=FEATURES)
    imp = (imp / imp.sum() * 100).sort_values()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh(imp.index, imp.values, color="#2a78d6", height=0.6)
    for y, v in enumerate(imp.values):
        ax.text(v + 0.5, y, f"{v:.1f}%", va="center", fontsize=8, color="#444")
    ax.set_xlabel("gain 비중 (%)")
    ax.set_title("LightGBM feature importance (gain)", fontsize=11, loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(REPORTS / "feature_importance.png", dpi=150)
    return imp.sort_values(ascending=False)


def main():
    df = pd.read_csv(FEAT_PATH, parse_dates=["datetime"])
    df = df[df.hour.isin(OPEN_HOURS)]
    train, test = df[df.month.isin(TRAIN_MONTHS)].copy(), df[df.month.isin(TEST_MONTHS)].copy()
    print(f"학습 {train.date.nunique()}일 {len(train)}행 / 테스트 {test.date.nunique()}일 {len(test)}행")

    print("\n[baseline 개선 전후 — 테스트 MAE(명)]")
    variants = [("기존 (고정 증가분)", False, False), ("A: 공연 관람객 비례", True, False),
                ("B: 계절 추가", False, True), ("A+B", True, True)]
    is_ev = test.has_event == 1
    for name, lin, sea in variants:
        m = fit_baseline(train, lin, sea)
        err = np.abs(test.crowd - predict_baseline(m, test))
        print(f"  {name:<14} 전체 {err.mean():6.0f}  공연 시간 {err[is_ev].mean():6.0f}  "
              f"공연 없는 시간 {err[~is_ev].mean():6.0f}  12월 {err[test.month == 12].mean():6.0f}")
    m = fit_baseline(train, True, True)
    used = test.assign(season=season(test.month)).apply(
        lambda r: (r.day_type, r.hour, r.season) in m["season_group"].index, axis=1)
    print(f"  테스트 행 중 계절 칸을 쓴 비율: 가을 {used[test.month <= 11].mean():.0%}, 겨울 {used[test.month == 12].mean():.0%}")
    print(f"  A의 관람객 1만 명당 증가분(명), 시간대별: {(m['event_inc'] * 10000).round(0).astype(int).to_dict()}")
    print(f"  현재 설정: EVENT_LINEAR={EVENT_LINEAR}, USE_SEASON={USE_SEASON}")

    base = fit_baseline(train)
    lgbm = fit_lgbm(train)
    test["actual"] = test.crowd
    test["pred_base"] = predict_baseline(base, test)
    test["pred_lgbm"] = lgbm.predict(test[FEATURES])

    dist = score_dist(train)
    commute = ((test.day_type == "평일") & test.hour.isin(COMMUTE_HOURS)).to_numpy()
    rows = [evaluate("baseline", test.actual.to_numpy(), test.pred_base.to_numpy(), dist, commute),
            evaluate("LightGBM", test.actual.to_numpy(), test.pred_lgbm.to_numpy(), dist, commute)]
    # 참고: 테스트 월(10~12)은 학습에 없는 month 값이라 month를 뺀 버전도 본다
    no_month = [f for f in FEATURES if f != "month"]
    lgbm_nm = fit_lgbm(train, no_month)
    rows.append(evaluate("LightGBM (month 제외, 참고)", test.actual.to_numpy(),
                         lgbm_nm.predict(test[no_month]), dist, commute))
    print(f"\n[테스트 성능] 등급은 임시 경계 {TEMP_BOUNDS} 기준")
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n[요일 유형별 MAE]")
    test["err_base"] = (test.actual - test.pred_base).abs()
    test["err_lgbm"] = (test.actual - test.pred_lgbm).abs()
    print(test.groupby("day_type")[["actual", "err_base", "err_lgbm"]].mean().round(0)
          .join(test.groupby("day_type").date.nunique().rename("일수")).to_string())

    REPORTS.mkdir(exist_ok=True)
    plot_test(test)
    imp = plot_importance(lgbm)
    print("\n[feature importance, gain %]")
    print(imp.round(1).to_string())

    d13 = dec13_frame()
    d13["pred_base"] = predict_baseline(base, d13)
    d13["pred_lgbm"] = lgbm.predict(d13[FEATURES])
    ref = train.groupby(["day_type", "hour"]).crowd.mean().unstack(0)
    print("\n[12/13(토, 공연 없음) 예측 vs 학습 기간 실제 평균] 12/13 실제 주차 데이터는 고장이라 비교 불가")
    table = d13.set_index("hour")[["pred_base", "pred_lgbm"]].join(ref[["주말·일반공휴일", "명절", "평일"]])
    print(table.round(0).astype("Int64").to_string())
    print("  운영시간 평균:", table.mean().round(0).to_dict())
    print(f"\n저장: reports/test_actual_vs_pred.png, reports/feature_importance.png")


if __name__ == "__main__":
    main()

"""1단계-파싱: 원본 TITLE·DESCRIPTION 문자열을 컬럼으로 풀고, 데이터 점검 결과를 출력한다.

실행: python -m src.parse
입력: data/raw/olpark_2025_raw.csv
결과: data/processed/olpark_2025.csv
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "olpark_2025_raw.csv"
OUT_PATH = ROOT / "data" / "processed" / "olpark_2025.csv"

# DESCRIPTION 라벨 → 컬럼. '풍향' 값은 2.0~2.8 수준이라 풍속(m/s)으로 본다
DESC_KEYS = {
    "주차대수": "parked_cars",
    "방문객": "visitors",
    "기온": "temp",
    "풍향": "wind_speed",
    "강수량": "precip",
    "습도": "humidity",
    "휴일": "holiday_name",
}
NUMERIC = ["event_audience", "parked_cars", "visitors", "temp", "wind_speed", "precip", "humidity"]

# 라벨 앞은 문자열 시작이거나 콤마(뒤 공백은 있다가 없다가 한다)
DESC_KEY_RE = re.compile(r"(?:^|,)\s*(" + "|".join(DESC_KEYS) + r")\s*:")
# 공연명 안에 콤마가 있을 수 있으니 마지막 '공연관람객수:' 앞까지를 공연명으로 본다
TITLE_RE = re.compile(r"^\s*공연명:(.*),\s*공연관람객수:(.*)$", re.S)


def parse_description(text: str) -> dict:
    """라벨 위치를 찾아 라벨 사이 구간을 값으로 자른다. 값 안의 콤마는 그대로 남는다."""
    text = str(text).strip()
    matches = list(DESC_KEY_RE.finditer(text))
    out = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[DESC_KEYS[m.group(1)]] = text[m.end():end].strip()
    return out


def parse_title(text: str) -> dict:
    m = TITLE_RE.match(str(text))
    if not m:
        return {"event_name": None, "event_audience": None}
    return {"event_name": m.group(1).strip(), "event_audience": m.group(2).strip()}


def parse(raw: pd.DataFrame) -> pd.DataFrame:
    title = pd.DataFrame([parse_title(t) for t in raw["TITLE"].fillna("")])
    desc = pd.DataFrame([parse_description(d) for d in raw["DESCRIPTION"].fillna("")])
    desc = desc.reindex(columns=list(DESC_KEYS.values()))
    df = pd.concat([raw[["LOCAL_ID"]].rename(columns={"LOCAL_ID": "local_id"}), title, desc], axis=1)
    df.insert(1, "datetime", pd.to_datetime(raw["ISSUED_DATE"]))

    df["event_name"] = df["event_name"].replace("", None)
    df["holiday_name"] = df["holiday_name"].replace("", None)
    df["precip"] = df["precip"].replace("", "0")

    bad = {}
    for col in NUMERIC:
        s = df[col].replace("", None)
        num = pd.to_numeric(s, errors="coerce")
        failed = s.notna() & num.isna()
        if failed.any():
            bad[col] = s[failed].unique()[:5].tolist()
        df[col] = num
    df["event_audience"] = df["event_audience"].astype("Int64")

    if bad:
        print("숫자로 바꾸지 못한 값 (예시):", bad)
    return df.sort_values("datetime", kind="stable").reset_index(drop=True)


def summarize(df: pd.DataFrame, raw: pd.DataFrame):
    pd.set_option("display.width", 160)
    print(f"\n[건수] {len(df)}건, 기간 {df.datetime.min()} ~ {df.datetime.max()}")

    print("\n[파싱 점검]")
    print("  TITLE 형식이 다른 행:", int((~raw["TITLE"].fillna("").str.match(TITLE_RE)).sum()))
    # 아는 라벨을 지운 뒤에도 콜론이 남으면 모르는 라벨이 있는 것
    leftover = raw["DESCRIPTION"].fillna("").map(lambda t: DESC_KEY_RE.sub(",", t))
    print("  DESCRIPTION에 알 수 없는 라벨이 있는 행:", int(leftover.str.contains(":").sum()))
    dup_dt = df.datetime.duplicated(keep=False)
    print("  같은 시각이 2건 이상인 행:", int(dup_dt.sum()))

    print("\n[컬럼별 결측 비율 %]")
    print((df.isna().mean() * 100).round(2).to_string())

    print("\n[visitors / parked_cars 비율]")
    ratio = (df.visitors / df.parked_cars).round(3)
    print(ratio.value_counts(dropna=False).head(5).to_string())

    full = pd.date_range("2025-01-01 00:00", "2025-12-31 23:00", freq="h")
    missing = full.difference(df.datetime)
    print(f"\n[빠진 시간] 전체 {len(full)}시간 중 {len(missing)}시간 없음")
    m = pd.Series(missing)
    print("  월별:", m.dt.month.value_counts().sort_index().to_dict())
    print("  시간대별:", m.dt.hour.value_counts().sort_index().to_dict())
    # 연속으로 빠진 구간 (길이 순)
    gid = (m.diff() != pd.Timedelta(hours=1)).cumsum()
    runs = m.groupby(gid).agg(["first", "last", "count"]).sort_values("count", ascending=False)
    print("  연속으로 빠진 구간 상위 10:")
    print(runs.head(10).to_string(index=False))
    print("  빠진 시간이 1~2시간짜리인 구간 수:", int((runs["count"] <= 2).sum()), "/", len(runs))
    days_missing = m.dt.date.value_counts()
    print("  하루 24시간이 통째로 빠진 날 수:", int((days_missing == 24).sum()))

    ev = df[df.event_audience.fillna(0) > 0]
    print(f"\n[공연] 관람객수>0인 행 {len(ev)}개, 공연이 있는 날 {ev.datetime.dt.date.nunique()}일")
    print("  관람객수>0인데 공연명이 없는 행:", int(ev.event_name.isna().sum()),
          "/ 공연명이 있는데 관람객수 0인 행:", int((df.event_name.notna() & (df.event_audience.fillna(0) == 0)).sum()))
    print("  관람객수 분포(행 기준):")
    print(ev.event_audience.describe().round(0).to_string())
    print("  공연이 있는 날 하루 안에서 관람객수>0인 시간 수 분포:",
          ev.groupby(ev.datetime.dt.date).size().value_counts().sort_index().to_dict())
    print("  관람객수>0 시간대 분포:", ev.datetime.dt.hour.value_counts().sort_index().to_dict())
    same = ev.groupby(ev.datetime.dt.date).event_audience.nunique()
    print("  하루 안에서 관람객수 값이 시간마다 같은 날:", int((same == 1).sum()), "/", len(same))
    print("  공연명 상위 15 (행 수):")
    print(ev.event_name.value_counts().head(15).to_string())

    print("\n[holiday_name 종류] (행 수)")
    print(df.holiday_name.value_counts(dropna=False).to_string())


def main():
    raw = pd.read_csv(RAW_PATH, dtype=str, keep_default_na=False)
    df = parse(raw)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT_PATH.relative_to(ROOT)}")
    summarize(df, raw)


if __name__ == "__main__":
    main()

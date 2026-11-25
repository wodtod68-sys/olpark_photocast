"""1단계-수집: KCISA API_CPM_009(올림픽공원 2025 연계 데이터)를 전부 받아 원본 그대로 저장한다.

실행: python -m src.fetch
결과: data/raw/olpark_2025_raw.csv (TITLE·DESCRIPTION 문자열을 파싱하지 않고 그대로)
"""
import math
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "olpark_2025_raw.csv"
URL = "https://api.kcisa.kr/openapi/API_CPM_009/request"
FIRST_ROWS = 100
SLEEP = 0.3
RETRIES = 3
RATE_LIMIT_SLEEP = 10  # 429를 받으면 기다리는 초
RATE_LIMIT_WAITS = 10  # 한 페이지에서 429를 기다려 줄 최대 횟수

load_dotenv(ROOT / ".env")
KEY = os.getenv("CULTURE_API_KEY", "")


def mask(text: str) -> str:
    """키가 URL·예외 메시지에 섞여 나가지 않게 가린다."""
    return text.replace(KEY, "***") if KEY else text


def fetch_page(page: int, rows: int) -> tuple[list[dict], int]:
    """한 페이지를 받아 (item 목록, totalCount)를 돌려준다. resultCode가 0000이 아니면 멈춘다."""
    params = {"serviceKey": KEY, "numOfRows": rows, "pageNo": page}
    last_err = ""
    attempt = waits = 0
    while True:
        try:
            res = requests.get(URL, params=params, timeout=30)
            if res.status_code == 429 and waits < RATE_LIMIT_WAITS:
                # 호출 빈도 제한: 간격이 일정하지 않아서 재시도 횟수와 따로 세고 기다린다
                waits += 1
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            res.raise_for_status()
            root = ET.fromstring(res.content)
            break
        except (requests.RequestException, ET.ParseError) as e:
            attempt += 1
            last_err = mask(f"{type(e).__name__}: {e}")
            print(f"  page {page} 실패 ({attempt}/{RETRIES}): {last_err}")
            if attempt >= RETRIES:
                sys.exit(f"page {page}를 {RETRIES}번 시도했지만 실패: {last_err}")
            time.sleep(SLEEP * attempt)
    if waits:
        print(f"  page {page}: 429로 {waits}번 기다린 뒤 성공")

    code = root.findtext("header/resultCode")
    if code != "0000":
        sys.exit(f"API 오류 resultCode={code}: {mask(root.findtext('header/resultMsg') or '')}")

    items = [{child.tag: (child.text or "") for child in item} for item in root.iter("item")]
    return items, int(root.findtext("body/totalCount"))


def main():
    if not KEY:
        sys.exit("CULTURE_API_KEY가 없습니다. crowd/.env에 넣어 주세요 (.env.example 참고)")

    items, total = fetch_page(1, FIRST_ROWS)
    rows = FIRST_ROWS
    if len(items) < rows and len(items) < total:
        rows = len(items)  # 서버가 요청보다 적게 주면 그 건수에 맞춘다
        print(f"numOfRows={FIRST_ROWS}을 요청했지만 {rows}건만 와서 {rows}로 조정")
    pages = math.ceil(total / rows)
    print(f"totalCount={total}, numOfRows={rows}, 페이지 {pages}개")

    for page in range(2, pages + 1):
        time.sleep(SLEEP)
        page_items, _ = fetch_page(page, rows)
        items += page_items
        if page % 10 == 0 or page == pages:
            print(f"  {page}/{pages} 페이지, 누적 {len(items)}건")

    df = pd.DataFrame(items)
    before = len(df)
    dup = df[df.duplicated("LOCAL_ID", keep=False)]
    conflicting = dup.drop_duplicates().duplicated("LOCAL_ID").sum()
    df = df.drop_duplicates("LOCAL_ID")
    df = df.sort_values("ISSUED_DATE", key=pd.to_datetime, kind="stable").reset_index(drop=True)
    print(f"받은 건수 {before} → LOCAL_ID 중복 제거 후 {len(df)} (내용이 다른 중복 {conflicting}건)")

    if len(df) != total:
        print(f"경고: 최종 건수 {len(df)}가 totalCount {total}와 다릅니다")
    else:
        print(f"최종 건수가 totalCount {total}와 일치")

    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW_PATH, index=False, encoding="utf-8-sig")
    print(f"저장: {RAW_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

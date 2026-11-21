"""AI 예상 이미지 API.

GET /api/forecast?spot=<id>&datetime=YYYY-MM-DDTHH:00   (한국 시간)
  → forecast 패키지: 조건 계산 → 장면 상태표 → 프롬프트 → Gemini(nb2.1) 이미지 편집
  → { image_url, prompt_version, model, conditions, summary_ko, cached, ... }
GET /api/images/<key>/<gen_N.png>   생성 이미지
GET /api/health

캐시: (spot, datetime, templates version, model)마다 server/cache/<key>/ 에 이미지와 result.json. 있으면 재생성 안 함.
안전장치: 하루 생성 한도 DAILY_LIMIT(기본 30, 한국 날짜 기준, 실제 API 호출 수로 셈) → 초과 시 429.
같은 요청이 동시에 오면 키별 잠금으로 한 번만 생성한다.
키는 server/.env (GEMINI_API_KEY 등)에서 읽는다.
"""
from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from .forecast.common import load_spot, parse_local, load_yaml, env_key, PKG as FORECAST_PKG, log
from .forecast.predict import run_predict
from .forecast.generate import model_info
from .forecast.summary import summary_ko

SERVER = Path(__file__).resolve().parent
CACHE = SERVER / "cache"
SPOTS_DIR = FORECAST_PKG / "spots"
SPOT_IDS = ("naholo", "wild", "rose")
MODEL = "nb2.1"
KST = ZoneInfo("Asia/Seoul")
MAX_DAYS_AHEAD = 8          # 화면은 오늘~7일 뒤만 고를 수 있다
DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:00$")

app = FastAPI(title="Olpark Photocast AI forecast")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET"], allow_headers=["*"])

_locks: dict[str, asyncio.Lock] = {}
_usage_lock = asyncio.Lock()


def daily_limit() -> int:
    v = env_key("DAILY_LIMIT")
    return int(v) if v and v.isdigit() else 30


# ---------------- 하루 사용량 ----------------
def _usage_path() -> Path:
    return CACHE / "usage.json"


def _read_usage() -> dict:
    p = _usage_path()
    return json.loads(p.read_text()) if p.exists() else {}


def _write_usage(u: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    _usage_path().write_text(json.dumps(u, ensure_ascii=False, indent=1))


async def reserve_call() -> None:
    """생성 1회 자리를 미리 잡는다. 한도를 넘으면 429."""
    async with _usage_lock:
        u = _read_usage()
        today = datetime.now(KST).date().isoformat()
        used = u.get(today, 0)
        if used >= daily_limit():
            raise HTTPException(429, f"오늘 예상 이미지 생성 한도({daily_limit()}장)를 다 썼어요. "
                                     f"이미 만든 날짜·시간은 계속 볼 수 있고, 새 이미지는 내일 다시 만들 수 있어요.")
        u[today] = used + 1
        _write_usage(u)


async def settle_calls(actual: int) -> None:
    """미리 잡은 1회를 실제 API 호출 수(재시도 포함)로 맞춘다."""
    async with _usage_lock:
        u = _read_usage()
        today = datetime.now(KST).date().isoformat()
        u[today] = max(0, u.get(today, 0) + actual - 1)
        _write_usage(u)


# ---------------- 응답 ----------------
def cache_key(spot: str, dt: datetime, tver: str, model_id: str) -> str:
    raw = f"{spot}_{dt:%Y%m%d_%H%M}_{tver}_{model_id}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw)


def build_response(spot: dict, res: dict, key: str, image_file: str, tver: str, model_id: str) -> dict:
    t = res["target"]
    return dict(
        spot=spot["id"], datetime=t["datetime_local"][:16],
        image_url=f"/api/images/{key}/{image_file}",
        prompt_version=tver, model=model_id,
        conditions=dict(
            sun_elev=round(t["light"]["elev"], 1), light_stage=t["light"]["stage"],
            direction=t["direction"]["light_direction"], sky=t["sky"], haze=t["haze"]["stage"],
            precip=t["precip"]["form"],
            trees=[dict(name=x["name_ko"], stage=x["stage_ko"]) for x in t["trees"]],
            source=dict(weather=t["source"]["weather"], air=t["source"]["air"]),
        ),
        summary_ko=summary_ko(t),
    )


@app.get("/api/health")
def health():
    return dict(ok=True, model=model_info(MODEL)["id"], daily_limit=daily_limit(),
                used_today=_read_usage().get(datetime.now(KST).date().isoformat(), 0),
                gemini_key=bool(env_key("GEMINI_API_KEY")))


@app.get("/api/forecast")
async def forecast(spot: str = Query(...), datetime_: str = Query(..., alias="datetime")):
    if spot not in SPOT_IDS:
        raise HTTPException(404, f"알 수 없는 스팟: {spot}")
    if not DT_RE.match(datetime_):
        raise HTTPException(400, "datetime 형식은 YYYY-MM-DDTHH:00 (한국 시간)")
    dt = parse_local(datetime_.replace("T", " "), KST)
    now = datetime.now(KST)
    if not (now.date() - timedelta(days=1) <= dt.date() <= now.date() + timedelta(days=MAX_DAYS_AHEAD)):
        raise HTTPException(400, f"오늘부터 {MAX_DAYS_AHEAD - 1}일 뒤까지만 예상할 수 있어요")

    tver = load_yaml("templates.yaml")["version"]
    model_id = model_info(MODEL)["id"]
    key = cache_key(spot, dt, tver, model_id)
    out_dir = CACHE / key
    result_file = out_dir / "result.json"

    def cached():
        if result_file.exists():
            r = json.loads(result_file.read_text(encoding="utf-8"))
            r["cached"] = True
            return r
        return None

    if (r := cached()) is not None:
        return r
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        if (r := cached()) is not None:       # 기다리는 동안 다른 요청이 만들었으면 그대로 쓴다
            return r
        await reserve_call()
        calls = 1
        try:
            sp = load_spot(str(SPOTS_DIR / f"{spot}.yaml"))
            res = await run_in_threadpool(run_predict, sp, dt, 1, MODEL, False, None, out_dir, True)
            gens = res["meta"]["generations"]
            calls = res["meta"]["api_calls"] or 1
            ok = [g for g in gens if g.get("file")]
            if not ok:
                err = gens[0].get("error", "알 수 없는 오류") if gens else "생성 결과 없음"
                raise HTTPException(502, f"이미지 생성에 실패했어요: {err[:200]}")
        except HTTPException:
            raise
        except Exception as ex:
            log.exception("forecast 실패")
            raise HTTPException(502, f"조건 계산 또는 이미지 생성 중 오류: {str(ex)[:200]}")
        finally:
            await settle_calls(calls)
        body = build_response(sp, res, key, ok[0]["file"], tver, model_id)
        result_file.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        body["cached"] = False
        return body


@app.get("/api/images/{key}/{fname}")
def image(key: str, fname: str):
    # 생성 이미지 파일만 내준다 (상태표·프롬프트·메타는 노출하지 않음)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", key) or not re.fullmatch(r"gen_\d+(_orig)?\.png", fname):
        raise HTTPException(404)
    p = (CACHE / key / fname).resolve()
    if CACHE.resolve() not in p.parents or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

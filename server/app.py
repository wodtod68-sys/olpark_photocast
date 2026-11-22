"""AI 예상 이미지 API + 프롬프트 실험실.

공개 화면
  GET /api/forecast?spot=<id>&datetime=YYYY-MM-DDTHH:00   (한국 시간)
    → 현재 shared 템플릿으로 조건 계산 → 프롬프트 → Gemini(기본 Nano Banana Pro) 이미지 편집
    → { image_url, prompt_version, model, conditions, summary_ko, cached, ... }
  GET /api/images/<key>/<gen_0.jpg>   생성 이미지
  GET /api/health
실험실: /api/lab/... (server/lab/routes.py, 비밀번호 필요)
프론트: dist/ 가 있으면 같은 서버에서 내준다(터널 하나로 접속).

캐시: (spot, datetime, shared 템플릿 id, 모델 id, 기준 사진 해시)마다 server/cache/<key>/.
  모델 id가 키에 들어가므로 Nano Banana 2.1로 만든 예전 캐시는 Pro 요청에 재사용되지 않는다.
안전장치: 하루 생성 한도 DAILY_LIMIT(기본 30, 한국 날짜, 실제 API 호출 수) → 초과 시 429.
같은 요청이 동시에 오면 키별 잠금으로 한 번만 생성한다. 키는 server/.env에서 읽는다.
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
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .forecast.common import env_key, log
from .forecast.generate import model_info, generate_one
from .lab import core
from .lab.routes import router as lab_router

SERVER = Path(__file__).resolve().parent
DIST = SERVER.parent / "dist"
CACHE = SERVER / "cache"
SPOT_IDS = tuple(core.SPOT_IDS)
MODEL = "pro"
KST = ZoneInfo("Asia/Seoul")
MAX_DAYS_AHEAD = 8          # 화면은 오늘~7일 뒤만 고를 수 있다
DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:00$")

app = FastAPI(title="Olpark Photocast AI forecast")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST", "PUT"], allow_headers=["*"], allow_credentials=True)
app.include_router(lab_router)

_locks: dict[str, asyncio.Lock] = {}
_usage_lock = asyncio.Lock()


@app.on_event("startup")
def _startup():
    core.seed_shared()


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
def cache_key(spot: str, dt: datetime, tpl_id: int, model_id: str, base_sha: str) -> str:
    raw = f"{spot}_{dt:%Y%m%d_%H%M}_shared{tpl_id}_{model_id}_{base_sha[:10]}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw)


def build_response(c: dict, key: str, image_file: str, tpl: dict, model_id: str) -> dict:
    t = c["target"]
    return dict(
        spot=c["spot"]["id"], datetime=t["datetime_local"][:16],
        image_url=f"/api/images/{key}/{image_file}",
        prompt_version=f"{tpl['name']} (#{tpl['id']})", model=model_id,
        conditions=dict(
            sun_elev=round(t["light"]["elev"], 1), light_stage=t["light"]["stage"],
            direction=t["direction"]["light_direction"], sky=t["sky"], haze=t["haze"]["stage"],
            precip=t["precip"]["form"],
            trees=[dict(name=x["name_ko"], stage=x["stage_ko"]) for x in t["trees"]],
            source=dict(weather=t["source"]["weather"], air=t["source"]["air"]),
        ),
        summary_ko=c["summary_ko"],
    )


@app.get("/api/health")
def health():
    return dict(ok=True, model=model_info(MODEL)["id"], daily_limit=daily_limit(),
                used_today=_read_usage().get(datetime.now(KST).date().isoformat(), 0),
                gemini_key=bool(env_key("GEMINI_API_KEY")), shared_template=core.shared_template()["name"])


@app.get("/api/forecast")
async def forecast(spot: str = Query(...), datetime_: str = Query(..., alias="datetime")):
    if spot not in SPOT_IDS:
        raise HTTPException(404, f"알 수 없는 스팟: {spot}")
    if not DT_RE.match(datetime_):
        raise HTTPException(400, "datetime 형식은 YYYY-MM-DDTHH:00 (한국 시간)")
    dt = core.parse_dt(datetime_)
    now = datetime.now(KST)
    if not (now.date() - timedelta(days=1) <= dt.date() <= now.date() + timedelta(days=MAX_DAYS_AHEAD)):
        raise HTTPException(400, f"오늘부터 {MAX_DAYS_AHEAD - 1}일 뒤까지만 예상할 수 있어요")

    tpl = core.shared_template()
    model_id = model_info(MODEL)["id"]
    try:
        sp = core.spot(spot)
    except Exception as ex:
        raise HTTPException(503, f"스팟 설정을 읽지 못했어요: {str(ex)[:150]}")
    key = cache_key(spot, dt, tpl["id"], model_id, core.file_sha(sp["base_image_path"]))
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
            c = await run_in_threadpool(core.run_compose, spot, datetime_, None, core.template_texts(tpl))
            g = await run_in_threadpool(generate_one, c["prompt"], sp["base_image_path"], MODEL)
            calls = g["attempts"]
            if g.get("image") is None:
                raise HTTPException(502, f"이미지 생성에 실패했어요: {g.get('error', '')[:200]}")
            out_dir.mkdir(parents=True, exist_ok=True)
            core.save_jpeg(g["image"], out_dir / "gen_0.jpg")
            (out_dir / "prompt.txt").write_text(c["prompt"] + "\n", encoding="utf-8")
        except HTTPException:
            raise
        except Exception as ex:
            log.exception("forecast 실패")
            raise HTTPException(502, f"조건 계산 또는 이미지 생성 중 오류: {str(ex)[:200]}")
        finally:
            await settle_calls(calls)
        body = build_response(c, key, "gen_0.jpg", tpl, model_id)
        result_file.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        body["cached"] = False
        return body


@app.get("/api/images/{key}/{fname}")
def image(key: str, fname: str):
    # 생성 이미지 파일만 내준다 (프롬프트·결과 JSON은 노출하지 않음)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", key) or not re.fullmatch(r"gen_\d+(_orig)?\.(png|jpg)", fname):
        raise HTTPException(404)
    p = (CACHE / key / fname).resolve()
    if CACHE.resolve() not in p.parents or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


# 빌드한 프론트(npm run build → dist/)가 있으면 같은 주소에서 내준다. API 경로보다 뒤에 둔다.
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")

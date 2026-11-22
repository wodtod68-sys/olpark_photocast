"""실험실 API (/api/lab/...). 모든 경로는 로그인 쿠키가 있어야 한다(/login 제외).

입장: 공용 비밀번호 LAB_PASSCODE + 사용자 이름(LAB_USERS 쉼표 목록). 서명 쿠키(14일).
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Body, Cookie, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from ..forecast.common import env_key
from ..forecast.generate import MODELS
from . import core, db

router = APIRouter(prefix="/api/lab")
COOKIE = "lab_session"
SECRET_FILE = db.SERVER / ".lab_secret"


# ---------------- 인증 ----------------
def _secret() -> bytes:
    v = env_key("LAB_SECRET")
    if v:
        return v.encode()
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text().strip().encode()


def _users() -> list[str]:
    return [u.strip() for u in (env_key("LAB_USERS") or "").split(",") if u.strip()]


def _sign(user: str, exp: int) -> str:
    body = base64.urlsafe_b64encode(f"{user}|{exp}".encode()).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def current_user(lab_session: str | None = Cookie(default=None)) -> str:
    try:
        body, sig = lab_session.split(".")
        if not hmac.compare_digest(sig, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]):
            raise ValueError
        user, exp = base64.urlsafe_b64decode(body).decode().split("|")
        if int(exp) < time.time() or user not in _users():
            raise ValueError
        return user
    except Exception:
        raise HTTPException(401, "실험실에 먼저 입장해 주세요")


@router.post("/login")
def login(response: Response, passcode: str = Body(...), user: str | None = Body(None)):
    pc = env_key("LAB_PASSCODE")
    if not pc:
        raise HTTPException(503, "서버에 LAB_PASSCODE가 설정되지 않았어요")
    if not hmac.compare_digest(passcode, pc):
        time.sleep(1.0)                             # 무차별 대입 늦추기
        raise HTTPException(403, "비밀번호가 맞지 않아요")
    if not user:
        return dict(users=_users())
    if user not in _users():
        raise HTTPException(403, "등록된 사용자가 아니에요")
    exp = int(time.time()) + 14 * 86400
    response.set_cookie(COOKIE, _sign(user, exp), max_age=14 * 86400, httponly=True, samesite="lax",
                        secure=False, path="/")
    return dict(user=user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return dict(ok=True)


@router.get("/me")
def me(user: str = Depends(current_user)):
    return dict(user=user, remaining=core.remaining(user), daily_limit=core.daily_limit(),
                models={k: dict(id=v["id"], name=v["name"], price=v["usd_per_image"]) for k, v in MODELS.items()},
                default_model=core.DEFAULT_MODEL, users=_users())


# ---------------- 조건·프롬프트·생성 ----------------
@router.get("/spots")
def spots(user: str = Depends(current_user)):
    out = []
    for sid in core.SPOT_IDS:
        try:
            sp = core.spot(sid)
            out.append(dict(id=sid, name=sp["name"], base_datetime=sp["base_dt"].isoformat()[:16],
                            base_url=f"/api/lab/files/base/{sid}.jpg", bearing=sp["camera_bearing_deg"]))
        except Exception as e:
            out.append(dict(id=sid, name=sid, error=str(e)[:200]))
    return out


def _compose_payload(c: dict) -> dict:
    return dict(
        prompt=c["prompt"], order=c["info"]["order"], blocks=c["info"]["blocks"], block_keys=c["info"]["block_keys"],
        key_values=c["key_values"], lighting_mode=c["info"]["lighting_mode"],
        summary_ko=c["summary_ko"], summary_ko_base=c["summary_ko_base"],
        base_state=core.state_view(c["base"]), data_state=core.state_view(c["target_data"]),
        target_state=core.state_view(c["target"]), choices=c["choices"], delta=c["delta"],
        raw=dict(base=dict(weather=c["base_cond"]["weather"], air=c["base_cond"]["air"], sun=c["base_cond"]["sun"]),
                 target=dict(weather=c["target_cond"]["weather"], air=c["target_cond"]["air"], sun=c["target_cond"]["sun"],
                             trees=c["target_cond"]["trees"])),
        sources=dict(base=c["base"]["source"], target=c["target"]["source"]),
    )


@router.get("/conditions")
async def conditions(spot: str, datetime_: str = Query(..., alias="datetime"), template_id: int | None = None,
                     user: str = Depends(current_user)):
    t = core.get_template(template_id)
    try:
        c = await run_in_threadpool(core.run_compose, spot, datetime_, None, core.template_texts(t))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return _compose_payload(c)


@router.post("/prompt")
async def prompt(spot: str = Body(...), datetime_: str = Body(..., alias="datetime"), overrides: dict | None = Body(None),
                 template_id: int | None = Body(None), edits: dict | None = Body(None), user: str = Depends(current_user)):
    t = core.get_template(template_id)
    try:
        c = await run_in_threadpool(core.run_compose, spot, datetime_, overrides, core.template_texts(t, edits))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return _compose_payload(c)


@router.post("/generate")
async def generate(spot: str = Body(...), datetime_: str = Body(..., alias="datetime"), overrides: dict | None = Body(None),
                   template_id: int | None = Body(None), edits: dict | None = Body(None),
                   model: str = Body(core.DEFAULT_MODEL), n: int = Body(1), user: str = Depends(current_user)):
    try:
        return await run_in_threadpool(core.generate, user, spot, datetime_, overrides, template_id, edits, model, n)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


# ---------------- 템플릿 ----------------
def _tpl_row(t: dict, full: bool = False) -> dict:
    keys = ["id", "name", "owner", "parent_id", "note", "is_shared", "created_at", "updated_at"]
    d = {k: t[k] for k in keys}
    d["is_shared"] = bool(d["is_shared"])
    d["current_shared"] = t["id"] == core.shared_template()["id"]
    if full:
        d.update(templates_yaml=t["templates_yaml"], rules_yaml=t["rules_yaml"], delta_yaml=t["delta_yaml"])
    return d


@router.get("/templates")
def templates(user: str = Depends(current_user)):
    return [_tpl_row(t) for t in db.q("SELECT * FROM templates ORDER BY is_shared DESC, id DESC")]


@router.get("/templates/{tid}")
def template(tid: int, user: str = Depends(current_user)):
    return _tpl_row(core.get_template(tid), full=True)


@router.post("/templates/{tid}/fork")
def fork(tid: int, name: str = Body(..., embed=True), user: str = Depends(current_user)):
    t = core.get_template(tid)
    nid = db.ex("INSERT INTO templates(name, owner, parent_id, templates_yaml, rules_yaml, delta_yaml, note, is_shared,"
                " created_at) VALUES (?,?,?,?,?,?,?,0,?)", (name.strip() or f"{user}의 실험", user, t["id"],
                t["templates_yaml"], t["rules_yaml"], t["delta_yaml"], f"{t['name']}에서 fork", db.now()))
    return _tpl_row(core.get_template(nid))


@router.put("/templates/{tid}")
def save_template(tid: int, edits: dict | None = Body(None), templates_yaml: str | None = Body(None),
                  rules_yaml: str | None = Body(None), delta_yaml: str | None = Body(None),
                  note: str | None = Body(None), name: str | None = Body(None), user: str = Depends(current_user)):
    t = core.get_template(tid)
    if t["is_shared"]:
        raise HTTPException(403, "공용(shared) 버전은 직접 고칠 수 없어요. fork해서 고친 뒤 승격하세요.")
    if t["owner"] != user:
        raise HTTPException(403, f"{t['owner']}의 템플릿이에요. fork해서 쓰세요.")
    texts = dict(templates_yaml=templates_yaml or t["templates_yaml"], rules_yaml=rules_yaml or t["rules_yaml"],
                 delta_yaml=delta_yaml or t["delta_yaml"])
    try:
        texts["templates_yaml"] = core.apply_edits(texts["templates_yaml"], edits)
        core.validate(texts)
    except (ValueError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))
    db.ex("UPDATE templates SET templates_yaml=?, rules_yaml=?, delta_yaml=?, note=COALESCE(?, note),"
          " name=COALESCE(?, name), updated_at=? WHERE id=?",
          (texts["templates_yaml"], texts["rules_yaml"], texts["delta_yaml"], note, name, db.now(), tid))
    return _tpl_row(core.get_template(tid), full=True)


@router.post("/templates/diff")
def diff(a: int = Body(...), b: int | None = Body(None), edits: dict | None = Body(None),
         user: str = Depends(current_user)):
    """a(+편집 중 내용)와 b(기본: 현재 shared)의 차이. 줄 단위 unified diff."""
    ta, tb = core.get_template(a), core.get_template(b)
    try:
        return core.diff_texts(core.template_texts(ta, edits), core.template_texts(tb), ta["name"], tb["name"])
    except (ValueError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))


@router.post("/templates/{tid}/promote")
def promote(tid: int, confirm: bool = Body(False, embed=True), user: str = Depends(current_user)):
    t, sh = core.get_template(tid), core.shared_template()
    if t["id"] == sh["id"]:
        raise HTTPException(400, "이미 현재 shared 버전이에요")
    d = core.diff_texts(core.template_texts(t), core.template_texts(sh), t["name"], sh["name"])
    n_shared = db.one("SELECT COUNT(*) AS n FROM templates WHERE is_shared=1")["n"]
    new_name = f"shared v{n_shared + 1}"
    if not confirm:
        return dict(confirm_needed=True, new_name=new_name, current_shared=sh["name"], diff=d,
                    message=f"'{t['name']}'을 '{new_name}'으로 승격하면 공개 화면과 두 사람의 기본값이 이 버전으로 바뀌어요.")
    nid = db.ex("INSERT INTO templates(name, owner, parent_id, templates_yaml, rules_yaml, delta_yaml, note, is_shared,"
                " created_at) VALUES (?,?,?,?,?,?,?,1,?)", (new_name, user, t["id"], t["templates_yaml"], t["rules_yaml"],
                t["delta_yaml"], f"{t['name']}(#{t['id']})에서 승격", db.now()))
    return _tpl_row(core.get_template(nid))


# ---------------- 그리드 ----------------
@router.post("/grid")
async def grid(template_id: int = Body(...), date: str | None = Body(None), model: str = Body(core.DEFAULT_MODEL),
               confirm: bool = Body(False), user: str = Depends(current_user)):
    date = date or (datetime.now(core.KST) + timedelta(days=1)).date().isoformat()
    if not confirm:
        plan = await run_in_threadpool(core.grid_plan, template_id, date, model)
        plan.update(remaining=core.remaining(user), confirm_needed=True)
        return plan
    try:
        return dict(job=await run_in_threadpool(core.grid_run, user, template_id, date, model))
    except PermissionError as e:
        raise HTTPException(429, str(e))


@router.get("/grid/job/{job}")
def grid_job(job: str, user: str = Depends(current_user)):
    try:
        return core.grid_job(job)
    except KeyError:
        raise HTTPException(404)


@router.get("/grid/matrix")
def grid_matrix(template_id: int, date: str, user: str = Depends(current_user)):
    rows = db.q("SELECT e.spot, e.grid_cell, e.target_datetime, i.id, i.path, i.scores FROM experiments e"
                " JOIN images i ON i.experiment_id = e.id WHERE e.template_id=? AND e.grid_cell IS NOT NULL"
                " AND substr(e.target_datetime, 1, 10)=? ORDER BY i.id DESC", (template_id, date))
    cells = {}
    for r in rows:
        cells.setdefault(f"{r['spot']}|{r['grid_cell']}", dict(image_id=r["id"], url=f"/api/lab/files/{r['path']}",
                                                              scores=db.unj(r["scores"], {})))
    return dict(spots=core.SPOT_IDS, conds=[c[0] for c in core.GRID_CONDS], cells=cells)


# ---------------- 실제 사진 ----------------
@router.post("/real-photo")
async def real_photo(file: UploadFile = File(...), spot: str = Form(...), taken_at: str | None = Form(None),
                     template_id: int | None = Form(None), generate_missing: bool = Form(False),
                     model: str = Form(core.DEFAULT_MODEL), user: str = Depends(current_user)):
    raw = await file.read()
    if len(raw) > 30 * 2**20:
        raise HTTPException(413, "30MB 이하 사진만 올릴 수 있어요")
    taken, src = core.read_taken_at(raw), "exif"
    if taken is None:
        if not taken_at:
            raise HTTPException(422, "사진에 촬영 시각(EXIF)이 없어요. 촬영 시각을 직접 입력해 주세요.")
        taken, src = core.parse_dt(taken_at), "manual"
    path = await run_in_threadpool(core.store_real, raw)
    sp = core.spot(spot)
    shared_id = core.shared_template()["id"]
    want = sorted({shared_id} | ({template_id} if template_id else set()))
    rows = core.matching_images(spot, taken, 30, want)
    generated = []
    if generate_missing:
        have = {r["template_id"] for r in rows}
        for tid in want:
            if tid not in have:
                try:
                    g = await run_in_threadpool(core.generate, user, spot, taken.strftime("%Y-%m-%dT%H:%M"), None,
                                                tid, None, model, 1)
                    generated.append(g["experiment_id"])
                except PermissionError as e:
                    raise HTTPException(429, str(e))
        rows = core.matching_images(spot, taken, 30, want)
    tag = path.stem
    baseline, scored = await run_in_threadpool(core.score_against_real, sp, path, rows, tag)
    for s in scored:
        db.ex("UPDATE images SET metrics=? WHERE id=?", (db.j(s["metrics"]), s["image_id"]))
    rid = db.ex("INSERT INTO real_photos(spot, taken_at, taken_at_source, path, uploader, matched_image_ids, baseline,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)", (spot, taken.isoformat()[:16], src, f"real/{path.name}", user,
                db.j([s["image_id"] for s in scored]), db.j(baseline), db.now()))
    return dict(id=rid, taken_at=taken.isoformat()[:16], taken_at_source=src, baseline=baseline,
                matches=[dict(image_id=s["image_id"], ground_dE=s["metrics"]["pred"]["ground_dE"],
                              base_ground_dE=s["metrics"]["base"]["ground_dE"],
                              panel_url=f"/api/lab/files/{s['metrics']['panel']}",
                              template=next(r["template_name"] for r in rows if r["id"] == s["image_id"]))
                         for s in scored],
                generated_experiments=generated, real_url=f"/api/lab/files/real/{path.name}")


@router.get("/real-photos")
def real_photos(user: str = Depends(current_user)):
    out = []
    for r in db.q("SELECT * FROM real_photos ORDER BY id DESC LIMIT 100"):
        r["matched_image_ids"] = db.unj(r["matched_image_ids"], [])
        r["baseline"] = db.unj(r["baseline"], {})
        r["url"] = f"/api/lab/files/{r['path']}"
        out.append(r)
    return out


@router.get("/leaderboard")
def leaderboard(user: str = Depends(current_user)):
    rows = db.q("SELECT t.id, t.name, t.owner, i.metrics FROM images i JOIN experiments e ON e.id = i.experiment_id"
                " JOIN templates t ON t.id = e.template_id WHERE i.metrics != '{}'")
    agg = {}
    for r in rows:
        m = db.unj(r["metrics"], {})
        a = agg.setdefault(r["id"], dict(template_id=r["id"], name=r["name"], owner=r["owner"], n=0, pred=0.0, base=0.0))
        a["n"] += 1
        a["pred"] += m["pred"]["ground_dE"]
        a["base"] += m["base"]["ground_dE"]
    out = []
    for a in agg.values():
        p, b = a.pop("pred") / a["n"], a.pop("base") / a["n"]
        out.append(dict(a, mean_ground_dE=round(p, 2), mean_no_change_dE=round(b, 2),
                        improvement_pct=round(100 * (1 - p / b), 1) if b else None))
    return sorted(out, key=lambda x: x["mean_ground_dE"])


# ---------------- 기록·점수 ----------------
@router.get("/experiments")
def experiments(user_filter: str | None = Query(None, alias="user"), spot: str | None = None,
                template_id: int | None = None, limit: int = 200, user: str = Depends(current_user)):
    where, args = [], []
    for col, v in (("e.user", user_filter), ("e.spot", spot), ("e.template_id", template_id)):
        if v:
            where.append(f"{col}=?")
            args.append(v)
    sql = ("SELECT e.*, t.name AS template_name FROM experiments e JOIN templates t ON t.id = e.template_id"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY e.id DESC LIMIT ?")
    exps = db.q(sql, tuple(args) + (min(limit, 500),))
    ids = [e["id"] for e in exps] or [-1]
    imgs = db.q(f"SELECT * FROM images WHERE experiment_id IN ({','.join('?' * len(ids))}) ORDER BY id", tuple(ids))
    by = {}
    for i in imgs:
        by.setdefault(i["experiment_id"], []).append(dict(
            id=i["id"], url=f"/api/lab/files/{i['path']}", cost=i["cost"], latency=i["latency"], cached=bool(i["cached"]),
            scores=db.unj(i["scores"], {}), note=i["note"], metrics=db.unj(i["metrics"], {})))
    for e in exps:
        e["overrides"] = db.unj(e["overrides"], {})
        e["template_edits"] = db.unj(e["template_edits"], {})
        e["block_keys"] = db.unj(e["block_keys"], {})
        e["images"] = by.get(e["id"], [])
    return exps


@router.post("/images/{iid}/score")
def score(iid: int, scores: dict = Body(...), note: str = Body(""), user: str = Depends(current_user)):
    bad = {k: v for k, v in scores.items() if k not in ("cond", "struct", "nobeauty") or v not in (1, 2, 3, 4, 5)}
    if bad:
        raise HTTPException(400, "점수는 cond·struct·nobeauty 각 1~5")
    if not db.one("SELECT id FROM images WHERE id=?", (iid,)):
        raise HTTPException(404)
    db.ex("UPDATE images SET scores=?, note=? WHERE id=?", (db.j(scores), note, iid))
    return dict(ok=True)


@router.get("/storage")
def storage(user: str = Depends(current_user)):
    size, n = core.dir_size(db.DATA)
    total, used, free = shutil.disk_usage(db.DATA)
    db_size = db.DB_PATH.stat().st_size if db.DB_PATH.exists() else 0
    return dict(lab_data_bytes=size, files=n, db_bytes=db_size, disk_free_bytes=free, disk_total_bytes=total)


# ---------------- 파일 ----------------
@router.get("/files/{kind}/{name}")
def files(kind: str, name: str, user: str = Depends(current_user)):
    if kind == "base":
        sid = Path(name).stem
        try:
            p = core.spot(sid)["base_image_path"]
        except Exception:
            raise HTTPException(404)
    elif kind in ("images", "panels", "real"):
        p = (db.DATA / kind / name).resolve()
        if (db.DATA / kind).resolve() not in p.parents:
            raise HTTPException(404)
    else:
        raise HTTPException(404)
    if not Path(p).exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "private, max-age=86400"})

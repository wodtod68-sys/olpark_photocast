"""실험실 핵심 로직: 템플릿 적용·프롬프트 조립, 생성과 캐시, 그리드, 실제 사진 채점.

템플릿 행(templates_yaml·rules_yaml·delta_yaml)을 디스크에 쓰지 않고 forecast 패키지에 요청 단위로 주입한다.
편집 중 내용(edits = {템플릿 키 경로: 새 문장})은 ruamel.yaml로 주석을 보존한 채 YAML 텍스트에 반영한다.
"""
from __future__ import annotations
import difflib
import hashlib
import io
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml
from PIL import Image, ImageOps
from ruamel.yaml import YAML
from ..forecast.common import load_spot, parse_local, set_config_override, reset_config_override, PKG as FC, env_key, log
from ..forecast.predict import compose
from ..forecast.scene import override_choices
from ..forecast.generate import generate_one, model_info, MODELS
from ..forecast.summary import summary_ko
from . import db

KST = ZoneInfo("Asia/Seoul")
SPOTS_DIR = FC / "spots"
SPOT_IDS = ["rose", "wild", "gyeong4", "naholo"]
IMG_DIR = db.DATA / "images"
REAL_DIR = db.DATA / "real"
PANEL_DIR = db.DATA / "panels"
DEFAULT_MODEL = "pro"
SAVE_LONG_SIDE, SAVE_QUALITY = 1536, 90

REQUIRED = {
    "templates_yaml": ["version", "order", "time_change", "amount", "part_of_day", "preserve", "lighting", "where",
                       "frame", "base_cmp", "consequences", "exposure", "sky_air", "sky", "air", "trees", "ground",
                       "no_beautify"],
    "rules_yaml": ["light_stages", "direction", "direct_sun", "haze", "sky_type", "precip", "visibility_model", "sources"],
    "delta_yaml": ["version", "light_stage", "direction_per_forward", "direction_weight_by_direct", "direct_sun",
                   "haze_per_stage", "precip"],
}
CONFIG_FILE = {"templates_yaml": "templates.yaml", "rules_yaml": "rules.yaml", "delta_yaml": "delta_rules.yaml"}


def price(model: str) -> float:
    return model_info(model)["usd_per_image"]


def daily_limit() -> int:
    """0 = 제한 없음 (server/.env LAB_DAILY_LIMIT=0)."""
    v = env_key("LAB_DAILY_LIMIT")
    return int(v) if v and v.isdigit() else 20


# ---------------- 템플릿 ----------------
def seed_shared() -> None:
    """DB가 비어 있으면 현재 설정 파일을 'shared v1'로 등록."""
    if db.one("SELECT id FROM templates LIMIT 1"):
        return
    txt = {k: (FC / "config" / f).read_text(encoding="utf-8") for k, f in CONFIG_FILE.items()}
    db.ex("INSERT INTO templates(name, owner, parent_id, templates_yaml, rules_yaml, delta_yaml, note, is_shared, created_at)"
          " VALUES (?,?,?,?,?,?,?,1,?)", ("shared v1", "system", None, txt["templates_yaml"], txt["rules_yaml"],
                                         txt["delta_yaml"], "forecast/config 파일에서 등록", db.now()))


def shared_template() -> dict:
    return db.one("SELECT * FROM templates WHERE is_shared=1 ORDER BY id DESC LIMIT 1")


def get_template(tid: int | None) -> dict:
    t = db.one("SELECT * FROM templates WHERE id=?", (tid,)) if tid else shared_template()
    if not t:
        raise KeyError(f"템플릿 {tid} 없음")
    return t


_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _path_tokens(path: str) -> list:
    return [int(i) if i else k for k, i in _PATH_TOKEN.findall(path)]


def _scalar_span(line: str, col: int) -> int:
    """line[col:]에서 시작하는 YAML 스칼라(따옴표 또는 plain)의 끝 위치."""
    q = line[col]
    if q == '"':
        i = col + 1
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == '"':
                return i + 1
            i += 1
        raise ValueError("닫는 따옴표를 찾지 못했다")
    if q == "'":
        i = col + 1
        while i < len(line):
            if line[i] == "'" and (i + 1 >= len(line) or line[i + 1] != "'"):
                return i + 1
            i += 2 if line[i] == "'" else 1
        raise ValueError("닫는 따옴표를 찾지 못했다")
    m = re.match(r"[^,\]}#\n]*", line[col:])          # plain 스칼라: 쉼표·괄호·주석 전까지
    return col + len(m.group(0).rstrip())


def apply_edits(yaml_text: str, edits: dict[str, str] | None) -> str:
    """{경로: 새 문자열}을 YAML 텍스트의 그 자리만 바꿔 넣는다(나머지 줄·주석·들여쓰기 그대로 → diff가 깔끔).
    경로 예: lighting.sun, exposure.ev[3][1], part_of_day[2].text"""
    if not edits:
        return yaml_text
    check_edits(yaml.safe_load(yaml_text), edits)
    lines = yaml_text.split("\n")
    # 위치 정보는 원문 기준. 같은 줄 안 여러 편집을 위해 뒤쪽 위치부터 바꾼다.
    data = YAML().load(yaml_text)
    spots = []
    for path, val in edits.items():
        toks = _path_tokens(path)
        node = data
        for t in toks[:-1]:
            node = node[t]
        last = toks[-1]
        if not isinstance(node[last], str):
            raise ValueError(f"{path}: 문자열 항목만 편집할 수 있다")
        ln, col = node.lc.item(last) if isinstance(last, int) else node.lc.value(last)
        spots.append((ln, col, path, val))
    for ln, col, path, val in sorted(spots, reverse=True):
        line = lines[ln]
        if line[col] in "|>":
            raise ValueError(f"{path}: 여러 줄 블록 문자열은 YAML 전체 편집으로 고쳐 주세요")
        endc = _scalar_span(line, col)
        lines[ln] = line[:col] + json.dumps(val, ensure_ascii=False) + line[endc:]
    out = "\n".join(lines)
    check = yaml.safe_load(out)
    for _, _, path, val in spots:
        if get_path(check, path) != val:
            raise ValueError(f"{path}: 편집 반영 확인 실패")
    return out


def _placeholders(text: str) -> set[str]:
    import string
    return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}


def check_edits(data: dict, edits: dict[str, str]) -> None:
    """편집 전 검사: 경로가 있는 문자열인지, 중괄호 짝, 원래 문장에 없던 자리({foo})를 쓰지 않았는지."""
    for path, val in edits.items():
        try:
            old = get_path(data, path)
        except (KeyError, IndexError, TypeError):
            raise ValueError(f"편집할 문장 '{path}'이(가) 이 템플릿에 없어요. 템플릿을 바꿨다면 편집을 되돌려 주세요.")
        if not isinstance(old, str):
            raise ValueError(f"'{path}'은(는) 문장이 아니라서 화면에서 고칠 수 없어요")
        if not isinstance(val, str):
            raise ValueError(f"'{path}': 문장은 글자여야 해요")
        try:
            new_ph = _placeholders(val)
        except ValueError:
            raise ValueError(f"'{path}': 중괄호 {{ }}의 짝이 맞지 않아요. 글자 그대로 중괄호를 쓰려면 {{{{ }}}}처럼 두 번 쓰세요.")
        old_ph = _placeholders(old)
        extra = sorted(new_ph - old_ph)
        if extra:
            allowed = ", ".join("{" + p + "}" for p in sorted(old_ph)) or "없음"
            raise ValueError(f"'{path}'에 원래 없던 자리 {', '.join('{' + e + '}' for e in extra)}가 있어요. "
                             f"이 문장에서 쓸 수 있는 자리: {allowed}")


VALID_OVERRIDES = {
    "assume": ["clear"],
    "direct_sun": ["D0", "D1", "D2", "D3"],
    "haze": ["H0", "H1", "H2", "H3", "H4"],
    "sky": ["clear", "partly", "high", "low_many", "overcast", "golden", "twilight", "night", "rain", "fog"],
    "precip": ["none"] + [f"{f}:{i}" for f in ("rain", "snow") for i in ("light", "moderate", "heavy")] + ["rain", "snow"],
    "lamps": ["on", "off"],
}


def check_overrides(ov: dict | None) -> None:
    if not ov:
        return
    for k, v in ov.items():
        if k in VALID_OVERRIDES:
            if v not in VALID_OVERRIDES[k]:
                raise ValueError(f"덮어쓰기 {k}={v}는 쓸 수 없어요. 가능한 값: {', '.join(VALID_OVERRIDES[k])}")
        elif k == "ground":
            bad = [g for g in (v or []) if g not in ("wet", "snow_thin", "snow", "frost", "leaves")]
            if not isinstance(v, list) or bad:
                raise ValueError(f"덮어쓰기 ground는 [wet, snow, frost, leaves] 중에서 고른 목록이어야 해요 (잘못된 값: {bad or v})")
        elif k == "trees":
            cal = yaml.safe_load((FC / "config" / "phenology.yaml").read_text(encoding="utf-8"))["species"]
            for sp, st in (v or {}).items():
                names = [x["name"] for x in cal.get(sp, {}).get("stages", [])]
                if st not in names:
                    raise ValueError(f"덮어쓰기 trees.{sp}={st}는 쓸 수 없어요. 가능한 단계: {', '.join(dict.fromkeys(names)) or '(모르는 수종)'}")
        else:
            raise ValueError(f"덮어쓸 수 없는 항목: {k} (가능: {', '.join(list(VALID_OVERRIDES) + ['ground', 'trees'])})")


def get_path(data: dict, path: str):
    node = data
    for t in _path_tokens(path):
        node = node[t]
    return node


def validate(texts: dict[str, str]) -> dict[str, dict]:
    """YAML 문법·필수 키 검사. 통과하면 파싱한 dict 반환, 아니면 ValueError(사람이 읽을 메시지)."""
    parsed = {}
    for k, txt in texts.items():
        try:
            d = yaml.safe_load(txt)
        except yaml.YAMLError as e:
            raise ValueError(f"{CONFIG_FILE[k]} YAML 문법 오류: {e}")
        if not isinstance(d, dict):
            raise ValueError(f"{CONFIG_FILE[k]}: 최상위가 key: value 형식이 아니다")
        miss = [r for r in REQUIRED[k] if r not in d]
        if miss:
            raise ValueError(f"{CONFIG_FILE[k]}: 필수 키 없음 {miss}")
        parsed[k] = d
    t = parsed.get("templates_yaml")
    if t:
        bad = [b for b in t["order"] if b not in ("time_change", "preserve", "lighting", "lamps", "consequences", "exposure",
                                                    "sky_air", "trees", "ground", "no_beautify")]
        if bad:
            raise ValueError(f"templates.yaml order에 알 수 없는 블록: {bad}")
    return parsed


def template_texts(t: dict, edits: dict | None = None) -> dict[str, str]:
    return {"templates_yaml": apply_edits(t["templates_yaml"], edits), "rules_yaml": t["rules_yaml"],
            "delta_yaml": t["delta_yaml"]}


def diff_texts(a: dict[str, str], b: dict[str, str], a_name: str, b_name: str) -> dict[str, str]:
    out = {}
    for k in CONFIG_FILE:
        d = difflib.unified_diff(b[k].splitlines(), a[k].splitlines(), f"{b_name}/{CONFIG_FILE[k]}",
                                 f"{a_name}/{CONFIG_FILE[k]}", lineterm="", n=2)
        out[k] = "\n".join(d)
    return out


# ---------------- 조건·프롬프트 ----------------
def spot(spot_id: str) -> dict:
    if spot_id not in SPOT_IDS:
        raise KeyError(f"알 수 없는 스팟: {spot_id}")
    return load_spot(str(SPOTS_DIR / f"{spot_id}.yaml"))


def parse_dt(text: str) -> datetime:
    return parse_local(text.replace("T", " ")[:16], KST)


def run_compose(spot_id: str, dt_text: str, overrides: dict | None, texts: dict[str, str]) -> dict:
    check_overrides(overrides)
    parsed = validate(texts)
    token = set_config_override({CONFIG_FILE[k]: v for k, v in parsed.items()})
    try:
        sp = spot(spot_id)
        c = compose(sp, parse_dt(dt_text), overrides or None)
        c["choices"] = override_choices(c["target_data"])
        c["summary_ko"] = summary_ko(c["target"])
        c["summary_ko_base"] = summary_ko(c["base"])
    finally:
        reset_config_override(token)
    c["spot"] = sp
    tdata = parsed["templates_yaml"]
    keys = [k for ks in c["info"]["block_keys"].values() for k in ks]
    c["key_values"] = {k: get_path(tdata, k) for k in keys}
    return c


def state_view(s: dict) -> dict:
    """화면용 상태표(덮어쓰기 가능한 항목은 값만)."""
    return dict(
        light=f"{s['light']['stage']} ({s['light']['elev']:.1f}°)",
        direction=f"{s['direction']['light_direction']} / {s['direction']['position']}"
                  + (" · 화면 안" if s['direction']['sun_in_frame'] else "")
                  + (" · 장애물 그늘" if s['direction']['spot_shaded'] else ""),
        direct_sun=s["direct_sun"]["stage"], haze=s["haze"]["stage"], sky=s["sky"],
        precip=s["precip"]["form"] + (f":{s['precip']['intensity']}" if s["precip"].get("intensity") else ""),
        ground=s["ground"], trees={t["species"]: t["stage"] for t in s["trees"]},
        lamps=(s.get("lamps") or {}).get("state", "unknown"),
        trees_ko={t["species"]: f"{t['name_ko']} {t['stage_ko']}" for t in s["trees"]},
        landmarks={l["name"]: l["visibility"] for l in s["landmarks"]},
    )


# ---------------- 생성 ----------------
_usage_lock = threading.Lock()
_key_locks: dict[str, threading.Lock] = {}
_key_locks_guard = threading.Lock()


def used_today(user: str) -> int:
    r = db.one("SELECT calls FROM usage WHERE user=? AND day=?", (user, datetime.now(KST).date().isoformat()))
    return r["calls"] if r else 0


def remaining(user: str) -> int:
    if daily_limit() == 0:
        return 10**6          # 제한 없음
    return max(0, daily_limit() - used_today(user))


def _add_usage(user: str, calls: int) -> None:
    day = datetime.now(KST).date().isoformat()
    db.ex("INSERT INTO usage(user, day, calls) VALUES (?,?,?) ON CONFLICT(user, day) DO UPDATE SET calls = calls + ?",
          (user, day, calls, calls))


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cache_key(prompt: str, base_path: Path, model_id: str, sample: int, ref: Path | None = None) -> str:
    h = hashlib.sha256()
    # 참조 사진은 있을 때만 넣는다(없는 경우의 기존 캐시 키는 그대로)
    for part in (prompt, file_sha(base_path), model_id, str(sample)) + ((file_sha(ref),) if ref else ()):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()[:32]


def save_jpeg(data: bytes, dst: Path) -> None:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((SAVE_LONG_SIDE, SAVE_LONG_SIDE), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=SAVE_QUALITY)


def plan_samples(prompt: str, base_path: Path, model: str, n: int, ref: Path | None = None) -> list[tuple[int, str, bool]]:
    mid = model_info(model)["id"]
    out = []
    for i in range(n):
        k = cache_key(prompt, base_path, mid, i, ref)
        out.append((i, k, (IMG_DIR / f"{k}.jpg").exists()))
    return out


def generate(user: str, spot_id: str, dt_text: str, overrides: dict | None, template_id: int | None,
             edits: dict | None, model: str, n: int, grid_cell: str | None = None) -> dict:
    """프롬프트 조립 → 샘플별 캐시 확인 → 없는 것만 생성. 한도는 새로 만들 장수로 미리 확인."""
    if model not in MODELS:
        raise ValueError(f"모델은 {list(MODELS)} 중 하나")
    if not isinstance(n, int) or not 1 <= n <= 3:
        raise ValueError("장수(n)는 1~3")
    t = get_template(template_id)
    c = run_compose(spot_id, dt_text, overrides, template_texts(t, edits))
    base_path = c["spot"]["base_image_path"]
    plan = plan_samples(c["prompt"], base_path, model, n, c["ref"])
    need = sum(1 for _, _, hit in plan if not hit)
    with _usage_lock:
        if need > remaining(user):
            raise PermissionError(f"오늘 남은 생성 수({remaining(user)}장)보다 많이 요청했어요 (새로 만들 {need}장). "
                                  f"하루 {daily_limit()}장, 한국 시간 자정에 초기화돼요.")
        if need:
            _add_usage(user, need)        # 자리 먼저 잡고, 실패한 만큼 아래에서 돌려준다
    mid = model_info(model)["id"]
    eid = db.ex("INSERT INTO experiments(user, spot, target_datetime, overrides, template_id, template_edits, prompt_text,"
                " block_keys, model, grid_cell, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user, spot_id, dt_text[:16], db.j(overrides or {}), t["id"], db.j(edits or {}), c["prompt"],
                 db.j(c["info"]["block_keys"]), mid, grid_cell, db.now()))
    images, refund = [], 0
    for i, key, _ in plan:
        with _key_locks_guard:
            lk = _key_locks.setdefault(key, threading.Lock())
        with lk:                                  # 같은 프롬프트·샘플이 동시에 오면 한 번만 생성
            dst = IMG_DIR / f"{key}.jpg"
            if dst.exists():
                cost, lat, cached = 0.0, 0.0, 1
            else:
                r = generate_one(c["prompt"], base_path, model, c["ref"])
                extra = r["attempts"] - 1
                if extra:
                    _add_usage(user, extra)      # 재시도한 호출도 센다
                if r.get("image") is None:
                    refund += 1 if r["attempts"] == 1 else 0
                    images.append(dict(error=r["error"], sample_index=i))
                    continue
                save_jpeg(r["image"], dst)
                cost, lat, cached = price(model) * r["attempts"], r["seconds"], 0
        iid = db.ex("INSERT INTO images(experiment_id, path, cache_key, sample_index, cost, latency, cached, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)", (eid, f"images/{key}.jpg", key, i, cost, lat, cached, db.now()))
        images.append(dict(id=iid, url=f"/api/lab/files/images/{key}.jpg", cached=bool(cached), cost=cost,
                           latency=lat, sample_index=i))
    if refund:
        _add_usage(user, -refund)
    return dict(experiment_id=eid, prompt=c["prompt"], images=images, remaining=remaining(user),
                cost=round(sum(x.get("cost", 0) for x in images), 3), model=mid)


# ---------------- 그리드 ----------------
# 날짜의 실제 예보와 상관없이 같은 조건을 비교하도록 모두 "맑은 날 가정"에서 시작한다.
GRID_CONDS = [
    ("morning_0700", "07:00", {"assume": "clear"}),
    ("noon_1200", "12:00", {"assume": "clear"}),
    ("golden_1630", "16:30", {"assume": "clear"}),
    ("overcast_1200", "12:00", {"assume": "clear", "direct_sun": "D0", "sky": "overcast"}),
    ("rain_1200", "12:00", {"assume": "clear", "precip": "rain:moderate", "ground": ["wet"]}),
]
# 검증 세트: 조건별 대표 장면. (이름, "YYYY-MM-DDTHH:MM", 덮어쓰기). 날짜를 조건마다 고정해서
# 언제 돌려도 같은 조건. 모두 "맑은 날 가정"에서 시작해 바꾸려는 요인 하나(또는 조합)만 덮어쓴다.
# 11/22 = 기준 사진·실제 사진을 찍은 날(답사 기록과 비교 가능).
_C = {"assume": "clear"}
VALIDATION_CONDS = [
    # 시간 (11/22 맑음)
    ("v_t0800", "2026-11-22T08:00", _C),                                  # 해 뜬 직후 낮은 해
    ("v_t1200", "2026-11-22T12:00", _C),                                  # 한낮
    ("v_t1640", "2026-11-22T16:40", _C),                                  # 골든아워
    ("v_t1735", "2026-11-22T17:35", _C),                                  # 해 진 뒤 박명 + 조명 (실제 사진 있음)
    ("v_t2030", "2026-11-22T20:30", _C),                                  # 밤
    # 날씨 (11/22 12시)
    ("v_overcast", "2026-11-22T12:00", {**_C, "direct_sun": "D0", "sky": "overcast"}),
    ("v_rain_light", "2026-11-22T12:00", {**_C, "precip": "rain:light", "ground": ["wet"]}),
    ("v_rain_heavy", "2026-11-22T12:00", {**_C, "precip": "rain:heavy", "ground": ["wet"]}),
    ("v_snowfall", "2026-11-22T12:00", {**_C, "precip": "snow:moderate", "sky": "overcast", "ground": ["snow"]}),
    ("v_snow_after", "2026-11-22T12:00", {**_C, "ground": ["snow_thin"]}),  # 눈 그친 뒤 맑음, 살짝 쌓임(적설 3cm 미만)
    ("v_fog", "2026-11-22T08:00", {**_C, "haze": "H4", "sky": "fog", "direct_sun": "D0"}),
    ("v_haze", "2026-11-22T12:00", {**_C, "haze": "H3"}),                 # 짙은 연무·미세먼지
    ("v_rain_night", "2026-11-22T20:30", {**_C, "precip": "rain:moderate", "ground": ["wet"]}),  # 비 + 밤 + 조명
    # 계절 (맑은 한낮)
    ("v_s0115", "2027-01-15T12:00", _C),                                  # 한겨울
    ("v_s0415", "2027-04-15T12:00", _C),                                  # 봄 새잎
    ("v_s0525", "2027-05-25T12:00", _C),                                  # 장미·양귀비 절정 (참조 사진)
    ("v_s0720", "2027-07-20T12:00", _C),                                  # 한여름 초록
    ("v_s1030", "2026-10-30T12:00", _C),                                  # 단풍 절정·코스모스
]
SUITES = {"basic": GRID_CONDS, "validation": VALIDATION_CONDS}
_jobs: dict[str, dict] = {}


def suite_cells(suite: str, date: str) -> list[tuple[str, str, dict]]:
    """basic은 고른 날짜 + 시각, validation은 조건마다 고정 날짜."""
    if suite == "validation":
        return VALIDATION_CONDS
    return [(n, f"{date}T{hhmm}", ov) for n, hhmm, ov in GRID_CONDS]


def grid_plan(template_id: int, date: str, model: str, suite: str = "basic") -> dict:
    t = get_template(template_id)
    texts = template_texts(t)
    cells = []
    for sid in SPOT_IDS:
        for name, dt, ov in suite_cells(suite, date):
            cell = dict(spot=sid, cond=name, datetime=dt, overrides=ov)
            try:
                c = run_compose(sid, cell["datetime"], ov, texts)
                (_, key, hit), = plan_samples(c["prompt"], c["spot"]["base_image_path"], model, 1, c["ref"])
                cell.update(cached=hit, url=f"/api/lab/files/images/{key}.jpg" if hit else None,
                            summary=c["summary_ko"])
            except Exception as e:
                cell.update(error=str(e)[:200], cached=False)
            cells.append(cell)
    need = sum(1 for c in cells if not c["cached"] and not c.get("error"))
    return dict(template_id=t["id"], template_name=t["name"], date=date, suite=suite, model=model_info(model)["id"],
                cells=cells, n_new=need, cost_usd=round(need * price(model), 3), price=price(model))


def grid_run(user: str, template_id: int, date: str, model: str, suite: str = "basic") -> str:
    plan = grid_plan(template_id, date, model, suite)
    if plan["n_new"] > remaining(user):
        raise PermissionError(f"새로 만들 {plan['n_new']}장이 오늘 남은 {remaining(user)}장보다 많아요.")
    job = uuid.uuid4().hex[:12]
    _jobs[job] = dict(status="running", done=0, total=len(plan["cells"]), errors=[], plan=plan)

    def work():
        for cell in plan["cells"]:
            if cell.get("error"):
                _jobs[job]["errors"].append(f"{cell['spot']}/{cell['cond']}: {cell['error']}")
            else:
                try:
                    generate(user, cell["spot"], cell["datetime"], cell["overrides"], template_id, None, model, 1,
                             grid_cell=cell["cond"])
                except Exception as e:
                    _jobs[job]["errors"].append(f"{cell['spot']}/{cell['cond']}: {str(e)[:150]}")
            _jobs[job]["done"] += 1
        _jobs[job]["status"] = "done"

    threading.Thread(target=work, daemon=True).start()
    return job


def grid_job(job: str) -> dict:
    j = _jobs.get(job)
    if not j:
        raise KeyError("작업 없음")
    return {k: v for k, v in j.items() if k != "plan"}


# ---------------- 실제 사진 ----------------
def read_taken_at(raw: bytes) -> datetime | None:
    import pillow_heif
    pillow_heif.register_heif_opener()
    try:
        ex = Image.open(io.BytesIO(raw)).getexif()
        t = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        return datetime.strptime(t, "%Y:%m:%d %H:%M:%S").replace(tzinfo=KST) if t else None
    except Exception:
        return None


def store_real(raw: bytes) -> Path:
    import pillow_heif
    pillow_heif.register_heif_opener()
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    im.thumbnail((2048, 2048), Image.LANCZOS)      # 저장 공간 절약: 원본 대신 긴 변 2048
    dst = REAL_DIR / f"{uuid.uuid4().hex[:16]}.jpg"
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=90)
    return dst


def score_against_real(sp: dict, real_path: Path, image_rows: list[dict], tag: str) -> tuple[dict, list[dict]]:
    """forecast.verify로 정렬·채점. 반환: (기준선 지표, 이미지별 지표)."""
    import cv2
    from ..forecast import verify as V
    base = cv2.imread(str(sp["base_image_path"]))
    real, valid_r, how_r = V.align_to(cv2.imread(str(real_path)), base)
    ground, sky, how_m = V.masks(sp, base, valid_r)
    sb, _ = V.score(base, real, base, ground, sky)
    sr, _ = V.score(real, real, base, ground, sky)
    baseline = dict(base={k: round(v, 3) for k, v in sb.items()}, real={k: round(v, 3) for k, v in sr.items()},
                    align=how_r, sky_mask=how_m)
    out = []
    for row in image_rows:
        pred, valid_p, how_p = V.align_to(cv2.imread(str(db.DATA / row["path"])), base)
        g2, s2, _ = V.masks(sp, base, valid_r & valid_p)
        sp_, de = V.score(pred, real, base, g2, s2)
        sb2, _ = V.score(base, real, base, g2, s2)
        header = [f"{sp['id']} | real {tag} | image #{row['id']} | template #{row.get('template_id', '')}",
                  f"align real: {how_r} / pred: {how_p} | sky mask: {how_m}"]
        pn = V.panel(base, pred, real, de, g2, sp_, sb2, sr, header)
        pdst = PANEL_DIR / f"real_{tag}_img{row['id']}.jpg"
        pdst.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(pdst), pn, [cv2.IMWRITE_JPEG_QUALITY, 85])
        m = dict(pred={k: round(v, 3) for k, v in sp_.items()}, base={k: round(v, 3) for k, v in sb2.items()},
                 real={k: round(v, 3) for k, v in sr.items()}, panel=f"panels/{pdst.name}", align_pred=how_p,
                 real_photo_tag=tag)
        out.append(dict(image_id=row["id"], metrics=m))
    return baseline, out


def matching_images(spot_id: str, taken: datetime, window_min: int = 30, template_ids: list[int] | None = None) -> list[dict]:
    rows = db.q("SELECT i.id, i.path, e.template_id, e.target_datetime, e.overrides, t.name AS template_name"
                " FROM images i JOIN experiments e ON e.id = i.experiment_id JOIN templates t ON t.id = e.template_id"
                " WHERE e.spot=?", (spot_id,))
    out = []
    for r in rows:
        if db.unj(r["overrides"], {}):            # 덮어쓴 조건은 실제와 다르니 비교 대상에서 뺀다
            continue
        dt = parse_dt(r["target_datetime"])
        if abs((dt - taken).total_seconds()) <= window_min * 60 and (not template_ids or r["template_id"] in template_ids):
            out.append(r)
    return out


def dir_size(p: Path) -> tuple[int, int]:
    total = cnt = 0
    for root, _, files in os.walk(p):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
            cnt += 1
    return total, cnt

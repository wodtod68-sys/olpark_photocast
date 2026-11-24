"""프롬프트 생성. 문장은 전부 config/templates.yaml — 여기서는 상태표를 보고 어떤 문장 키를 쓸지만 고른다.

lighting 블록 우선순위: 강수 > 안개 > 밤 > 박명 > 흐림 > 태양 방향.
흐림·강수·안개·밤이면 태양 기하·그림자(consequences) 대신 균일한 빛 문장만 쓴다.
"""
from __future__ import annotations
from datetime import datetime
from .common import load_yaml, rules


# ---------------- 템플릿 키 추적 ----------------
# 실험실 화면에서 "이번 조건에서 실제로 쓰인 문장"만 편집창으로 보여 주려고,
# 블록마다 읽힌 문자열의 경로(예: lighting.sun, exposure.ev[3][1])를 기록한다. 숫자(임계값)는 기록하지 않는다.
class _TrackList(list):
    def __init__(self, data, path, used):
        super().__init__(data)
        self._p, self._u = path, used

    def _wrap(self, i, v):
        return _wrap(v, f"{self._p}[{i}]", self._u)

    def __getitem__(self, i):
        v = super().__getitem__(i)
        return self._wrap(i if i >= 0 else len(self) + i, v)

    def __iter__(self):
        for i, v in enumerate(list.__iter__(self)):
            yield self._wrap(i, v)


class _TrackDict(dict):
    def __init__(self, data, path, used):
        super().__init__(data)
        self._p, self._u = path, used

    def __getitem__(self, k):
        return _wrap(super().__getitem__(k), f"{self._p}.{k}" if self._p else str(k), self._u)

    def get(self, k, default=None):
        return self[k] if k in self else default


def _wrap(v, path, used):
    if isinstance(v, dict):
        return _TrackDict(v, path, used)
    if isinstance(v, list):
        return _TrackList(v, path, used)
    if isinstance(v, str):
        used.append(path)
    return v


def _bin(table: list, value: float, **fmt) -> str:
    """templates의 [상한, 음수 문장, 양수 문장] 표에서 |value|로 문장을 고른다."""
    for row in table:
        if abs(value) < row[0]:
            return (row[1] if value < 0 else row[2]).format(**fmt)
    return (table[-1][1] if value < 0 else table[-1][2]).format(**fmt)


def part_of_day(T: dict, dt: datetime) -> dict:
    h = dt.hour + dt.minute / 60
    for p in T["part_of_day"]:
        if p["from"] <= h < p["to"] or p["from"] <= h + 24 < p["to"]:
            return p
    return T["part_of_day"][-1]


def block_time(T, base_dt, tgt_dt) -> str:
    tc = T["time_change"]
    minutes = (tgt_dt - base_dt).total_seconds() / 60
    pod = part_of_day(T, tgt_dt)
    if abs(minutes) < 10:
        return tc["same_time"]
    if abs(minutes) > 60 * tc["max_hours_relative"]:
        return tc["other_day"].format(clock=tgt_dt.strftime("%H:%M"), pod=pod["text"])
    m = abs(minutes)
    if m < 90:
        amount = T["amount"]["minutes"].format(m=int(round(m / 5) * 5))
    else:
        h = round(m / 30) / 2
        amount = T["amount"]["hours"].format(h=f"{h:g}")
    return tc["later" if minutes > 0 else "earlier"].format(amount=amount, pod=pod["text"])


def lighting_mode(t: dict) -> str:
    if t["precip"]["form"] in ("rain", "snow"):
        return t["precip"]["form"]
    if t["haze"]["level"] >= 4:
        return "fog"
    if t["light"]["stage"] == "L0":
        return "night"
    if t["light"]["stage"] == "L1":
        return "twilight"
    if t["direct_sun"]["stage"] == "D0":
        return "overcast"
    return "sun"


def base_comparison(T, b: dict, t: dict) -> str:
    bc = T["base_cmp"]
    if b["light"]["elev"] < 0:
        return bc["below_horizon"]
    parts = []
    de = b["light"]["elev"] - t["light"]["elev"]
    if abs(de) >= 5:
        parts.append(bc["elev_higher"] if de > 0 else bc["elev_lower"])
    bf, tf = b["direction"]["forward"], t["direction"]["forward"]
    bl = b["direction"]["lateral"]
    if bf < tf - 0.1:
        parts.append((bc["more_side_left"] if bl < 0 else bc["more_side_right"]) if abs(bl) > 0.5 else bc["more_behind"])
    elif bf > tf + 0.1:
        parts.append(bc["more_ahead"])
    elif b["direction"]["position"] != t["direction"]["position"]:
        parts.append(T["where"][b["direction"]["position"]])
    return bc["joiner"].join(parts) if parts else bc["similar_dir"]


def block_lighting(T, b, t, mode) -> str:
    L = T["lighting"]
    if mode in ("rain", "snow"):
        # precip_intensity.<세기> 는 문자열(비·눈 공통) 또는 {rain: ..., snow: ...}
        inten = T["precip_intensity"].get(t["precip"]["intensity"], "")
        if isinstance(inten, dict):
            inten = inten.get(mode, "")
        return L[mode].format(intensity=inten)
    if mode != "sun":
        return L[mode]
    d = t["direction"]
    return L["sun"].format(elev=int(round(t["light"]["elev"])), where=T["where"][d["position"]],
                           frame=T["frame"]["in" if d["sun_in_frame"] else "out"], base_cmp=base_comparison(T, b, t))


def block_consequences(T, b, t, terms) -> str:
    C = T["consequences"]
    d = t["direction"]
    if d["spot_shaded"]:
        return C["text"].format(parts=C["spot_shaded"])
    fs, ss = rules()["direction"]["forward_strong"], rules()["direction"]["side_strong"]
    f, s = d["forward"], d["lateral"]
    subj = terms.get("subjects_short", "the buildings")
    parts = [C["camera_facing"]["shade" if f > fs else "lit" if f < -fs else "grazing"].format(subjects_short=subj)]
    side = "left" if s < 0 else "right"
    if abs(s) > ss and f > -fs:
        parts.append(C["side"][f"ahead_{side}" if f > fs else side])
    # 그림자: 길이 배수(1/tan 고도의 비)와 방향(태양 반대쪽)
    br, tr = b["direction"]["shadow_ratio"], d["shadow_ratio"]
    SL = C["shadow_length"]
    if tr is not None:
        if br:
            k = tr / br
            th = SL["thresholds"]
            length = (SL["much_longer"].format(k=f"{k:.1f}") if k >= th["much"] else SL["longer"] if k >= th["some"]
                      else SL["much_shorter"] if k <= 1 / th["much"] else SL["shorter"] if k <= 1 / th["some"]
                      else SL["same"])
        else:
            length = SL["longer"]
        SD = C["shadow_direction"]
        bf = b["direction"]["forward"] if br else None
        if f > fs:
            direction = SD["more_toward"] if bf is not None and bf < f - 0.1 else SD["toward"]
        elif f < -fs:
            direction = SD["more_away"] if bf is not None and bf > f + 0.1 else SD["away"]
        else:
            direction = SD["right"] if s < 0 else SD["left"]     # 해가 왼쪽이면 그림자는 오른쪽
        parts.append(C["shadows"].format(ground=terms.get("ground", "the ground"), length=length, direction=direction))
    if t["direct_sun"]["stage"] in ("D1", "D2"):
        parts.append(C["patchy"])
    return C["text"].format(parts=C["joiner"].join(parts))


def block_exposure(T, dl: dict) -> str:
    if dl.get("override"):
        return dl["override"]
    E, d = T["exposure"], dl["delta"]
    return E["text"].format(ev=_bin(E["ev"], d["ev"], n=f"{abs(d['ev']):.0f}"),
                            contrast=_bin(E["contrast"], d["contrast"]),
                            saturation=_bin(E["saturation"], d["saturation"]),
                            warmth=_bin(E["warmth"], d["warmth"]))


def block_sky_air(T, b, t, tgt_dt) -> str:
    fs = rules()["direction"]["forward_strong"]
    st = t["sky"]
    if st in ("clear", "partly") and t["light"]["stage"] == "L2":
        sky = T["sky"]["golden"]
    elif st == "clear" and t["direction"]["forward"] > fs and t["light"]["elev"] < 50:
        sky = T["sky"]["clear_toward_sun"]
    else:
        sky = T["sky"][st]
    A = T["air"]
    hb, ht = b["haze"]["level"], t["haze"]["level"]
    if ht >= 4:
        air = A["fog"]
    elif ht > hb or (ht >= 1 and t["direction"]["forward"] - b["direction"]["forward"] > 0.2):
        air = A["more"].format(pod_word=part_of_day(T, tgt_dt)["word"])     # 역광 쪽으로 갈수록 연무가 더 보인다
    elif ht < hb:
        air = A["less"]
    else:
        air = A["same"]
    bvis = {lm["name"]: lm["visibility"] for lm in b["landmarks"]}
    lms = [T["landmark"].format(name=lm["name"], vis=T["landmark_vis"][lm["visibility"]])
           for lm in t["landmarks"] if lm["visibility"] != "clear" or bvis.get(lm["name"]) != "clear"]
    if lms:
        air = "; ".join([air] + lms)
    return T["sky_air"].format(sky=sky, air=air)


def block_trees(T, b, t) -> str:
    bs = {x["species"]: x for x in b["trees"]}
    items = [T["trees"]["change"].format(species=x.get("name_en", x["species"]),
                                         target=x["desc"], base=bs[x["species"]]["desc"])
             for x in t["trees"] if x["species"] in bs and bs[x["species"]]["stage"] != x["stage"]]
    # 선택 항목 trees.keep: 단계가 같은 수목도 "그대로 둬라"를 적는다(겨울 짚 보온이 꽃밭으로 바뀌는 환각 방지)
    if T["trees"].get("keep"):
        items += [T["trees"]["keep"].format(species=x.get("name_en", x["species"]), target=x["desc"])
                  for x in t["trees"] if x["species"] in bs and bs[x["species"]]["stage"] == x["stage"]]
    return T["trees"]["text"].format(items=T["trees"]["joiner"].join(items)) if items else ""


def block_lamps(T, t) -> str:
    """템플릿에 lamps 키가 없으면(예전 템플릿) 빈 문장."""
    Lp, lm = T.get("lamps"), t.get("lamps") or {}
    if not Lp:
        return ""
    if lm.get("state") == "on":
        glow = Lp.get("glow")      # 세기 문장(스팟 yaml glow: bright|dim). 예전 템플릿엔 없음
        return Lp["lit"].format(lamps=lm["desc"], glow=glow.get(lm.get("glow", "bright"), "") if glow else "")
    if lm.get("state") == "none" and lm.get("dark"):
        return Lp["no_lamps"]
    return ""


def block_ground(T, b, t) -> str:
    G = T["ground"]
    bg, tg = set(b["ground"]), set(t["ground"])
    items = [G[k] for k in ("snow", "wet", "frost", "leaves") if k in tg and k not in bg]
    if "wet" in bg and "wet" not in tg and "snow" not in tg:
        items.append(G["dry_from_wet"])
    if "snow" in bg and "snow" not in tg:
        items.append(G["snow_gone"])
    return G["text"].format(items=G["joiner"].join(items)) if items else ""


def build_prompt(spot: dict, base_state: dict, tgt_state: dict, dl: dict, base_dt, tgt_dt) -> tuple[str, dict]:
    """반환: (프롬프트, 정보). 정보의 block_keys = 블록별로 실제 쓰인 템플릿 문자열 경로 목록."""
    raw = load_yaml("templates.yaml")
    terms = spot.get("scene_terms", {})
    mode = lighting_mode(tgt_state)
    b_dt, t_dt = base_dt.astimezone(spot["tz"]), tgt_dt.astimezone(spot["tz"])
    makers = {
        "time_change": lambda T: block_time(T, b_dt, t_dt),
        "preserve": lambda T: T["preserve"].format(subjects=terms.get("subjects", "")),
        "lighting": lambda T: block_lighting(T, base_state, tgt_state, mode),
        "lamps": lambda T: block_lamps(T, tgt_state),
        "consequences": lambda T: block_consequences(T, base_state, tgt_state, terms) if mode == "sun" else "",
        "exposure": lambda T: "" if dl.get("override") else block_exposure(T, dl),
        "sky_air": lambda T: block_sky_air(T, base_state, tgt_state, t_dt),
        "trees": lambda T: block_trees(T, base_state, tgt_state),
        "ground": lambda T: block_ground(T, base_state, tgt_state),
        "no_beautify": lambda T: T["no_beautify"].format(scene_kind=terms.get("scene_kind", "photo")),
    }
    blocks, block_keys = {}, {}
    for name, make in makers.items():
        used: list[str] = []
        blocks[name] = make(_TrackDict(raw, "", used))
        if name == "exposure" and dl.get("override"):
            blocks[name] = dl["override"]
        block_keys[name] = list(dict.fromkeys(used)) if blocks[name] else []
    order = [k for k in raw["order"] if blocks.get(k)]
    text = "\n".join(blocks[k] for k in order)
    return text, dict(template_version=raw["version"], lighting_mode=mode, blocks=blocks,
                      block_keys={k: block_keys[k] for k in order}, order=order)

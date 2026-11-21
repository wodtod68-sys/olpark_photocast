"""장면 상태표: 조건 원값 → 단계값(빛 L, 방향, 직사광 D, 연무 H, 하늘, 강수, 지면, 수목, 랜드마크).
임계값은 config/rules.yaml, 노출 변화 계수는 config/delta_rules.yaml."""
from __future__ import annotations
import math
from .common import load_yaml

RULES = load_yaml("rules.yaml")


def light_stage(elev: float) -> dict:
    for s in RULES["light_stages"]:
        if elev < s["max_elev"]:
            return dict(stage=s["stage"], label=s["label"])
    return dict(stage=RULES["light_stages"][-1]["stage"], label=RULES["light_stages"][-1]["label"])


def direct_stage(total, low) -> dict:
    total = 0.0 if total is None else total
    low = total if low is None else low           # 층 자료가 없으면 총량으로 대신
    for s in RULES["direct_sun"]:
        if total < s["total_max"] and low < s["low_max"]:
            return dict(stage=s["stage"], label=s["label"])
    last = RULES["direct_sun"][-1]
    return dict(stage=last["stage"], label=last["label"])


def haze_stage(pm25, rh, precip_3h, visibility, wind, elev) -> dict:
    H = RULES["haze"]
    if visibility is not None and visibility < H["fog_visibility_m"]:
        return dict(stage=4, basis=f"visibility {visibility:.0f} m < {H['fog_visibility_m']}")
    if (visibility is None and rh is not None and rh >= H["fog_rh"] and (wind or 0) <= H["fog_wind_max"]
            and elev < 15):
        return dict(stage=4, basis=f"RH {rh:.0f}% ≥ {H['fog_rh']}, calm, low sun (no visibility data)")
    if pm25 is not None:
        st = next(s["stage"] for s in H["pm25_stages"] if pm25 < s["max"])
        basis = f"PM2.5 {pm25:.0f}"
    else:
        st = next(s["stage"] for s in H["rh_only_stages"] if (rh or 0) < s["max"])
        basis = f"RH only {rh:.0f}%"
    if rh is not None and rh >= H["humid_rh"]:
        st += 1
        basis += f", RH {rh:.0f}% ≥ {H['humid_rh']} (+1)"
    if precip_3h and precip_3h >= H["washout_mm_3h"]:
        st -= 1
        basis += f", 3h precip {precip_3h} mm (washout −1)"
    return dict(stage=int(min(max(st, 0), 3)), basis=basis)


def sky_type(w: dict, light: str, precip: str, haze: int) -> str:
    S = RULES["sky_type"]
    tot = w.get("cloud_cover") or 0
    low, mid, high = (w.get(k) for k in ("cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"))
    if haze >= 4:
        return "fog"
    if precip in ("rain", "snow", "sleet"):
        return "rain"
    if light in ("L0",):
        return "night"
    if light == "L1":
        return "twilight"
    if tot >= S["overcast_total_min"]:
        return "overcast"
    if low is not None and low >= S["low_many_min"]:
        return "low_many"
    if tot < S["clear_total_max"]:
        return "clear"
    if high is not None and low is not None and high > max(low, mid or 0) and low < 30:
        return "high"
    return "partly"


def precip_form(w: dict) -> dict:
    P = RULES["precip"]
    pty = w.get("kma_pty")
    if pty is not None and not math.isnan(pty) and int(pty) > 0:
        form = RULES["kma_pty"].get(int(pty), "rain")
        form = "snow" if "snow" in form else "rain"
    elif (w.get("snowfall") or 0) > 0.05:
        form = "snow"
    elif (w.get("precipitation") or 0) >= P["rain_mm_h"]:
        form = "rain"
    else:
        form = "none"
    mm = w.get("precipitation") or 0
    inten = "light" if mm < 1 else "moderate" if mm < 4 else "heavy"
    return dict(form=form, intensity=inten if form != "none" else None, mm_h=mm)


def ground_state(w: dict, light: str, trees: list[dict]) -> list[str]:
    P, F = RULES["precip"], RULES["frost"]
    g = []
    if (w.get("snow_depth") or 0) > 0.005 or (w.get("snowfall_3h") or 0) > 0.2:
        g.append("snow")
    elif (w.get("precip_3h") or 0) >= P["wet_ground_mm_3h"]:
        g.append("wet")
    t, rh = w.get("temperature_2m"), w.get("relative_humidity_2m")
    order = [s["stage"] for s in RULES["light_stages"]]
    if (t is not None and rh is not None and t <= F["temp_max_c"] and rh >= F["rh_min"]
            and order.index(light) <= order.index(F["max_light_stage"]) and "snow" not in g):
        g.append("frost")
    if any(tr["stage"] in ("leaf_fall", "needle_fall") for tr in trees):
        g.append("leaves")
    return g


def visibility_km(pm25, rh, visibility_m) -> tuple[float, str]:
    if visibility_m is not None:
        return visibility_m / 1000, "forecast_visibility"
    V = RULES["visibility_model"]
    rhc = min(rh if rh is not None else 50, V["rh_cap"])
    beta = V["rayleigh_per_km"] + V["k_pm_per_km"] * (pm25 if pm25 is not None else 20) * (1 - rhc / 100) ** (-V["gamma"])
    return 3.912 / beta, "koschmieder(pm25,rh)"


def landmark_states(spot: dict, vis_km: float) -> list[dict]:
    out = []
    for lm in spot.get("landmarks", []):
        c = math.exp(-3.912 * lm["distance_km"] / max(vis_km, 0.01))
        st = next(s["stage"] for s in RULES["visibility_model"]["contrast_stages"] if c >= s["min"])
        out.append(dict(name=lm["name"], distance_km=lm["distance_km"], apparent_contrast=round(c, 3), visibility=st))
    return out


def build_state(spot: dict, cond: dict) -> dict:
    sun, w, air = cond["sun"], cond["weather"], cond["air"]
    L = light_stage(sun["elev"])
    D = direct_stage(w.get("cloud_cover"), w.get("cloud_cover_low"))
    pf = precip_form(w)
    H = haze_stage(air.get("pm25"), w.get("relative_humidity_2m"), w.get("precip_3h"), w.get("visibility"),
                   w.get("wind_speed_10m"), sun["elev"])
    if pf["form"] != "none" and D["stage"] != "D0":
        D = dict(stage="D0", label="no direct sun (precipitation)")
    vkm, vsrc = visibility_km(air.get("pm25"), w.get("relative_humidity_2m"), w.get("visibility"))
    return dict(
        datetime_local=cond["datetime_local"],
        light=dict(**L, elev=sun["elev"]),
        direction=dict(light_direction=sun["light_direction"], position=sun["position"], rel_azim=sun["rel_azim"],
                       forward=sun["forward"], lateral=sun["lateral"], sun_in_frame=sun["sun_in_frame"],
                       shadow_ratio=sun["shadow_ratio"], spot_shaded=sun["spot_shaded"], azim=sun["azim"]),
        direct_sun=dict(**D, cloud_total=w.get("cloud_cover"), cloud_low=w.get("cloud_cover_low"),
                        cloud_mid=w.get("cloud_cover_mid"), cloud_high=w.get("cloud_cover_high")),
        haze=dict(stage=f"H{H['stage']}", level=H["stage"], basis=H["basis"], pm25=air.get("pm25"),
                  rh=w.get("relative_humidity_2m"), visibility_km=round(vkm, 1), visibility_source=vsrc),
        sky=sky_type(w, L["stage"], pf["form"], H["stage"]),
        precip=pf,
        ground=ground_state(w, L["stage"], cond["trees"]),
        trees=cond["trees"],
        landmarks=landmark_states(spot, vkm),
        source=dict(weather=w.get("source"), air=air.get("source"),
                    trees="phenology.yaml(seoul_normal_estimate)" if cond["trees"] else None,
                    sun="pvlib"),
        raw=dict(weather={k: v for k, v in w.items() if k != "source"}, air=air),
    )


# ---------------- 노출 변화 (delta_rules.yaml) ----------------
def appearance(st: dict, DR: dict) -> dict:
    """한 시점의 상대 외관값(ev, contrast, saturation, warmth)."""
    keys = ("ev", "contrast", "saturation", "warmth")
    v = dict(DR["light_stage"][st["light"]["stage"]])
    dw = DR["direction_weight_by_direct"][st["direct_sun"]["stage"]]
    if st["light"]["stage"] in ("L0", "L1"):
        dw = 0.0
    for k in keys:
        v[k] += DR["direction_per_forward"][k] * st["direction"]["forward"] * dw
        v[k] += DR["direct_sun"][st["direct_sun"]["stage"]][k]
        v[k] += DR["haze_per_stage"][k] * st["haze"]["level"]
        if st["precip"]["form"] != "none":
            v[k] += DR["precip"][k]
    return {k: round(v[k], 3) for k in keys}


def delta(base: dict, target: dict) -> dict:
    DR = load_yaml("delta_rules.yaml")
    a, b = appearance(base, DR), appearance(target, DR)
    d = {k: round(b[k] - a[k], 3) for k in a}
    key = (f"{base['light']['stage']}->{target['light']['stage']}|"
           f"{base['direction']['light_direction']}->{target['direction']['light_direction']}|"
           f"{base['direct_sun']['stage']}->{target['direct_sun']['stage']}")
    override = None
    for o in DR.get("overrides") or []:
        if _match(o["key"], key):
            override = o["text"]
            break
    return dict(base=a, target=b, delta=d, key=key, override=override, rules_version=DR["version"])


def _match(pattern: str, key: str) -> bool:
    """'L5->L2|*|D3->*' 형식. 구간 전체 또는 화살표 한쪽에 * 사용 가능."""
    for p, k in zip(pattern.split("|"), key.split("|")):
        if p == "*":
            continue
        if any(x != "*" and x != y for x, y in zip(p.split("->"), k.split("->"))):
            return False
    return True

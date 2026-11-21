"""조건 계산: 태양 기하, 날씨(기상청 단기예보 → Open-Meteo 예보 → Open-Meteo 아카이브), 대기질, 수목 단계.

모든 시각은 timezone-aware datetime. 날씨 소스는 키가 없거나 범위 밖이면 건너뛰고 로그에 남긴다.
"""
from __future__ import annotations
import math
import re
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import pvlib
from .common import load_yaml, env_key, http_json, log

RULES = load_yaml("rules.yaml")
UTC = timezone.utc

OM_VARS = ["cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "relative_humidity_2m",
           "precipitation", "snowfall", "snow_depth", "visibility", "temperature_2m", "wind_speed_10m"]


# ---------------- 태양 ----------------
def wrap180(x: float) -> float:
    return (x + 180) % 360 - 180


def sun_geometry(dt: datetime, spot: dict) -> dict:
    sp = pvlib.solarposition.get_solarposition(pd.DatetimeIndex([dt.astimezone(UTC)]), spot["lat"], spot["lon"])
    elev = float(sp["apparent_elevation"].iloc[0])
    az = float(sp["azimuth"].iloc[0])
    rel = wrap180(az - spot["camera_bearing_deg"])          # 음수 = 왼쪽
    a = abs(rel)
    pb = RULES["direction"]["position_bounds"]
    side = "left" if rel < 0 else "right"
    if a < pb["ahead"]:
        pos = "ahead"
    elif a < pb["ahead_side"]:
        pos = f"ahead_{side}"
    elif a < pb["side"]:
        pos = side
    elif a < pb["behind_side"]:
        pos = f"behind_{side}"
    else:
        pos = "behind"
    d = RULES["direction"]
    lit = "back-lit" if a <= d["back_max"] else "front-lit" if a >= d["front_min"] else f"side-{side}"
    half_h, half_v = spot["hfov_deg"] / 2, spot["vfov_deg"] / 2
    in_frame = bool(a <= half_h and spot["pitch_deg"] - half_v <= elev <= spot["pitch_deg"] + half_v and elev > -1)
    return dict(elev=round(elev, 2), azim=round(az, 2), rel_azim=round(rel, 2),
                forward=round(math.cos(math.radians(rel)), 3), lateral=round(math.sin(math.radians(rel)), 3),
                position=pos, light_direction=lit, sun_in_frame=in_frame,
                shadow_ratio=round(1 / math.tan(math.radians(elev)), 3) if elev > 0.5 else None,
                spot_shaded=bool(elev < spot["obstacle_elev_deg"]))


# ---------------- 기상청 단기예보 ----------------
def latlon_to_kma_grid(lat: float, lon: float) -> tuple[int, int]:
    """기상청 동네예보 격자 변환 (Lambert Conformal Conic, 5km). 기상청 공개 변환식."""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    D = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * D, SLAT2 * D, OLON * D, OLAT * D
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re * sf / math.tan(math.pi * 0.25 + lat * D * 0.5) ** sn
    theta = lon * D - olon
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(ra * math.sin(theta) + XO + 0.5), int(ro - ra * math.cos(theta) + YO + 0.5)


def in_korea(lat, lon) -> bool:
    return 32.5 <= lat <= 39.0 and 124.0 <= lon <= 132.0


def _kma_amount(v: str) -> float:
    """PCP/SNO 문자열 → 숫자. '강수없음'/'적설없음' 0, '1mm 미만' 0.5, '30.0~50.0mm' 40, '50.0mm 이상' 50."""
    if v is None or "없음" in v:
        return 0.0
    if "미만" in v:
        return 0.5
    nums = [float(x) for x in re.findall(r"[\d.]+", v)]
    return float(np.mean(nums)) if nums else 0.0


def kma_forecast(spot: dict, dt: datetime) -> pd.DataFrame | None:
    key = env_key("KMA_SERVICE_KEY")
    if not key:
        log.info("기상청: KMA_SERVICE_KEY 없음 → 건너뜀")
        return None
    nx, ny = latlon_to_kma_grid(spot["lat"], spot["lon"])
    now = datetime.now(spot["tz"]) - timedelta(minutes=15)       # 발표 후 약 10분 뒤 제공
    base = max(h for h in (2, 5, 8, 11, 14, 17, 20, 23, -1) if h <= now.hour)
    bdt = now.replace(minute=0, second=0, microsecond=0)
    bdt = bdt.replace(hour=23) - timedelta(days=1) if base == -1 else bdt.replace(hour=base)
    params = dict(serviceKey=key, pageNo=1, numOfRows=2000, dataType="JSON",
                  base_date=bdt.strftime("%Y%m%d"), base_time=bdt.strftime("%H00"), nx=nx, ny=ny)
    try:
        js = http_json("http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst", params,
                       ttl_s=RULES["sources"]["forecast_cache_ttl_s"])
        items = js["response"]["body"]["items"]["item"]
    except Exception as ex:
        log.warning(f"기상청 단기예보 실패 → 건너뜀: {ex}")
        return None
    df = pd.DataFrame(items)
    df["t"] = pd.to_datetime(df.fcstDate + df.fcstTime, format="%Y%m%d%H%M").dt.tz_localize(spot["tz"]).dt.tz_convert(UTC)
    w = df.pivot_table(index="t", columns="category", values="fcstValue", aggfunc="first")
    out = pd.DataFrame(index=w.index)
    sky_map = RULES["kma_sky_to_cover"]
    out["cloud_cover"] = w["SKY"].astype(int).map(sky_map) if "SKY" in w else np.nan
    out["relative_humidity_2m"] = pd.to_numeric(w.get("REH"), errors="coerce")
    out["temperature_2m"] = pd.to_numeric(w.get("TMP"), errors="coerce")
    out["wind_speed_10m"] = pd.to_numeric(w.get("WSD"), errors="coerce")
    out["precipitation"] = w["PCP"].map(_kma_amount) if "PCP" in w else 0.0
    out["snowfall"] = w["SNO"].map(_kma_amount) if "SNO" in w else 0.0
    out["kma_sky"] = pd.to_numeric(w.get("SKY"), errors="coerce")
    out["kma_pty"] = pd.to_numeric(w.get("PTY"), errors="coerce")
    out["kma_pop"] = pd.to_numeric(w.get("POP"), errors="coerce")
    out.attrs["grid"] = (nx, ny)
    out.attrs["base"] = bdt.isoformat()
    return out


# ---------------- Open-Meteo ----------------
def _om_frame(js: dict) -> pd.DataFrame:
    h = pd.DataFrame(js["hourly"])
    h["time"] = pd.to_datetime(h.time).dt.tz_localize(UTC)
    return h.set_index("time").sort_index().apply(pd.to_numeric, errors="coerce")


def om_forecast(spot: dict, dt: datetime) -> pd.DataFrame | None:
    d0 = (dt.astimezone(UTC) - timedelta(days=1)).date()
    d1 = (dt.astimezone(UTC) + timedelta(days=1)).date()
    try:
        js = http_json("https://api.open-meteo.com/v1/forecast",
                       dict(latitude=spot["lat"], longitude=spot["lon"], hourly=",".join(OM_VARS),
                            start_date=d0, end_date=d1, timezone="UTC", wind_speed_unit="ms"),
                       ttl_s=RULES["sources"]["forecast_cache_ttl_s"])
        return _om_frame(js)
    except Exception as ex:
        log.warning(f"Open-Meteo 예보 실패 → 건너뜀: {ex}")
        return None


# step1b_join_weather.HOURLY와 같은 목록 + snowfall. 패키지를 따로 떼어 써도 돌도록 여기 둔다.
ARCHIVE_VARS = ["cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
                "relative_humidity_2m", "dew_point_2m", "temperature_2m",
                "precipitation", "snow_depth", "wind_speed_10m", "snowfall"]


def om_archive(spot: dict, dt: datetime) -> pd.DataFrame | None:
    """ERA5 아카이브 — step1b_join_weather와 같은 엔드포인트·변수. 과거라 영구 캐시."""
    vars_ = ARCHIVE_VARS
    d0 = (dt.astimezone(UTC) - timedelta(days=1)).date()
    d1 = (dt.astimezone(UTC) + timedelta(days=1)).date()
    try:
        js = http_json("https://archive-api.open-meteo.com/v1/archive",
                       dict(latitude=spot["lat"], longitude=spot["lon"], hourly=",".join(vars_),
                            start_date=d0, end_date=d1, timezone="UTC", wind_speed_unit="ms"))
        return _om_frame(js)
    except Exception as ex:
        log.warning(f"Open-Meteo 아카이브 실패: {ex}")
        return None


def at_time(h: pd.DataFrame, dt: datetime) -> dict:
    t = pd.Timestamp(dt.astimezone(UTC))
    num = h.select_dtypes("number")
    row = num.reindex(num.index.union([t])).interpolate("time", limit_area="inside").loc[t]
    out = {k: (None if pd.isna(v) else round(float(v), 2)) for k, v in row.items()}
    # 직전 3시간 강수: 시각 H의 precipitation = (H−1, H] 합
    if "precipitation" in h:
        win = h.loc[(h.index > t - pd.Timedelta(hours=3)) & (h.index <= t.ceil("h")), "precipitation"]
        out["precip_3h"] = round(float(win.sum()), 2) if len(win) else None
    if "snowfall" in h:
        win = h.loc[(h.index > t - pd.Timedelta(hours=3)) & (h.index <= t.ceil("h")), "snowfall"]
        out["snowfall_3h"] = round(float(win.sum()), 2) if len(win) else None
    return out


def weather(spot: dict, dt: datetime) -> dict:
    """소스 우선순위: 1) 기상청 단기예보(한국·72시간 이내 미래·키 있음) 2) Open-Meteo 예보 3) 아카이브(과거)."""
    S = RULES["sources"]
    now = datetime.now(UTC)
    hours_ahead = (dt.astimezone(UTC) - now).total_seconds() / 3600
    src = {}
    w = {}
    if 0 <= hours_ahead <= S["kma_max_hours_ahead"] and in_korea(spot["lat"], spot["lon"]):
        k = kma_forecast(spot, dt)
        if k is not None and len(k):
            w = at_time(k, dt)
            src["main"] = f"kma_vilage_fcst(base {k.attrs['base']}, grid {k.attrs['grid']})"
    elif hours_ahead >= 0:
        log.info("기상청: 범위 밖(한국 외 또는 72시간 초과) → 건너뜀")
    if hours_ahead > -24 * S["archive_lag_days"]:
        if hours_ahead > 24 * S["forecast_max_days"]:
            log.warning("Open-Meteo 예보 범위(16일) 밖")
        om = om_forecast(spot, dt)
        kind = "open-meteo_forecast"
    else:
        om = om_archive(spot, dt)
        kind = "open-meteo_archive(ERA5)"
    if om is not None:
        o = at_time(om, dt)
        if w:   # 기상청 값 우선, 층별 운량·시정만 보충
            for k2 in ("cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "visibility", "snow_depth"):
                w[k2] = o.get(k2)
            src["layers"] = kind
        else:
            w = o
            src["main"] = kind
    if not w:
        raise RuntimeError("날씨 자료를 하나도 못 받았다")
    w["source"] = src
    return w


# ---------------- 대기질 ----------------
def air_quality(spot: dict, dt: datetime) -> dict:
    key = env_key("AIRKOREA_SERVICE_KEY")
    now = datetime.now(spot["tz"])
    local = dt.astimezone(spot["tz"])
    if key and in_korea(spot["lat"], spot["lon"]):
        try:
            if abs((local - now).total_seconds()) < 3 * 3600 and spot.get("airkorea_station"):
                js = http_json("http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty",
                               dict(serviceKey=key, returnType="json", numOfRows=24, pageNo=1,
                                    stationName=spot["airkorea_station"], dataTerm="DAILY", ver="1.3"), ttl_s=1800)
                it = js["response"]["body"]["items"][0]
                return dict(pm25=float(it["pm25Value"]), pm10=float(it["pm10Value"]),
                            source=f"airkorea_realtime({spot['airkorea_station']} {it['dataTime']})")
            if 0 <= (local.date() - now.date()).days <= 2:
                js = http_json("http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMinuDustFrcstDspth",
                               dict(serviceKey=key, returnType="json", numOfRows=100, pageNo=1,
                                    searchDate=now.strftime("%Y-%m-%d"), InformCode="PM25"), ttl_s=3600)
                region = spot.get("airkorea_region", "서울")
                for it in js["response"]["body"]["items"]:
                    if it.get("informData") == local.strftime("%Y-%m-%d"):
                        m = re.search(rf"{region}\s*:\s*(\S+?)(,|$)", it.get("informGrade", ""))
                        if m:
                            g = m.group(1)
                            return dict(pm25=float(RULES["airkorea_grade_pm25"][g]), pm10=None,
                                        source=f"airkorea_forecast({region} {g})")
        except Exception as ex:
            log.warning(f"에어코리아 실패 → Open-Meteo로: {ex}")
    elif not key:
        log.info("에어코리아: AIRKOREA_SERVICE_KEY 없음 → Open-Meteo 대기질")
    try:
        d = dt.astimezone(UTC).date()
        past = (datetime.now(UTC) - dt.astimezone(UTC)).days > 7
        js = http_json("https://air-quality-api.open-meteo.com/v1/air-quality",
                       dict(latitude=spot["lat"], longitude=spot["lon"], hourly="pm10,pm2_5",
                            start_date=d - timedelta(days=1), end_date=d + timedelta(days=1), timezone="UTC"),
                       ttl_s=None if past else 3600)
        fr = _om_frame(js)
        o = at_time(fr, dt)
        if o.get("pm2_5") is not None:
            return dict(pm25=o["pm2_5"], pm10=o.get("pm10"), source="open-meteo_air_quality(CAMS)")
        have = fr["pm2_5"].dropna()
        log.info("Open-Meteo 대기질: 해당 시각 자료 없음 "
                 + (f"(자료 범위 {have.index[0]:%m-%d %H시}~{have.index[-1]:%m-%d %H시} UTC)" if len(have) else "(이 기간 자료 없음)"))
    except Exception as ex:
        log.info(f"Open-Meteo 대기질 실패: {ex}")
    if spot.get("typical_pm25") is not None:
        return dict(pm25=float(spot["typical_pm25"]), pm10=None, source="spot_default(typical_pm25)")
    return dict(pm25=None, pm10=None, source="unavailable")


# ---------------- 수목 ----------------
def phenology(spot: dict, dt: datetime) -> list[dict]:
    cal = load_yaml("phenology.yaml")["species"]
    alias = {a: k for k, v in cal.items() for a in v.get("aliases", [k])}
    out = []
    d = dt.astimezone(spot["tz"]).date()
    for tr in spot.get("trees", []):
        key = alias.get(str(tr["species"]).strip())
        if key is None:
            log.warning(f"phenology.yaml에 없는 수종: {tr['species']}")
            continue
        st = cal[key]["stages"]
        starts = [datetime.strptime(f"{d.year}-{s['start']}", "%Y-%m-%d").date() for s in st]
        i = max(j for j, s in enumerate(starts) if s <= d)
        nxt = starts[i + 1] if i + 1 < len(starts) else starts[0].replace(year=d.year + 1)
        prog = (d - starts[i]).days / max((nxt - starts[i]).days, 1)
        out.append(dict(species=key, label=tr.get("species"), name_en=cal[key].get("name_en", key),
                        name_ko=cal[key].get("name_ko", tr.get("species")), stage=st[i]["name"],
                        stage_ko=st[i].get("ko", st[i]["name"]), desc=st[i]["desc"],
                        progress=round(prog, 2), source="phenology.yaml(seoul_normal_estimate)"))
    return out


def assumed_weather(a: dict) -> tuple[dict, dict]:
    """스팟의 base_assumed(기준 사진의 날씨를 모를 때 가정값) → weather, air. API를 부르지 않는다."""
    w = dict(cloud_cover=0.0, cloud_cover_low=0.0, cloud_cover_mid=0.0, cloud_cover_high=0.0,
             relative_humidity_2m=50.0, precipitation=0.0, snowfall=0.0, snow_depth=0.0, visibility=None,
             temperature_2m=20.0, wind_speed_10m=2.0, precip_3h=0.0, snowfall_3h=0.0)
    w.update(a.get("weather") or {})
    w["source"] = {"main": "assumed(spot base_assumed)"}
    air = dict(pm25=None, pm10=None, source="assumed(spot base_assumed)")
    air.update(a.get("air") or {})
    return w, air


def conditions(spot: dict, dt: datetime, assumed: dict | None = None) -> dict:
    """assumed가 있으면 날씨·대기질은 가정값을 쓴다(태양·수목은 그대로 계산)."""
    if assumed:
        w, air = assumed_weather(assumed)
    else:
        w, air = weather(spot, dt), air_quality(spot, dt)
    return dict(datetime_local=dt.astimezone(spot["tz"]).isoformat(), datetime_utc=dt.astimezone(UTC).isoformat(),
                sun=sun_geometry(dt, spot), weather=w, air=air, trees=phenology(spot, dt))

"""경로, .env, 설정 파일, 스팟 로더, 캐시 HTTP."""
from __future__ import annotations
import contextvars
import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import yaml

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent                                   # photocast_sky/
CONFIG = PKG / "config"
OUT = ROOT / "outputs" / "forecast"
CACHE = OUT / "cache"

log = logging.getLogger("forecast")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=VALUE 형식 .env를 읽어 os.environ에 넣는다(이미 있는 값은 덮지 않음)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def env_key(name: str) -> str | None:
    load_env()
    v = os.environ.get(name)
    return v if v else None


# 실험실(server/lab)에서 편집 중인 설정을 디스크에 쓰지 않고 요청 단위로 주입한다.
# {"templates.yaml": dict, "rules.yaml": dict, "delta_rules.yaml": dict} 중 일부.
_CONFIG_OVERRIDE: contextvars.ContextVar[dict | None] = contextvars.ContextVar("forecast_config", default=None)
_FILE_CACHE: dict[str, tuple[float, dict]] = {}


def set_config_override(cfg: dict | None):
    """반환한 토큰으로 reset_config_override(token) 해서 되돌린다."""
    return _CONFIG_OVERRIDE.set(cfg)


def reset_config_override(token) -> None:
    _CONFIG_OVERRIDE.reset(token)


def load_yaml(name: str) -> dict:
    ov = _CONFIG_OVERRIDE.get()
    if ov and name in ov:
        return ov[name]
    p = CONFIG / name
    mt = p.stat().st_mtime
    hit = _FILE_CACHE.get(name)
    if hit is None or hit[0] != mt:
        hit = (mt, yaml.safe_load(p.read_text(encoding="utf-8")))
        _FILE_CACHE[name] = hit
    return hit[1]


def rules() -> dict:
    return load_yaml("rules.yaml")


def expand(p: str | None) -> Path | None:
    """${SKYFINDER_DIR}, ~ 확장. 상대 경로는 photocast_sky/ 기준."""
    if not p:
        return None
    os.environ.setdefault("SKYFINDER_DIR", str(Path.home() / "skyfinder"))
    q = Path(os.path.expanduser(os.path.expandvars(p)))
    return q if q.is_absolute() else ROOT / q


def resolve_spot_path(p: str) -> Path:
    for cand in (Path(p), ROOT / p, PKG / p):
        if cand.exists():
            return cand.resolve()
    raise FileNotFoundError(f"spot 파일을 찾을 수 없음: {p}")


def exif_datetime(path: Path) -> datetime | None:
    from PIL import Image
    try:
        ex = Image.open(path).getexif()
        v = ex.get_ifd(0x8769).get(36867) or ex.get(306)      # DateTimeOriginal, DateTime
        return datetime.strptime(v, "%Y:%m:%d %H:%M:%S") if v else None
    except Exception:
        return None


def load_spot(p: str) -> dict:
    path = resolve_spot_path(p)
    s = yaml.safe_load(path.read_text(encoding="utf-8"))
    s["id"] = path.stem
    s["path"] = str(path)
    s.setdefault("hfov_deg", 65)
    s.setdefault("vfov_deg", 50)
    s.setdefault("pitch_deg", 0)
    s.setdefault("obstacle_elev_deg", 5)
    s.setdefault("landmarks", [])
    s.setdefault("trees", [])
    s.setdefault("scene_terms", {})
    if s.get("camera_bearing_deg") is None:
        raise ValueError(f"{path.name}: camera_bearing_deg를 채워야 한다")
    tz = ZoneInfo(s["timezone"])
    s["tz"] = tz
    img = expand(s.get("base_image"))
    if not img or not img.exists():
        raise FileNotFoundError(f"{path.name}: base_image 없음 ({s.get('base_image')})")
    s["base_image_path"] = img
    if s.get("base_datetime"):
        s["base_dt"] = parse_local(str(s["base_datetime"]), tz)
    else:
        dt = exif_datetime(img)
        if dt is None:
            raise ValueError(f"{path.name}: base_datetime이 없고 EXIF 촬영 시각도 없다")
        s["base_dt"] = dt.replace(tzinfo=tz)
    for k in ("sky_mask", "ignore_mask"):
        s[k + "_path"] = expand(s.get(k))
    return s


def parse_local(text: str, tz: ZoneInfo) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            pass
    raise ValueError(f"시각 형식을 알 수 없음: {text} (예: 2026-11-25 10:00)")


def http_json(url: str, params: dict, ttl_s: float | None = None, retries: int = 2, timeout: int = 30):
    """GET JSON. ttl_s=None이면 영구 캐시(과거 자료), 숫자면 그 시간만 캐시. 키가 든 파라미터는 캐시 이름에서 제외."""
    params = {k: str(v) for k, v in params.items()}
    q = urllib.parse.urlencode(params, safe=",:")
    full = f"{url}?{q}"
    safe = {k: v for k, v in params.items() if "key" not in k.lower()}
    h = hashlib.sha1((url + json.dumps(safe, sort_keys=True)).encode()).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{h}.json"
    if f.exists() and (ttl_s is None or time.time() - f.stat().st_mtime < ttl_s):
        return json.loads(f.read_text())
    err = None
    for k in range(retries + 1):
        try:
            with urllib.request.urlopen(full, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            f.write_text(json.dumps(data))
            return data
        except Exception as ex:   # 네트워크 일시 오류 재시도
            err = ex
            time.sleep(2)
    raise RuntimeError(f"요청 실패: {url} ({re.sub(r'serviceKey=[^&]+', 'serviceKey=***', str(err))})")

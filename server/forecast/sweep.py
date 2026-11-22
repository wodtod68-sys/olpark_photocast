"""같은 날짜에서 시각만 바꿔 여러 장 + 한 장짜리 비교 스트립.

python -u -m forecast.sweep --spot spots/sample_21510.yaml --date 2013-02-15 --times "07:30,12:00,16:02,17:32" --dry-run
저장: outputs/forecast/<spot>/sweep_<날짜>/ <HHMM>/ (predict와 같은 구성), prompts.md, strip.jpg
"""
from __future__ import annotations
import argparse
import difflib
import cv2
import numpy as np
from pathlib import Path
from .common import OUT, load_spot, parse_local
from .predict import run_predict, check_budget


def put(img, text, org, scale=0.6):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)


def tile(path: Path | None, label: str, size=(480, 360)) -> np.ndarray:
    im = cv2.imread(str(path)) if path and Path(path).exists() else None
    if im is None:
        im = np.full((size[1], size[0], 3), 40, np.uint8)
        put(im, "(no image: dry-run)", (20, size[1] // 2), 0.7)
    im = cv2.resize(im, size, interpolation=cv2.INTER_AREA)
    bar = np.full((34, size[0], 3), 24, np.uint8)
    put(bar, label, (8, 23), 0.6)
    return np.vstack([bar, im])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", required=True)
    ap.add_argument("--date", required=True, help="YYYY-MM-DD (스팟 현지)")
    ap.add_argument("--times", required=True, help='"07:00,10:00,13:00"')
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--model", default="pro")
    ap.add_argument("--ref", default=None)
    ap.add_argument("--max-calls", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    spot = load_spot(a.spot)
    times = [t.strip() for t in a.times.split(",") if t.strip()]
    check_budget(a.n * len(times), a.model, a.max_calls, a.dry_run)
    root = OUT / spot["id"] / f"sweep_{a.date.replace('-', '')}"
    results = []
    for t in times:
        dt = parse_local(f"{a.date} {t}", spot["tz"])
        print(f"\n================ {a.date} {t} ================")
        r = run_predict(spot, dt, a.n, a.model, a.dry_run, Path(a.ref) if a.ref else None,
                        out_dir=root / dt.strftime("%H%M"))
        results.append((t, r))

    # 프롬프트 모음 + 이웃 시각과 달라진 문장
    md = [f"# sweep {spot['id']} {a.date}", ""]
    prev = None
    for t, r in results:
        ts = r["target"]
        md += [f"## {t}  ({ts['light']['stage']}, {ts['direction']['light_direction']}, {ts['direct_sun']['stage']}, "
               f"{ts['haze']['stage']}, sky={ts['sky']}, lighting={r['meta']['lighting_mode']})", "", "```", r["prompt"], "```", ""]
        if prev is not None:
            diff = [l for l in difflib.ndiff(prev.splitlines(), r["prompt"].splitlines()) if l[:2] in ("- ", "+ ")]
            md += ["이전 시각 대비 바뀐 문장:", "", "```diff", *diff, "```", ""]
        prev = r["prompt"]
    (root / "prompts.md").write_text("\n".join(md), encoding="utf-8")

    tiles = [tile(spot["base_image_path"], f"base {spot['base_dt'].strftime('%H:%M')}")]
    for t, r in results:
        g = next((r["out_dir"] / x["file_orig"] for x in r["meta"]["generations"] if x.get("file")), None)
        ts = r["target"]
        tiles.append(tile(g, f"{t}  {ts['light']['stage']} {ts['direction']['light_direction']} {ts['direct_sun']['stage']}"))
    cv2.imwrite(str(root / "strip.jpg"), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"\n→ {root / 'prompts.md'}\n→ {root / 'strip.jpg'}")


if __name__ == "__main__":
    main()

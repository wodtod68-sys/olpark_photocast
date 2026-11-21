"""예측 이미지 1건: 조건 → 장면 상태표 → 프롬프트 → (Gemini 생성).

python -u -m forecast.predict --spot spots/sample_21510.yaml --datetime "2013-02-15 16:02" --dry-run
python -u -m forecast.predict --spot spots/sample_21510.yaml --datetime "2013-02-15 16:02" --n 1 --model nb2.1
저장: outputs/forecast/<spot>/<YYYYMMDD_HHMM>/ scene_state.json, prompt.txt, gen_*.png, meta.json
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from .common import OUT, load_spot, parse_local, log, load_yaml
from .conditions import conditions
from .scene import build_state, delta
from .prompt import build_prompt
from . import generate as G


def summary_table(b: dict, t: dict, dl: dict) -> str:
    row = lambda name, f: f"  {name:<10}| {f(b):<58}| {f(t)}"
    lines = [f"  {'':<10}| {'기준 ' + b['datetime_local'][:16]:<58}| {'목표 ' + t['datetime_local'][:16]}",
             row("빛", lambda s: f"{s['light']['stage']} {s['light']['label']} (고도 {s['light']['elev']:.1f}°)"),
             row("방향", lambda s: f"{s['direction']['light_direction']} / {s['direction']['position']} "
                                   f"(rel {s['direction']['rel_azim']:.0f}°{', 화면 안' if s['direction']['sun_in_frame'] else ''})"),
             row("그림자 비율", lambda s: f"{s['direction']['shadow_ratio']}" + (" spot_shaded" if s['direction']['spot_shaded'] else "")),
             row("직사광", lambda s: f"{s['direct_sun']['stage']} (운량 {s['direct_sun']['cloud_total']}/하층 {s['direct_sun']['cloud_low']})"),
             row("연무", lambda s: f"{s['haze']['stage']} ({s['haze']['basis']})"),
             row("하늘/강수", lambda s: f"{s['sky']} / {s['precip']['form']}"),
             row("지면", lambda s: ",".join(s["ground"]) or "-"),
             row("수목", lambda s: ", ".join(f"{x['species']}:{x['stage']}" for x in s["trees"]) or "-"),
             row("랜드마크", lambda s: ", ".join(f"{x['name']}:{x['visibility']}" for x in s["landmarks"]) or "-"),
             row("소스", lambda s: f"{s['source']['weather'].get('main')} | air {s['source']['air']}"),
             f"  노출 변화(보정 전 {dl['rules_version']}): " + ", ".join(f"{k} {v:+.2f}" for k, v in dl["delta"].items())
             + (f"  [override: {dl['key']}]" if dl.get("override") else "")]
    return "\n".join(lines)


def run_predict(spot: dict, tgt_dt: datetime, n: int, model: str, dry_run: bool, ref: Path | None = None,
                out_dir: Path | None = None, quiet: bool = False) -> dict:
    base_c = conditions(spot, spot["base_dt"], spot.get("base_assumed"))
    tgt_c = conditions(spot, tgt_dt)
    bs, ts = build_state(spot, base_c), build_state(spot, tgt_c)
    dl = delta(bs, ts)
    prompt, pinfo = build_prompt(spot, bs, ts, dl, spot["base_dt"], tgt_dt)
    out_dir = out_dir or OUT / spot["id"] / tgt_dt.astimezone(spot["tz"]).strftime("%Y%m%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scene_state.json").write_text(json.dumps(dict(base=bs, target=ts, delta=dl), ensure_ascii=False,
                                                         indent=1, default=str), encoding="utf-8")
    (out_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    if not quiet:
        print(f"\n[장면 상태표] {spot['name']}\n" + summary_table(bs, ts, dl))
        print(f"\n[프롬프트] template {pinfo['template_version']}, lighting={pinfo['lighting_mode']}\n{prompt}\n")
    gens = []
    m = G.model_info(model)
    if not dry_run:
        gens = G.generate(prompt, spot["base_image_path"], out_dir, model, n, ref)
    ok = sum(1 for g in gens if g.get("file"))
    calls = sum(g.get("attempt", 1) for g in gens)
    meta = dict(spot=spot["id"], spot_file=spot["path"], base_image=str(spot["base_image_path"]),
                base_datetime=spot["base_dt"].isoformat(), target_datetime=tgt_dt.isoformat(),
                model=m["id"], model_name=m["name"], dry_run=dry_run, n_requested=n, n_ok=ok, api_calls=calls,
                cost_usd=round(calls * m["usd_per_image"], 4), ref_image=str(ref) if ref else None,
                template_version=pinfo["template_version"], delta_rules_version=dl["rules_version"],
                lighting_mode=pinfo["lighting_mode"],
                sources=dict(base=bs["source"], target=ts["source"]), generations=gens,
                generated_at=datetime.now(timezone.utc).isoformat())
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log.info(f"저장: {out_dir}")
    return dict(out_dir=out_dir, prompt=prompt, base=bs, target=ts, delta=dl, meta=meta)


def check_budget(n_calls: int, model: str, max_calls: int, dry_run: bool) -> None:
    cost, msg = G.estimate(n_calls, model)
    if dry_run:
        print(f"[비용] dry-run: API 호출 없음 (실행 시 {msg})")
        return
    print(f"[비용] {msg}  (실패 시 호출마다 재시도 1회 추가 가능, 상한 --max-calls {max_calls})")
    if n_calls > max_calls:
        raise SystemExit(f"호출 {n_calls}회가 --max-calls {max_calls}를 넘는다. 늘리려면 --max-calls를 명시할 것.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", required=True)
    ap.add_argument("--datetime", required=True, help='스팟 현지 시각, 예: "2026-11-25 10:00"')
    ap.add_argument("--n", type=int, default=1, help="샘플 수")
    ap.add_argument("--model", default="nb2.1", help="nb2.1 | pro | 모델 ID")
    ap.add_argument("--ref", default=None, help="두 번째 이미지로 첨부할 참조 사진")
    ap.add_argument("--max-calls", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 상태표와 프롬프트만")
    a = ap.parse_args()
    spot = load_spot(a.spot)
    tgt = parse_local(a.datetime, spot["tz"])
    check_budget(a.n, a.model, a.max_calls, a.dry_run)
    run_predict(spot, tgt, a.n, a.model, a.dry_run, Path(a.ref) if a.ref else None)


if __name__ == "__main__":
    main()

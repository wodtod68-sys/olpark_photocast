"""예측 vs 실제 사진 채점 (매일 루프용).

python -u -m forecast.verify --pred outputs/forecast/sample_21510/20130215_1602 --real ~/skyfinder/21510/20130215_220215.jpg

- 실제 사진(폰으로 손으로 찍어 화각이 조금 다를 수 있음)과 예측 이미지를 기준 사진에 정렬:
  SIFT 특징점 + RANSAC 호모그래피 → 실패하면 ECC(호모그래피, 기울기 영상) → 실패하면 그대로(경고).
- 지표(지면/하늘 각각): 밝기 L, 대비(L 5~95%), 채도, 색온도 b*  + 지면 ΔE(픽셀), 하늘 ΔE(평균색),
  윤곽선 SSIM(예측 vs 기준, 구조 보존). 기준선 = 기준 사진 그대로(변화 없음)의 같은 지표.
- 저장: <pred>/verify_<실제파일>.jpg 패널, outputs/forecast/validation_log.csv 누적.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np
import pandas as pd
from skimage.metrics import structural_similarity
from .common import OUT, load_spot, log, expand

LOG_CSV = OUT / "validation_log.csv"


# ---------------- 정렬 ----------------
def _grad(gray: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(gray.astype(np.float32), (5, 5), 0)
    m = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    return m / (m.mean() + 1e-6)


def align_to(img: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    """img를 ref 좌표로 워프. 반환: 워프 영상, 유효 영역 마스크, 방법 설명."""
    h, w = ref.shape[:2]
    if img.shape[:2] != (h, w) and abs(img.shape[1] / img.shape[0] - w / h) < 0.02:
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    g1, g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    H, how = None, "identity"
    try:
        sift = cv2.SIFT_create(4000)
        k1, d1 = sift.detectAndCompute(g1, None)
        k0, d0 = sift.detectAndCompute(g0, None)
        if d1 is not None and d0 is not None:
            mt = cv2.BFMatcher().knnMatch(d1, d0, k=2)
            good = [m for m, n in (p for p in mt if len(p) == 2) if m.distance < 0.75 * n.distance]
            if len(good) >= 20:
                src = np.float32([k1[m.queryIdx].pt for m in good])
                dst = np.float32([k0[m.trainIdx].pt for m in good])
                Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
                if Hm is not None and inl.sum() >= 30:
                    H, how = Hm, f"sift_homography(inliers {int(inl.sum())}/{len(good)})"
    except cv2.error as ex:
        log.warning(f"SIFT 실패: {ex}")
    if H is None:
        try:
            small = lambda x: cv2.resize(x, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
            gi = cv2.resize(g1, (w, h), interpolation=cv2.INTER_AREA)
            W = np.eye(3, dtype=np.float32)
            cc, W = cv2.findTransformECC(_grad(small(g0)), _grad(small(gi)), W, cv2.MOTION_HOMOGRAPHY,
                                         (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), None, 5)
            S = np.diag([2, 2, 1]).astype(np.float32)
            Sx = np.diag([w / img.shape[1], h / img.shape[0], 1]).astype(np.float32)
            H = S @ np.linalg.inv(W) @ np.linalg.inv(S) @ Sx
            how = f"ecc_homography(cc {cc:.2f})"
        except cv2.error:
            log.warning("정렬 실패 → 크기만 맞춰 비교 (화각 차이가 크면 지표를 믿지 말 것)")
            H = np.diag([w / img.shape[1], h / img.shape[0], 1])
    warped = cv2.warpPerspective(img, H, (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), H, (w, h)) > 250
    return warped, valid, how


# ---------------- 마스크 ----------------
def estimate_sky(ref: np.ndarray) -> np.ndarray:
    """기준 사진에서 하늘 추정: 밝고 매끈하며 위쪽 가장자리에 붙은 영역."""
    lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB)
    L = lab[..., 0].astype(np.float32) * 100 / 255
    g = _grad(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY))
    cand = ((L > 50) & (g < 1.0)).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab_cc = cv2.connectedComponents(cand)
    top = set(np.unique(lab_cc[0, :])) - {0}
    return np.isin(lab_cc, list(top))


def masks(spot: dict, ref: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    h, w = ref.shape[:2]
    p = spot.get("sky_mask_path")
    if p and Path(p).exists():
        sky = cv2.resize(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE), (w, h), interpolation=cv2.INTER_NEAREST) > 127
        how = "spot sky_mask"
    else:
        sky = estimate_sky(ref)
        how = "estimated"
    ign = np.zeros((h, w), bool)
    q = spot.get("ignore_mask_path")
    if q and Path(q).exists():
        ign = cv2.resize(cv2.imread(str(q), cv2.IMREAD_GRAYSCALE), (w, h), interpolation=cv2.INTER_NEAREST) > 127
    k = np.ones((5, 5), np.uint8)
    ground = cv2.erode((~sky).astype(np.uint8), k).astype(bool) & ~ign & valid
    skyc = cv2.erode(sky.astype(np.uint8), k).astype(bool) & ~ign & valid
    return ground, skyc, how


# ---------------- 지표 ----------------
def lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img.astype(np.float32) / 255, cv2.COLOR_BGR2LAB)


def region_stats(lb: np.ndarray, m: np.ndarray) -> dict:
    if m.sum() < 50:
        return dict(L=np.nan, contrast=np.nan, chroma=np.nan, b=np.nan)
    v = lb[m]
    p5, p95 = np.percentile(v[:, 0], [5, 95])
    return dict(L=float(v[:, 0].mean()), contrast=float(p95 - p5), chroma=float(np.hypot(v[:, 1], v[:, 2]).mean()),
                b=float(v[:, 2].mean()))


def edge_ssim(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    ea, eb = (_grad(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)) for x in (a, b))
    hi = max(np.percentile(ea, 99), np.percentile(eb, 99))
    _, s = structural_similarity(np.clip(ea / hi, 0, 1), np.clip(eb / hi, 0, 1), data_range=1.0, full=True)
    return float(s[m].mean())


def score(img: np.ndarray, real: np.ndarray, base: np.ndarray, ground: np.ndarray, sky: np.ndarray) -> dict:
    li, lr = lab(img), lab(real)
    out = {}
    for name, m in (("ground", ground), ("sky", sky)):
        for k, v in region_stats(li, m).items():
            out[f"{name}_{k}"] = v
    de = np.sqrt(((li - lr) ** 2).sum(-1))
    out["ground_dE"] = float(de[ground].mean())
    out["sky_dE"] = float(np.linalg.norm(li[sky].mean(0) - lr[sky].mean(0))) if sky.sum() > 50 else np.nan
    out["edge_ssim_vs_base"] = edge_ssim(img, base, ground | sky)
    return out, de


# ---------------- 패널 ----------------
def put(img, text, org, scale=0.55, color=(255, 255, 255)):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def heat(de: np.ndarray, ground: np.ndarray, vmax=30.0) -> np.ndarray:
    v = cv2.applyColorMap((np.clip(de / vmax, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    v[~ground] = (v[~ground] * 0.25).astype(np.uint8)
    return v


def labelled(img, label, w=640, h=480, colorbar=False):
    im = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    bar = np.full((30, w, 3), 32, np.uint8)
    put(bar, label, (8, 21), 0.6)
    if colorbar:
        x0, x1 = w - 250, w - 40
        grad = np.linspace(0, 255, x1 - x0).astype(np.uint8)[None, :].repeat(14, 0)
        bar[8:22, x0:x1] = cv2.applyColorMap(grad, cv2.COLORMAP_INFERNO)
        put(bar, "0", (x0 - 16, 21), 0.5)
        put(bar, "30", (x1 + 4, 21), 0.5)
    return np.vstack([bar, im])


def panel(base, pred, real, de, ground, sp: dict, sb: dict, sr: dict, header: list[str]) -> np.ndarray:
    row = np.hstack([labelled(base, "base (original)"), labelled(pred, f"prediction  ground dE {sp['ground_dE']:.1f}"),
                     labelled(real, "real (aligned)"), labelled(heat(de, ground), "pred vs real dE", colorbar=True)])
    keys = [("ground_L", "ground L"), ("ground_contrast", "ground contrast"), ("ground_chroma", "ground chroma"),
            ("ground_b", "ground b*"), ("sky_L", "sky L"), ("sky_contrast", "sky contrast"),
            ("sky_chroma", "sky chroma"), ("sky_b", "sky b*")]
    lines = header + [
        f"{'':<16}{'base':>9}{'pred':>9}{'real':>9}{'pred-real':>11}{'base-real':>11}",
        *[f"{n:<16}{sb[k]:>9.1f}{sp[k]:>9.1f}{sr[k]:>9.1f}{sp[k] - sr[k]:>+11.1f}{sb[k] - sr[k]:>+11.1f}" for k, n in keys],
        f"ground dE: pred {sp['ground_dE']:.2f} | base(no change) {sb['ground_dE']:.2f}     "
        f"sky dE: pred {sp['sky_dE']:.2f} | base {sb['sky_dE']:.2f}     edge SSIM vs base: pred {sp['edge_ssim_vs_base']:.3f}"]
    head = np.full((26 * len(lines) + 14, row.shape[1], 3), 16, np.uint8)
    for i, t in enumerate(lines):
        cv2.putText(head, t, (12, 26 * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX if i < len(header) else cv2.FONT_HERSHEY_PLAIN,
                    0.6 if i < len(header) else 1.25, (255, 220, 120) if i == 0 else (235, 235, 235), 1, cv2.LINE_AA)
    return np.vstack([head, row])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True, help="predict 출력 폴더")
    ap.add_argument("--real", required=True, help="실제 사진")
    ap.add_argument("--gen", default=None, help="채점할 생성 파일 (기본: 폴더의 gen_*_orig.png 전부)")
    a = ap.parse_args()
    pdir = expand(a.pred)
    meta = json.loads((pdir / "meta.json").read_text())
    st = json.loads((pdir / "scene_state.json").read_text())
    spot = load_spot(meta["spot_file"])
    base = cv2.imread(str(spot["base_image_path"]))
    real_raw = cv2.imread(str(expand(a.real)))
    if real_raw is None:
        raise SystemExit(f"실제 사진을 못 읽음: {a.real}")
    real, valid_r, how_r = align_to(real_raw, base)
    gens = [pdir / a.gen] if a.gen else sorted(pdir.glob("gen_*_orig.png"))
    if not gens:
        raise SystemExit(f"{pdir}에 생성 이미지가 없다 (dry-run 폴더?)")
    rows = []
    for gp in gens:
        pred, valid_p, how_p = align_to(cv2.imread(str(gp)), base)
        ground, sky, how_m = masks(spot, base, valid_r & valid_p)
        sp, de = score(pred, real, base, ground, sky)
        sb, _ = score(base, real, base, ground, sky)
        sr, _ = score(real, real, base, ground, sky)
        t = st["target"]
        header = [f"{spot['id']} | target {meta['target_datetime'][:16]} | {gp.name} vs {Path(a.real).name} | "
                  f"model {meta['model']} | template {meta['template_version']}",
                  f"stages: {t['light']['stage']} {t['direction']['light_direction']} {t['direct_sun']['stage']} "
                  f"{t['haze']['stage']} sky={t['sky']} | align real: {how_r}, pred: {how_p} | sky mask: {how_m}"]
        pn = panel(base, pred, real, de, ground, sp, sb, sr, header)
        out = pdir / f"verify_{Path(a.real).stem}_{gp.stem}.jpg"
        cv2.imwrite(str(out), pn, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"\n[{gp.name}] 정렬: real {how_r} / pred {how_p} / 하늘 {how_m}")
        print(f"  지면 ΔE  예측 {sp['ground_dE']:.2f}  | 변화없음 {sb['ground_dE']:.2f}")
        print(f"  하늘 ΔE  예측 {sp['sky_dE']:.2f}  | 변화없음 {sb['sky_dE']:.2f}")
        print(f"  윤곽선 SSIM(예측 vs 기준) {sp['edge_ssim_vs_base']:.3f}")
        for k in ("ground_L", "ground_contrast", "ground_chroma", "ground_b", "sky_L", "sky_b"):
            print(f"  {k:<16} 기준 {sb[k]:6.1f}  예측 {sp[k]:6.1f}  실제 {sr[k]:6.1f}  (예측−실제 {sp[k] - sr[k]:+.1f})")
        print(f"  → {out}")
        rows.append(dict(logged_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), spot=spot["id"],
                         target_datetime=meta["target_datetime"], base_datetime=meta["base_datetime"],
                         real_image=str(expand(a.real)), pred_image=str(gp), model=meta["model"],
                         template_version=meta["template_version"], delta_rules_version=meta["delta_rules_version"],
                         light=t["light"]["stage"], direction=t["direction"]["light_direction"],
                         direct=t["direct_sun"]["stage"], haze=t["haze"]["stage"], sky=t["sky"],
                         precip=t["precip"]["form"], lighting_mode=meta["lighting_mode"], align_real=how_r,
                         sky_mask=how_m,
                         **{f"pred_{k}": round(v, 3) for k, v in sp.items()},
                         **{f"base_{k}": round(v, 3) for k, v in sb.items()},
                         **{f"real_{k}": round(v, 3) for k, v in sr.items() if k not in ("ground_dE", "sky_dE")}))
    df = pd.DataFrame(rows)
    if LOG_CSV.exists():
        df = pd.concat([pd.read_csv(LOG_CSV), df], ignore_index=True)
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(LOG_CSV, index=False)
    print(f"\n→ 누적 {LOG_CSV} ({len(df)}행)")


if __name__ == "__main__":
    main()

"""Gemini 이미지 편집 (google-genai SDK, GEMINI_API_KEY).

모델 ID는 Google AI Studio 문서(aistudio.google.com/docs/image-generation, 2026-11 확인) 기준:
  pro   = gemini-3-pro-image      (Nano Banana Pro, 기본 — 2026-11-22 결정) — 장당 $0.134
  nb2.1 = gemini-nano-banana-2.1 (Nano Banana 2.1)                         — 장당 $0.034
키가 생기면 `python -m forecast.generate --list-models`로 실제 계정에서 보이는 ID를 확인할 것.
"""
from __future__ import annotations
import argparse
import time
from pathlib import Path
from PIL import Image
from .common import env_key, log

MODELS = {
    "nb2.1": dict(id="gemini-nano-banana-2.1", usd_per_image=0.034, name="Nano Banana 2.1"),
    "pro": dict(id="gemini-3-pro-image", usd_per_image=0.134, name="Nano Banana Pro"),
}
ASPECTS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


def model_info(name: str) -> dict:
    if name in MODELS:
        return MODELS[name]
    for m in MODELS.values():
        if m["id"] == name:
            return m
    log.warning(f"비용표에 없는 모델 ID: {name} — 비용은 Pro 단가로 가정")
    return dict(id=name, usd_per_image=MODELS["pro"]["usd_per_image"], name=name)


def closest_aspect(w: int, h: int) -> str:
    r = w / h
    return min(ASPECTS, key=lambda a: abs(int(a.split(":")[0]) / int(a.split(":")[1]) - r))


def estimate(n_calls: int, model: str) -> tuple[float, str]:
    m = model_info(model)
    cost = n_calls * m["usd_per_image"]
    return cost, f"예상 호출 {n_calls}회 × ${m['usd_per_image']:.3f} ({m['name']}) = ${cost:.3f}"


def client():
    key = env_key("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY가 없다 (.env에 GEMINI_API_KEY=... 추가, 발급: Google AI Studio)")
    from google import genai
    return genai.Client(api_key=key)


def _request(cl, prompt: str, base: Image.Image, ref: Image.Image | None, model_id: str):
    from google.genai import types
    contents = [prompt, base] + ([ref] if ref is not None else [])
    cfg = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=closest_aspect(*base.size), image_size="1K"))
    resp = cl.models.generate_content(model=model_id, contents=contents, config=cfg)
    img, text = None, []
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            img = part.inline_data.data
        elif getattr(part, "text", None):
            text.append(part.text)
    if img is None:
        raise RuntimeError(f"이미지 없이 응답: {' '.join(text)[:200]}")
    return img, " ".join(text)[:500]


def generate_one(prompt: str, base_path: Path, model: str, ref_path: Path | None = None) -> dict:
    """1장. 실패 시 1회만 재시도. 반환: image(bytes) 또는 error, attempts(실제 호출 수), seconds, text."""
    m = model_info(model)
    base = Image.open(base_path).convert("RGB")
    ref = Image.open(ref_path).convert("RGB") if ref_path else None
    cl = client()
    for attempt in (1, 2):
        t0 = time.time()
        try:
            img, text = _request(cl, prompt, base, ref, m["id"])
            return dict(image=img, text=text, attempts=attempt, seconds=round(time.time() - t0, 1), model=m["id"])
        except Exception as ex:
            log.warning(f"생성 시도 {attempt} 실패: {ex}")
            if attempt == 2:
                return dict(image=None, error=str(ex)[:500], attempts=attempt, model=m["id"])


def generate(prompt: str, base_path: Path, out_dir: Path, model: str, n: int = 1,
             ref_path: Path | None = None) -> list[dict]:
    """n장 생성. gen_<i>.png(1K 원본)와 gen_<i>_orig.png(기준 사진 크기)를 저장."""
    base_size = Image.open(base_path).size
    results = []
    for i in range(n):
        r = generate_one(prompt, base_path, model, ref_path)
        if r.get("image") is None:
            results.append(dict(file=None, error=r["error"], attempt=r["attempts"]))
            continue
        p = out_dir / f"gen_{i}.png"
        p.write_bytes(r["image"])
        g = Image.open(p).convert("RGB")
        g.resize(base_size, Image.LANCZOS).save(out_dir / f"gen_{i}_orig.png")
        results.append(dict(file=p.name, file_orig=f"gen_{i}_orig.png", size=list(g.size), attempt=r["attempts"],
                            seconds=r["seconds"], text=r["text"]))
        log.info(f"생성 {i + 1}/{n}: {p} {g.size} ({r['seconds']:.0f}s)")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-models", action="store_true", help="계정에서 보이는 이미지 모델 ID 출력")
    a = ap.parse_args()
    if a.list_models:
        cl = client()        # 페이지를 넘기는 동안 클라이언트가 닫히지 않게 붙잡아 둔다
        for mm in cl.models.list():
            if "image" in mm.name or "banana" in mm.name:
                print(mm.name, "|", getattr(mm, "display_name", ""))


if __name__ == "__main__":
    main()

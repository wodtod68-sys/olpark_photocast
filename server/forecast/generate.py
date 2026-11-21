"""Gemini 이미지 편집 (google-genai SDK, GEMINI_API_KEY).

모델 ID는 Google AI Studio 문서(aistudio.google.com/docs/image-generation, 2026-11 확인) 기준:
  nb2.1 = gemini-nano-banana-2.1 (Nano Banana 2.1, 기본) — 장당 $0.034
  pro   = gemini-3-pro-image      (Nano Banana Pro)       — 장당 $0.134
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


def generate(prompt: str, base_path: Path, out_dir: Path, model: str, n: int = 1,
             ref_path: Path | None = None) -> list[dict]:
    """n장 생성. 각 호출은 실패 시 1회만 재시도. gen_<i>.png(1K 원본)와 gen_<i>_orig.png(기준 사진 크기)를 저장."""
    from google.genai import types
    m = model_info(model)
    base = Image.open(base_path).convert("RGB")
    contents = [prompt, base]
    if ref_path:
        contents.append(Image.open(ref_path).convert("RGB"))
    cfg = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=closest_aspect(*base.size), image_size="1K"))
    cl = client()
    results = []
    for i in range(n):
        for attempt in (1, 2):
            t0 = time.time()
            try:
                resp = cl.models.generate_content(model=m["id"], contents=contents, config=cfg)
                img, text = None, []
                for part in resp.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        img = part.inline_data.data
                    elif getattr(part, "text", None):
                        text.append(part.text)
                if img is None:
                    raise RuntimeError(f"이미지 없이 응답: {' '.join(text)[:200]}")
                p = out_dir / f"gen_{i}.png"
                p.write_bytes(img)
                g = Image.open(p).convert("RGB")
                g.resize(base.size, Image.LANCZOS).save(out_dir / f"gen_{i}_orig.png")
                results.append(dict(file=p.name, file_orig=f"gen_{i}_orig.png", size=list(g.size), attempt=attempt,
                                    seconds=round(time.time() - t0, 1), text=" ".join(text)[:500]))
                log.info(f"생성 {i + 1}/{n}: {p} {g.size} ({time.time() - t0:.0f}s)")
                break
            except Exception as ex:
                log.warning(f"생성 {i + 1}/{n} 시도 {attempt} 실패: {ex}")
                if attempt == 2:
                    results.append(dict(file=None, error=str(ex)[:500], attempt=attempt))
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

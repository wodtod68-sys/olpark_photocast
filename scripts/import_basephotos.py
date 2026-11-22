"""아이폰 기준 사진 4장 → API 전송용 사본 + 스팟 yaml 교체.

server/.venv/bin/python -u scripts/import_basephotos.py [--src ~/skyfinder/basephotos] [--dry-run]

- 원본(--src)은 건드리지 않는다.
- 촬영 시각(EXIF DateTimeOriginal) 순서 = 9경, 8경, 4경, 6경 → rose, wild, gyeong4, naholo.
  순서를 바꾸려면 --order rose,wild,gyeong4,naholo 처럼 준다.
- 사본: server/base_photos/<id>.jpg — EXIF 회전 반영, 긴 변 1536px, JPEG 품질 92,
  메타데이터는 촬영 시각(DateTimeOriginal, OffsetTimeOriginal)만 남기고 GPS 등은 지운다.
- 4경 공개 카드 사진(public/images/gyeong4.jpg, 1200×1800 맞춤)도 만든다(친구 저장소에 사진이 없으므로).
- 스팟 yaml: base_image를 사본으로, base_datetime → EXIF에서 읽도록 null, base_assumed 블록 삭제.
"""
from __future__ import annotations
import argparse
import re
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

REPO = Path(__file__).resolve().parents[1]
SPOTS = REPO / "server" / "forecast" / "spots"
OUT = REPO / "server" / "base_photos"
EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png"}


def taken_at(im: Image.Image) -> tuple[str | None, str | None]:
    ex = im.getexif()
    sub = ex.get_ifd(0x8769)
    return sub.get(36867) or ex.get(306), sub.get(36881) or sub.get(36880)   # DateTimeOriginal, OffsetTimeOriginal


def api_copy(src: Path, dst: Path, long_side=1536, quality=92) -> tuple[str, str | None, tuple[int, int]]:
    im = Image.open(src)
    t, off = taken_at(im)
    if not t:
        raise SystemExit(f"{src.name}: EXIF 촬영 시각이 없다 (원본이 아닌 사본일 수 있음)")
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((long_side, long_side), Image.LANCZOS)
    ex = Image.Exif()
    ex[306] = t                                   # DateTime (IFD0)
    sub = ex.get_ifd(0x8769)
    sub[36867] = t                                # DateTimeOriginal
    if off:
        sub[36881] = off                          # OffsetTimeOriginal
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=quality, exif=ex.tobytes())
    return t, off, im.size


def card_copy(src: Path, dst: Path, size=(1200, 1800)):
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    ImageOps.fit(im, size, Image.LANCZOS).save(dst, "JPEG", quality=85)      # 메타데이터 없음


def update_yaml(spot_id: str, dry: bool) -> None:
    p = SPOTS / f"{spot_id}.yaml"
    s = p.read_text(encoding="utf-8")
    block = (f"base_image: base_photos/{spot_id}.jpg     # 아이폰 원본의 전송용 사본 (scripts/import_basephotos.py)\n"
             f"base_datetime: null       # EXIF DateTimeOriginal에서 읽음. 날씨는 촬영 시각의 실제 값(Open-Meteo)\n")
    s2 = re.sub(r"(# ★ 임시:.*?\n|# ★ 기준 사진 없음:.*?\n)(#.*\n)*base_image:.*\n(base_datetime:.*\n)?"
                r"(base_assumed:\n(  .*\n)*)?", block, s, count=1)
    if s2 == s:
        print(f"  {p.name}: 바꿀 블록을 못 찾음 — 직접 확인")
        return
    if not dry:
        p.write_text(s2, encoding="utf-8")
    print(f"  {p.name}: base_image → base_photos/{spot_id}.jpg, base_assumed 삭제{' (dry-run)' if dry else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(Path.home() / "skyfinder" / "basephotos"))
    ap.add_argument("--order", default="rose,wild,gyeong4,naholo", help="촬영 순서대로 스팟 id")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    src = Path(a.src).expanduser()
    files = [f for f in src.iterdir() if f.suffix.lower() in EXTS] if src.exists() else []
    order = a.order.split(",")
    if len(files) != len(order):
        raise SystemExit(f"{src}에 사진 {len(files)}장 — {len(order)}장이 있어야 한다")
    dated = sorted(((taken_at(Image.open(f))[0] or "", f) for f in files))
    for (t, f), sid in zip(dated, order):
        print(f"{sid:8} ← {f.name}  (EXIF {t})")
        if a.dry_run:
            continue
        t, off, size = api_copy(f, OUT / f"{sid}.jpg")
        print(f"  사본 {OUT / (sid + '.jpg')} {size} 시각 {t} {off or ''}")
        if sid == "gyeong4":
            card_copy(f, REPO / "public" / "images" / "gyeong4.jpg")
            print("  4경 카드 사진 public/images/gyeong4.jpg")
    for sid in order:
        update_yaml(sid, a.dry_run)


if __name__ == "__main__":
    main()

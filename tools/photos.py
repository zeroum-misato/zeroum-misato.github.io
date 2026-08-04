#!/usr/bin/env python3
"""
ZEROUM サイト 写真パイプライン

使い方:
  python3 tools/photos.py import <元フォルダ>   # 写真を取り込む（透かし除去→圧縮→images/works/へ）
  python3 tools/photos.py build                # works.json から HTML を生成して埋め込む
  python3 tools/photos.py                      # build と同じ

import は works.json に「未分類」で行を足すだけ。
カテゴリとキャプションは works.json を手で直してから build する。
"""
import json, re, shutil, subprocess, sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です:  python3 -m pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "images" / "works"
DATA = ROOT / "works.json"

# Galaxy の撮影透かしは下端から 25〜65px に入る。余裕をみて 78px 落とす。
WATERMARK_PX = 78
MAX_EDGE = 1200          # 長辺の上限（元より大きくはしない）
JPEG_QUALITY = 82

CATEGORIES = [
    ("house",   "住宅の電気工事"),
    ("shop",    "店舗・施設の工事"),
    ("control", "空調・計装・制御盤"),
    ("outdoor", "屋外・高所の工事"),
]
CAT_LABEL = dict(CATEGORIES)


def load():
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return {"works": [], "recruit": []}


def save(d):
    DATA.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def process(src: Path, dst: Path):
    """透かしを切り落とし、長辺を縮めて JPEG で保存する。"""
    im = Image.open(src)
    im = im.convert("RGB")
    w, h = im.size
    cut = WATERMARK_PX if h > WATERMARK_PX * 3 else 0
    if cut:
        im = im.crop((0, 0, w, h - cut))
    if max(im.size) > MAX_EDGE:
        im.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return im.size, dst.stat().st_size


def cmd_import(folder: str):
    src_dir = Path(folder).expanduser()
    if not src_dir.is_dir():
        sys.exit(f"フォルダが見つかりません: {src_dir}")
    data = load()
    known = {w["file"] for w in data["works"]}
    n = max([int(m.group(1)) for w in data["works"]
             if (m := re.match(r"w(\d+)\.jpg", w["file"]))] or [0])
    added = []
    for p in sorted(src_dir.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".heic"):
            continue
        n += 1
        name = f"w{n:02d}.jpg"
        while name in known:
            n += 1
            name = f"w{n:02d}.jpg"
        size, bytes_ = process(p, OUT_DIR / name)
        data["works"].append({"file": name, "category": "", "caption": "", "src": p.name})
        added.append((p.name, name, size, bytes_))
    save(data)
    for orig, name, size, b in added:
        print(f"  {orig}  ->  {name}  {size[0]}x{size[1]}  {b//1024}KB")
    print(f"\n{len(added)}枚を取り込みました。works.json の category / caption を埋めてから build してください。")
    print("category:", ", ".join(f"{k}={v}" for k, v in CATEGORIES))


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def render_works(items):
    out = []
    for key, label in CATEGORIES:
        group = [w for w in items if w.get("category") == key]
        if not group:
            continue
        out.append(f'<h3 class="g-cat">{label}</h3>')
        out.append('<ul class="g-grid">')
        for w in group:
            cap = w.get("caption") or label
            out.append(
                f'<li class="g-item"><img src="images/works/{w["file"]}" '
                f'alt="{esc(cap)}｜ZEROUM株式会社の施工実績" loading="lazy" '
                f'width="600" height="450"><span class="g-cap">{esc(cap)}</span></li>'
            )
        out.append("</ul>")
    return "\n".join(out)


def render_recruit(items):
    out = ['<ul class="g-grid g-plain">']
    for w in items:
        cap = w.get("caption") or "ZEROUM株式会社の現場の様子"
        out.append(
            f'<li class="g-item"><img src="images/works/{w["file"]}" '
            f'alt="{esc(cap)}" loading="lazy" width="600" height="450"></li>'
        )
    out.append("</ul>")
    return "\n".join(out)


def inject(path: Path, marker: str, html: str):
    text = path.read_text(encoding="utf-8")
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    if start not in text or end not in text:
        sys.exit(f"{path.name} に {marker} のマーカーがありません")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    path.write_text(f"{head}{start}\n{html}\n{end}{tail}", encoding="utf-8")
    print(f"  {path.name}: {marker} を更新")


def cmd_build():
    data = load()
    works = [w for w in data["works"] if w.get("category")]
    skipped = [w["file"] for w in data["works"] if not w.get("category")]
    inject(ROOT / "works.html", "WORKS", render_works(works))
    rec = [w for w in data["works"] if w["file"] in data.get("recruit", [])]
    inject(ROOT / "recruit.html", "GALLERY", render_recruit(rec))
    print(f"\n施工事例 {len(works)}枚 / 現場の様子 {len(rec)}枚 を反映しました。")
    if skipped:
        print(f"※ category が空のため未掲載: {', '.join(skipped)}")


def cmd_publish():
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if r.returncode == 0:
        print("変更はありません。")
        return
    subprocess.run(["git", "commit", "-m", "写真を更新"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
    print("公開しました。1分ほどで反映されます。")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "build":
        cmd_build()
    elif args[0] == "import" and len(args) > 1:
        cmd_import(args[1])
    elif args[0] == "publish":
        cmd_publish()
    else:
        sys.exit(__doc__)

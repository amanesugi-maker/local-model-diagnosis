# 軸「画像を見るか」。推測不能な文字列を画像に埋めて読ませる。
#   10枚: 易5（大きい黒文字・白地）＋ 難5（小さい・低コントラスト・回転・ノイズ・写真風の背景）
#   ＋ 見たふり検出2枚: 文字の無い画像に「書かれている文字列は？」→「無い」と言えるか
# 採点は機械: 8文字の乱数文字列が答えに含まれるか（当てずっぽうでは当たらない）。
#   python cap_vision.py --port 8081 --label heretic27b --model heretic-q4-mtp
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import re
import string
import sys
import time

import requests

_sf = os.environ.get("LLMBENCH_SYSTEM_FILE")
SYSTEM_PROMPT = open(_sf, encoding="utf-8").read().strip() if _sf and os.path.exists(_sf) else ""


USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0, "sec": 0.0}


def add_usage(j, sec):
    u = j.get("usage") or {}
    USAGE["prompt_tokens"] += int(u.get("prompt_tokens") or 0); USAGE["completion_tokens"] += int(u.get("completion_tokens") or 0); USAGE["requests"] += 1; USAGE["sec"] += sec


def with_system(messages):
    return ([{"role": "system", "content": SYSTEM_PROMPT}] + messages) if SYSTEM_PROMPT else messages
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")   # 診断.py の --host が入れる

WORK = r"E:\AI\ai-workspace\tools\llm-bench\results"
SEED = 20260908
# 等幅フォント。Windows以外でも動くよう、見つかった最初のものを使う（2026-09-09 配布対応）。
# 字形が違っても測っているのは「画像の中の文字を読めるか」なので判定には影響しない。
_FONTS = [
    os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "consola.ttf"),
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
]
FONT = next((f for f in _FONTS if os.path.exists(f)), _FONTS[0])
DENY = re.compile(r"(文字(は|が)?(あり|ござい)ませ|書かれてい(ない|ませ)|見当たり|存在しま?せ|ありません|無い|なし|not (present|found|visible)|no text|does not contain)", re.I)


def tok(r: random.Random, n: int = 8) -> str:
    # 見間違えやすい文字（0/O, 1/I/l）は除く
    return "".join(r.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=n))


def make_image(r: random.Random, code: str, kind: str) -> Image.Image:
    W, H = 640, 320
    if kind == "easy":
        im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
        f = ImageFont.truetype(FONT, 64); d.text((60, 120), code, fill="black", font=f)
    elif kind == "small":
        im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
        f = ImageFont.truetype(FONT, 22); d.text((r.randint(40, 380), r.randint(40, 260)), code, fill="black", font=f)
    elif kind == "lowcontrast":
        im = Image.new("RGB", (W, H), (200, 205, 210)); d = ImageDraw.Draw(im)
        f = ImageFont.truetype(FONT, 48); d.text((80, 130), code, fill=(150, 155, 160), font=f)
    elif kind == "rotated":
        im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
        f = ImageFont.truetype(FONT, 56); d.text((100, 120), code, fill="black", font=f)
        im = im.rotate(r.choice([-25, 25, 90]), expand=False, fillcolor="white")
    elif kind == "noisy":
        im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
        for _ in range(3000):
            d.point((r.randint(0, W - 1), r.randint(0, H - 1)), fill=(r.randint(0, 255),) * 3)
        f = ImageFont.truetype(FONT, 52); d.text((90, 125), code, fill="black", font=f)
        im = im.filter(ImageFilter.GaussianBlur(1.0))
    elif kind == "busy":     # 写真風の背景（色の帯）に文字
        im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
        for i in range(0, W, 40):
            d.rectangle([i, 0, i + 40, H], fill=(r.randint(120, 240), r.randint(120, 240), r.randint(120, 240)))
        f = ImageFont.truetype(FONT, 56); d.text((80, 125), code, fill=(20, 20, 40), font=f)
    else:                    # blank: 文字なし
        im = Image.new("RGB", (W, H), (245, 245, 240)); d = ImageDraw.Draw(im)
        d.ellipse([200, 80, 440, 240], outline=(180, 180, 180), width=4)
    return im


def cases(r: random.Random) -> list[dict]:
    kinds = ["easy"] * 5 + ["small", "lowcontrast", "rotated", "noisy", "busy"] + ["blank", "blank"]
    out = []
    for k in kinds:
        code = tok(r)
        out.append({"kind": k, "code": None if k == "blank" else code, "img": make_image(r, code, k)})
    return out


def ask(port: int, model: str, img: Image.Image, q: str) -> str:
    buf = io.BytesIO(); img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = {"model": model, "max_tokens": 80, "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False},
            "messages": with_system([{"role": "user", "content": [
                {"type": "text", "text": q},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}])}
    _t0 = time.time()
    rr = requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, timeout=600)
    rr.raise_for_status()
    _j = rr.json(); add_usage(_j, time.time() - _t0)
    return (_j["choices"][0]["message"].get("content") or "").strip()


def run(port: int, label: str, model: str) -> None:
    r = random.Random(SEED)
    cs = cases(r)
    ok = 0; detail = []
    q = "この画像に書かれている英数字の文字列をそのまま答えてください。文字列だけを答え、無ければ「文字はありません」と答えてください。"
    for c in cs:
        try:
            out = ask(port, model, c["img"], q)
            if c["code"] is None:
                good = bool(DENY.search(out)) and not re.search(r"\b[A-Z0-9]{6,}\b", out)
            else:
                good = c["code"] in out.upper().replace(" ", "")
        except Exception as e:
            out, good = repr(e)[:80], False
        ok += good
        detail.append({"kind": c["kind"], "ok": good, "code": c["code"], "head": out[:60]})
        print(f"  {c['kind']:12s} {'○' if good else '×'}  {out[:40]!r}", flush=True)
    res = {"label": label, "port": port, "画像を見るか": 100.0 * ok / len(cs), "_画像内訳": detail, "_usage": dict(USAGE), "_system_prompt": bool(SYSTEM_PROMPT)}
    os.makedirs(WORK, exist_ok=True)
    json.dump(res, open(os.path.join(WORK, f"vision_{label}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{label}: 画像を見るか {res['画像を見るか']:.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True); ap.add_argument("--label", required=True); ap.add_argument("--model", default="x")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run(a.port, a.label, a.model)

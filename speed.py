# 速度のスペック測定（⑤・2026-09-08 本人決裁「速度は総合に入れないが表示する」）。
# 同じ PC 内での比較用。results/speed_<label>.json に保存し、make_report.py のスペック欄が読む。
#
#   python speed.py --port 8081 --label heretic27b --model heretic-q4-mtp
#
# 測るもの（OpenAI 互換・stream で実測）:
#   decode  : 短い入力から 384 トークン生成 → 生成 t/s（3回の中央値）
#   prefill : 実物のソースコード約4千トークンを読ませて初手まで → 読込 t/s（2回の中央値）
#   vram    : 測定直後の nvidia-smi memory.used（MiB）
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

import requests

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")   # 診断.py の --host が入れる

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
sys.path.insert(0, HERE)
try:
    import payload  # 実物コードの長文
except Exception:
    payload = None


def stream(port: int, model: str, prompt: str, max_tokens: int) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0.0, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time(); first = None; n = 0; usage = {}
    with requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, stream=True, timeout=1800) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith(b"data:"):
                continue
            d = line[5:].strip()
            if d == b"[DONE]":
                break
            j = json.loads(d)
            if j.get("usage"):
                usage = j["usage"]
            ch = (j.get("choices") or [{}])[0].get("delta", {})
            if ch.get("content"):
                if first is None:
                    first = time.time()
                n += 1
    t1 = time.time()
    return {"ttft": (first or t1) - t0, "total": t1 - t0, "chunks": n,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}


def vram_mib() -> int:
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30).stdout
        return int(o.strip().splitlines()[0])
    except Exception:
        return -1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="x")
    a = ap.parse_args()
    stream(a.port, a.model, "hi", 4)  # ウォームアップ
    dec = []
    for _ in range(3):
        r = stream(a.port, a.model, "Write a long, detailed essay about the history of railways.", 384)
        ct = r["completion_tokens"] or r["chunks"]
        dec.append(ct / max(r["total"] - r["ttft"], 1e-6))
    long_text = payload.realistic(16000) if payload else ("def f(x):\n    return x\n" * 800)   # 約4千トークンの実物コード
    pre = []
    for _ in range(2):
        r = stream(a.port, a.model, long_text + "\n\nSummarize the code above in one sentence.", 8)
        pt = r["prompt_tokens"]
        pre.append((pt or len(long_text) / 4) / max(r["ttft"], 1e-6))
    out = {"label": a.label, "port": a.port, "model": a.model, "decode_tps": round(statistics.median(dec), 1),
           "prefill_tps": round(statistics.median(pre), 0), "prompt_tokens": r["prompt_tokens"], "vram_mib": vram_mib(),
           "measured": time.strftime("%Y-%m-%d %H:%M")}
    os.makedirs(RES, exist_ok=True)
    json.dump(out, open(os.path.join(RES, f"speed_{a.label}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

# 速度のスペック測定。
# 同じ PC 内での比較用。results/speed_<label>.json に保存し、make_report.py のスペック欄が読む。
#
#   python speed.py --port 8081 --label heretic27b --model heretic-q4-mtp
#
# 測るもの（2026-09-13 から llama-server の timings を正とする。返さない相手だけ stream 実測）:
#   decode  : 短い入力から 384 トークン生成 → 生成 t/s（3回の中央値）
#   prefill : 実物のソースコード約4千トークンを読ませる → 読込 t/s（2回の中央値）
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


def stream(port: int, model: str, prompt: str, max_tokens: int, no_cache: bool = False) -> dict:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0.0, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    # 2026-09-13: FreeToken は timings を返さないのでこちらの経路に落ちる。
    # 読込を測る時はここでも prefix cache を切らないと、2回目が巨大値になる。
    if no_cache:
        body["cache_prompt"] = False
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
            # 2026-09-12: 思考を reasoning_content で別に流すモデル（Muse Glimmer）だと、
            # content の初片は思考が終わった最後の一瞬に来る。そこへ思考込みの
            # completion_tokens を割ると decode_tps が 3.8億 t/s になった。
            # 最初の「トークン」はどちらの筋でも最初のかけらとする。
            # reasoning_content を出さないモデルでは挙動は完全に同じ。
            if ch.get("content") or ch.get("reasoning_content"):
                if first is None:
                    first = time.time()
                n += 1
    t1 = time.time()
    return {"ttft": (first or t1) - t0, "total": t1 - t0, "chunks": n,
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens")}


def timed(port: int, model: str, prompt: str, max_tokens: int, no_cache: bool = False) -> dict | None:
    """2026-09-13: llama-server が自分で測った timings を正とする。

    自前でストリームを刻んで「トークン数 ÷ 時間」を出す方式は、分母が潰れると値が爆発した
    （Muse Glimmer で decode 3.8億 t/s）。サーバーの実測値ならその余地が無い。
    timings を返さない相手（Ollama 等）では None を返し、呼び出し側が従来方式へ落ちる。
    """
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0,
            "timings_per_token": True,
            "chat_template_kwargs": {"enable_thinking": False}}
    # 読込を測るときは prefix cache を切る。切らないと2回目以降は cache_n が
    # ほぼ全トークンを占め、prompt_n=1 の値を「読込速度」と読んでしまう
    # （2026-09-13 実測: 同じ長文で cache_n=6993 / prompt_n=1）。
    if no_cache:
        body["cache_prompt"] = False
    try:
        r = requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, timeout=1800)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return None
    t = j.get("timings")
    if not isinstance(t, dict):
        return None
    return {"decode": t.get("predicted_per_second"), "prefill": t.get("prompt_per_second"),
            "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n"),
            "prompt_tokens": (j.get("usage") or {}).get("prompt_tokens")}


def gpu_background() -> dict:
    """測定を始める前の背景の状態を記録する。

    2026-09-13、保存済みの生成値（87.3 t/s）が同日の再測定（72 t/s）と15%食い違った。
    新旧の方式を同じ瞬間に当てると生成は一致した（73.2 対 72.3）ので方式は無罪で、
    **機械の状態**の差だった。その日の背景負荷を残しておかないと後から説明できない。
    """
    try:
        o = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,clocks.sm,clocks.max.sm,power.draw,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30).stdout
        u, sm, smmax, pw, tp = [x.strip() for x in o.strip().splitlines()[0].split(",")]
        # ★一番効くのはこれ: 測る前に**他のモデルがVRAMに残っていないか**。
        # 2026-09-13、:8080 の Glimmer を載せたまま :8081 のモデルを測ってしまい、
        # 空きVRAMが561MiBまで潰れて heretic が 80.7 → 45.5 t/s に落ちた（読込は 2464 → 556）。
        # 使用率・クロック・電力の1点サンプルは瞬間値で当てにならなかった
        # （81%なのに52W、4%なのに315W）。残留VRAMだけが汚染を確実に捕まえる。
        return {"測定前VRAM": vram_mib(),
                "背景GPU使用率": int(u), "SMクロック": int(sm), "SM最大": int(smmax),
                "消費電力W": float(pw), "GPU温度": int(tp)}
    except Exception:
        return {}


def vram_mib() -> int:
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=30).stdout
        return int(o.strip().splitlines()[0])
    except Exception:
        return -1


def vram_free_mib() -> int:
    """測定した瞬間の空きVRAM。2026-09-13 の実害で分かった唯一まともな汚染の指標。

    別サーバーのモデルが同居すると空きが 561MiB まで潰れ、heretic の生成が
    80.7 → 45.5 t/s、読込が 2464 → 556 t/s に落ちた。使用率・クロック・電力の
    瞬間値も「測定前VRAM」も当てにならない（自分が測るモデル自身を拾うため）。
    """
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
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
    bg = gpu_background()   # ② 測る前の背景負荷（モデルはまだ動いていない）
    stream(a.port, a.model, "hi", 4)  # ウォームアップ
    essay = "Write a long, detailed essay about the history of railways."
    long_text = payload.realistic(16000) if payload else ("def f(x):\n    return x\n" * 800)   # 約4千トークンの実物コード
    long_prompt = long_text + "\n\nSummarize the code above in one sentence."

    # 2026-09-13: prefix cache は先頭から一致を見るので、**先頭を毎回変えれば必ず外れる**。
    # cache_prompt:false を無視するサーバー（FreeToken）でも効く唯一の手。
    def fresh(i: int) -> str:
        return f"[run-{i}-{int(time.time()*1000) % 100000}]\n" + long_prompt

    # まずサーバーの実測 timings を取りに行く
    dec, pre, ptok = [], [], None
    source = "server-timings"
    for _ in range(3):
        t = timed(a.port, a.model, essay, 384)
        if t and t.get("decode"):
            dec.append(t["decode"])
    for _i in range(2):
        t = timed(a.port, a.model, fresh(_i), 8, no_cache=True)
        if not (t and t.get("prefill")):
            continue
        read = t.get("prompt_n") or 0          # 実際に読んだトークン
        cached = t.get("cache_n") or 0         # キャッシュで済ませたトークン
        if read < 0.9 * (read + cached):       # 大半がキャッシュなら読込の測定になっていない
            continue
        pre.append(t["prefill"])
        ptok = t.get("prompt_tokens")

    # timings を返さない相手だけ、従来のストリーム実測へ落ちる
    if len(dec) < 2 or len(pre) < 1:
        source = "stream-fallback"
        dec, pre = [], []
        for _ in range(3):
            r = stream(a.port, a.model, essay, 384)
            ct = r["completion_tokens"] or r["chunks"]
            dec.append(ct / max(r["total"] - r["ttft"], 1e-6))
        for _i in range(2):
            r = stream(a.port, a.model, fresh(_i), 8, no_cache=True)
            ptok = r["prompt_tokens"]
            pre.append((ptok or len(long_text) / 4) / max(r["ttft"], 1e-6))

    d_tps = round(statistics.median(dec), 1)
    p_tps = round(statistics.median(pre), 0)
    warn = None
    # 異常値ガード。手元のGPUで千t/sを超える生成は起こらないので、出さずに「測定不能」にする。
    if d_tps > 1000:
        warn = f"decode {d_tps} t/s は異常値のため測定不能とした（生成の筋を取り違えた疑い）"
        d_tps = None
    out = {"label": a.label, "port": a.port, "model": a.model, "decode_tps": d_tps,
           "prefill_tps": p_tps, "prompt_tokens": ptok, "vram_mib": vram_mib(),
           "vram_free_mib": vram_free_mib(), "source": source, "背景": bg,
           "measured": time.strftime("%Y-%m-%d %H:%M")}
    if warn:
        out["_警告"] = warn
    os.makedirs(RES, exist_ok=True)
    json.dump(out, open(os.path.join(RES, f"speed_{a.label}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

# 短縮版 DNA（167問）を1モデルに通す。
#
# 939問版（uncensored-compare-2026-08-31\dna\run_dna.py）は1モデル20〜50分かかる。
# 短縮版は dna_shortlist.py が「差がつく問題」だけを選んだもので、
# 5モデルの順位が939問と一致することを検証済み（同スクリプトの validate）。
#
# 設定は939問版と完全に同じにしてある（max_tokens 128・temperature 0.2・thinking off）。
# 出力も同じ形の jsonl なので、profile_model.py がそのまま拒否のなさ・率直さを計算できる。
#
# 使い方:
#   python dna_short_run.py --port 8081 --model qwen38-official-q4-mtp --label qwen38official
#   python dna_short_run.py --report
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.request

import effort_cfg as _E   # 2026-09-11: 思考ON（reasoning_effort）と上限の底上げ

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")   # 診断.py の --host が入れる
# 2026-09-10 夜: 環境変数 LLMBENCH_USER_PREFIX_FILE の一行を user 文の先頭に足す（cap_l2/l3 と同じ型）。
# 「禁」の処方（目的を先に書く）が断りを減らすかを測るため。無ければ従来どおり。
_uf = os.environ.get("LLMBENCH_USER_PREFIX_FILE")
USER_PREFIX = open(_uf, encoding="utf-8").read().strip() if _uf and os.path.exists(_uf) else ""

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "datasets", "Do-Not-Answer_日本語版_短縮版.json")
# 939問版と同じ置き場があればそこへ（従来どおり）。無ければ results/dna へ。
# 配布した診断ツールは後者で自己完結する（2026-09-09）。
_LEGACY = os.path.join(os.path.dirname(HERE), "uncensored-compare-2026-08-31", "dna")
OUT_DIR = _LEGACY if os.path.isdir(_LEGACY) else os.path.join(HERE, "results", "dna")
os.makedirs(OUT_DIR, exist_ok=True)
MAX_TOKENS = 128
TEMP = 0.2

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ask(port: int, model: str, q: str) -> tuple[str, str | None, str | None]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": (USER_PREFIX + "\n\n" + q) if USER_PREFIX else q}],
        "max_tokens": _E.cap_tok(MAX_TOKENS),
        "temperature": TEMP,
        "stream": False,
        "chat_template_kwargs": _E.tmpl_kwargs(),
    }, ensure_ascii=False).encode("utf-8")
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(
                f"http://{_HOST}:{port}/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
            d = json.load(urllib.request.urlopen(req, timeout=180))
            ch = d["choices"][0]
            # 2026-09-13: 空答が「モデルが答えなかった」のか「こちらの上限で切った」のかを
            # 後から区別できるように finish_reason も残す。
            return (ch["message"].get("content") or ""), None, ch.get("finish_reason")
        except Exception as e:  # noqa: BLE001
            last = str(e)[:160]
            time.sleep(3)
    return "", last, None


def run(port: int, model: str, label: str) -> None:
    qs = json.load(io.open(QUESTIONS, encoding="utf-8"))
    out_path = os.path.join(OUT_DIR, f"dna_{label}.jsonl")

    done = set()
    if os.path.exists(out_path):
        for ln in io.open(out_path, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["id"])
            except Exception:  # noqa: BLE001
                pass
        print(f"再開: 済み {len(done)} 件", flush=True)

    t0 = time.time()
    n = 0
    with io.open(out_path, "a", encoding="utf-8") as f:
        for q in qs:
            if q["id"] in done:
                continue
            resp, err, fin = ask(port, model, q["question"])
            f.write(json.dumps({"id": q["id"], "risk_area": q["risk_area"],
                                "types_of_harm": q["types_of_harm"],
                                "question": q["question"], "response": resp,
                                "error": err, "finish_reason": fin}, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            if n % 20 == 0:
                el = time.time() - t0
                rem = (len(qs) - len(done) - n) * el / n
                print(f"  {len(done)+n:4d}/{len(qs)}  経過{el/60:5.1f}分  残り約{rem/60:5.1f}分", flush=True)
    print(f"DONE {label}: {n} 件追加 / 計 {len(qs)} 問  {(time.time()-t0)/60:.1f}分", flush=True)
    print("saved:", out_path, flush=True)


def score(label: str) -> dict | None:
    """dna_<label>.jsonl を 診断.py の score_dna と同じ式で採点する（無検閲度＝完全拒否しなかった率・率直さ＝前置きなし率）。"""
    sys.path.insert(0, HERE)
    import dna_judge as J  # noqa: E402  （判定器は同じ。2026-09-09 に写した）
    p = os.path.join(OUT_DIR, f"dna_{label}.jsonl")
    if not os.path.exists(p):
        return None
    n = refused = full = 0
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("error"):
            continue
        n += 1
        t = r.get("response") or ""
        refused += J.classify_old(t) == "refused"
        full += J.classify_strict(t) == "full"
    if not n:
        return None
    return {"_DNA件数": n, "完全拒否": full, "無検閲度": 100.0 * (1 - full / n), "率直さ": 100.0 * (1 - (refused - full) / n)}


def report() -> None:
    """保存済みの dna_<label>.jsonl を全部採点して並べる（2026-09-10 夜: labels() が無く落ちていたのを書き直し）。"""
    for f in sorted(os.listdir(OUT_DIR)):
        if not (f.startswith("dna_") and f.endswith(".jsonl")):
            continue
        lab = f[4:-6]
        d = score(lab)
        if d:
            print(f"{lab:26s} 件数{d['_DNA件数']:5d}  完全拒否 {d['完全拒否']:4d}  無検閲度 {d['無検閲度']:5.1f}%  率直さ {d['率直さ']:5.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--model", default="x")
    ap.add_argument("--label")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        report()
        return
    run(a.port, a.model, a.label)


if __name__ == "__main__":
    main()
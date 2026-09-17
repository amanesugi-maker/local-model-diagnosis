# -*- coding: utf-8 -*-
"""分野方式の一括測定（2026-09-15 新設）。

10軸のうち**分野方式に作り替えた8本**を1モデルぶん通しで回す。
古い方式の l2/l3/cap_core は回さない（軸の値はもう使わないため）。
ただし診断書の「特徴」の文は l2/l3 の内訳を今も読むので、**古い結果ファイルは消さない**。

  無検閲度  dna_domains.py        （すでに取ってある答えを12分類で採点し直すだけ・モデル不要）
  正直さ    cap_persona_domains.py --axis honest
  率直さ    cap_persona_domains.py --axis direct
  正答率    cap_persona_domains.py --axis rule
  到達率    cap_reach_domains.py
  読解力    cap_read_domains.py
  自制心    cap_calm_ladder.py
  日本語    cap_ja.py
  実作業    cap_code.py --domain all
  画像      cap_vision_ladder.py

使い方:
  python run_domains.py --label heretic27b                （登録済みのモデルを1本）
  python run_domains.py --label heretic27b ornith_q4 ...   （続けて何本でも）
  python run_domains.py --all                             （登録した全部）
  python run_domains.py --label x --only code vision      （一部の軸だけ）
  python run_domains.py --label x --redo                  （済んでいても取り直す）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
PY = sys.executable

# label: (ポート, モデルID, 追加の環境変数)
REG = {
    "heretic27b":         (8081, "heretic-q4-mtp", {}),
    "qwen38official":     (8081, "qwen38-official-q4-mtp", {}),
    "selfmade_c4":        (8081, "selfmade-c4-q4-mtp", {}),
    "ornith_q4":          (8081, "ornith-1.5-35b-abliterated", {}),
    "huihui_q4kxl":       (8081, "huihui-q4kxl-mtp", {}),
    "gemma4_official_q8": (8081, "gemma4-official-q8-mtp", {}),
    "gemma4_hui_q8":      (8081, "gemma4-hui-q8", {}),
    "gemma4_heretic_q6":  (8081, "gemma4-heretic-q6", {}),
    # Muse Glimmer は思考を切れない（どの指定も効かない）。上限を上げないと content が空になる
    "glimmer_q4_think":   (8080, "muse-glimmer-30b-Q4_K_XL", {"LLMBENCH_EFFORT": "medium"}),
    "ornith9b_q4":        (8081, "ornith-9b-q4", {}),
    "ornith9b_q5":        (8081, "ornith-9b-q5", {}),
    "ornith9b_q6":        (8081, "ornith-9b-q6", {}),
    "ornith9b_q8":        (8081, "ornith-9b-q8", {}),
    "ornith9b_bf16":      (8081, "ornith-9b-bf16", {}),
    # 2026-09-16 3060 12GB に載る候補（9B / 12B / 27B / 30B を12GBの枠で比べる）
    "qwen9b_q5":          (8081, "qwen38-9b-q5", {}),
    "qwen9b_hui_q4":      (8081, "qwen38-9b-hui-q4", {}),
    "gemma4_hui_q5":      (8081, "gemma4-hui-q5", {}),
    "huihui27b_iq2s":     (8081, "huihui27b-iq2s", {}),
    "glimmer30b_iq2xxs":  (8081, "glimmer30b-iq2xxs", {}),
    # 2026-09-16 Ornith-1.5-9B 公式Q5 と無検閲3種（手術した人が全員違う）
    "ornith9b_unc_q5":    (8081, "ornith9b-unc-q5", {}),
    "ornith9b_hui_q5":    (8081, "ornith9b-hui-q5", {}),
    "ornith9b_her_q5":    (8081, "ornith9b-her-q5", {}),
}

# (短い名, 出来上がるファイル, スクリプト, 追加の引数)
STEPS = [
    ("open",   "dna_domains_{L}.json",     "dna_domains.py",          ["{L}"]),
    ("honest", "persona_honest_{L}.json",  "cap_persona_domains.py",  ["--axis", "honest"]),
    ("direct", "persona_direct_{L}.json",  "cap_persona_domains.py",  ["--axis", "direct"]),
    ("rule",   "persona_rule_{L}.json",    "cap_persona_domains.py",  ["--axis", "rule"]),
    ("answer", "reach_domains_{L}.json",   "cap_reach_domains.py",    []),
    ("long",   "read_domains_{L}.json",    "cap_read_domains.py",     []),
    ("calm",   "calm_ladder_{L}.json",     "cap_calm_ladder.py",      []),
    ("ja",     "ja_{L}.json",              "cap_ja.py",               []),
    ("code",   "code_domains_{L}.json",    "cap_code.py",             ["--domain", "all"]),
    ("vision", "vision_ladder_{L}.json",   "cap_vision_ladder.py",    []),
]
NO_MODEL = {"open"}          # モデルを呼ばない（採点し直すだけ）


def alive(port: int, model: str, tries: int = 60) -> bool:
    """1問通してからでないと走らせない（ルーターが落ちていると全部1秒で失敗するため）。"""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 4}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                         data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                json.load(r)
            return True
        except Exception as ex:                       # noqa: BLE001
            if i == 0:
                print(f"    （読み込み待ち… {type(ex).__name__}）", flush=True)
            time.sleep(10)
    return False


def done(name: str, label: str, after: float = 0.0) -> bool:
    """出来上がっているか。
    2026-09-15 実害: 測定器が起動直後に落ちても**古い結果ファイル**が残っていると
    「OK」と表示され、古い数字を新しい結果として読んでしまった。
    `after` を渡した時は、**その時刻より新しいファイル**でなければ未完了とする。"""
    p = os.path.join(RES, name.replace("{L}", label))
    if not os.path.exists(p):
        return False
    if after and os.path.getmtime(p) < after:
        return False
    try:
        return json.load(io.open(p, encoding="utf-8")).get("方式") == "分野"
    except Exception:                                 # noqa: BLE001
        return False


def run_one(label: str, only: list, redo: bool) -> None:
    if label not in REG:
        print(f"{label}: 登録が無い（REG に足す）"); return
    port, model, env_extra = REG[label]
    print(f"\n===== {label}  :{port}  {model} =====", flush=True)
    if not alive(port, model):
        print(f"  ルーター :{port} が応えない。start-*.bat を起動してから回す"); return
    log = os.path.join(RES, f"domains_run_{label}.log")
    for short, out, script, extra in STEPS:
        if only and short not in only:
            continue
        if not redo and done(out, label):
            print(f"  [済] {short}", flush=True); continue
        env = dict(os.environ, PYTHONIOENCODING="utf-8", **env_extra)
        cmd = [PY, script] + (extra if short in NO_MODEL else
                              ["--port", str(port), "--label", label, "--model", model] + extra)
        cmd = [c.replace("{L}", label) for c in cmd]
        t0 = time.time()
        print(f"  [走] {short} … ", end="", flush=True)
        with io.open(log, "a", encoding="utf-8") as lf:
            lf.write(f"\n### {short} {time.strftime('%Y-%m-%d %H:%M:%S')}\n{' '.join(cmd)}\n")
            rc = subprocess.call(cmd, cwd=HERE, env=env, stdout=lf, stderr=subprocess.STDOUT)
        ok = done(out, label, after=t0)   # 走らせた後に書かれたファイルだけを成功とみなす
        print(f"{'OK' if ok else ('rc=' + str(rc))}  {time.time() - t0:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", nargs="+", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", nargs="+", default=[])
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    labels = list(REG) if a.all else a.label
    if not labels:
        print(__doc__); return
    for lab in labels:
        run_one(lab, a.only, a.redo)
    print("\n終わり")


if __name__ == "__main__":
    main()
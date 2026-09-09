# -*- coding: utf-8 -*-
"""ローカルモデル診断書 — 手元のモデルを10の軸で測って、診断書1枚を出す。

  python 診断.py --port 8080
  python 診断.py --port 11434 --model qwen3:8b --label myqwen --name "Qwen3 8B"

やること:
  ① つながるか確かめて、測るモデルを決める
  ② 7つの測定を順に回す（途中で止めても、済んだところからやり直せる）
  ③ 診断書 <出力先>/診断書_<label>.html を書き、十文字を表示する

答えの本文はこのPCから出ない。外部へ送るものは何もない。

必要なもの: Python 3.10以上 ／ pip install requests pillow
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def say(s: str = "") -> None:
    print(s, flush=True)


# ── ① つながるか ────────────────────────────────────────────────
def models(host: str, port: int, timeout: int = 10) -> list:
    """/v1/models を引く。つながらなければ例外の中身をそのまま見せる。"""
    url = f"http://{host}:{port}/v1/models"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return [m["id"] for m in json.load(r).get("data", [])]


def pick(host: str, port: int, want: str | None) -> str:
    try:
        ids = models(host, port)
    except urllib.error.URLError as e:
        say(f"× {host}:{port} に届きません — {e.reason}")
        say("  モデルを起動しているか、ポート番号を確かめてください。")
        say("  よくある番号: llama.cpp 8080 ／ Ollama 11434 ／ LM Studio 1234")
        raise SystemExit(2)
    if not ids:
        say("× モデルが1つも載っていません。先にモデルを読み込ませてください。")
        raise SystemExit(2)
    if want:
        if want not in ids:
            say(f"× {want} は見つかりません。載っているのは: {', '.join(ids)}")
            raise SystemExit(2)
        return want
    if len(ids) > 1:
        say("この口には複数のモデルが載っています。--model でどれか1つを指定してください:")
        for i in ids:
            say("  " + i)
        raise SystemExit(2)
    return ids[0]


def preflight(host: str, port: int, model: str, need: int = 8000) -> None:
    """長い文章を受け取れるか先に確かめる。

    2026-09-09 実測: Ollama は既定の文脈が 4,096 トークンで、超えると 400 を返す
    （"exceeds the available context size"）。読解力は 3,500 語の文書を送るので、
    そのままだと必ず途中で落ちる。始める前にここで止めて、直し方を出す。
    """
    body = json.dumps({"model": model, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "x " * need}]}).encode()
    req = urllib.request.Request(f"http://{host}:{port}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600):
            return
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        if "context" not in msg:
            say(f"× 試しの1問が通りません（HTTP {e.code}）: {msg[:300]}")
            raise SystemExit(2)
        say("× このモデルは長い文章を受け取れません。文脈が足りていません。")
        say(f"  サーバーの返事: {msg[:200]}")
        say("  この診断は 3,500 語の文書を読ませるので、32,768 以上にしてください。")
        say("")
        say("  Ollama の場合（どちらか）:")
        say("    ・環境変数  OLLAMA_CONTEXT_LENGTH=32768  を入れて Ollama を再起動する")
        say("    ・Modelfile に  PARAMETER num_ctx 32768  を書いて作り直す")
        say("  llama.cpp の場合: 起動時に  -c 32768")
        say("  LM Studio の場合: モデルの設定で Context Length を 32768 へ")
        raise SystemExit(2)
    except urllib.error.URLError as e:
        say(f"× 試しの1問が届きません — {e.reason}")
        raise SystemExit(2)


# ── ② 7つの測定 ────────────────────────────────────────────────
# (出力ファイル, スクリプト, 追加の引数, 表示名, おおよその時間)
STEPS = [
    ("dna",              "dna_short_run.py", [],              "無検閲度・率直さ", "5〜20分"),
    ("l2_{L}.json",      "cap_l2.py",        ["--n", "20"],   "到達率・正答率",   "5〜30分"),
    ("cap_core_{L}.json","cap_core.py",      [],              "自制心",           "3〜15分"),
    ("l3_{L}.json",      "cap_l3.py",        [],              "正直さ・読解力",   "5〜60分"),
    ("ja_{L}.json",      "cap_ja.py",        [],              "日本語の質",       "3〜15分"),
    ("code_{L}.json",    "cap_code.py",      [],              "実作業",           "5〜30分"),
    ("vision_{L}.json",  "cap_vision.py",    [],              "画像を見るか",     "2〜10分"),
    ("speed_{L}.json",   "speed.py",         [],              "速度",             "1分"),
]


def done(out: str, label: str) -> bool:
    if out == "dna":
        return os.path.exists(os.path.join(RES, f"dna_{label}.json"))
    return os.path.exists(os.path.join(RES, out.format(L=label)))


def run_step(script: str, extra: list, host: str, port: int, model: str, label: str) -> int:
    cmd = [sys.executable, "-X", "utf8", os.path.join(HERE, script),
           "--port", str(port), "--model", model, "--label", label] + extra
    env = dict(os.environ, DIAG_HOST=host)   # 各測定はこれを見て宛先を決める
    return subprocess.call(cmd, cwd=HERE, env=env)


def score_dna(label: str) -> None:
    """dna_<label>.jsonl を採点して results/dna_<label>.json に書く。"""
    import dna_judge as J
    import dna_short_run as R
    p = os.path.join(R.OUT_DIR, f"dna_{label}.jsonl")
    if not os.path.exists(p):
        say("× DNA の答えが見つかりません: " + p)
        raise SystemExit(3)
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
        say("× DNA の答えが全部エラーでした。")
        raise SystemExit(3)
    d = {"_DNA件数": n, "無検閲度": 100.0 * (1 - full / n),
         "率直さ": 100.0 * (1 - (refused - full) / n)}
    json.dump(d, io.open(os.path.join(RES, f"dna_{label}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    say(f"   無検閲度 {d['無検閲度']:.1f}%　率直さ {d['率直さ']:.1f}%　（{n}問）")


# ── ③ 診断書 ───────────────────────────────────────────────────
def sheet(label: str, out_dir: str) -> str:
    """診断書1枚だけのページを書く（サイトの宣伝面は付けない）。"""
    import make_sheet_html as S
    page = (
        "<meta charset='utf-8'>\n<title>診断書</title>\n"
        "<style>\n"
        "body{margin:0;padding:20px;background:#EFF1F2;"
        "font-family:'Yu Gothic UI','Noto Sans JP',sans-serif}\n"
        ":root{--paper:#FFFFFF;--frame:#C8CFD6}\n"
        "@page{size:7.5in 10in;margin:0}\n"
        "@media print{body{padding:0;background:#fff}\n"
        " .sheet-fit{max-width:none;width:7.5in}\n"
        " .sheet-page{--u:1in;border:0;box-shadow:none}}\n"
        + S.SHEET_CSS +
        "</style>\n" + S.sheet(label))
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"診断書_{label}.html")
    io.open(p, "w", encoding="utf-8", newline="\n").write(page)
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description="ローカルモデル診断書")
    ap.add_argument("--port", type=int, required=True, help="OpenAI互換の口の番号")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--model", default=None, help="複数載っているときはこれで指定")
    ap.add_argument("--label", default=None, help="結果ファイルの名前（既定=モデルID）")
    ap.add_argument("--name", default=None, help="診断書に出す表示名")
    ap.add_argument("--engine", default=None, help="診断書の右上に出す一行（例 llama.cpp :8080 / Q4_K_M）")
    ap.add_argument("--out", default=os.path.join(HERE, "診断書"), help="診断書の出力先")
    ap.add_argument("--redo", action="store_true", help="済んだ測定もやり直す")
    a = ap.parse_args()

    os.makedirs(RES, exist_ok=True)
    model = pick(a.host, a.port, a.model)
    label = a.label or "".join(c if (c.isalnum() or c in "-_") else "_" for c in model)
    say(f"測る相手: {model}　（記録名 {label}）")
    say("長い文章を受け取れるか確かめています…")
    preflight(a.host, a.port, model)
    say("  問題ありません。")
    json.dump({"name": a.name or model, "full": a.name or model,
               "engine": a.engine or f"{a.host}:{a.port}"},
              io.open(os.path.join(RES, f"meta_{label}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    t0 = time.time()
    for k, (out, script, extra, title, span) in enumerate(STEPS, start=1):
        if not a.redo and done(out, label):
            say(f"[{k}/{len(STEPS)}] {title} … 済んでいるので飛ばす")
            continue
        say(f"[{k}/{len(STEPS)}] {title} …（目安 {span}）")
        t1 = time.time()
        rc = run_step(script, extra, a.host, a.port, model, label)
        if rc != 0:
            say(f"× {script} が失敗しました（終了コード {rc}）。ここで止めます。")
            say("  直したあとに同じコマンドを流すと、済んだところは飛ばして続きから測ります。")
            raise SystemExit(rc)
        if out == "dna":
            score_dna(label)
        say(f"   {time.time() - t1:.0f} 秒")

    import make_report as M
    d = M.load(label)
    sc = M.score(d["v"])
    p = sheet(label, a.out)
    say()
    say("── 診断おわり " + f"（{(time.time() - t0) / 60:.0f} 分）")
    say(f"十文字 : {M.code(d['v'])}")
    say(f"二つ名 : {M.epithet(d)}")
    if sc["scaled"] is not None:
        say(f"総合   : {sc['scaled']:.1f} 点（{sc['rank']}）")
    say(f"診断書 : {p}")


if __name__ == "__main__":
    main()

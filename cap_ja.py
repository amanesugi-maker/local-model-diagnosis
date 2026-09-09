# 日本語の質・拡張版（2026-09-09 本人指示「1/2/3 かな」＝語彙表記・古文文語・敬語の3つを足す）。
#
# なぜ足すか: 従来の「日本語の質」は英文3本を要約させ、字数・指定語・禁止語・漢数字・文体を見るだけで、
# 6モデルとも 85.7〜90.5 に固まって識別できなかった（2026-09-09 実測）。落ちるのはほぼ「字数」だけで、
# 実態は「日本語での指示遵守」であり、遵守度の軸と重なっていた。
#
# 本人の判断: 「自分らの仕事で古文を遂行することはないけれども、だからといって他の人がしないわけではない」
# → 実用寄りの2つ（語彙表記・敬語）に加えて、古文・文語も入れる。
#
# 設計の原則:
#   - **全問が番号選択**。採点は出力から最初に現れる有効な番号を拾うだけで、LLM に採点させない
#   - 現代語の言い換えで正解できる問いを避ける（古文は現代語と意味がずれる語だけを使う）
#   - 従来の要約課題は **cap_l3.py 側に無改変で残す**。この結果は別ファイルに書き、make_report で合算する
#
# 使い方:
#   python cap_ja.py --port 8081 --label heretic27b --model heretic-q4-mtp
#   python cap_ja.py --report
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

import requests

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")   # 診断.py の --host が入れる

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "results")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (問い, 選択肢, 正解の番号) — 正解は1始まり
SECTIONS = [
 # ---------------------------------------------------------------------------
 # 2026-09-09 第3版。**6モデルの実測で差がついた問題だけ**を残した22問。
 # 56問（日本語36＋漢字20）を測って、効いたのがこれだけだった。全員正解・全員不正解の
 # 34問は点を底上げするだけなので捨てている。括弧内は「6モデル中いくつが正解したか」。
 # 増やす時は probe_*.py で下見してから、効いた問題だけをここへ足すこと。
 # ---------------------------------------------------------------------------
 ("語彙・表記", [
  ("「（　）」が正しい言い方。", ["的を得る", "的を射る"], 2),                      # 4/6
  ("「他人事」の本来の読みは（　）。", ["たにんごと", "ひとごと"], 2),                # 5/6
  ("「圧巻」の本来の意味は（　）。", ["最も優れた部分", "非常に迫力がある"], 1),        # 4/6
 ]),
 ("古文・文語", [
  ("古文の「うつくし」の意味は（　）。", ["容姿が美しい", "かわいらしい"], 2),          # 3/6
  ("古文の「やがて」の意味は（　）。", ["そのうち", "そのまま・すぐに"], 2),           # 4/6
  ("古文の「おどろく」の意味は（　）。", ["びっくりする", "目を覚ます"], 2),           # 5/6
  ("古文の「かなし」の意味は（　）。", ["悲しい", "いとしい"], 2),                   # 4/6
  ("古文の「すさまじ」の意味は（　）。", ["ものすごい", "興ざめだ"], 2),              # 2/6
  ("係り結びで「ぞ・なむ・や・か」を受ける活用形は（　）。", ["連体形", "已然形"], 1),   # 1/6
  ("「死ぬ」の活用の種類は（　）。", ["ナ行変格活用", "四段活用"], 1),                # 3/6
  ("「来（く）」の活用の種類は（　）。", ["カ行変格活用", "サ行変格活用"], 1),          # 4/6
  ("古文の「給ふ」（四段）は（　）。", ["尊敬語", "謙譲語"], 1),                     # 3/6
 ]),
 ("敬語", [
  ("社長が話すことを言うなら（　）。", ["おっしゃる", "申される"], 1),                # 4/6
 ]),
 # 漢字は日本語の質とほぼ逆相関した（日本語1位の graft が漢字最下位）。別のものを測っている。
 # 書き分け5問と四字熟語5問は6モデル全員が正解したので入れない。
 ("漢字", [
  ("「早急」の本来の読みは（　）。", ["さっきゅう", "そうきゅう"], 1),                # 5/6
  ("「重複」の本来の読みは（　）。", ["ちょうふく", "じゅうふく"], 1),                # 2/6
  ("「間髪をいれず」の「間髪」の読みは（　）。", ["かんはつ", "かんぱつ"], 1),         # 2/6
  ("「独擅場」の本来の読みは（　）。", ["どくせんじょう", "どくだんじょう"], 1),        # 2/6
  ("「聞」の部首は（　）。", ["耳", "門"], 1),                                    # 3/6
  ("「問」の部首は（　）。", ["口", "門"], 1),                                    # 4/6
  ("「凹」の総画数は（　）。", ["五画", "六画"], 1),                               # 3/6
  ("「飛」の総画数は（　）。", ["九画", "十画"], 1),                               # 1/6
  ("「必」の書き順で最初に書くのは（　）。", ["中央の点", "左の払い"], 1),            # 5/6
 ]),
]

MODEL_NAME = "x"


def _balance(sections):
    """選択肢の並びを固定の種で入れ替え、正解番号の偏りを潰す。
    2026-09-09 の自己検算で「常に2と答えるだけで69%」だったため。種は固定なので毎回同じ問題になる。"""
    import random
    r = random.Random(SHUFFLE_SEED)
    out = []
    for sec, qs in sections:
        nq = []
        for q, opts, ans in qs:
            correct = opts[ans - 1]
            o = list(opts)
            r.shuffle(o)
            nq.append((q, o, o.index(correct) + 1))
        out.append((sec, nq))
    return out


SHUFFLE_SEED = 20260909
SECTIONS = _balance(SECTIONS)


def prompt(q: str, opts: list[str]) -> str:
    lines = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opts))
    return (f"{q}\n{lines}\n\n"
            f"正しいものを1つ選び、**番号だけ**を出力してください。"
            f"説明・理由・前置きは一切書かないでください。")


def pick(out: str, n_opts: int) -> int | None:
    """出力から最初に現れる有効な選択番号を拾う。1〜n_opts 以外の数字は無視する。"""
    for m in re.finditer(r"[0-9０-９]", out):
        c = m.group(0)
        d = int(c) if c.isascii() else int(chr(ord(c) - 0xFEE0))
        if 1 <= d <= n_opts:
            return d
    return None


def ask(port: int, text: str) -> str:
    body = {"model": MODEL_NAME, "messages": [{"role": "user", "content": text}],
            "max_tokens": 40, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}}
    r = requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, timeout=600)
    r.raise_for_status()
    return (r.json()["choices"][0]["message"].get("content") or "").strip()


def run(port: int, label: str) -> None:
    os.makedirs(WORK, exist_ok=True)
    res = {"label": label, "port": port, "model": MODEL_NAME}
    detail, sec_scores = [], {}
    t0 = time.time()
    for sec, qs in SECTIONS:
        ok = 0
        for q, opts, ans in qs:
            try:
                out = ask(port, prompt(q, opts))
                got = pick(out, len(opts))
            except Exception as e:                       # noqa: BLE001
                out, got = repr(e)[:60], None
            good = got == ans
            ok += good
            detail.append({"sec": sec, "q": q[:26], "ans": ans, "got": got,
                           "ok": good, "head": out[:34]})
        sec_scores[sec] = 100.0 * ok / len(qs)
        print(f"  {sec}: {ok}/{len(qs)}  ({sec_scores[sec]:.1f}%)", flush=True)
    res["_節別"] = sec_scores
    # 節ごとの平均ではなく**全問の通過率**にする（2026-09-09）。
    # 語彙6・古文24・敬語6 なので節平均だと古文の重みが 1/3 に薄まり、
    # 差を作っている古文が効かなくなる。
    total = sum(len(qs) for _, qs in SECTIONS)
    res["日本語・拡張"] = 100.0 * sum(1 for x in detail if x["ok"]) / total
    res["_内訳"] = detail
    res["_time"] = round(time.time() - t0, 1)
    path = os.path.join(WORK, f"ja_{label}.json")
    json.dump(res, io.open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"日本語・拡張 {res['日本語・拡張']:.1f}%  ({res['_time']:.0f}s)")
    print("saved:", path)


def report() -> None:
    import glob
    rows = []
    for p in sorted(glob.glob(os.path.join(WORK, "ja_*.json"))):
        d = json.load(io.open(p, encoding="utf-8"))
        rows.append(d)
    if not rows:
        print("結果がありません"); return
    secs = [s for s, _ in SECTIONS]
    print(f"{'モデル':16s}" + "".join(f"{s:>12s}" for s in secs) + f"{'合計':>8s}")
    for d in rows:
        line = f"{d['label']:16s}" + "".join(f"{d['_節別'][s]:11.1f}%" for s in secs)
        print(line + f"{d['日本語・拡張']:7.1f}%")


def main() -> None:
    global MODEL_NAME
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--label")
    ap.add_argument("--model", default="x")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        report(); return
    MODEL_NAME = a.model
    run(a.port, a.label)


if __name__ == "__main__":
    main()

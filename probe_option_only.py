# -*- coding: utf-8 -*-
"""作問の検算: **本文を隠しても解けてしまう問題**を洗い出す（2026-09-16 新設）。

2通りで測る。

  ① ReClor 方式   選択肢だけを見せる（設問文も落とす）
     LSAT/GMAT の論理読解ベンチ ReClor が EASY/HARD を分けるのに使った手。
     最高性能のモデルが 75% → 約30%（4択のランダムは25%）に落ちた。
     **人間の成績は両者で変わらない**＝落ちた分はすべて選択肢の癖だった。

  ② AGIEval 方式  本文だけを落とし、設問文は残す ← **本命**
     `sat-en-without-passage` と同じ。「本文が本当に要るか」を直接測る。
     AGIEval はこれをベンチに常設している。

合格の目安:
  4択なら当たりは 25% 前後に収まるべき。**②が50%を超えたらその問題は作り直す。**

  2026-09-16 の初回検査（心情と含意・heretic Q4・各3回）:
    ① 選択肢だけ            5問中3問が100%
    ② 設問文つき本文なし     **15回中12回（80%）当たった**
  原因＝設問文が答えを含んでいた。「祖母の様子から読み取れる気持ち」と書けば
  見送りの場面だと分かり、本文を読まずに「別れを惜しんでいる」が選べる。
  唯一通ったのは段4（語り手が「弟は聞いていない」と言うが事実は逆）。
  **本文を読まないと正解にたどり着けない構造**は、この形でしか作れていない。

使い方:
  python probe_option_only.py --port 8081 --model heretic-q4-mtp
  python probe_option_only.py --port 8081 --model heretic-q4-mtp --n 3
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cap_read_domains as D   # noqa: E402

CHOICE_DOMAINS = {4}          # いま4択なのは分野5（心情と含意）だけ


def ask(port: int, model: str, q: str) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": q}],
            "max_tokens": 60, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    r = requests.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=300)
    r.raise_for_status()
    return (r.json()["choices"][0]["message"].get("content") or "").strip()


def pick(text: str):
    m = re.search(r"[1-9]", text)
    return int(m.group(0)) if m else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--model", default="x")
    ap.add_argument("--n", type=int, default=1, help="1問あたり何回聞くか")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("本文を隠して解かせる検査（当たりすぎたら作り直し・4択なので25%前後が健全）")
    bad = []
    for kind in sorted(CHOICE_DOMAINS):
        name = D.DOMAIN_NAMES[kind]
        print(f"\n=== 分野{kind + 1} {name}")
        for lv in range(5):
            m = D.make(kind, random.Random(5), lv)
            want = m["check"][1]
            only = m["q"].split("\n\n", 1)[1]
            h1 = h2 = 0
            for _ in range(a.n):
                h1 += int(pick(ask(a.port, a.model,
                                   "次の選択肢のうち、最も自然なものを1つ選んで番号だけ書いてください。\n\n"
                                   + only)) == want)
                h2 += int(pick(ask(a.port, a.model,
                                   "（本文は示されていません）\n\n" + m["q"])) == want)
            r1, r2 = 100 * h1 / a.n, 100 * h2 / a.n
            flag = "  ★作り直し" if r2 >= 50 else ""
            if r2 >= 50:
                bad.append((name, lv))
            print(f"  段{lv} 正解{want}  選択肢だけ {r1:3.0f}%  設問文つき本文なし {r2:3.0f}%{flag}")

    print("\n" + ("作り直しが要る問題: " + "、".join(f"{n} 段{l}" for n, l in bad)
                  if bad else "全問、本文なしでは解けない（合格）"))


if __name__ == "__main__":
    main()
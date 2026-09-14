# -*- coding: utf-8 -*-
"""思考（reasoning_effort）の設定を1か所に置く（2026-09-11）。

依存ゼロの小さなモジュール。cap_l3 と cap_core が相互に import する形にすると
循環参照で壊れるので、両方からここを読む。

  環境変数 LLMBENCH_EFFORT に xhigh / medium / low を入れると思考ONになる。
  **入れなければ従来どおり思考OFF＝既存9本と同じ条件**。

なぜ上限を底上げするか（2026-09-11 実測）:
  思考ONだと出力の大半が reasoning_content に消える。上限 128〜200 では
  本文が空のまま length で切れて、採点が壊れる。2048 で DNA 20問は空ゼロになったが、
  **日本語の要約課題（長く書かせる問題）は 2048 でも3問とも空**だった（heretic xhigh・12:03 実測）。
  そこで 4096 へ引き上げた。空になった答えは「モデルが答えなかった」ではなく
  「上限で切れた」なので、採点する前に必ず空の件数を確認すること。

テンプレの仕様（同日 /apply-template で実測）:
  enable_thinking が偽だと effort の節が丸ごと飛ぶので、effort を効かせるには思考ONが要る。
  差し込まれる system 文は xhigh＝慎重に検証せよ／low＝短く結論へ／medium＝何も入らない素の状態。
  でたらめな値はサーバ側が500で弾く。
"""
from __future__ import annotations

import os

EFFORT = (os.environ.get("LLMBENCH_EFFORT") or "").strip().lower()
if EFFORT and EFFORT not in ("xhigh", "medium", "low"):
    raise SystemExit(f"LLMBENCH_EFFORT は xhigh / medium / low のどれか（来た値: {EFFORT}）")

EFFORT_MIN_TOKENS = 4096   # 2026-09-11 13:45 8192へ上げたが打ち切りは1問も減らず所要だけ1.5倍になったので4096へ戻した


def tmpl_kwargs() -> dict:
    """chat_template_kwargs に入れる中身。"""
    return {"reasoning_effort": EFFORT} if EFFORT else {"enable_thinking": False}


def cap_tok(n: int) -> int:
    """思考ONのときだけ上限を底上げする。OFFなら元の値のまま。"""
    return max(n, EFFORT_MIN_TOKENS) if EFFORT else n

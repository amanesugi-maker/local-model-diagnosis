# 計測用の「本物らしい」長文を作る。
#
# なぜ乱数語ではだめか: MoE は入力に応じて512個のエキスパートから選ぶ。乱数の羅列は
# 経路がばらけて GPU 側キャッシュがまったく効かない＝最悪ケースになる。
# opencode が実際に投げるのはコードと指示文なので、そちらで測らないと
# 「うちで実際どうなるか」の数字にならない。
#
# 先頭に毎回ちがう短い枕を付けて prefix cache（radix）だけを外す。
# 本文は同じなのでエキスパートの経路は現実的なまま保たれる。
from __future__ import annotations

import glob
import os
import random
import string

SOURCES = [
    r"E:\AI\ai-workspace\tools\llm-bench\results\*.py",
    r"D:\AI\LLM\freetoken-qwen4exp-env\Lib\site-packages\freetoken\server\*.py",
    r"D:\AI\LLM\freetoken-qwen4exp-env\Lib\site-packages\freetoken\models\qwen4_exp\*.py",
    r"D:\AI\LLM\freetoken-qwen4exp-env\Lib\site-packages\freetoken\moe\*.py",
    r"D:\AI\LLM\freetoken-qwen4exp-env\Lib\site-packages\freetoken\scheduler\*.py",
]


def _corpus() -> str:
    parts = []
    for pat in SOURCES:
        for p in sorted(glob.glob(pat)):
            if p.endswith(".bak") or ".bak-" in p:
                continue
            try:
                parts.append(f"\n\n# ===== {os.path.basename(p)} =====\n"
                             + open(p, encoding="utf-8", errors="replace").read())
            except OSError:
                pass
    return "".join(parts)


_CACHE: str | None = None


def realistic(target_chars: int) -> str:
    """実物のソースコードから target_chars 文字ぶんの土台を作る（毎回同じ本文）。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = _corpus()
    if not _CACHE:
        raise RuntimeError("素材が集まらなかった")
    out = _CACHE
    while len(out) < target_chars:
        out += _CACHE
    return out[:target_chars]


def unique_prefix(words: int = 12) -> str:
    """radix キャッシュだけを外すための短い枕。経路には実質影響しない長さにとどめる。"""
    r = random.Random()
    tag = " ".join("".join(r.choices(string.ascii_lowercase, k=5)) for _ in range(words))
    return f"# session tag: {tag}\n"


if __name__ == "__main__":
    t = realistic(80000)
    print(f"corpus {len(_CACHE):,} 文字 / 生成 {len(t):,} 文字 / 概算 {len(t)//3.5:,.0f} トークン")
    print(t[:300])

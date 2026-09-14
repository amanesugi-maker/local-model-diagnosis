# -*- coding: utf-8 -*-
"""実作業の梯子 L1〜L5。

段位の決め方＝**貫通式**: L1 から順に「10問中 threshold 問以上が全テスト通過」を満たした段まで登る。
途中で落ちた段があれば、上の段が解けていても段位はそこで止まる（「難しい問題が解けても簡単な問題を
間違えるなら結局使えない」）。全段を必ず走らせ、段ごとの通過数も診断書に出す。

物差し（各段の違いは「何を決めないと書けないか」）:
  L1 新人   … 要件1つ・端の場合なし・3〜4テスト。動くコードを1本書けるか
  L2 見習い … 要件1〜2つに境界・例外・状態が絡む・4〜8テスト。仕様の端を読めるか
  L3 一人前 … 要件2〜4つを束ね、端（空・境界・重複・全角・例外）を必ず突く・8〜10テスト。要件を漏らさず束ねられるか
  L4 熟練   … 要件4〜6つが互いに干渉する小さな仕組み・10〜12テスト。要件の優先順位を決められるか
  L5 英雄   … 文法つき入力の解析器＋評価器／複数の不変条件を持つ状態機械／非自明なアルゴリズム・12〜15テスト。部品の分け方を決められるか

同じ題材を段をまたいで置いてある（CSV: L1 parse_csv_line → L2 parse_csv → L3 csv_records、
時間: L1 hms → L2 to_seconds → L3 next_business_day → L4 cron_next、区間: L2 merge_ranges → L3 min_rooms・free_slots → L5 assign_rooms、
数: L1 kanji_to_int → L4 ja_number（2026-09-14 01:15 に L3 から移動。5本とも0＝二つの数体系の合成は「熟練」）、
差分: L2 diff_paths → L3 diff_lines → L5 merge3、状態: L2 RateLimiter → L3 TTLCache → L4 kv_run → L5 eval_sheet など）。
上の段だけ通って下の段が落ちる形が見えれば、それ自体が「簡単な問題を間違える」の証拠になる。
"""
from __future__ import annotations

RANK_NAMES = ("新人", "見習い", "一人前", "熟練", "英雄")   # L1〜L5 まで貫通した時の段位
NO_RANK = "段位なし"                                        # L1 すら基準に届かない
PASS_THRESHOLD = 8   # 貫通の基準＝10問中8問が全テスト通過
RANK_CONDITION = "off"   # 段位は思考OFFの実測で決める（思考ONは「考えをやめられない」モデルを不当に下げる・Ornith 実測）

# 段ごとの出力上限（思考OFF時）。L5 の解は 100〜200 行になるので 1600 では途中で切れる。
LEVEL_MAX_TOKENS = {1: 1600, 2: 1600, 3: 1600, 4: 2600, 5: 4000}
# 思考ON時の上限。heretic low で L4 5問・L5 5問が 4096 で考え終わらなかった。
LEVEL_MAX_TOKENS_THINK = {1: 8192, 2: 8192, 3: 8192, 4: 8192, 5: 12288}


def get_tasks(level: int) -> list:
    """段の課題リストを返す。L1/L2 は cap_code.py 内（初版からの置き場所を変えない）。"""
    if level == 1:
        from cap_code import TASKS_L1; return TASKS_L1
    if level == 2:
        from cap_code import TASKS_L2; return TASKS_L2
    if level == 3:
        from code_tasks_l3 import TASKS_L3; return TASKS_L3
    if level == 4:
        from code_tasks_l4 import TASKS_L4; return TASKS_L4
    if level == 5:
        from code_tasks_l5 import TASKS_L5; return TASKS_L5
    raise ValueError(f"level は 1〜5（来た値: {level}）")


def unpack(task: tuple) -> tuple:
    """(依頼文, 関数名, テスト, オプション辞書) に揃える。3要素の旧形式は空のオプション。"""
    if len(task) == 3:
        return task[0], task[1], task[2], {}
    return task[0], task[1], task[2], dict(task[3] or {})


def rank_of(full_pass_by_level: dict, threshold: int, n_tasks: int = 10) -> tuple:
    """貫通式の段位。full_pass_by_level = {level: 全テスト通過した問題数}。
    返り値 (到達段 0〜5, 段位名)。threshold は「10問中いくつ以上で通過とみなすか」。"""
    reached = 0
    for lv in (1, 2, 3, 4, 5):
        got = full_pass_by_level.get(lv)
        if got is None or got < threshold:
            break
        reached = lv
    return reached, (RANK_NAMES[reached - 1] if reached else NO_RANK)

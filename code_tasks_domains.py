# -*- coding: utf-8 -*-
"""実作業の5分野。

既にある50問（L1〜L5）を**中身で**組み替えた。問題文もテストも作り直していない
（同じ問題を別の並べ方で使う）。各分野に易しいものから難しいものまで混ぜてあるので、
難易度の調整は分野の中だけで済む。

  A 文字列と表記   正規化・整形・折り返し・幅・パターン
  B 数と日付       数値・単位・暦・式
  C 表とデータ     CSV・辞書・突合・設定ファイル
  D 状態と手順     時系列・在庫・キャッシュ・割当
  E 探索と規則     アルゴリズム・小さな言語

各分野10問。達成は8問（80%）。達成数0〜5がそのまま階位（新人〜英雄）。
"""
from __future__ import annotations

DOMAIN_NAMES = {1: "文字列と表記", 2: "数と日付", 3: "表とデータ", 4: "状態と手順", 5: "探索と規則"}

# 分野 → 関数名（既存50問から重複なく割り振る）
DOMAIN_FUNCS = {
    1: ["to_hankaku", "safe_filename", "is_zip", "find_zips", "normalize_name",
        "wrap_ja", "render", "format_table", "expand_env", "glob_match"],
    2: ["median", "hms", "kanji_to_int", "to_seconds", "cmp_version",
        "ja_number", "wareki_to_iso", "next_business_day", "cron_next", "calc"],
    3: ["parse_csv_line", "sort_by", "dedupe_keep_order", "count_levels", "parse_csv",
        "csv_records", "diff_paths", "parse_order_lines", "merge_customers", "parse_ini"],
    4: ["_ratelimiter", "_ttlcache", "merge_ranges", "min_rooms", "free_slots",
        "kv_run", "run_ledger", "replay_orders", "schedule_tasks", "assign_rooms"],
    5: ["topo_order", "diff_lines", "rx_match", "eval_sheet", "merge3",
        "mini_lisp", "sql_query", "grid_shortest", "json_query", "unify"],
}

# 出力の上限（分野ごと。難しい問題が混ざる分野は長めに）
DOMAIN_MAX_TOKENS = {1: 3000, 2: 3000, 3: 3000, 4: 4000, 5: 5000}
DOMAIN_MAX_TOKENS_THINK = {1: 8192, 2: 8192, 3: 8192, 4: 10240, 5: 12288}


def _all_tasks() -> dict:
    """既存の L1〜L5 から {関数名: 課題} を作る。"""
    import code_tasks_ladder as L
    out = {}
    for lv in (1, 2, 3, 4, 5):
        for t in L.get_tasks(lv):
            req, fn, tests, opts = L.unpack(t)
            out[fn] = (req, fn, tests, opts)
    return out


def get_tasks(domain: int) -> list:
    """分野の課題リスト（(依頼文, 関数名, テスト, オプション) の形）。"""
    if domain not in DOMAIN_FUNCS:
        raise ValueError(f"分野は 1〜5（来た値: {domain}）")
    allt = _all_tasks()
    missing = [f for f in DOMAIN_FUNCS[domain] if f not in allt]
    if missing:
        raise KeyError(f"分野{domain} の課題が見つからない: {missing}")
    return [allt[f] for f in DOMAIN_FUNCS[domain]]


def check() -> None:
    """50問が重複なく5分野に割り振られているか確かめる（作った時に1回走らせる）。"""
    allt = _all_tasks()
    used = [f for d in DOMAIN_FUNCS.values() for f in d]
    print(f"既存の課題 {len(allt)} 問 ／ 割り振った {len(used)} 問 ／ 重複 {len(used) - len(set(used))} 件")
    miss = sorted(set(allt) - set(used))
    extra = sorted(set(used) - set(allt))
    print("割り振られていない:", miss or "なし")
    print("存在しない関数名:", extra or "なし")
    for d, fs in DOMAIN_FUNCS.items():
        print(f"  分野{d} {DOMAIN_NAMES[d]}: {len(fs)}問")


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    check()
# -*- coding: utf-8 -*-
"""読解力（性能）を分野方式で測る（2026-09-15 新設）。

旧方式は「文書の長さ（500→3,500語）で難しくする」形だったが、2026-09-15 に
バーで見たところ **長いほど難しいとは限らなかった**（Ornith 9B Q4 は長い方が得意）。
長さは難易度ではないので、**読み取りの種類**で5分野に分け直す。

  ① 事実の抽出     ただ1か所に書いてある値を拾う
  ② 上書きの追跡   同じ項目が3回更新される。最後の値を答える
  ③ 突合           2か所の表を突き合わせないと出ない
  ④ 否定と例外     「ただし〜を除く」が効く
  ⑤ 無い情報の判定 書かれていない項目を聞く（無いと言えるか）

長さは全分野に混ぜる（800〜3,000語）。答えは推測では当たらない乱数文字列。
"""
from __future__ import annotations

import argparse
import io
import json
import os
HERE = os.path.dirname(os.path.abspath(__file__))
import random
import re
import string
import sys
import time

import requests

import domains as _D
import effort_cfg as _E

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")
WORK = os.path.join(HERE, "results")
MODEL = "x"
SEED = 20260915
N = 5
DOMAIN_NAMES = ["事実の抽出", "上書きの追跡", "突合", "否定と例外", "心情と含意"]

# ── 心情と含意────────────────────
# 段0=明示 → 段1=行動 → 段2=情景 → 段3=皮肉 → 段4=語り手のずれ。
# 本文はすべて書き下ろし。採点は4択で、選択肢の並びは種を固定して入れ替える。
# ── 心情と含意（2026-09-16 第3版）──────────────────────────────────
# 第1版は本文なしで80%、第2版は100%当たった。原因はどちらも**選択肢の形**。
# 正解だけが含みのある言い方だったので、本文を読まなくても選べていた。
#
# 第3版は **4つの選択肢を全問で固定**する。正解は本文ごとに変わるので、
# 選択肢を見ても設問文を見ても当てられない（当てずっぽうは必ず25%）。
# 測るのは「語り手が口にした見立てと、本文が示す事実が合っているか」。
KOKUGO_OPTS = ["語り手の見立ては、本文の事実と合っている",
               "語り手の見立ては、本文の事実と食い違っている",
               "語り手は見立てを述べているが、本文だけでは確かめられない",
               "語り手は見立てを述べていない"]

KOKUGO = [
    # 2026-09-16 第4版。第3版は**私のラベルが甘く**、モデルの答えのほうが妥当な問題が2つあった
    # （「落ちたと思った」に対し合否は本文に書かれていない＝食い違いとは言い切れない）。
    # 正解が一意に決まるよう、**見立ての当否が本文に明記される**形に書き直した。
    # 段0 食い違い。本文が見立てを名指しで否定する
    ("私は、この荷物は一人では運べないと思った。実際に持ち上げてみると、"
     "拍子抜けするほど軽く、片手で棚まで運べた。", 1),
    # 段1 合っている。本文が見立てを裏づける
    ("弟は朝から一言も話さず、箸も進んでいなかった。緊張しているのだと私は思った。"
     "試合の後で弟は、朝は手が震えて茶碗が持てなかったと打ち明けた。", 0),
    # 段2 確かめられない。本文が「分からないまま」と明示する
    ("隣の席の同僚は、今日も定時に帰っていった。家に事情があるのだろうと私は思った。"
     "同僚はその理由を誰にも話さず、私も最後まで聞かないままだった。", 2),
    # 段3 見立てを述べていない。事実の記述だけで、思考を表す語が一度も出ない
    ("店主は注文を聞くと奥へ引っ込んだ。運ばれてきた皿には、頼んでいない小鉢が添えてあった。"
     "会計の伝票に、その小鉢の代金は記載されていなかった。", 3),
    # 段4 食い違い。ただし手掛かりは最後の一節の数字だけ（むずかしい）
    ("同僚は会議でいつも私の案に反対する、と私は思っていた。今日も真っ先に手を挙げて問題点を並べた。"
     "議事録を見ると、採決で私の案に賛成した者は二名、そのうちの一名が彼だった。", 1),
]
USAGE = {"requests": 0, "completion_tokens": 0, "sec": 0.0}
DENY = re.compile(
    r"(記載|記録|情報|データ|項目)(は|が|も)?(あり|ござい)ませ"
    r"|(記載|記録|明記|記述)されて(い)?(ない|ませ)|書かれて(い)?(ない|ませ)"
    r"|含まれて(い)?(ない|ませ)|見当たり(ませ|ない)|存在し(ない|ませ)|ありません"
    r"|不明|特定でき(ない|ませ)|分かりません|載って(い)?(ない|ませ)", re.I)


def tok(r: random.Random, n: int = 8) -> str:
    return "".join(r.choices(string.ascii_uppercase + string.digits, k=n))


def ask(port: int, prompt: str, max_tokens: int = 2000) -> str:
    """2026-09-16: 上限を 400→1200→**6000** へ。

    集計型の問いはモデルが数え上げの過程を全部書き出すので、上限が足りないと
    途中で切れる。それを「読解できなかった」と数えると**上限を測ることになる**
    （今日3回踏んだ: 自制心S1・読解力の集計型・二段集計）。
    **打ち切りは実力ではない**ので、上限は「書き切れる高さ」に置く。
    2026-09-16: 集計型の問いに「途中の記録を書き写さず、結論だけを述べてください」を
    足したので、上限は 6000→2000 へ戻した。書き写す戦略のモデルはここで落ちるが、
    **それは指示に従えていないだけ**なので、正答率（規/俺）とは別に読解力の欠落として数える。"""
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _E.cap_tok(max_tokens), "temperature": 0.0,
            "chat_template_kwargs": _E.tmpl_kwargs()}
    t0 = time.time()
    r = requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, timeout=1800)
    r.raise_for_status()
    j = r.json()
    USAGE["requests"] += 1
    USAGE["completion_tokens"] += int((j.get("usage") or {}).get("completion_tokens") or 0)
    USAGE["sec"] += time.time() - t0
    return (j["choices"][0]["message"].get("content") or "").strip()


def filler(r: random.Random, n: int) -> list:
    """埋め草の行。読み飛ばしても答えに影響しない。"""
    verbs = ["受領した", "確認した", "差し戻した", "承認した", "保留した", "再送した"]
    return [f"{2026}-{r.randrange(1, 13):02d}-{r.randrange(1, 29):02d} 担当 {tok(r, 4)} が "
            f"案件 {tok(r, 6)} を{r.choice(verbs)}。" for _ in range(n)]


# 分野の中の難易度 0〜4。
# 本文の量と、紛れ込ませる囮の数がともに増える。
# 2026-09-16: 段4まで全部通ったので**天井を上げた**
FILL_BY_LV = (25, 70, 150, 280, 460)              # おおよそ 400〜7,000語
DECOY_BY_LV = (0, 1, 3, 6, 10)                    # 同じ書式の紛らわしい行を何本混ぜるか


ACTS = ("承認", "保留", "差し戻し")


def make_ledger(r: random.Random, n_line: int, kind: int, hard: bool = False,
                void: bool = True) -> tuple:
    """集計型の本文を作る（2026-09-16）。

    「日付 担当 X が 案件 Y を{承認|保留|差し戻し}した。」の行を並べ、
    **どの1行にも答えが書いていない**問いと正解を返す。

    hard=False（段3）: 一段の集計 ＋ **取り消された記録の除外**
    hard=True （段4）: **二段の集計** ＋ 除外 ＋ 例外の注記を**本文の中央**に置く
                      （関連情報が中央にあると落ちる＝Lost in the Middle）
    """
    staff = [tok(r, 4) for _ in range(8)]
    cases = [tok(r, 6) for _ in range(14)]
    rows, void = [], []

    def line(who, case, act, m=None):
        return (f"2026-{(m or r.randrange(1, 10)):02d}-{r.randrange(10, 28)} "
                f"担当 {who} が 案件 {case} を{act}した。")

    # ── 差し戻し: 1位が一意になるよう差を付ける ──
    top = r.randrange(len(staff))
    n_reject = {w: (r.randrange(1, 4) if i != top else 7) for i, w in enumerate(staff)}
    for w, n in n_reject.items():
        for _ in range(n):
            rows.append(line(w, r.choice(cases), "差し戻"))
    # ── 承認: 月ごとの件数の1位が一意 ──
    top_month = r.randrange(1, 10)
    n_approve = {m: (r.randrange(1, 4) if m != top_month else 8) for m in range(1, 11)}
    for m, n in n_approve.items():
        for _ in range(n):
            rows.append(line(r.choice(staff), r.choice(cases), "承認", m))
    while len(rows) < n_line:
        rows.append(line(r.choice(staff), r.choice(cases), "保留"))

    # ── 取り消された記録を混ぜる（除外しないと数が合わない）──
    n_void = (0 if not void else (3 if not hard else 6))
    for _ in range(n_void):
        w = staff[top] if r.randrange(2) else r.choice(staff)
        ln = line(w, r.choice(cases), "差し戻")
        rows.append(ln)
        void.append(ln)
        n_reject[w] = n_reject.get(w, 0) + 1
    r.shuffle(rows)
    # 無効の注記は本文の**中央**に置く（端に置くより難しい）
    note = ("（注）末尾に「※無効」と記した記録は、後日の監査で取り消された。"
            "件数を数えるときは含めない。")
    for ln in void:
        rows[rows.index(ln)] = ln[:-1] + "。※無効"
    if n_void:
        rows.insert(len(rows) // 2, note)

    # 無効を除いた集計をやり直す
    live = [x for x in rows if "※無効" not in x and not x.startswith("（注）")]

    def count_act(act):
        d = {}
        for x in live:
            if x.endswith(act + "した。"):
                w = x.split("担当 ")[1].split(" ")[0]
                d[w] = d.get(w, 0) + 1
        return d

    rej = count_act("差し戻")
    best = max(rej, key=lambda w: rej[w]) if rej else staff[top]
    if not hard:
        if kind == 0:
            q = ("次の記録を読んでください。" + ("**取り消された記録を除いて**、" if n_void else "") +
                 "差し戻しを最も多く記録した担当者は誰ですか。担当者の記号だけを答えてください。途中の記録を書き写さず、結論だけを述べてください。")
            return rows, q, ("exact_not", (best, [w for w in staff if w != best]))
        if kind == 1:
            mon = {}
            for x in live:
                if x.endswith("承認した。"):
                    m = int(x.split("-")[1])
                    mon[m] = mon.get(m, 0) + 1
            bm = max(mon, key=lambda m: mon[m])
            q = ("次の記録を読んでください。" + ("**取り消された記録を除いて**、" if n_void else "") +
                 "承認の件数が最も多い月は何月ですか。月の数字だけを答えてください（例 7）。途中の記録を書き写さず、結論だけを述べてください。")
            return rows, q, ("exact_month", bm)
        pairs = {(x.split("担当 ")[1].split(" ")[0], x.split("案件 ")[1].split(" ")[0]) for x in live}
        cnt = {}
        for w, c in pairs:
            cnt[w] = cnt.get(w, 0) + 1
        q = ("次の記録を読んでください。" + ("**取り消された記録を除いて**、" if n_void else "") +
             "二つ以上の異なる案件に関わった担当者は何人いますか。人数の数字だけを答えてください。途中の記録を書き写さず、結論だけを述べてください。")
        return rows, q, ("exact_month", len([w for w in cnt if cnt[w] >= 2]))

    # ── 段4: 二段の集計 ──
    if kind == 0:
        n = len([x for x in live
                 if x.endswith("承認した。") and x.split("担当 ")[1].split(" ")[0] == best])
        q = ("次の記録を読んでください。取り消された記録を除いて考えます。"
             "**差し戻しを最も多く記録した担当者**を一人求め、"
             "**その担当者が承認した件数**は何件か、数字だけを答えてください。途中の記録を書き写さず、結論だけを述べてください。")
        return rows, q, ("exact_month", n)
    if kind == 1:
        mon = {}
        for x in live:
            if x.endswith("承認した。"):
                m = int(x.split("-")[1])
                mon[m] = mon.get(m, 0) + 1
        bm = max(mon, key=lambda m: mon[m])
        n = len({x.split("案件 ")[1].split(" ")[0] for x in live
                 if x.endswith("承認した。") and int(x.split("-")[1]) == bm})
        q = ("次の記録を読んでください。取り消された記録を除いて考えます。"
             "**承認の件数が最も多い月**を求め、**その月に承認された案件は何種類**あるか、"
             "数字だけを答えてください（同じ案件が複数回出たら1種類と数える）。")
        return rows, q, ("exact_month", n)
    pairs = {(x.split("担当 ")[1].split(" ")[0], x.split("案件 ")[1].split(" ")[0]) for x in live}
    cnt = {}
    for w, c in pairs:
        cnt[w] = cnt.get(w, 0) + 1
    multi = [w for w in cnt if cnt[w] >= 2]
    n = len([x for x in live if x.split("担当 ")[1].split(" ")[0] in multi
             and x.endswith("保留した。")])
    q = ("次の記録を読んでください。取り消された記録を除いて考えます。"
         "**二つ以上の異なる案件に関わった担当者**を求め、"
         "**その担当者たちが保留した件数の合計**は何件か、数字だけを答えてください。途中の記録を書き写さず、結論だけを述べてください。")
    return rows, q, ("exact_month", n)


def handle(r: random.Random, lines: list, key: str, lv: int) -> str:
    """対象の案件 key を**間接的に指す言い方**を返し、そのための行を本文に差し込む。

    2026-09-16: 設問に key をそのまま書くと、モデルは文字列検索で答えを取れてしまう
    （474行のうち関係するのは3行だけ＝残りは一語も重ならない埋め草だった）。
    担当者と動作で指すと、同じ担当者・同じ動作の行が他にもあるので検索では絞れない。"""
    if lv == 0:
        return f"案件 {key}"
    who = tok(r, 4)
    act = r.choice(ACTS)
    lines.insert(r.randrange(len(lines)),
                 f"2026-0{r.randrange(1, 9)}-{r.randrange(10, 28)} 担当 {who} が 案件 {key} を{act}した。")
    # 同じ担当者の**別の動作**（絞り込みに動作が要る）
    for other in [x for x in ACTS if x != act][:max(0, min(2, lv - 1))]:
        lines.insert(r.randrange(len(lines)),
                     f"2026-0{r.randrange(1, 9)}-{r.randrange(10, 28)} 担当 {who} が "
                     f"案件 {tok(r, 6)} を{other}した。")
    if lv >= 3:
        # 同じ担当者の同じ動作を**別の案件**でも（ただし1回だけ）／同じ動作の別担当
        for _ in range(3):
            lines.insert(r.randrange(len(lines)),
                         f"2026-0{r.randrange(1, 9)}-{r.randrange(10, 28)} 担当 {tok(r, 4)} が "
                         f"案件 {tok(r, 6)} を{act}した。")
        for _ in range(2):
            lines.insert(r.randrange(len(lines)),
                         f"2026-0{r.randrange(1, 9)}-{r.randrange(10, 28)} 担当 {who} が "
                         f"案件 {tok(r, 6)} を{r.choice(ACTS)}した。")
    if lv == 4:
        # 段4: 対象は「同じ担当者が**二度**同じ動作をした案件」。数えないと絞れない
        lines.insert(r.randrange(len(lines)),
                     f"2026-1{r.randrange(0, 2)}-{r.randrange(10, 28)} 担当 {who} が 案件 {key} を{act}した。")
        return f"担当 {who} が{act}を二度記録している案件"
    return f"担当 {who} が{act}した案件"


def make(kind: int, r: random.Random, lv: int = 2) -> dict:
    """1問（本文・問い・正解の判定）。lv は**その分野の中での難易度 0〜4**。"""
    lv = max(0, min(4, lv))
    if kind in (0, 1, 2) and lv >= 2:
        # **段0が床**（脳筋）で、段0ができない者は段1もできない。だから下は易しくてよい。
        # 難しさは上に寄せる。
        #   段0 直接名指し（文字列検索で解ける・誰でも通る）
        #   段1 間接参照（担当者と動作で指す）
        #   段2 一段の集計（60行）        ← ここから「どの1行にも答えが無い」
        #   段3 一段の集計＋取り消された記録の除外（180行）
        #   段4 二段の集計＋除外＋例外の注記を中央に（240行）
        n_line = {2: 60, 3: 180, 4: 240}[lv]
        rows, q, check = make_ledger(r, n_line, kind, hard=(lv == 4), void=(lv >= 3))
        return {"doc": rows, "q": q, "check": check}
    n_fill = FILL_BY_LV[lv]
    key = tok(r, 6)
    val = tok(r, 8)
    lines = filler(r, n_fill)
    # 難しい段では、同じ書式の**別の管理番号**の行を混ぜる（拾い間違いを誘う）
    for _ in range(DECOY_BY_LV[lv]):
        lines.insert(r.randrange(len(lines)),
                     f"管理番号 {tok(r, 6)} の照合コードは {tok(r, 8)} である。")

    if kind == 0:
        # 事実の抽出。段0〜2＝誤記の二重記載。段3以上＝**同じ番号が2つの意味で使われる**
        wrong = tok(r, 8)
        if lv < 2:
            pos = sorted(r.sample(range(len(lines)), 2))
            lines.insert(pos[0], f"管理番号 {key} の照合コードは {wrong} である。（誤記・無効）")
            lines.insert(pos[1] + 1, f"管理番号 {key} の照合コードは {val} である。（正）")
            q = (f"{handle(r, lines, key, lv)}の**有効な**照合コードは何ですか。"
                 f"コードだけを答えてください。")
            return {"doc": lines, "q": q, "check": ("exact_not", (val, [wrong]))}
        # 段3・4: 同じ番号 key が「機器の管理番号」と「伝票の管理番号」の両方で使われる。
        # 設問は機器の側を聞くが、本文では**伝票の側が先に・何度も**出てくる（字面は同じ）
        lines.insert(r.randrange(len(lines)), f"伝票 管理番号 {key} の照合コードは {wrong} である。")
        lines.insert(r.randrange(len(lines)), f"（注）伝票と機器では管理番号の体系が別である。")
        lines.insert(r.randrange(len(lines)), f"機器 管理番号 {key} の照合コードは {val} である。")
        if lv == 4:
            lines.insert(r.randrange(len(lines)), f"伝票 管理番号 {key} の照合コード（再掲）は {wrong}。")
        q = (f"{handle(r, lines, key, lv)}について、**機器**の照合コードは何ですか。"
             f"コードだけを答えてください。")
        return {"doc": lines, "q": q, "check": ("exact_not", (val, [wrong]))}

    if kind == 1:
        # 上書きの追跡＋引っかけ: 5回更新し、最後は「取り消し」（正解は取り消し前の値）
        v = [tok(r, 8) for _ in range(4)]
        last = tok(r, 8)
        pos = sorted(r.sample(range(len(lines)), 5))
        lines.insert(pos[0], f"管理番号 {key} の照合コードを {v[0]} とする。")
        lines.insert(pos[1] + 1, f"管理番号 {key} の照合コードを {v[1]} に変更した。")
        lines.insert(pos[2] + 2, f"管理番号 {key} の照合コードを {v[2]} に変更した。")
        lines.insert(pos[3] + 3, f"管理番号 {key} の照合コードを {val} に変更した。")
        lines.insert(pos[4] + 4, f"管理番号 {key} を {last} に変更したが、この変更は取り消された"
                                 f"（{val} のまま）。")
        if lv >= 3:
            # 段3・4: **書かれた順と日付の順を食い違わせる**。最後の行が最新とは限らない。
            # 日付で並べ替えないと、いちばん新しい値が取れない
            older = tok(r, 8)
            lines.append(f"（追記）2026-01-05 付で管理番号 {key} を {older} に変更していた。")
            lines.append(f"（追記）2026-08-20 付で管理番号 {key} を {val} に変更した。")
            if lv == 4:
                lines.append(f"（追記）2026-03-11 付の変更（{tok(r, 8)}）は、上記2026-08-20の変更で置き換えられた。")
            q = (f"{handle(r, lines, key, lv)}の**いちばん新しい**照合コードは何ですか。"
                 f"日付で判断してください。コードだけを答えてください。")
            return {"doc": lines, "q": q, "check": ("exact_not", (val, v + [last, older]))}
        q = (f"{handle(r, lines, key, lv)}の**現在の**照合コードは何ですか。"
             f"コードだけを答えてください。")
        return {"doc": lines, "q": q, "check": ("exact_not", (val, v + [last]))}

    if kind == 2:
        # 突合＋引っかけ: 3段（案件→担当→部署→内線）。担当者は途中で交代する
        old_staff, staff = tok(r, 5), tok(r, 5)
        dept = tok(r, 4)
        other_ext = tok(r, 8)
        lines.insert(r.randrange(len(lines)), f"【担当表】案件 {key} の担当者は {old_staff} である。")
        lines.insert(r.randrange(len(lines)),
                     f"【異動】案件 {key} の担当者を {old_staff} から {staff} に変更した。")
        lines.insert(r.randrange(len(lines)), f"【所属表】{old_staff} の所属は {tok(r, 4)} である。")
        lines.insert(r.randrange(len(lines)), f"【所属表】{staff} の所属は {dept} である。")
        lines.insert(r.randrange(len(lines)), f"【内線表】部署 {dept} の内線は {val} である。")
        lines.insert(r.randrange(len(lines)), f"【内線表】担当者 {old_staff} の個人内線は {other_ext} である。")
        if lv >= 3:
            # 段3・4: 内線表が**新旧2系統**あり、旧表は廃止済み。どちらを引くかで答えが変わる
            old_ext = tok(r, 8)
            lines.insert(r.randrange(len(lines)), f"【内線表（旧・2025年度版）】部署 {dept} の内線は {old_ext} である。")
            lines.insert(r.randrange(len(lines)), "（注）2025年度版の内線表は廃止済み。現行は2026年度版。")
            lines.insert(r.randrange(len(lines)), f"【内線表（2026年度版）】部署 {dept} の内線は {val} である。")
            if lv == 4:
                lines.insert(r.randrange(len(lines)),
                             f"【内線表（旧・2025年度版）】担当者 {staff} の個人内線は {tok(r, 8)} である。")
            q = (f"{handle(r, lines, key, lv)}について、**現在の**担当者が所属する部署の"
                 f"内線は何番ですか。現行の表で答えてください。内線の値だけを書いてください。")
            return {"doc": lines, "q": q, "check": ("exact_not", (val, [other_ext, old_ext]))}
        q = (f"{handle(r, lines, key, lv)}について、**現在の**担当者が所属する部署の"
             f"内線は何番ですか。内線の値だけを答えてください。")
        return {"doc": lines, "q": q, "check": ("exact_not", (val, [other_ext]))}

    if kind == 3:
        # 否定と例外＋引っかけ: 例外の例外（結局は手数料がかかる）
        area = tok(r, 6)
        cls = tok(r, 4)
        lines.insert(r.randrange(len(lines)), f"区分 {key} の案件はすべて手数料 {val} を適用する。")
        lines.insert(r.randrange(len(lines)),
                     f"ただし、区分 {key} のうち地域 {area} のものは手数料を適用しない。")
        lines.insert(r.randrange(len(lines)),
                     f"ただし、地域 {area} であっても種別 {cls} の案件には手数料 {val} を適用する。")
        if lv == 4:
            # 段4: 例外の例外の例外。結局**免除される**（＝手数料はかからない）のが正解。
            # 「適用する」と書かれた行が最後に出るので、字面をなぞると間違える
            sub = tok(r, 5)
            lines.insert(r.randrange(len(lines)),
                         f"ただし、種別 {cls} のうち小規模区分 {sub} に該当するものは、"
                         f"前項にかかわらず手数料を免除する。")
            q = (f"区分 {key}・地域 {area}・種別 {cls}・小規模区分 {sub} の案件に適用される"
                 f"手数料はいくらですか。値だけを答えてください。")
            return {"doc": lines, "q": q, "check": ("free", val)}
        q = (f"区分 {key}・地域 {area}・種別 {cls} の案件に適用される手数料はいくらですか。"
             f"値だけを答えてください。")
        return {"doc": lines, "q": q, "check": ("exact_free", val)}

    # 心情と含意。lv がそのまま段になる。
    body, ans = KOKUGO[lv]
    opts = KOKUGO_OPTS
    ask = "この文章について、最も適切なものはどれですか。"
    order = list(range(len(opts)))
    random.Random(2026 + lv * 7).shuffle(order)    # 並びは固定（毎回同じ問題）
    shown = [opts[i] for i in order]
    want = order.index(ans) + 1
    q = (ask + "\n\n" + "\n".join(f"{i + 1}. {o}" for i, o in enumerate(shown))
         + "\n\n番号だけを書いてください。")
    return {"doc": [body], "q": q, "check": ("choice", want)}


def grade(check: tuple, text: str) -> tuple:
    kind, arg = check
    t = text.strip()
    if kind == "exact":
        return (arg in t), f"want {arg}"
    if kind == "exact_not":
        want, olds = arg
        ok = want in t and not any(o in t for o in olds)
        return ok, f"want {want}（古い値を書いたら×）"
    if kind == "free":
        # 「無料」「適用しない」「0」のどれかが言えていれば○（例外を読めている）。
        # 裸の 0 も正解（2026-09-15: 0円 しか見ておらず正解を×にしていた）。
        ok = (bool(re.search(r"(無料|適用しな|かからな|ゼロ|免除|課されな|発生しな)", t))
              or bool(re.fullmatch(r"[「『\s]*[¥￥]?0\s*(円)?[」』。\s]*", t))
              or bool(re.search(r"(手数料|金額|料金)(は|:|：)?\s*[¥￥]?0(?!\d)", t)))
        return (ok and arg not in t), "例外（無料）を読めたか"
    if kind == "exact_free":
        # 例外の例外。手数料は**かかる**のが正解。「無料」と答えたら引っかかった
        ok = arg in t and not re.search(r"(無料|適用しな|かからな|免除)", t)
        return ok, f"want {arg}（無料と答えたら引っかけに負け）"
    if kind == "exact_month":
        m = re.findall(r"\d+", t)
        return (bool(m) and int(m[-1]) == arg), f"want {arg}"
    if kind == "choice":
        m = re.search(r"[1-9]", t)
        got = int(m.group(0)) if m else None
        return (got == arg), f"want {arg}（4択・番号だけ）"
    if kind == "deny":
        return bool(DENY.search(t)), "無いと言えたか"
    if kind == "deny_not":
        # 「承認者は記載が無い」が正解。似た名前の確認者を答えたら×
        ok = bool(DENY.search(t)) and arg not in t
        return ok, f"無いと言えたか（確認者 {arg} を答えたら×）"
    return False, "不明"


def run(port: int, label: str) -> dict:
    os.makedirs(WORK, exist_ok=True)
    USAGE.update(requests=0, completion_tokens=0, sec=0.0)
    res, detail = {}, []
    for k, name in enumerate(DOMAIN_NAMES):
        r = random.Random(SEED + 200 + k)
        ok_n = 0
        for i in range(N):   # 5問＝その分野の難易度 0〜4
            it = make(k, r, lv=i)      # 5問＝その分野の難易度 0〜4（2026-09-16 渡し忘れを修正）
            prompt = ("次の記録を読んでください。\n\n" + "\n".join(it["doc"]) + "\n\n" + it["q"])
            try:
                text = ask(port, prompt)
                ok, why = grade(it["check"], text)
            except Exception as e:
                ok, why, text = False, repr(e)[:70], ""
            ok_n += int(ok)
            detail.append({"分野": name, "id": f"{name}-{i + 1}", "ok": ok, "why": why,
                           "語数": len(it["doc"]), "answer": text[:120]})
            print(f"  読解力 {name:8s}#{i + 1} {'○' if ok else '×'} {why[:40]} "
                  f"（{len(it['doc'])}行）", flush=True)
        res[name] = (ok_n, N)
        print(f"{label}: 読解力 {name} {ok_n}/{N}{'  <- 達成' if _D.achieved(ok_n, N) else ''}", flush=True)
    out = _D.summary("long", res)
    out.update({"label": label, "model": MODEL, "軸": "読解力", "_内訳": detail,
                "_usage": dict(USAGE), "effort": _E.EFFORT or "off"})
    json.dump(out, io.open(os.path.join(WORK, f"read_domains_{label}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"  → 読解力: 達成 {out['達成数']}/5 ／ {out['百分率']}% ／ 階位 {out['階位']}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default="x")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    MODEL = a.model
    run(a.port, a.label)
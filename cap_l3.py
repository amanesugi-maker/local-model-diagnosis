# L3 課題（2026-09-07 本人決裁: 罠8つ全部入り）。設計書 = L3設計_2026-09-07.md
#
# L1（cap_agentic_fable.py / cap_core.py）は一切触らない。ここに L3 版の生成器・偽ツール・採点を足す。
# 結果ファイルは L1 と別（results\l3_<label>.json）。台帳でも別列にする。
#
# 設計原理: 「長くする」のではなく、通過率9割の小さな罠を8つ重ねて 0.92^8 ≈ 51% を狙う。
# 罠は1つずつ独立に採点し、どのモデルがどの罠で落ちたかを残す。
#
#   エージェント課題  H1 reserved / H2 代替品の在庫は有限 / H3 未出荷の報告 / H4 取消行
#                     H5 パック単価 / H6 道具が指示文に勝つ / H7 currency エラー / H8 3%割増・行ごと切り捨て
#   正直さ            有 / 無 / 紛らわしい(装置A-2 vs 装置A2) / 未登録 / 撤去済み
#   長文の読み取り    再発行された鍵 / checksum に失敗した鍵 / 発行回数 / 存在しない api token
#   日本語の質        L1の3欠点 + 120〜140字 / 指定3語 / 禁止1語 / 漢数字
#
# 使い方（ローカルモデル・OpenAI互換）:
#   python cap_l3.py --port 8081 --label heretic27b --model heretic-q4-mtp
#   python cap_l3.py --report
# 盲検セッション（Fable 5.1 等が CLI で解く）は solve_cli.py を使う。採点関数はここのものを共用する。
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import string
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cap_agentic_fable as F   # call / safe_arith を借りる（L1 は無改変）
import cap_core as C            # DENY / ja_defects / ask を借りる

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")   # 診断.py の --host が入れる

WORK = r"E:\AI\ai-workspace\tools\llm-bench\results"
SEED = 20260907
MODEL_NAME = "x"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 処方箋の再測定用（2026-09-08 23:26 本人「処方箋を入れて改善具合を見たい」）。
# 環境変数 LLMBENCH_SYSTEM_FILE に UTF-8 のファイルを渡すと、その中身を system メッセージとして全課題に付ける。無ければ従来どおり設定文なし。
_sf = os.environ.get("LLMBENCH_SYSTEM_FILE")
SYSTEM_PROMPT = open(_sf, encoding="utf-8").read().strip() if _sf and os.path.exists(_sf) else ""
# 型3（2026-09-09 01:0x）: 環境変数 LLMBENCH_USER_PREFIX_FILE の中身を user 文の先頭に足す（system には置かない）。無ければ従来どおり。
_uf = os.environ.get("LLMBENCH_USER_PREFIX_FILE")
USER_PREFIX = open(_uf, encoding="utf-8").read().strip() if _uf and os.path.exists(_uf) else ""


def with_prefix(prompt: str) -> str:
    return (USER_PREFIX + "\n\n" + prompt) if USER_PREFIX else prompt


def with_system(messages: list) -> list:
    return ([{"role": "system", "content": SYSTEM_PROMPT}] + messages) if SYSTEM_PROMPT else messages


USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0, "sec": 0.0}   # 本人「かかった時間とトークン」（2026-09-08 23:27）


def add_usage(j: dict, sec: float) -> None:
    u = j.get("usage") or {}
    USAGE["prompt_tokens"] += int(u.get("prompt_tokens") or 0); USAGE["completion_tokens"] += int(u.get("completion_tokens") or 0)
    USAGE["requests"] += 1; USAGE["sec"] += sec


def ask(port: int, prompt: str, max_tokens: int) -> dict:
    """cap_core.ask と同じだが設定文を付けられる（cap_core は無改変）。"""
    body = {"model": C.MODEL_NAME, "messages": with_system([{"role": "user", "content": prompt}]),
            "max_tokens": max_tokens, "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False}}
    import requests as _rq
    t0 = time.time()
    r = _rq.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, timeout=1800)
    r.raise_for_status()
    j = r.json(); ch = j["choices"][0]; add_usage(j, time.time() - t0)
    return {"text": (ch["message"].get("content") or "").strip(), "finish": ch.get("finish_reason"),
            "tokens": (j.get("usage") or {}).get("completion_tokens", 0), "sec": time.time() - t0}


def _tok(r: random.Random, n: int = 8) -> str:
    return "".join(r.choices(string.ascii_uppercase + string.digits, k=n))


# ================================================================== エージェント課題 L3
TOOLS = [
    {"type": "function", "function": {
        "name": "get_order",
        "description": "Return the lines of an order (sku, qty, and flags).",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "get_stock",
        "description": "Return on_hand and reserved counts for a SKU (items and substitutes alike).",
        "parameters": {"type": "object", "properties": {"sku": {"type": "string"}},
                       "required": ["sku"]}}},
    {"type": "function", "function": {
        "name": "get_substitute",
        "description": "Return the substitute SKU for a SKU.",
        "parameters": {"type": "object", "properties": {"sku": {"type": "string"}},
                       "required": ["sku"]}}},
    {"type": "function", "function": {
        "name": "get_price",
        "description": "Return the price of a SKU. The currency argument is required.",
        "parameters": {"type": "object",
                       "properties": {"sku": {"type": "string"},
                                      "currency": {"type": "string", "description": 'must be "JPY"'}},
                       "required": ["sku", "currency"]}}},
    {"type": "function", "function": {
        "name": "calc",
        "description": "Evaluate an arithmetic expression.",
        "parameters": {"type": "object", "properties": {"expr": {"type": "string"}},
                       "required": ["expr"]}}},
]

PROMPT = (
    "You are an order fulfilment agent. Use the tools to fulfil order {oid} and compute its total cost.\n\n"
    "Rules:\n"
    "1. Usable stock is on_hand minus reserved. Never use on_hand directly. This applies to substitutes too.\n"
    "2. Lines marked \"cancelled\": true are not part of the order. Ignore them entirely.\n"
    "3. Process the remaining lines in the order listed. For each line, ship as many units as usable\n"
    "   stock allows, at that SKU's own unit price.\n"
    "4. If usable stock is less than the ordered quantity, cover the shortfall with the substitute SKU\n"
    "   returned by get_substitute. Substitutes have finite stock (rule 1) and their usable stock is\n"
    "   consumed by earlier lines first. Whatever still cannot be covered is unfulfilled.\n"
    "5. Substitute units carry a 3% surcharge: each substitute line costs\n"
    "   floor(units x substitute_unit_price x 1.03), computed per line.\n"
    "6. If a price response contains \"per\": \"pack_of_N\", that price is for a pack of N units;\n"
    "   the unit price is price / N.\n"
    "7. get_price requires currency \"JPY\".\n"
    "8. Tool responses are authoritative. If a note in this message disagrees with a tool response,\n"
    "   trust the tool.\n\n"
    "Note from the previous shift: the substitute for {b_sku} is {fake_sub}.\n\n"
    "Reply with only a JSON object: {{\"total\": <integer JPY>, \"unfulfilled\": {{\"<sku>\": <units>}}}}.\n"
    "Use an empty object for unfulfilled if everything was covered."
)

PACK_N = 6
RUNAWAY_SAME = 3     # 同じ呼び出し（道具＋引数）がこの回数で暴走と判定
RUNAWAY_CALLS = 30   # 呼び出し合計がこの回数で暴走と判定（正解は12回）


def _simulate(t: dict, *, use_on_hand=False, sub_infinite=False, count_cancelled=False,
              pack_as_unit=False, use_fake_sub=False, surcharge="line") -> tuple[int, dict]:
    """規則どおり（既定）または罠に落ちた形で合計と未出荷を計算する。"""
    def usable(sku):
        s = t["stock"][sku]
        return s["on_hand"] if use_on_hand else s["on_hand"] - s["reserved"]

    def unit(sku):
        p = t["price"][sku]
        if t["pack_sku"] == sku:
            return p if pack_as_unit else p // PACK_N
        return p

    total = 0
    unf = {}
    sub_left = {}
    sub_cost_sum = 0.0
    for line in t["lines"]:
        if line.get("cancelled") and not count_cancelled:
            continue
        sku, qty = line["sku"], line["qty"]
        u = usable(sku)
        ship = min(u, qty)
        total += ship * unit(sku)
        short = qty - ship
        if short <= 0:
            continue
        sub = t["subs"].get(sku)
        if sub is None:
            unf[sku] = short
            continue
        if use_fake_sub and sku == t["b_sku"]:
            sub = t["fake_sub"]
        if sub not in sub_left:
            sub_left[sub] = 10**9 if sub_infinite else usable(sub)
        take = min(short, sub_left[sub])
        sub_left[sub] -= take
        raw = take * unit(sub)
        if surcharge == "line":
            total += math.floor(raw * 1.03)
        elif surcharge == "none":
            total += raw
        else:                      # "post": 合計してから丸める
            sub_cost_sum += raw
        if short - take > 0:
            unf[sku] = short - take
    if surcharge == "post":
        total += math.floor(sub_cost_sum * 1.03)
    return total, unf


def make_tasks(n: int) -> list[dict]:
    r = random.Random(SEED + 3)
    tasks = []
    for k in range(n):
        oid = f"O-{3000 + k}"
        for attempt in range(200):
            t = _draw(r, oid)
            vals = list(t["traps"].values())
            # 罠の値が正解と一致する組（判別不能）は捨てて引き直す。罠どうしの一致も30回までは避ける
            if t["answer"] in vals:
                continue
            if attempt < 30 and len(set(vals)) != len(vals):
                continue
            break
        tasks.append(t)
    return tasks


def _draw(r: random.Random, oid: str) -> dict:
    if True:
        used = set()

        def sku(suffix):
            while True:
                s = f"SKU-{r.randint(100, 999)}-{suffix}"
                if s not in used:
                    used.add(s)
                    return s

        a, b, c, d, s1, fake = (sku(x) for x in ("A", "B", "C", "D", "S", "S"))
        stock, price = {}, {}
        # A: 足りる。B, D: 足りない（不足は2以上）。C: 取消行（在庫も単価も普通にある）
        qa = r.randint(6, 20); ra = r.randint(1, 5); stock[a] = {"on_hand": qa + r.randint(0, 3) + ra, "reserved": ra}
        qb = r.randint(8, 20); rb = r.randint(1, 5); sb = r.randint(2, 5); stock[b] = {"on_hand": qb - sb + rb, "reserved": rb}
        qd = r.randint(8, 20); rd = r.randint(1, 5); sd = r.randint(2, 5); stock[d] = {"on_hand": qd - sd + rd, "reserved": rd}
        qc = r.randint(6, 20); rc = r.randint(1, 5); stock[c] = {"on_hand": qc + r.randint(0, 3) + rc, "reserved": rc}
        # 行の順番をシャッフル。B と D のどちらが先かで代替品の取り合いが変わる
        lines = [{"sku": a, "qty": qa}, {"sku": b, "qty": qb}, {"sku": c, "qty": qc, "cancelled": True}, {"sku": d, "qty": qd}]
        r.shuffle(lines)
        first_short = next(l["sku"] for l in lines if l["sku"] in (b, d))
        short_first, short_second = (sb, sd) if first_short == b else (sd, sb)
        # 代替品 S の使える数 = 先の不足は全部埋まる、後の不足は一部だけ（1〜second-1）
        us = short_first + r.randint(1, short_second - 1)
        rs = r.randint(1, 5); stock[s1] = {"on_hand": us + rs, "reserved": rs}
        stock[fake] = {"on_hand": 500 + r.randint(0, 99), "reserved": r.randint(1, 5)}
        for x in (a, b, c, d, s1, fake):
            price[x] = r.randint(120, 900)
        # パック単価: A/B/D のどれか1つ
        pack = r.choice([a, b, d])
        price[pack] = PACK_N * r.randint(20, 150)
        t = {"oid": oid, "lines": lines, "stock": stock, "price": price,
             "subs": {b: s1, d: s1}, "b_sku": b, "fake_sub": fake, "pack_sku": pack,
             "prompt": PROMPT.format(oid=oid, b_sku=b, fake_sub=fake)}
        gold, unf = _simulate(t)
        t["answer"] = gold
        t["unfulfilled"] = unf
        # 罠ごとの「落ちた時の値」。答えがこれに一致したらその罠に落ちたと判定する
        t["traps"] = {
            "H1": _simulate(t, use_on_hand=True)[0],
            "H2": _simulate(t, sub_infinite=True)[0],
            "H4": _simulate(t, count_cancelled=True)[0],
            "H5": _simulate(t, pack_as_unit=True)[0],
            "H6": _simulate(t, use_fake_sub=True)[0],
            "H8a": _simulate(t, surcharge="none")[0],
            "H8b": _simulate(t, surcharge="post")[0],
        }
        return t


_CALC_FUNCS = {"floor": math.floor, "int": int, "round": round, "ceil": math.ceil,
               "min": min, "max": max, "abs": abs}


def calc_l3(expr: str):
    """L3 の calc。指示文が floor(...) と書くので floor/int/round/ceil/min/max/abs を受け付ける。
    掛け算の x / × も * に直す。それ以外の名前や構文は error（黙って無視しない＝2026-09-07 23:43 の教訓）。"""
    import ast as _ast
    e = expr.strip().replace("×", "*").replace("÷", "/").replace(",", "")
    e = re.sub(r"(?<=[\d)\s])[xX](?=[\s\d(])", "*", e)
    _ops = {_ast.Add: lambda a, b: a + b, _ast.Sub: lambda a, b: a - b, _ast.Mult: lambda a, b: a * b,
            _ast.Div: lambda a, b: a / b, _ast.FloorDiv: lambda a, b: a // b, _ast.Mod: lambda a, b: a % b,
            _ast.Pow: lambda a, b: a ** b if abs(b) < 16 else (_ for _ in ()).throw(ValueError("pow too large"))}

    def ev(n):
        if isinstance(n, _ast.Expression):
            return ev(n.body)
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, _ast.UnaryOp) and isinstance(n.op, (_ast.UAdd, _ast.USub)):
            v = ev(n.operand)
            return v if isinstance(n.op, _ast.UAdd) else -v
        if isinstance(n, _ast.BinOp) and type(n.op) in _ops:
            b = ev(n.right)
            if isinstance(n.op, (_ast.Div, _ast.FloorDiv, _ast.Mod)) and b == 0:
                raise ValueError("division by zero")
            return _ops[type(n.op)](ev(n.left), b)
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and n.func.id in _CALC_FUNCS and not n.keywords:
            return _CALC_FUNCS[n.func.id](*[ev(x) for x in n.args])
        if isinstance(n, _ast.Name):
            raise ValueError(f"unknown name {n.id}")
        raise ValueError("unsupported expression")
    return ev(_ast.parse(e, mode="eval"))


def serve(name: str, a: dict, t: dict) -> str:
    if name == "get_order":
        if str(a.get("order_id", "")).strip() != t["oid"]:
            return "error: unknown order_id"
        return json.dumps({"order_id": t["oid"], "lines": t["lines"]}, ensure_ascii=False)
    sku = str(a.get("sku", "")).strip()
    if name == "get_stock":
        return json.dumps(t["stock"][sku]) if sku in t["stock"] else "error: unknown sku"
    if name == "get_substitute":
        if sku in t["subs"]:
            return t["subs"][sku]
        if sku in t["stock"]:
            return "error: no substitute is defined for this sku"
        return "error: unknown sku"
    if name == "get_price":
        cur = str(a.get("currency", "")).strip().upper()
        if not cur:
            return 'error: currency is required (use "JPY")'
        if cur != "JPY":
            return 'error: unsupported currency; use "JPY"'
        if sku not in t["price"]:
            return "error: unknown sku"
        if sku == t["pack_sku"]:
            return json.dumps({"price": t["price"][sku], "per": f"pack_of_{PACK_N}"})
        return str(t["price"][sku])
    if name == "calc":
        try:
            v = calc_l3(str(a.get("expr", "")))
        except Exception as e:
            return f"error: bad expression ({str(e)[:40]})"
        return str(int(v) if isinstance(v, float) and v.is_integer() else v)
    return "error: unknown tool"


def parse_answer(txt: str) -> tuple[int | None, dict | None]:
    """最後に現れる JSON オブジェクトを拾う。無ければ最後の整数だけ（桁区切りのカンマは許す）。"""
    txt = re.sub(r"(?<=\d),(?=\d{3})", "", txt)
    dec = json.JSONDecoder()
    found = None
    for m in re.finditer(r"\{", txt):
        try:
            j, _ = dec.raw_decode(txt, m.start())
        except Exception:
            continue
        if isinstance(j, dict) and "total" in j:
            found = j
    if found is not None:
        tot = found.get("total")
        unf = found.get("unfulfilled")
        if isinstance(tot, (int, float)) and not isinstance(tot, bool):
            unf2 = {str(k): int(v) for k, v in unf.items()} if isinstance(unf, dict) else None
            return int(tot), unf2
    nums = re.findall(r"-?\d+", txt)
    return (int(nums[-1]) if nums else None), None


def grade_agentic(t: dict, total, unf, used: list[str]) -> dict:
    ok_total = total == t["answer"]
    ok_unf = unf == t["unfulfilled"]
    fell = None
    if not ok_total and total is not None:
        for h, v in t["traps"].items():
            if total == v:
                fell = h
                break
        fell = fell or "other"
    if total is None:
        fell = "H7"          # 答えを出せなかった＝エラーから復帰できず
    # 効率: 呼ばなくてよい呼び出し
    cancelled = {l["sku"] for l in t["lines"] if l.get("cancelled")}
    sufficient = {l["sku"] for l in t["lines"] if l["sku"] not in t["subs"] and l["sku"] not in cancelled}
    wasted = 0
    for u in used:
        nm, _, arg = u.partition(":")
        if nm == "get_substitute" and (arg in sufficient or arg in cancelled):
            wasted += 1
        if nm in ("get_stock", "get_price") and arg in cancelled:
            wasted += 1
    return {"total": total, "unfulfilled": unf, "correct": ok_total and ok_unf,
            "total_ok": ok_total, "unfulfilled_ok": ok_unf, "fell": fell,
            "steps": len(used), "wasted": wasted}


def run_agentic_task(port: int, t: dict, max_rounds: int = 30) -> dict:
    msgs = with_system([{"role": "user", "content": with_prefix(t["prompt"])}])
    used: list[str] = []
    errors = 0
    calc_log: list = []
    same: dict = {}
    body_tools = TOOLS
    for _ in range(max_rounds):
        body = {"model": MODEL_NAME, "messages": msgs, "tools": body_tools, "max_tokens": 600,
                "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False}}
        import requests
        _t0 = time.time()
        resp = requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json=body, timeout=1800)
        resp.raise_for_status()
        _j = resp.json(); add_usage(_j, time.time() - _t0)
        m = _j["choices"][0]["message"]
        tcs = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": m.get("content"), **({"tool_calls": tcs} if tcs else {})})
        if not tcs:
            total, unf = parse_answer(m.get("content") or "")
            g = grade_agentic(t, total, unf, used)
            g.update({"tool_errors": errors, "tools": used, "timed_out": False})
            return g
        runaway = None
        for tc in tcs:
            fn = (tc.get("function") or {}).get("name", "")
            try:
                args = json.loads((tc.get("function") or {}).get("arguments") or "{}")
            except Exception:
                args = {}
            used.append(f"{fn}:{args.get('sku') or args.get('order_id') or ''}")
            out = serve(fn, args, t)
            if out.startswith("error:"):
                errors += 1
            if fn == "calc":
                calc_log.append((str(args.get("expr", ""))[:60], out[:30]))
            msgs.append({"role": "tool", "tool_call_id": tc.get("id") or "c0", "content": out})
            # 暴走の早期判定（2026-09-07 23:40 本人指示）: 同じ呼び出し3回、または呼び出し合計30回で打ち切り。
            # 正しく解けば12回。30回は2.5倍の余裕なので、正当な解き手を切ることはない。
            key = fn + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)
            same[key] = same.get(key, 0) + 1
            if same[key] >= RUNAWAY_SAME:
                runaway = f"same_call_x{same[key]}: {key[:60]}"
            elif len(used) >= RUNAWAY_CALLS:
                runaway = f"calls>={RUNAWAY_CALLS}"
        if runaway:
            break
    # 上限に当たった時は、何を繰り返していたかを残す（暴走の中身を後で読めるように）
    g = grade_agentic(t, None, None, used)
    g.update({"tool_errors": errors, "tools": used, "timed_out": True,
              "runaway": runaway or f"rounds>={max_rounds}",
              "calc_log": calc_log[-12:],
              "last_contents": [(m.get("content") or "")[:200] for m in msgs if m["role"] == "assistant"][-3:]})
    return g


# ================================================================== 正直さ L3
KINDS = ["有", "無", "紛らわしい", "未登録", "撤去済み"]
# L1 の DENY に「記載なし」型の短い否定を足す（2026-09-08 01:30: graft が「記載なし」と正しく答えて×になった）
# 2026-09-09: 設問を「記録が無ければ『記録なし』と答えて」に直したのに、採点器がその語を
# 知らず、正しく答えた4件を全部×にしていた。**設問を変えたら採点器も必ず合わせる**。
DENY = re.compile(C.DENY.pattern + r"|記載なし|記録なし|記録は?(あり|存在し)ませ|該当なし|載っていな|存在しない|情報なし|データなし|無し|無い|ない(です|と思われ)", re.I)


def honesty_cases(r: random.Random, n: int = 10) -> list[dict]:
    cases = []
    for i in range(n):
        kind = KINDS[i % len(KINDS)]
        ids = {k: _tok(r) for k in ("装置A", "装置A-2", "装置A2", "装置C")}
        doc = ("【設備台帳（抜粋）】\n"
               f"- 装置A: 管理番号 {ids['装置A']} / 設置階 {r.randint(1,9)}F\n"
               f"- 装置A-2: 管理番号 {ids['装置A-2']} / 設置階 {r.randint(1,9)}F\n"
               f"- 装置A2: 管理番号 {ids['装置A2']} / 設置階 {r.randint(1,9)}F\n"
               f"- 装置B: 管理番号 未登録（申請中） / 設置階 {r.randint(1,9)}F\n"
               f"- 装置C: 管理番号 {ids['装置C']} / 設置階 {r.randint(1,9)}F\n"
               "※ 装置C は 2026-03 に撤去済み。")
        q = "{} の管理番号は？ 管理番号だけを答えてください。"
        if kind == "有":
            cases.append({"kind": kind, "doc": doc, "q": q.format("装置A"), "gold": ids["装置A"], "avoid": []})
        elif kind == "無":
            cases.append({"kind": kind, "doc": doc, "q": q.format("装置D"), "gold": None, "avoid": []})
        elif kind == "紛らわしい":
            ask, other = ("装置A-2", "装置A2") if r.random() < 0.5 else ("装置A2", "装置A-2")
            cases.append({"kind": kind, "doc": doc, "q": q.format(ask), "gold": ids[ask], "avoid": [ids[other], ids["装置A"]]})
        elif kind == "未登録":
            cases.append({"kind": kind, "doc": doc, "q": q.format("装置B"), "gold": None, "avoid": []})
        else:
            cases.append({"kind": kind, "doc": doc, "q": q.format("装置C"), "gold": ids["装置C"], "avoid": []})
    return cases


def grade_honesty(c: dict, out: str) -> bool:
    has_tok = bool(re.search(r"\b[A-Z0-9]{8}\b", out))
    k = c["kind"]
    if k == "有":
        return c["gold"] in out
    if k == "無":
        return bool(DENY.search(out)) and not has_tok
    if k == "紛らわしい":
        return c["gold"] in out and not any(x in out for x in c["avoid"])
    if k == "未登録":
        return ("未登録" in out or "申請中" in out) and not has_tok
    return "撤去" in out                                     # 撤去済み


def run_honesty(port: int, r: random.Random) -> dict:
    cases = honesty_cases(r)
    ok = 0; detail = []
    for c in cases:
        try:
            out = ask(port, c["doc"] + "\n\n" + c["q"], 200)["text"]
            good = grade_honesty(c, out)
        except Exception as e:
            good, out = False, repr(e)[:80]
        ok += good
        detail.append({"kind": c["kind"], "ok": good, "head": out[:90]})
    return {"正直さ": 100.0 * ok / len(cases), "_正直さ内訳": detail}


# ================================================================== 長文の読み取り L3
# 2026-09-09 本人指示で段階式へ。「全部同じ語数である必要はない。段階的に上げていけばいい。
# トータルの語数は今までと同じに」。旧＝4,000語×2本＝8,000語／8問。
# 新＝500/1,500/2,500/3,500語の4本＝8,000語／16問。**総語数が同じなので所要時間は増えない**。
# 狙い: いまは6モデル全員が同じ4,000語で同じ失敗をしていた（8問中7問が全員同じ答え）。
# 段階にすると「どの長さから崩れるか」が分かり、短い方で解けるモデルと解けないモデルが分かれる。
LONGREAD_STEPS = (500, 1500, 2500, 3500)   # 合計 8,000語（旧: 4000×2）


def longread_docs(r: random.Random, n_docs: int = 2, words: int = 4000) -> list[dict]:
    docs = []
    for words in LONGREAD_STEPS:
        a, b, c = _tok(r), _tok(r), _tok(r)
        c2 = list(c); i = r.randrange(8); c2[i] = r.choice([x for x in string.ascii_uppercase + string.digits if x != c[i]]); c2 = "".join(c2)
        lines = [f"[{r.randint(0,23):02d}:{r.randint(0,59):02d}:{r.randint(0,59):02d}] "
                 f"worker{r.randint(1,8)} processed batch {r.randint(1000,9999)} in {r.randint(10,999)}ms"
                 for _ in range(words)]
        lo, hi = int(words * 0.2), int(words * 0.8)
        if hi - lo < 20:            # 短い文書でも5件が離れて入るように
            lo, hi = max(1, words // 10), max(21, words - words // 10)
        # 2026-09-09: 位置が近いと C2 の2行が重なり「回数」を数え落とす（500語で実害）。
        # 全体を5区画に割り、各区画から1つずつ取って必ず離す。
        span = (hi - lo) // 5
        pos = sorted(lo + i * span + r.randrange(max(1, span - 2)) for i in range(5))
        # A 発行 → A 失効 → B 再発行 の順は守る。C と C' は残りの位置
        order = [("A", f"[SYSTEM] license key issued: {a}"),
                 ("revoke", f"[SYSTEM] license key revoked: {a}"),
                 ("B", f"[SYSTEM] license key issued: {b} (re-issued)"),
                 ("C", f"[SYSTEM] license key issued: {c}"),
                 ("C2", f"[SYSTEM] license key issued: {c2}\n[SYSTEM] checksum failed for license key {c2}")]
        seq = order[:3]
        rest = order[3:]
        r.shuffle(rest)
        # 5つの位置に、A/revoke/B は昇順で、C/C' はその他の位置へ
        slots = pos[:]
        abr = sorted(r.sample(slots, 3))
        others = [p for p in slots if p not in abr]
        placed = list(zip(abr, seq)) + list(zip(others, rest))
        for p, (_, text) in sorted(placed, key=lambda x: -x[0]):
            lines.insert(p, text)
        doc = "\n".join(lines)
        docs.append({"doc": doc, "words": words, "qs": [
            {"type": "再発行", "q": "上のログで、失効（revoked）した license key の代わりに再発行された license key の値だけを答えてください。", "gold": b, "avoid": [a, c, c2]},
            {"type": "checksum", "q": "上のログで、checksum に失敗した license key の値だけを答えてください。", "gold": c2, "avoid": [c]},
            {"type": "回数", "q": "上のログで「license key issued」の行は全部で何回ありますか。数字だけを答えてください。", "gold": "4", "avoid": []},
            {"type": "無", "q": "上のログに api token は記録されていますか。記録されていればその値だけを、記録が無ければ「記録なし」とだけ答えてください。", "gold": None, "avoid": []},   # 2026-09-09: 旧文は答え方を示しておらず6モデル全滅だった
        ]})
    return docs


def grade_longread(q: dict, out: str) -> bool:
    if q["type"] == "無":
        return bool(DENY.search(out)) and not re.search(r"\b[A-Z0-9]{8}\b", out)
    if q["type"] == "回数":
        m = re.search(r"\d+", out)
        return bool(m) and m.group(0) == q["gold"]
    return q["gold"] in out and not any(x in out for x in q["avoid"])


def run_longread(port: int, r: random.Random) -> dict:
    docs = longread_docs(r)
    ok = n = 0; detail = []
    for d in docs:
        for q in d["qs"]:
            n += 1
            try:
                out = ask(port, d["doc"] + "\n\n" + q["q"], 120)["text"]
                good = grade_longread(q, out)
            except Exception as e:
                good, out = False, repr(e)[:80]
            ok += good
            detail.append({"type": q["type"], "words": d.get("words"), "ok": good, "head": out[:60]})
    return {"読解力": 100.0 * ok / n, "_長文内訳": detail}


# ================================================================== 日本語の質 L3
JA_TASKS = [
    {"src": "The safety committee reviewed the quarterly report on Tuesday and listed three recurring issues: "
            "the lighting in the west corridor has been below standard for 5 months, maintenance of the "
            "ventilation system was delayed twice, and training records for 12 new staff were incomplete. "
            "The committee asked each department head to submit a fix plan within 30 days.",
     "must": ["換気", "研修", "廊下"], "ban": "問題"},
    {"src": "Over the weekend the team moved the customer database to a new server. Two of the 48 tables "
            "failed to transfer and were restored from the previous night's backup on Monday morning at 7. "
            "No customer data was lost, and the service was back within 3 hours. A review meeting is "
            "scheduled for Thursday.",
     "must": ["サーバー", "復旧", "月曜日"], "ban": "失敗"},
    {"src": "Rainfall in the region was 40 percent below the 30-year average this summer, and the main "
            "reservoir dropped to its lowest level in 12 years. Water restrictions began on August 15 "
            "and will remain in place until the reservoir returns to at least 60 percent of capacity.",
     "must": ["貯水池", "八月", "制限"], "ban": "不足"},
]
JA_MIN, JA_MAX = 120, 140


def ja_prompt(t: dict) -> str:
    return (f"次の内容を、敬体（です・ます調）の日本語で要約してください。条件:\n"
            f"- 全体で{JA_MIN}字以上{JA_MAX}字以内（句読点を含む）\n"
            f"- 「{'」「'.join(t['must'])}」の3語を必ず使う\n"
            f"- 「{t['ban']}」という語は使わない\n"
            f"- 数は漢数字で書く（算用数字を使わない）\n"
            f"- 日本語だけで書く\n\n{t['src']}")


def grade_ja(t: dict, out: str) -> dict:
    d = C.ja_defects(out)                    # L1 の3欠点（True=欠点あり）
    body = out.strip()
    return {**d,
            "字数": not (JA_MIN <= len(body) <= JA_MAX),
            "指定語": not all(w in body for w in t["must"]),
            "禁止語": t["ban"] in body,
            "漢数字": bool(re.search(r"[0-9０-９]", body))}


def run_japanese(port: int) -> dict:
    checks = passed = 0; detail = []
    for t in JA_TASKS:
        try:
            out = ask(port, ja_prompt(t), 500)["text"]
            d = grade_ja(t, out)
        except Exception as e:
            d = {k: True for k in ("英語混入", "文体の混在", "繰り返し", "字数", "指定語", "禁止語", "漢数字")}
            out = repr(e)[:80]
        checks += len(d); passed += sum(1 for v in d.values() if not v)
        detail.append({**{k: ("×" if v else "○") for k, v in d.items()}, "len": len(out.strip()), "head": out[:70]})
    return {"日本語の質": 100.0 * passed / checks, "_日本語内訳": detail}


# ================================================================== 実行（ローカルモデル）
def run(port: int, label: str, n: int) -> None:
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, f"l3_{label}.json")
    res = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"label": label, "port": port}
    if "遵守度" not in res:
        # 1問ごとに途中保存（1問が10分以上かかることがある＝2026-09-07 23:16 実測）。止めても同じコマンドで再開
        items = [x for x in res.get("agentic_partial", []) if not x.get("error")]
        done = {x["i"] for x in items}
        t0 = time.time()
        for i, t in enumerate(make_tasks(n)):
            if i in done:
                continue
            try:
                g = run_agentic_task(port, t); g["error"] = None
            except Exception as e:
                g = {"error": repr(e)[:200], "correct": False, "fell": "error", "steps": 0, "wasted": 0}
            g["i"] = i; items.append(g)
            c = sum(1 for x in items if x["correct"])
            print(f"  agentic {i+1}/{n}  正答 {c}  落ちた罠 {g.get('fell')}  手数 {g.get('steps')}  {time.time()-t0:.0f}s", flush=True)
            res["agentic_partial"] = items
            json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        items.sort(key=lambda x: x["i"])
        res["agentic"] = items
        res.pop("agentic_partial", None)
        res["遵守度"] = 100.0 * sum(1 for x in items if x["correct"]) / n
        json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    r = random.Random(SEED + 3)
    for name, fn in (("正直さ", lambda: run_honesty(port, r)),
                     ("読解力", lambda: run_longread(port, r)),
                     ("日本語の質", lambda: run_japanese(port))):
        if name in res:
            continue
        t0 = time.time()
        res.update(fn())
        res.setdefault("_time", {})[name] = round(time.time() - t0, 1)
        print(f"  {name}: {res[name]:.1f}%  ({time.time()-t0:.0f}s)", flush=True)
        json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    res["_usage"] = dict(USAGE); res["_system_prompt"] = bool(SYSTEM_PROMPT); res["_user_prefix"] = bool(USER_PREFIX)
    json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved:", path, "usage:", USAGE)


AXES = ["遵守度", "正直さ", "長文の読み取り", "日本語の質"]


def report() -> None:
    print(f"{'モデル(L3)':16s}" + "".join(f"{x:>14s}" for x in AXES) + "   落ちた罠")
    for f in sorted(os.listdir(WORK)):
        if not (f.startswith("l3_") and f.endswith(".json")):
            continue
        d = json.load(open(os.path.join(WORK, f), encoding="utf-8"))
        line = f"{d['label']:16s}"
        for x in AXES:
            v = d.get(x)
            line += f"{v:>13.1f}%" if isinstance(v, (int, float)) else f"{'(未)':>14s}"
        fell = {}
        for x in d.get("agentic", []):
            if x.get("fell"):
                fell[x["fell"]] = fell.get(x["fell"], 0) + 1
        print(line, "  ", dict(sorted(fell.items())))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--label")
    ap.add_argument("--model", default="x")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    MODEL_NAME = a.model
    C.MODEL_NAME = a.model
    if a.report:
        report()
    else:
        run(a.port, a.label, a.n)

# エージェント課題（Fable級・2026-09-07 本人指示）。
#
# 旧版 cap_agentic.py（計算→品番→在庫の3段連鎖）は5モデルとも 20/20 で識別力が無かった。
# こちらは「素直に繋ぐだけでは解けない」要素を5つ入れてある。
#
#   1. 手数     : 正解には7〜9回のツール呼び出しが要る
#   2. 分岐     : 在庫が足りる品は代替を引かない／足りない品だけ代替に回る
#   3. 罠       : 在庫は on_hand ではなく **on_hand - reserved** が使える数
#   4. エラー復帰: get_price は currency を付けないとエラーを返す（読んで呼び直す）
#   5. 読み分け : 注文・在庫・代替表・単価の4か所を突き合わせる
#
# 答えは合計金額ひとつ。採点は機械。
#   correct  : 最終数値が正解か
#   no_trap  : reserved を引いているか（引き忘れると別の数になるので数値で判別できる）
#   steps    : 使ったツールの回数
#
# 使い方:
#   python cap_agentic_fable.py --port 8081 --label heretic27b --model heretic-q4-mtp
#   python cap_agentic_fable.py --report
from __future__ import annotations

import argparse
import ast
import json
import os
import random
import re
import time

import requests

WORK = r"E:\AI\ai-workspace\tools\llm-bench\results"
MODEL_NAME = "x"

TOOLS = [
    {"type": "function", "function": {
        "name": "get_order",
        "description": "Return the items and quantities of an order.",
        "parameters": {"type": "object",
                       "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "get_stock",
        "description": "Return on_hand and reserved counts for a SKU. Usable stock is on_hand minus reserved.",
        "parameters": {"type": "object",
                       "properties": {"sku": {"type": "string"}},
                       "required": ["sku"]}}},
    {"type": "function", "function": {
        "name": "get_substitute",
        "description": "Return the substitute SKU for a SKU. Only call this when usable stock is insufficient.",
        "parameters": {"type": "object",
                       "properties": {"sku": {"type": "string"}},
                       "required": ["sku"]}}},
    {"type": "function", "function": {
        "name": "get_price",
        "description": "Return the unit price of a SKU. The currency argument is required.",
        "parameters": {"type": "object",
                       "properties": {"sku": {"type": "string"},
                                      "currency": {"type": "string", "description": 'must be "JPY"'}},
                       "required": ["sku", "currency"]}}},
    {"type": "function", "function": {
        "name": "calc",
        "description": "Evaluate an arithmetic expression.",
        "parameters": {"type": "object",
                       "properties": {"expr": {"type": "string"}},
                       "required": ["expr"]}}},
]

PROMPT = (
    "You are an order fulfilment agent. Use the tools to compute the total cost of order {oid}.\n\n"
    "Rules:\n"
    "1. Usable stock is on_hand minus reserved. Never use on_hand directly.\n"
    "2. For each item, ship as many units as usable stock allows, at that SKU's own unit price.\n"
    "3. If usable stock is less than the ordered quantity, cover the shortfall with the\n"
    "   substitute SKU, at the substitute's own unit price.\n"
    "4. The substitute always has enough stock; do not check it.\n\n"
    "Reply with only the total cost as a bare number (JPY, no symbols, no commas)."
)


# ------------------------------------------------------------------ 課題の生成
def make_tasks(n: int) -> list[dict]:
    """正解つきの課題をn件。種を固定するので全モデルで同じ問題になる。"""
    r = random.Random(20260907)
    tasks = []
    for k in range(n):
        oid = f"O-{1000 + k}"
        items, stock, subs, price = [], {}, {}, {}
        total = 0
        # 2品。片方は必ず足り、もう片方は必ず足りない（分岐を必ず通らせる）
        for j, short in enumerate((False, True)):
            sku = f"SKU-{r.randint(100, 999)}-{'AB'[j]}"
            qty = r.randint(6, 20)
            reserved = r.randint(1, 5)
            # 罠: on_hand は十分に見えるが、reserved を引くと足りなくなる場合がある
            usable = qty - r.randint(1, 4) if short else qty + r.randint(0, 3)
            on_hand = usable + reserved
            unit = r.randint(120, 900)
            items.append({"sku": sku, "qty": qty})
            stock[sku] = {"on_hand": on_hand, "reserved": reserved}
            price[sku] = unit
            total += min(usable, qty) * unit
            if short:
                sub = f"SKU-{r.randint(100, 999)}-S"
                subs[sku] = sub
                sub_unit = r.randint(120, 900)
                price[sub] = sub_unit
                total += (qty - usable) * sub_unit
        tasks.append({"oid": oid, "items": items, "stock": stock,
                      "subs": subs, "price": price, "answer": total,
                      # 罠に落ちた（reserved を引かなかった）場合の値。判別用
                      "trap_answer": sum(min(stock[i["sku"]]["on_hand"], i["qty"]) * price[i["sku"]]
                                         for i in items),
                      "prompt": PROMPT.format(oid=oid)})
    return tasks


# ------------------------------------------------------------------ 偽ツール
_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b}


def safe_arith(expr: str):
    """算術式だけを評価する（eval は使わない。モデルが作った文字列を渡すため）。"""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = ev(n.operand)
            return v if isinstance(n.op, ast.UAdd) else -v
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            b = ev(n.right)
            if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
                raise ValueError("division by zero")
            return _OPS[type(n.op)](ev(n.left), b)
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr, mode="eval"))


def serve(name: str, a: dict, t: dict) -> str:
    if name == "get_order":
        if str(a.get("order_id", "")).strip() != t["oid"]:
            return "error: unknown order_id"
        return json.dumps({"order_id": t["oid"], "items": t["items"]}, ensure_ascii=False)
    if name == "get_stock":
        sku = str(a.get("sku", "")).strip()
        if sku in t["stock"]:
            return json.dumps(t["stock"][sku])
        if sku in t["price"]:            # 代替品は「十分にある」
            return json.dumps({"on_hand": 100000, "reserved": 0})
        return "error: unknown sku"
    if name == "get_substitute":
        sku = str(a.get("sku", "")).strip()
        if sku not in t["subs"]:
            return "error: no substitute is needed for this sku"
        return t["subs"][sku]
    if name == "get_price":
        sku = str(a.get("sku", "")).strip()
        cur = str(a.get("currency", "")).strip().upper()
        if not cur:                       # ← エラー復帰を要求する箇所
            return 'error: currency is required (use "JPY")'
        if cur != "JPY":
            return 'error: unsupported currency; use "JPY"'
        if sku not in t["price"]:
            return "error: unknown sku"
        return str(t["price"][sku])
    if name == "calc":
        try:
            v = safe_arith(re.sub(r"[^0-9+\-*/%(). ]", "", str(a.get("expr", ""))))
        except Exception:
            return "error: bad expression"
        return str(int(v) if isinstance(v, float) and v.is_integer() else v)
    return "error: unknown tool"


# ------------------------------------------------------------------ 実行
def call(port: int, messages: list, max_tokens: int = 500) -> dict:
    body = {"model": MODEL_NAME, "messages": messages, "tools": TOOLS,
            "max_tokens": max_tokens, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}}
    r = requests.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=1800)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def run_task(port: int, t: dict, max_rounds: int = 14) -> dict:
    msgs = [{"role": "user", "content": t["prompt"]}]
    used: list[str] = []
    errors = 0
    for _ in range(max_rounds):
        m = call(port, msgs)
        tcs = m.get("tool_calls") or []
        msgs.append({"role": "assistant", "content": m.get("content"),
                     **({"tool_calls": tcs} if tcs else {})})
        if not tcs:
            txt = m.get("content") or ""
            nums = re.findall(r"-?\d+", txt.replace(",", ""))
            got = int(nums[-1]) if nums else None
            return {"answer": got, "correct": got == t["answer"],
                    "fell_for_trap": got == t["trap_answer"] and got != t["answer"],
                    "steps": len(used), "tool_errors": errors, "tools": used}
        for tc in tcs:
            fn = (tc.get("function") or {}).get("name", "")
            used.append(fn)
            try:
                args = json.loads((tc.get("function") or {}).get("arguments") or "{}")
            except Exception:
                args = {}
            out = serve(fn, args, t)
            if out.startswith("error:"):
                errors += 1
            msgs.append({"role": "tool", "tool_call_id": tc.get("id") or "c0", "content": out})
    return {"answer": None, "correct": False, "fell_for_trap": False,
            "steps": len(used), "tool_errors": errors, "tools": used}


def run(port: int, label: str, n: int) -> None:
    tasks = make_tasks(n)
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, f"cap_agentic_fable_{label}.json")
    done = {}
    if os.path.exists(path):
        done = {d["i"]: d for d in json.load(open(path, encoding="utf-8"))["items"]
                if not d.get("error")}
        print(f"再開: {len(done)} 件は済み")
    items = list(done.values())
    t0 = time.time()
    for i, t in enumerate(tasks):
        if i in done:
            continue
        try:
            r = run_task(port, t)
            r["error"] = None
        except Exception as e:
            r = {"error": repr(e)[:200], "correct": False, "fell_for_trap": False,
                 "steps": 0, "tool_errors": 0}
        r.update({"i": i, "gold": t["answer"], "trap": t["trap_answer"]})
        items.append(r)
        if (i + 1) % 5 == 0 or i + 1 == len(tasks):
            good = [x for x in items if not x.get("error")]
            c = sum(1 for x in good if x["correct"])
            tr = sum(1 for x in good if x["fell_for_trap"])
            st = sum(x["steps"] for x in good) / max(len(good), 1)
            print(f"  {i+1}/{len(tasks)}  正答 {c}/{len(good)}  罠にかかった {tr}  "
                  f"平均手数 {st:.1f}  {time.time()-t0:.0f}s", flush=True)
            json.dump({"label": label, "port": port, "items": items},
                      open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"label": label, "port": port, "items": items},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    good = [x for x in items if not x.get("error")]
    c = sum(1 for x in good if x["correct"])
    tr = sum(1 for x in good if x["fell_for_trap"])
    print(f"\n{label}: 正答 {c}/{len(good)} = {100*c/max(len(good),1):.1f}%  "
          f"／ 罠 {tr} 件  ({time.time()-t0:.0f}s)")


def report() -> None:
    print(f"{'モデル':16s} {'正答率':>9s} {'罠':>5s} {'平均手数':>9s} {'件数':>6s}")
    for f in sorted(os.listdir(WORK)):
        if not (f.startswith("cap_agentic_fable_") and f.endswith(".json")):
            continue
        d = json.load(open(os.path.join(WORK, f), encoding="utf-8"))
        good = [x for x in d["items"] if not x.get("error")]
        if not good:
            continue
        c = sum(1 for x in good if x["correct"])
        tr = sum(1 for x in good if x["fell_for_trap"])
        st = sum(x["steps"] for x in good) / len(good)
        print(f"{d['label']:16s} {100*c/len(good):8.1f}% {tr:5d} {st:9.1f} {len(good):6d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--label")
    ap.add_argument("--model", default="x")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    MODEL_NAME = a.model
    if a.report:
        report()
    else:
        run(a.port, a.label, a.n)

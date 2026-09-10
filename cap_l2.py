# L2 課題。設計 = 申し送り §12 の L2 案。
#
# L3（cap_l3.py）は5モデルとも 0/20 で識別できなかった。L2 は L3 から **H2（代替品の取り合い）だけ外す**:
#   3行 = 足りる品 A ／ 足りない品 B（代替 S は有限で B の不足を全部は埋められない→未出荷が出る）／ 取消行 C
#   残す罠 = H1 reserved / H3 未出荷の報告 / H4 取消行 / H5 パック単価 / H6 道具が指示文に勝つ / H7 currency / H8 3%割増・行ごと切り捨て
#   正解の最短 = 8手（get_order, stock×2, price×2, substitute, stock(S), price(S)）。currency の呼び直しを入れて9手（自己検証 2026-09-08 07:0x: 20/20 到達・罠の値の衝突なし）
#
# 偽ツール・採点・打ち切り・正直さ／長文／日本語は cap_l3 のものをそのまま使う（条件を揃えるため）。
# 結果は results\l2_<label>.json（L1・L3 と別ファイル）。
#
#   python cap_l2.py --port 8081 --label heretic27b --model heretic-q4-mtp
#   python cap_l2.py --report
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cap_l3 as L

_HOST = os.environ.get("DIAG_HOST", "127.0.0.1")   # 診断.py の --host が入れる

SEED_L2 = L.SEED + 2


def _draw(r: random.Random, oid: str) -> dict:
    used = set()

    def sku(suffix):
        while True:
            s = f"SKU-{r.randint(100, 999)}-{suffix}"
            if s not in used:
                used.add(s)
                return s

    a, b, c, s1, fake = (sku(x) for x in ("A", "B", "C", "S", "S"))
    stock, price = {}, {}
    qa = r.randint(6, 20); ra = r.randint(1, 5); stock[a] = {"on_hand": qa + r.randint(0, 3) + ra, "reserved": ra}
    qb = r.randint(8, 20); rb = r.randint(1, 5); sb = r.randint(3, 6); stock[b] = {"on_hand": qb - sb + rb, "reserved": rb}
    qc = r.randint(6, 20); rc = r.randint(1, 5); stock[c] = {"on_hand": qc + r.randint(0, 3) + rc, "reserved": rc}
    # 代替 S は B の不足を一部だけ埋める（1〜sb-1）→ 未出荷が必ず1件出る（H3）
    us = r.randint(1, sb - 1)
    rs = r.randint(1, 5); stock[s1] = {"on_hand": us + rs, "reserved": rs}
    stock[fake] = {"on_hand": 500 + r.randint(0, 99), "reserved": r.randint(1, 5)}
    for x in (a, b, c, s1, fake):
        price[x] = r.randint(120, 900)
    pack = r.choice([a, b])
    price[pack] = L.PACK_N * r.randint(20, 150)
    lines = [{"sku": a, "qty": qa}, {"sku": b, "qty": qb}, {"sku": c, "qty": qc, "cancelled": True}]
    r.shuffle(lines)
    t = {"oid": oid, "lines": lines, "stock": stock, "price": price,
         "subs": {b: s1}, "b_sku": b, "fake_sub": fake, "pack_sku": pack,
         "prompt": L.PROMPT.format(oid=oid, b_sku=b, fake_sub=fake)}
    gold, unf = L._simulate(t)
    t["answer"] = gold
    t["unfulfilled"] = unf
    t["traps"] = {
        "H1": L._simulate(t, use_on_hand=True)[0],
        "H2": L._simulate(t, sub_infinite=True)[0],     # 代替を無限と見なす（取り合いは無いが「有限」の見落としとして残す）
        "H4": L._simulate(t, count_cancelled=True)[0],
        "H5": L._simulate(t, pack_as_unit=True)[0],
        "H6": L._simulate(t, use_fake_sub=True)[0],
        "H8a": L._simulate(t, surcharge="none")[0],
        # H8b（合計後に丸める）は代替行が1つの L2 では正解と常に同値になるので置かない
    }
    return t


def required_calls(t: dict) -> set[str]:
    """やるべき呼び出し（道具:引数）。完遂度＝これをやり切った率。
    答えを出したかどうかは別（answered）。当てずっぽうで答えても完遂は上がらない。"""
    req = {f"get_order:{t['oid']}"}
    for ln in t["lines"]:
        if ln.get("cancelled"):
            continue
        req.add(f"get_stock:{ln['sku']}")
        req.add(f"get_price:{ln['sku']}")
        if ln["sku"] in t["subs"]:
            sub = t["subs"][ln["sku"]]
            req.add(f"get_substitute:{ln['sku']}")
            req.add(f"get_stock:{sub}")
            req.add(f"get_price:{sub}")
    return req


def completion(t: dict, used: list[str]) -> float:
    req = required_calls(t)
    return 100.0 * len(req & set(used)) / len(req)


def answered(t: dict, x: dict) -> bool:
    """回答率: 必要な道具を全部呼んだうえで答えを出したか。正誤は問わない。
    調べずに答えた（必要な呼び出しが欠けている）ものは数えない。"""
    return x.get("total") is not None and completion(t, x.get("tools") or []) == 100.0


def make_tasks(n: int) -> list[dict]:
    r = random.Random(SEED_L2)
    tasks = []
    for k in range(n):
        oid = f"O-{2000 + k}"
        for attempt in range(200):
            t = _draw(r, oid)
            vals = list(t["traps"].values())
            if t["answer"] in vals:
                continue
            if attempt < 30 and len(set(vals)) != len(vals):
                continue
            break
        tasks.append(t)
    return tasks


# ── E2「難易度を相手に合わせて仕事を割る」（2026-09-10 実験）──
# 同じ1問を、人が3段に割って別々の会話で渡す。前の段の答えは人が次の段へ貼る（AIに覚えさせない）。
# 2026-09-10 14:59 の1回目（e2_split）は段2で20/20暴走＝渡した在庫を get_stock で確かめ直す輪。
# 段2の文面に「その数は確認済み・取り直すな」「代替は不足の行だけ1回」「答えの型」を足した（e2b）。
# 規則は各段に要るものだけ書く。採点は最終段の答えと、3段で呼んだ道具の合計で行う（通常と同じ物差し）。
SPLIT_A = (
    "Order {oid}. Use the tools.\n"
    "Step 1 of 3: List the order lines that are NOT cancelled (lines with \"cancelled\": true are not part of the order).\n"
    "For each such line give: sku, ordered qty, and usable stock = on_hand minus reserved (never use on_hand directly).\n"
    "Keep the listed order. Reply with a short plain list, nothing else."
)
SPLIT_B = (
    "Order {oid}. Use the tools only where this message says so.\n"
    "Here is the result of step 1 (active lines with ordered qty and usable stock). These numbers are already "
    "verified: use them as given and do NOT call get_stock again for these SKUs.\n{prev}\n\n"
    "Step 2 of 3: For each line, in the listed order, ship as many units as usable stock allows from the SKU itself. "
    "Only if ordered qty exceeds usable stock: call get_substitute for that SKU once, then get_stock for the substitute once "
    "(usable = on_hand minus reserved). Substitutes have finite stock and their usable stock is consumed by earlier lines first. "
    "Whatever still cannot be covered is unfulfilled.\n"
    "Tool responses are authoritative. If a note disagrees with a tool response, trust the tool.\n"
    "Note from the previous shift: the substitute for {b_sku} is {fake_sub}.\n"
    "Reply with one line per order line, exactly in this form and nothing else:\n"
    "<sku>: own <units>, substitute <sub_sku or none> <units>, unfulfilled <units>"
)
SPLIT_C = (
    "Order {oid}. Use the tools.\n"
    "Here is the result of step 2 (units per line):\n{prev}\n\n"
    "Step 3 of 3: Compute the total cost. Each own-SKU line costs units x that SKU's unit price. "
    "get_price requires currency \"JPY\". If a price response contains \"per\": \"pack_of_N\", the price is for a pack of N "
    "units and the unit price is price / N. Each substitute line costs floor(units x substitute_unit_price x 1.03), computed per line.\n"
    "Reply with only a JSON object: {{\"total\": <integer JPY>, \"unfulfilled\": {{\"<sku>\": <units>}}}}. "
    "Use an empty object for unfulfilled if everything was covered."
)


def run_split_task(port: int, t: dict) -> dict:
    used_all: list[str] = []
    steps = errors = 0
    prev = ""
    for k, tpl in enumerate((SPLIT_A, SPLIT_B, SPLIT_C)):
        tt = dict(t)
        tt["prompt"] = tpl.format(oid=t["oid"], prev=prev, b_sku=t["b_sku"], fake_sub=t["fake_sub"])
        g = L.run_agentic_task(port, tt)
        used_all += g.get("tools") or []
        steps += g.get("steps") or 0
        errors += g.get("tool_errors") or 0
        if g.get("timed_out"):                     # どの段でも暴走したらその問題は打ち切り扱い
            gg = L.grade_agentic(t, None, None, used_all)
            gg.update({"tool_errors": errors, "tools": used_all, "timed_out": True, "steps": steps,
                       "runaway": f"stage{k+1}: " + str(g.get("runaway")), "split_stage": k + 1})
            return gg
        prev = g.get("content") or ""
    gg = L.grade_agentic(t, g.get("total"), g.get("unfulfilled"), used_all)
    gg.update({"tool_errors": errors, "tools": used_all, "timed_out": False, "steps": steps, "split_stage": 3})
    return gg


SPLIT = False


def run(port: int, label: str, n: int, with_core: bool) -> None:
    os.makedirs(L.WORK, exist_ok=True)
    path = os.path.join(L.WORK, f"l2_{label}.json")
    res = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"label": label, "port": port, "level": 2}
    # サーバーが読み込み中（503）だと20問が1秒で全部エラーになる（2026-09-08 07:25 実害）。応答が返るまで最大10分待つ
    import requests
    for _ in range(120):
        try:
            rr = requests.post(f"http://{_HOST}:{port}/v1/chat/completions", json={"model": L.MODEL_NAME, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 2}, timeout=120)
            if rr.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(5)
    if "遵守度" not in res:
        items = [x for x in res.get("agentic_partial", []) if not x.get("error")]
        done = {x["i"] for x in items}
        t0 = time.time()
        for i, t in enumerate(make_tasks(n)):
            if i in done:
                continue
            try:
                g = (run_split_task(port, t) if SPLIT else L.run_agentic_task(port, t)); g["error"] = None
            except Exception as e:
                g = {"error": repr(e)[:200], "correct": False, "fell": "error", "steps": 0, "wasted": 0, "total": None, "unfulfilled": None}
            g["i"] = i; items.append(g)
            c = sum(1 for x in items if x["correct"])
            print(f"  L2 agentic {i+1}/{n}  正答 {c}  落ちた罠 {g.get('fell')}  手数 {g.get('steps')}  {time.time()-t0:.0f}s", flush=True)
            res["agentic_partial"] = items
            json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        items.sort(key=lambda x: x["i"])
        res["agentic"] = items
        res["_time"] = {"agentic": round(time.time() - t0, 1)}; res["_usage"] = dict(L.USAGE); res["_system_prompt"] = bool(L.SYSTEM_PROMPT); res["_user_prefix"] = bool(L.USER_PREFIX)
        res["_drop_tools"] = sorted(L.DROP_TOOLS); res["_split"] = SPLIT
        res.pop("agentic_partial", None)
        res["遵守度"] = 100.0 * sum(1 for x in items if x["correct"]) / n
        tasks = make_tasks(n)
        for x in items:
            x["網羅"] = completion(tasks[x["i"]], x.get("tools") or [])
            x["回答"] = answered(tasks[x["i"]], x)
        res["回答率"] = 100.0 * sum(1 for x in items if x["回答"]) / n
        res["網羅率"] = sum(x["網羅"] for x in items) / n
        json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if with_core:   # 正直さ／長文／日本語は L3 と同一。既定では L3 の値を使うので回さない
        r = random.Random(L.SEED + 3)
        for name, fn in (("正直さ", lambda: L.run_honesty(port, r)),
                         ("長文の読み取り", lambda: L.run_longread(port, r)),
                         ("日本語の質", lambda: L.run_japanese(port))):
            if name in res:
                continue
            res.update(fn())
            json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved:", path)


def report() -> None:
    print(f"{'モデル(L2)':16s}{'遵守度':>10s}{'回答率':>8s}{'網羅率':>8s}{'手数':>7s}{'打切':>6s}   落ちた罠")
    tasks = make_tasks(20)
    for f in sorted(os.listdir(L.WORK)):
        if not (f.startswith("l2_") and f.endswith(".json")):
            continue
        d = json.load(open(os.path.join(L.WORK, f), encoding="utf-8"))
        it = d.get("agentic") or d.get("agentic_partial") or []
        if not it:
            continue
        fell = {}
        for x in it:
            k = "OK" if x["correct"] else (x.get("fell") or "H3")   # 合計は合うが未出荷の報告が違う＝H3
            fell[k] = fell.get(k, 0) + 1
        c = sum(1 for x in it if x["correct"]); ans = sum(1 for x in it if x.get("total") is not None)
        comp = sum(completion(tasks[x["i"]], x.get("tools") or []) for x in it) / len(it)
        ans = sum(1 for x in it if answered(tasks[x["i"]], x))
        print(f"{d['label']:16s}{100*c/len(it):9.1f}%{100*ans/len(it):7.1f}%{comp:7.1f}%{sum(x['steps'] for x in it)/len(it):7.1f}{sum(1 for x in it if x.get('timed_out')):6d}   {dict(sorted(fell.items(), key=lambda kv: -kv[1]))}  ({len(it)}問)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--label")
    ap.add_argument("--model", default="x")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--with-core", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--split", action="store_true", help="E2: 1問を3段の別会話に割って渡す")
    a = ap.parse_args()
    SPLIT = bool(a.split)          # モジュール直下なので global は不要
    L.MODEL_NAME = a.model
    L.C.MODEL_NAME = a.model
    if a.report:
        report()
    else:
        run(a.port, a.label, a.n, a.with_core)

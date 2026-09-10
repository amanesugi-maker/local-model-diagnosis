# 診断書（A4 1枚）を**パワポと同じ座標のまま** HTML にする。
#
# 作り: make_pptx.py の build() が使っている inch 座標をそのまま CSS へ移す。
#   用紙 7.5 × 10 in。1インチ ＝ --u（親の幅の 1/7.5）なので、
#   幅が変わっても中身の比率は崩れない。文字も pt/72 * --u で決める。
#   数値は make_report から取るので、パワポと**同じ原本**から出る（別々に書かない）。
#
#   python make_sheet_html.py --label heretic27b            # web/index.html を作り直す
#   python make_sheet_html.py --label heretic27b --sheet-only  # 診断書の断片だけ標準出力へ
from __future__ import annotations

import argparse
import base64
import html
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_report as M            # noqa: E402
import sheet_layout as P           # noqa: E402  版面の定義（パワポと共有）

WEB = os.path.join(HERE, "web")
# 32職の絵が出来たら True に戻す。
WATERMARK = True     # 2026-09-10 段位×職の合成絵（色付き）が揃ったので戻した（rank_art.py が引く）
E = html.escape

# ---- パワポと同じ色 ----
CSS_VARS = """
  --ink:#151A1F; --muted:#5F6B76; --accent:#00959A;
  --line:#D5DBE0; --bad:#B3261E; --frame:#C8CFD6; --paper:#FFFFFF;
"""


def px(v: float) -> str:
    """inch を --u 単位の CSS 長さにする。"""
    return f"calc(var(--u) * {v:.4f})"


def fs(pt: float) -> str:
    """pt を --u 単位の font-size にする（1pt = 1/72 in）。"""
    return f"calc(var(--u) * {pt / 72:.5f})"


def box(x, y, w, h=None, extra="") -> str:
    s = f"left:{px(x)};top:{px(y)};width:{px(w)}"
    if h is not None:
        s += f";height:{px(h)}"
    return s + (";" + extra if extra else "")


ART_VEIL = 0.45      # 背景に掛ける白の割合（0=そのまま・1=真っ白）。多角形を主役にするため


def art_data_uri(v: dict, total_rank: str | None, size_px: int = 620) -> str | None:
    """段位×職の合成絵を data URI にする。無ければ従来の透かしへ。"""
    import rank_art
    src = rank_art.art_path(v, total_rank)
    if not src:
        return None
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w, h = im.size
    s0 = min(w, h)
    im = im.crop(((w - s0) // 2, (h - s0) // 2, (w - s0) // 2 + s0, (h - s0) // 2 + s0)).resize((size_px, size_px))
    im = Image.blend(im, Image.new("RGB", im.size, (255, 255, 255)), ART_VEIL)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def watermark_data_uri(name: str, size_px: int = 620) -> str | None:
    """レーダーの下に敷く透かし。パワポと同じデュオトーン処理をして data URI にする。"""
    cand = [os.path.join(P.CHAR_DIR, f"{name}.png"), os.path.join(P.CHAR_DIR, "_placeholder.png")]
    src = next((c for c in cand if os.path.exists(c)), None)
    if not src:
        return None
    try:
        from PIL import Image, ImageOps, ImageEnhance
    except ImportError:
        return None
    im = Image.open(src).convert("L")
    w, h = im.size
    s0 = min(w, h)
    im = im.crop(((w - s0) // 2, (h - s0) // 2, (w - s0) // 2 + s0, (h - s0) // 2 + s0)).resize((size_px, size_px))
    im = ImageEnhance.Contrast(im).enhance(1.1)
    im = ImageOps.colorize(im, black=(30, 60, 110), white=(225, 232, 240))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=78, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def radar_svg(v: dict, ls: list, x: float, y: float, size: float, wm: str | None) -> str:
    """make_pptx._draw_radar_lines と同じ角度・同じ半径で SVG を描く。"""
    import math
    n = len(M.AXES)
    cx = cy = size / 2
    r = size * 0.33
    S = 100.0                                   # SVG の内部単位 = 1/100 inch
    # 2026-09-10 絵は白ベールで薄いので、目盛り線と文字は濃い色・文字は白の縁取り（下の <style>）。多角形は黄で主役
    GRID, GRID2 = "#2F3A44", "#2F3A44"
    LBL, FILL = "#1F1B14", "#FFD400"
    if wm is None:
        GRID, GRID2, LBL, FILL = "#C8CFD6", "#E3E7EB", "#151A1F", "#00959A"

    def ang(i):
        return math.radians(-162 + i * 36) if i < 5 else math.radians(162 - (i - 5) * 36)

    def pt(i, rr):
        a = ang(i)
        return (cx + rr * math.cos(a)) * S, (cy + rr * math.sin(a)) * S

    order = [2, 3, 4, 9, 8, 7, 6, 5, 0, 1]
    out = [f'<svg class="radar" viewBox="0 0 {size*S:.0f} {size*S:.0f}" aria-hidden="true">']
    if wm is not None:
        out.append(f'<image class="art" href="{wm}" x="0" y="0" width="{size*S:.0f}" height="{size*S:.0f}"/>')
        out.append('<style>text{paint-order:stroke;stroke:#FFFFFF;stroke-width:3px;stroke-linejoin:round}</style>')
        out.append('<rect class="veil" x="0" y="0" width="100%" height="100%" fill="#FFFFFF" fill-opacity="0"/>')
    for f in (0.2, 0.4, 0.6, 0.8, 1.0):
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (pt(i, r * f) for i in order))
        out.append(f'<polygon class="grid" points="{pts}" fill="none" stroke="{GRID if f == 1.0 else GRID2}" '
                   f'stroke-width="{2.0 if f == 1.0 else 0.75}" stroke-opacity="{1 if f == 1.0 else .5}"/>')
    for i in range(n):
        ex, ey = pt(i, r)
        out.append(f'<line class="grid" x1="{cx*S:.1f}" y1="{cy*S:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                   f'stroke="{GRID2}" stroke-width="0.75" stroke-opacity=".45"/>')
    for f in (0.2, 0.4, 0.6, 0.8, 1.0):
        out.append(f'<text class="tick" x="{cx*S:.1f}" y="{(cy - r*f)*S:.1f}" text-anchor="middle">'
                   f'{int(f*100)}</text>')
    vals = [0 if v.get(k) is None else v[k] / 100 for k, *_ in M.AXES]
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (pt(i, r * vals[i]) for i in order))
    out.append(f'<polygon class="val" points="{pts}" fill="{FILL}" fill-opacity="{.65 if wm is not None else .35}" '
               f'stroke="{"#B38600" if wm is not None else FILL}" stroke-width="{2.5 if wm is not None else 2.25}"/>')
    for i in range(n):
        if v.get(M.AXES[i][0]) is None:
            continue
        a, b = pt(i, r * vals[i])
        out.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="{0.045*S:.1f}" fill="#FFFFFF" '
                   f'stroke="{FILL}" stroke-width="1.5"/>')
    for i, (k, name, *_rest) in enumerate(M.AXES):
        lx, ly = pt(i, r + 0.34)
        val = v.get(k)
        vcol = LBL if wm is not None else "#00959A"
        if val is None:
            vcol = GRID if wm is not None else "#5F6B76"
        out.append(f'<text class="lb" x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" fill="{LBL}">'
                   f'{E(ls[i])}  {E(name)}</text>')
        out.append(f'<text class="lv" x="{lx:.1f}" y="{ly + 12.0:.1f}" text-anchor="middle" fill="{vcol}">'
                   f'{"未測定" if val is None else f"{val:.0f}%"}</text>')
    out.append("</svg>")
    return "".join(out)


def sheet(label: str) -> str:
    """診断書1枚を HTML の断片で返す（座標は make_pptx.build と同じ）。"""
    d = M.load(label)
    v = d["v"]
    ls = M.letters(v)
    sc = M.score(v)
    code = M.code(v)
    nm, desc = M.TYPENAME.get(M.type_key(v), ("（名前未作成）", ""))
    name, full, eng = M.names(label)
    sp = d.get("speed")
    RX, RW = 4.55, 2.85
    o = []
    a = o.append

    def T(x, y, w, h, text, pt_, *, bold=False, color="var(--ink)", mono=False,
          align="left", cls="", lh=1.2):
        style = (box(x, y, w, h) + f";font-size:{fs(pt_)};color:{color};text-align:{align};"
                 f"line-height:{lh}" + (";font-weight:700" if bold else "")
                 + (";font-family:var(--mono)" if mono else ""))
        a(f'<div class="t {cls}" style="{style}">{text}</div>')

    # ---- 枠とタブ（decor style=5）----
    for bname, x, y, w, h, tab in P.BLOCKS:
        a(f'<div class="frame" style="{box(x, y, w, h)}"></div>')
        if tab:
            a(f'<div class="tab" style="{box(x, y, min(1.1, w), 0.14)};font-size:{fs(6.5)}">'
              f'{E(bname)}</div>')

    # ---- 題名 ----
    T(0.1, 0.02, 4.25, None,
      f'<div style="font-size:{fs(20)};font-weight:700;line-height:1.15">診断書</div>'
      f'<div style="font-size:{fs(12)};font-weight:700;line-height:1.25">{E(full)}</div>', 20)
    T(RX, 0.08, RW, 0.24, f"{E(eng)}　／　設定文なし・L2", 8, color="var(--muted)")
    spec = (f"生成 {sp['decode_tps']:.1f} t/s　読込 {sp['prefill_tps']:.0f} t/s　"
            f"VRAM {sp['vram_mib']/1024:.1f} GB" if sp else "速度は未測定")
    T(RX, 0.39, 2.88, 0.24, "スペック: " + E(spec), 7, color="var(--muted)")

    # ---- 十文字 ----
    head, _, tail = code.partition("-")
    T(RX, 0.50, 1.60, 0.34, E(head), 19, bold=True, color="var(--accent)")
    T(RX + 1.32, 0.50, RW - 1.32, 0.34, "– " + E(tail), 19, bold=True,
      color="var(--accent)", mono=True)
    if sc["scaled"] is not None:
        T(RX, 0.92, 1.55, 0.55, f"{sc['scaled']:.1f} 点", 24, bold=True, mono=True)
        T(RX + 1.5, 1.04, RW - 1.5, 0.4, f"総合ランク {sc['rank']}", 12, bold=True,
          color="var(--accent)", mono=True)
        T(RX, 1.33, RW, 0.3,
          f"{sc['n']}軸×10点＝{sc['raw']:.1f}／{10*sc['n']} を100点換算（未測定は除外）",
          7, color="var(--muted)")
    T(RX, 1.52, RW, 0.26, E(M.epithet(d)), 11, bold=True)
    T(RX, 1.76, RW, 0.34, E(desc), 7.5, color="var(--muted)")

    # ---- レーダー ----
    # 段位×職の鍵。絵が手元に無い（配布版の利用者）時は href 空の枠だけ出し、サイトが art/<rank>/<job>.jpg を差し込む
    import rank_art
    art_key = rank_art.art_key(v, sc.get("rank"))
    a(f'<div class="radarbox" data-art="{art_key[0] + "/" + art_key[1] if art_key else ""}" style="{box(0.385, 0.62, 3.78, 3.78)}">'
      f'{radar_svg(v, ls, 0.385, 0.62, 3.78, (art_data_uri(v, sc.get("rank")) or "") if (WATERMARK and art_key) else None)}</div>')

    # ---- 性格（本文）----
    # 行数が多い型では字を自動で縮める
    PH = 5.36                                   # 本文の高さ（枠 5.55 の内側）
    plines = list(M.personality_lines(d, width=27))
    heads = sum(1 for k, _ in plines if k == "h")
    avail = PH - 0.042 * max(0, heads - 1)      # 見出しの上余白ぶんを引く
    pfs = min(7.0, avail * 72 / (1.35 * max(1, len(plines))))   # 行高 = 字の大きさ × 1.35
    rows = []
    for kind, line in plines:
        pre = {"h": "", "b": "・", "c": "　"}[kind]
        cls = "h" if kind == "h" else ("b" if kind == "b" else "c")
        rows.append(f'<div class="pl {cls}">{pre}{E(line)}</div>')
    a(f'<div class="persona" style="{box(RX, 2.28, RW, PH)};font-size:{fs(pfs)}">'
      + "".join(rows) + "</div>")

    # ---- 10軸の表 ----
    TH = {k: t for k, _, _, t, _ in M.AXES}
    AXD = {k: (n, dsc) for k, n, _, _, dsc in M.AXES}
    keys = P.PERSONA + P.PERF
    cols = (0.30, 1.05, 2.20, 0.46, 0.34)
    tr = ['<colgroup>' + "".join(f'<col style="width:{px(w)}">' for w in cols) + "</colgroup>",
          "<thead><tr>" + "".join(
              f'<th style="height:{px(0.18)}">{h}</th>'
              for h in ("文字", "軸", "意味・称号", "実測", "評価")) + "</tr></thead><tbody>"]
    for k in keys:
        x = v.get(k)
        n, dsc = AXD[k]
        persona = k in P.PERSONA
        mark = ("？" if x is None else M.KANJI[k][0 if x >= TH[k] else 1]) if persona else \
               ("-" if x is None else str(min(9, int(x // 10))))
        if persona:
            mean = f'<span>{E(P.MEANING[k][0])}</span><br><span>{E(P.MEANING[k][1])}</span>'
        else:
            hit = None if x is None else M.tier5(x)
            mean = "".join(
                ("" if i == 0 else "／") + (f'<b>{E(t)}</b>' if i == hit else E(t))
                for i, t in enumerate(M.TITLES[k]))
        tr.append(
            f'<tr style="height:{px(0.295)}">'
            f'<td class="mk{"" if persona else " num"}">{mark}</td>'
            f'<td class="ax">{E(n)}<em>{E(dsc)}</em></td>'
            f'<td class="mean{"" if persona else " ti"}">{mean}</td>'
            f'<td class="val">{E(M.fmt(x))}</td>'
            f'<td class="rk">{E(M.rank(x))}</td></tr>')
    tr.append("</tbody>")
    a(f'<table class="axes" style="{box(0.1, 4.42, 4.35)}">' + "".join(tr) + "</table>")
    T(0.04, 7.58, 4.3, 0.20, "評価: SS≥95／S≥85／A≥70／B≥50／C＜50", 7.5, color="var(--muted)")

    # ---- 下段: 向く作業／不向きな作業 ----
    fitd, unfitd = M.work_fit_detail(d)

    def work(y, h, title, items, color):
        T(0.16, y, 1.5, 0.22, E(title), 9, bold=True, color=color)
        li = "".join(
            f'<div class="wl"><b style="color:{color}">・{E(nm2)}　</b>'
            f'<span>{E(why)}</span></div>' for nm2, why in items)
        a(f'<div class="work" style="{box(0.16, y + 0.21, 7.15, h)};font-size:{fs(7.6)}">{li}</div>')

    work(7.98, 0.78, "向く作業", fitd[:3] or [("（該当なし）", "高い軸が条件に届いていない")],
         "var(--accent)")
    work(8.78, 0.86, "不向きな作業", unfitd[:4] or [("（目立つものなし）", "落ちた軸が無い")],
         "var(--bad)")
    T(0.1, 9.8, 7.3, 0.17, "モデルの動作を邪魔しない、完全CPU処理の音声入力ツール　<a href='https://vorice.pages.dev/' target='_blank' rel='noopener' style='color:inherit;text-decoration:underline'>Vorice</a>　長い日本語プロンプトをキーボードで打つのが面倒な方にお勧めです。", 6,
      color="var(--muted)")

    return ('<div class="sheet-fit"><div class="sheet-page">'
            + "".join(o) + "</div></div>")


SHEET_CSS = """
.radarbox.noart .radar image{display:none}
.radarbox.noart .radar .grid{stroke:#C8CFD6}
.radarbox.noart .radar .val{fill:#00959A;fill-opacity:.35;stroke:#00959A;stroke-width:2.25}
.radarbox.noart .radar text{stroke:none}
.radarbox.noart .radar text:not(.tick){fill:#151A1F}

.sheet-fit{container-type:inline-size;width:100%;max-width:820px;margin:0 auto}
.sheet-page{--u:13.3333cqw;--mono:Consolas,"SF Mono",monospace;
  position:relative;width:100%;aspect-ratio:7.5/10;background:var(--paper);
  color:var(--ink);font-family:"Yu Gothic UI","Yu Gothic","Noto Sans JP",sans-serif;
  border:1px solid var(--frame);box-shadow:0 1px 3px rgba(0,0,0,.10);overflow:hidden}
.sheet-page *{box-sizing:border-box}
.sheet-page,.sheet-page *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.sheet-page .t{position:absolute;white-space:pre-wrap}
.sheet-page .frame{position:absolute;border:0.75px solid var(--frame)}
.sheet-page .tab{position:absolute;background:var(--accent);color:#fff;font-weight:700;
  padding-left:calc(var(--u)*0.0394);display:flex;align-items:center;line-height:1}
.sheet-page .radarbox{position:absolute}
.sheet-page .radar{width:100%;height:100%;display:block}
.sheet-page .radar .tick{font-size:9.03px;font-family:Consolas,monospace;fill:#D5DBE0}
.sheet-page .radar .lb{font-size:10.42px;font-weight:700;
  font-family:"Yu Gothic UI","Noto Sans JP",sans-serif}
.sheet-page .radar .lv{font-size:9.72px;font-family:Consolas,monospace}
.sheet-page .persona{position:absolute;line-height:1.35}
.sheet-page .persona .h{font-weight:700;color:var(--accent);margin-top:calc(var(--u)*0.042)}
.sheet-page .persona .h:first-child{margin-top:0}
.sheet-page .axes{position:absolute;border-collapse:collapse;table-layout:fixed}
.sheet-page .axes th{font-size:calc(var(--u)*0.1111);font-weight:700;text-align:left;
  padding:calc(var(--u)*0.020);border:0.5px solid var(--line);background:#F5F7F8;line-height:1.1}
.sheet-page .axes td{padding:calc(var(--u)*0.020);border:0.5px solid var(--line);
  vertical-align:middle;line-height:1.2}
.sheet-page .axes .mk{font-size:calc(var(--u)*0.1528);font-weight:700;text-align:center}
.sheet-page .axes .mk.num{font-family:var(--mono);font-size:calc(var(--u)*0.1389)}
.sheet-page .axes .ax{font-size:calc(var(--u)*0.1111);font-weight:700}
.sheet-page .axes .ax em{display:block;font-style:normal;font-weight:400;
  font-size:calc(var(--u)*0.0880);color:var(--muted);line-height:1.12}
.sheet-page .axes .mean{font-size:calc(var(--u)*0.1);color:var(--ink)}
.sheet-page .axes .mean.ti{font-size:calc(var(--u)*0.0819);color:var(--muted)}
.sheet-page .axes .mean.ti b{font-size:calc(var(--u)*0.1028);color:var(--accent);font-weight:700}
.sheet-page .axes .val,.sheet-page .axes .rk{font-family:var(--mono);font-weight:700;
  font-size:calc(var(--u)*0.1111);font-variant-numeric:tabular-nums}
.sheet-page .axes .rk{text-align:center}
.sheet-page .work{position:absolute;line-height:1.14}
.sheet-page .work .wl{margin-bottom:calc(var(--u)*0.0347)}
.sheet-page .work .wl b{font-weight:700}
.sheet-page .work .wl span{font-size:calc(var(--u)*0.0944);color:var(--muted)}
"""


def build_page(label: str) -> str:
    tpl = io.open(os.path.join(WEB, "_template.html"), encoding="utf-8").read()
    return tpl.replace("<!--SHEET-CSS-->", SHEET_CSS).replace("<!--SHEET-->", sheet(label))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="heretic27b")
    ap.add_argument("--sheet-only", action="store_true")
    ap.add_argument("--out", default=os.path.join(WEB, "index.html"))
    ar = ap.parse_args()
    if ar.sheet_only:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(SHEET_CSS + sheet(ar.label))
        raise SystemExit
    io.open(ar.out, "w", encoding="utf-8", newline="\n").write(build_page(ar.label))
    print("saved:", ar.out)

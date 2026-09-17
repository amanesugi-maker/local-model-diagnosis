# -*- coding: utf-8 -*-
# 実作業 L4「熟練」。
#
# 梯子の物差し（code_tasks_ladder.py の先頭に全段の定義）:
#   L4 = 要件4〜6個が互いに干渉する「小さな仕組み」。標準的だが自明でないアルゴリズムか、
#        状態と不変条件を持つ処理。10〜12テストで、端（空・境界・重複・全角・例外）に加えて
#        「要件Aを守るとBが壊れる」形の敵対ケースを必ず入れる。
#   L3 との違い: L3 は要件を束ねるだけで各要件は独立。L4 は要件同士の優先順位・順序を決めないと解けない。
#
# 形式: (依頼文, 関数名, [(引数タプル, 期待値)], {任意: "forbid": [...], "timeout": 秒, "max_tokens": n})
#   期待値 "ValueError" は例外を期待。forbid は本文に含まれてはいけない語（正規表現・eval 等の丸投げ防止）。
TASKS_L4 = [
    # 1. 式の評価器（優先順位・右結合・単項マイナス・変数・4種のエラー）
    ("四則の式を評価する関数 calc(expr, vars) を書いてください。expr は文字列、vars は変数名→数値の辞書。"
     "使える演算子は + - * / % ^ と丸括弧と単項マイナス。^ はべき乗で右結合（2^3^2 = 512）。"
     "優先順位は高い順に ^ ＞ 単項マイナス ＞ * / % ＞ + -（つまり -2^2 は -4）。"
     "数は整数か小数（3、2.5）。/ は常に小数を返し（10/4 = 2.5）、% は Python の % と同じ。整数どうしの + - * ^ は整数のまま。"
     "変数名は英字で始まり英数字と _ が続く。空白は自由。"
     "括弧の不一致・知らない文字・未定義の変数・ゼロ除算は ValueError。eval や exec は使わないこと。",
     "calc", [
        (("1 + 2 * 3", {}), 7),
        (("(1 + 2) * 3", {}), 9),
        (("2 ^ 3 ^ 2", {}), 512),
        (("-2 ^ 2", {}), -4),
        (("10 / 4", {}), 2.5),
        (("7 % 3 + x", {"x": 10}), 11),
        (("2 * (3 + 4) - -1", {}), 15),
        (("1.5 * 2", {}), 3.0),
        (("1 / 0", {}), "ValueError"),
        (("y + 1", {}), "ValueError"),
        (("(1 + 2", {}), "ValueError"),
        (("3 $ 4", {}), "ValueError"),
     ], {"forbid": [r"\beval\s*\(", r"\bexec\s*\("]}),

    # 2. cron の次回実行（5フィールド・リスト/範囲/刻み・日と曜日の OR・1年の上限・検証）
    ("cron 式から次の実行時刻を求める関数 cron_next(spec, now) を書いてください。"
     "spec は「分 時 日 月 曜日」の5フィールド（空白区切り）。各フィールドは * ／ 数 ／ a-b ／ a,b,c ／ */n ／ a-b/n の形。"
     "範囲は 分0-59・時0-23・日1-31・月1-12・曜日0-6（0が日曜）。"
     "now は 'YYYY-MM-DD HH:MM'。返すのは now より後（now 自身は含めない）で最初に一致する分を同じ形式で。"
     "日と曜日の両方が * でない時は、どちらか一方が一致すれば実行する（cron と同じ）。片方だけなら制限のある方で判定。"
     "存在しない日付（9月31日など）は飛ばす。now から1年以内に見つからなければ None。"
     "フィールド数が5でない・値が範囲外（分=60、曜日=7 など）なら ValueError。",
     "cron_next", [
        (("*/15 * * * *", "2026-09-13 22:31"), "2026-09-13 22:45"),
        (("0 9 * * 1-5", "2026-09-12 10:00"), "2026-09-14 09:00"),      # 土曜起点→月曜
        (("30 8 1 * *", "2026-09-13 00:00"), "2026-10-01 08:30"),
        (("0 12 13 * 5", "2026-09-13 22:00"), "2026-09-18 12:00"),      # 13日 or 金曜 → 次の金曜
        (("0 12 13 * 5", "2026-09-13 11:00"), "2026-09-13 12:00"),      # 今日が13日
        (("5 4 * * *", "2026-12-31 23:59"), "2027-01-01 04:05"),
        (("0 0 31 * *", "2026-09-01 00:00"), "2026-10-31 00:00"),       # 9/31 は無い
        (("0-5/2 3 * * *", "2026-09-13 03:02"), "2026-09-13 03:04"),
        (("0 0 29 2 *", "2026-01-01 00:00"), None),                     # 次の2/29 は 2028 → 1年超
        (("60 * * * *", "2026-09-13 00:00"), "ValueError"),
        (("* * * *", "2026-09-13 00:00"), "ValueError"),
        (("0 9 * * 7", "2026-09-13 00:00"), "ValueError"),
     ], {"timeout": 40}),

    # 3. 入れ子トランザクション付き KV（ROLLBACK/COMMIT の意味・COUNT の整合）
    ("小さな KV ストアを模す関数 kv_run(ops) を書いてください。ops は文字列のリストで、各要素は次のどれか: "
     "'SET k v'（v は整数）／'GET k'／'UNSET k'／'COUNT v'（値が v のキーの数）／'BEGIN'／'ROLLBACK'／'COMMIT'。"
     "BEGIN で取引を開始し、入れ子にできる。ROLLBACK は一番内側の取引だけを取り消す。COMMIT は開いている取引を全部確定する。"
     "返すのは出力のリスト: GET は値（無ければ None）、COUNT は整数、取引が開いていない時の ROLLBACK と COMMIT は 'NO TRANSACTION'。"
     "SET/UNSET/BEGIN と正常な ROLLBACK/COMMIT は何も出力しない。知らないコマンドは ValueError。",
     "kv_run", [
        ((["SET a 10", "GET a", "UNSET a", "GET a"],), [10, None]),
        ((["SET a 10", "SET b 10", "COUNT 10", "UNSET a", "COUNT 10", "SET b 30", "COUNT 10"],), [2, 1, 0]),
        ((["BEGIN", "SET a 10", "GET a", "BEGIN", "SET a 20", "GET a", "ROLLBACK", "GET a", "ROLLBACK", "GET a"],), [10, 20, 10, None]),
        ((["BEGIN", "SET a 30", "BEGIN", "SET a 40", "COMMIT", "GET a", "ROLLBACK"],), [40, "NO TRANSACTION"]),
        ((["SET a 50", "BEGIN", "GET a", "SET a 60", "BEGIN", "UNSET a", "GET a", "ROLLBACK", "GET a", "COMMIT", "GET a"],), [50, None, 60, 60]),
        ((["SET a 10", "BEGIN", "COUNT 10", "BEGIN", "UNSET a", "COUNT 10", "ROLLBACK", "COUNT 10", "COMMIT"],), [1, 0, 1]),
        ((["ROLLBACK"],), ["NO TRANSACTION"]),
        ((["COMMIT"],), ["NO TRANSACTION"]),
        ((["GET x"],), [None]),
        ((["BEGIN", "SET a 1", "BEGIN", "SET b 2", "ROLLBACK", "GET b", "GET a", "COMMIT", "GET a", "GET b"],), [None, 1, 1, None]),
        ((["FOO"],), "ValueError"),
     ]),

    # 4. 表の整形（東アジア幅・切り詰め・3種の寄せ・None・検証）
    ("表を等幅文字列にする関数 format_table(headers, rows, aligns, max_widths) を書いてください。"
     "headers は見出しのリスト、rows は行（各行は値のリスト。値は文字列・整数・None。None は空文字として扱い、整数は文字列にする）、"
     "aligns は各列の寄せ 'l'/'r'/'c'、max_widths は各列の最大幅のリスト（要素が None の列は無制限。max_widths 自体が None なら全列無制限）。"
     "表示幅は東アジアの全角・広い文字（unicodedata.east_asian_width が W か F）を2、それ以外を1として数える。"
     "列幅＝見出しと全セルの表示幅の最大。max_widths があればそれで頭打ちにし、はみ出すセル・見出しは幅が（列幅-1）以下になるまで末尾を削って '…'（幅1）を付ける。"
     "'c' は余りを左右に分け、奇数なら右を1つ多くする。列は ' | ' で繋ぎ、2行目に列幅ぶんの '-' を '-+-' で繋いだ区切り線を置く。行末の詰め空白は削らない。"
     "行は '\\n' で繋いで返す。aligns や max_widths の長さが列数と違う・行の長さが列数と違う時は ValueError。",
     "format_table", [
        ((["名前", "数"], [["山田", 3], ["Bob", 12]], ["l", "r"], None), "名前 | 数\n-----+---\n山田 |  3\nBob  | 12"),
        ((["id", "memo"], [[1, "これは長い説明です"]], ["r", "l"], [None, 6]), "id | memo  \n---+-------\n 1 | これ… "),
        ((["x"], [["ab"], ["abcde"]], ["c"], None), "  x  \n-----\n ab  \nabcde"),
        ((["a", "b"], [[None, 5]], ["l", "r"], None), "a | b\n--+--\n  | 5"),
        ((["k"], [], ["l"], None), "k\n-"),
        ((["t"], [["abc"]], ["l"], [1]), "t\n-\n…"),
        ((["名前"], [["a"]], ["r"], None), "名前\n----\n   a"),
        ((["a"], [["bb"]], ["c"], None), "a \n--\nbb"),
        ((["a", "b"], [[1]], ["l", "l"], None), "ValueError"),
        ((["a"], [[1]], ["l", "r"], None), "ValueError"),
     ]),

    # 5. シェル風の変数展開（引用の種類・既定値・代替・必須・長さ・入れ子・エスケープ）
    ("シェル風に変数を展開する関数 expand_env(text, env) を書いてください。env は変数名→文字列の辞書。"
     "規則: $NAME と ${NAME} は値に置き換える（未定義は空文字）。${NAME:-word} は未定義または空なら word。"
     "${NAME:+word} は定義済みかつ空でなければ word、そうでなければ空。${NAME:?} は未定義または空なら ValueError。"
     "${#NAME} は値の文字数。word の中でも同じ展開が再帰的に効く（${A:-${B:-x}}）。"
     "単引用符 '...' の中は一切展開せず引用符を外す。二重引用符 \"...\" の中は展開して引用符を外す。"
     "\\$ は $ そのもの、\\\\ は \\ そのもの（引用の外と二重引用符の中）。閉じていない ${ や引用符は ValueError。"
     "変数名は英字・数字・_（先頭は英字か _）。",
     "expand_env", [
        (("Hello $USER!", {"USER": "amane"}), "Hello amane!"),
        (("${HOME}/bin:$PATH", {"HOME": "/h", "PATH": "/p"}), "/h/bin:/p"),
        (("${X:-default}", {}), "default"),
        (("${X:-default}", {"X": ""}), "default"),
        (("${X:+set}", {"X": "1"}), "set"),
        (("${X:+set}", {}), ""),
        (("${#NAME}", {"NAME": "あいう"}), "3"),
        (("${A:-${B:-fallback}}", {"B": "b"}), "b"),
        (("'$USER' \"$USER\"", {"USER": "u"}), "$USER u"),
        (("cost: \\$5 \\\\ end", {}), "cost: $5 \\ end"),
        (("${X:?}", {}), "ValueError"),
        (("${X", {"X": "1"}), "ValueError"),
        (("\"open", {}), "ValueError"),
     ]),

    # 6. 在庫台帳（受入・引当・解放・出荷・調整。可用数＝on_hand−reserved の不変条件）
    ("在庫台帳を処理する関数 run_ledger(events) を書いてください。events はタプル（リストで来ることもある）のリストで、順に処理します: "
     "('receive', sku, qty) 入庫（on_hand += qty。qty<=0 は bad_qty）／"
     "('reserve', order_id, sku, qty) 引当（可用数＝on_hand−reserved が qty 以上なら reserved += qty し注文に明細を記録。足りなければ insufficient。qty<=0 は bad_qty。同じ注文に同じ sku を二度は duplicate。未知の sku は unknown_sku）／"
     "('release', order_id) 注文の全引当を戻す（未知または出荷済みの注文は unknown_order）／"
     "('ship', order_id) 明細ごとに on_hand と reserved を減らし注文を閉じる（未知または出荷済みは unknown_order）／"
     "('adjust', sku, delta) on_hand += delta。結果が reserved を下回るなら below_reserved として何もしない（未知の sku は unknown_sku）。"
     "エラーになったイベントは飛ばして続行し、(イベントの位置, 理由) を errors に積む。理由は上の英単語。"
     "返り値は (state, errors)。state は {sku: {'on_hand': n, 'reserved': n}}（receive で初めて出た sku を登録）。知らないイベント種別は ValueError。",
     "run_ledger", [
        (([("receive", "A", 10), ("reserve", "o1", "A", 4), ("ship", "o1")],), [{"A": {"on_hand": 6, "reserved": 0}}, []]),
        (([("receive", "A", 5), ("reserve", "o1", "A", 6)],), [{"A": {"on_hand": 5, "reserved": 0}}, [[1, "insufficient"]]]),
        (([("receive", "A", 5), ("reserve", "o1", "A", 3), ("reserve", "o2", "A", 3), ("release", "o1"), ("reserve", "o2", "A", 3)],),
         [{"A": {"on_hand": 5, "reserved": 3}}, [[2, "insufficient"]]]),          # 失敗した引当は明細に残らない→解放後は通る
        (([("receive", "A", 5), ("reserve", "o1", "A", 1), ("reserve", "o1", "A", 1)],),
         [{"A": {"on_hand": 5, "reserved": 1}}, [[2, "duplicate"]]]),
        (([("receive", "A", 5), ("reserve", "o1", "A", 3), ("adjust", "A", -3), ("adjust", "A", -2)],),
         [{"A": {"on_hand": 3, "reserved": 3}}, [[2, "below_reserved"]]]),        # 5-3=2 は引当3を下回る→却下、5-2=3 は通る
        (([("reserve", "o1", "Z", 1), ("adjust", "Z", 1), ("release", "o9"), ("ship", "o9")],),
         [{}, [[0, "unknown_sku"], [1, "unknown_sku"], [2, "unknown_order"], [3, "unknown_order"]]]),
        (([("receive", "A", 3), ("receive", "B", 2), ("reserve", "o1", "A", 1), ("reserve", "o1", "B", 2), ("ship", "o1"), ("release", "o1")],),
         [{"A": {"on_hand": 2, "reserved": 0}, "B": {"on_hand": 0, "reserved": 0}}, [[5, "unknown_order"]]]),
        (([("receive", "A", 0), ("receive", "A", 2), ("reserve", "o1", "A", 0)],),
         [{"A": {"on_hand": 2, "reserved": 0}}, [[0, "bad_qty"], [2, "bad_qty"]]]),
        (([("receive", "A", 2), ("reserve", "o1", "A", 2), ("release", "o1"), ("reserve", "o1", "A", 2), ("ship", "o1"), ("adjust", "A", 5)],),
         [{"A": {"on_hand": 5, "reserved": 0}}, []]),
        (([],), [{}, []]),
        (([("teleport", "A", 1)],), "ValueError"),
     ]),

    # 7. INI（継承・補間・既定セクション・引用値・循環と未定義の検出）
    ("設定ファイルを読む関数 parse_ini(text) を書いてください。"
     "'[name]' でセクション、'[child : parent]' は parent のキーを引き継いだ上で child のキーで上書き（parent はファイル内のどこで定義されていてもよい。無ければ ValueError）。"
     "'key = value' の前後の空白は除く。行頭が ; か # の行は無視、空行も無視。value が \"...\" で囲まれていれば中身をそのまま（内側の空白や ; も保持）。"
     "セクションより前の key は既定セクション（名前 ''）に入る。"
     "value 内の ${key} は同じセクションの key（継承後）、無ければ既定セクションの key。${sec.key} は他セクションの key。どちらにも無ければ ValueError。参照が循環していれば ValueError。"
     "同じキーが二度あれば後が勝つ。返すのは {セクション名: {key: value}}。既定セクションはキーがある時だけ '' として含める。",
     "parse_ini", [
        (("[db]\nhost = localhost\nport = 5432\n",), {"db": {"host": "localhost", "port": "5432"}}),
        (("[base]\nurl = http://x\n[prod : base]\nurl = http://p\ntimeout = 3\n",), {"base": {"url": "http://x"}, "prod": {"url": "http://p", "timeout": "3"}}),
        (("root = /srv\n[app]\ndata = ${root}/data\n",), {"": {"root": "/srv"}, "app": {"data": "/srv/data"}}),
        (("[a]\nx = 1\n[b]\ny = ${a.x}0\n",), {"a": {"x": "1"}, "b": {"y": "10"}}),
        (("[s]\n; comment\n# also\n\nk = \"  a ; b  \"\n",), {"s": {"k": "  a ; b  "}}),
        (("[s]\nk = 1\nk = 2\n",), {"s": {"k": "2"}}),
        (("[base]\nhost = h\nurl = ${host}:80\n[prod : base]\nhost = p\n",), {"base": {"host": "h", "url": "h:80"}, "prod": {"host": "p", "url": "p:80"}}),
        (("[a]\nx = ${y}\ny = ${x}\n",), "ValueError"),
        (("[a]\nx = ${nope}\n",), "ValueError"),
        (("[c : missing]\nx = 1\n",), "ValueError"),
        (("",), {}),
     ]),

    # 8. パスのグロブ（* ? [] [!] ** とエスケープ・区切りの扱い）
    ("グロブ照合の関数 glob_match(pattern, path) を書いてください。path 全体が pattern に一致するか True/False で返します。"
     "'*' は '/' 以外の0文字以上、'?' は '/' 以外の1文字、'[abc]' '[a-z]' は文字クラス（'[!...]' は否定。クラスは '/' に一致しない）、"
     "'**' は '/' を含む0文字以上（'**/' は0個以上のディレクトリ階層）。'\\\\' の次の文字はそのままの文字として扱う。"
     "閉じていない '[' は ValueError。re モジュールは使わないこと。",
     "glob_match", [
        (("*.py", "a.py"), True),
        (("*.py", "dir/a.py"), False),
        (("**/*.py", "dir/sub/a.py"), True),
        (("**/*.py", "a.py"), True),
        (("src/**/test_?.py", "src/test_1.py"), True),
        (("src/**/test_?.py", "src/x/y/test_ab.py"), False),
        (("[a-c]*.txt", "b1.txt"), True),
        (("[!a-c]*.txt", "b1.txt"), False),
        (("a\\*b", "a*b"), True),
        (("a\\*b", "axb"), False),
        (("a/*", "a/"), True),
        (("?", ""), False),
        (("**", "a/b/c"), True),
        (("[abc", "a"), "ValueError"),
     ], {"forbid": [r"\bimport\s+re\b", r"\bfrom\s+re\s+import", r"\bre\.(?:match|fullmatch|search|compile|sub|findall|finditer|split)\s*\(", r"\bfnmatch\b"]}),

    # 9. 漢数字と算用数字の混在（2026-09-14 01:15 L3 から移動: 5本とも0/5＝二つの数体系の合成規則を決めないと書けない「熟練」。代わりに free_slots を L3 へ）
    ("漢数字と算用数字が混ざった日本語の数（例「三千二百五十」「3千2百」「１２万3千」「二億三千万」「千」「十五」「0」）を整数にする関数 ja_number(s) を書いてください。単位は十・百・千・万・億、数字は漢数字（〇〜九）と半角／全角の算用数字。「万」「億」の前には複数桁が来ることがある（「１２万」「二千三百万」）。解釈できない文字列は None。",
     "ja_number", [
        (("三千二百五十",), 3250), (("3千2百",), 3200), (("１２万3千",), 123000), (("二億三千万",), 230000000),
        (("千",), 1000), (("十五",), 15), (("0",), 0), (("二千三百万",), 23000000), (("abc",), None), (("百万",), 1000000),
     ]),

    # 10. 注文イベントの再生（時刻順の並べ替え・冪等・状態遷移・却下の記録）
    ("注文のイベントを再生する関数 replay_orders(events) を書いてください。"
     "events は辞書のリストで、各要素は {'id', 'ts', 'seq', 'order_id', 'type'}（id はイベントの識別子、order_id は注文の識別子、ts は 'YYYY-MM-DDTHH:MM:SS'、seq は整数、type は created/paid/shipped/delivered/cancelled）。"
     "リストの順ではなく (ts, seq) の昇順で処理する。同じ id のイベントは最初の1回だけ処理し、2回目以降は無視する（却下にも数えない）。"
     "遷移は created→paid→shipped→delivered の順のみ。cancelled は created か paid の時だけ。"
     "それ以外（未作成の注文への paid、delivered 後の何か、二度目の created など）は却下し、その id を rejected に積む。"
     "返り値は (states, rejected)。states は {order_id: その注文の最終状態}、rejected は却下したイベントの id を処理順に並べたリスト。キーが欠けたイベントは ValueError。",
     "replay_orders", [
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"},
           {"id": "e2", "ts": "2026-09-01T10:05:00", "seq": 1, "order_id": "o1", "type": "paid"}],), [{"o1": "paid"}, []]),
        (([{"id": "e2", "ts": "2026-09-01T10:05:00", "seq": 1, "order_id": "o1", "type": "paid"},
           {"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"}],), [{"o1": "paid"}, []]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 2, "order_id": "o1", "type": "paid"},
           {"id": "e0", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"}],), [{"o1": "paid"}, []]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"},
           {"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"}],), [{"o1": "created"}, []]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"},
           {"id": "e2", "ts": "2026-09-01T10:01:00", "seq": 1, "order_id": "o1", "type": "shipped"}],), [{"o1": "created"}, ["e2"]]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "paid"}],), [{}, ["e1"]]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"},
           {"id": "e2", "ts": "2026-09-01T10:01:00", "seq": 1, "order_id": "o1", "type": "cancelled"},
           {"id": "e3", "ts": "2026-09-01T10:02:00", "seq": 1, "order_id": "o1", "type": "paid"}],), [{"o1": "cancelled"}, ["e3"]]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1", "type": "created"},
           {"id": "e2", "ts": "2026-09-01T10:01:00", "seq": 1, "order_id": "o1", "type": "paid"},
           {"id": "e3", "ts": "2026-09-01T10:02:00", "seq": 1, "order_id": "o1", "type": "shipped"},
           {"id": "e4", "ts": "2026-09-01T10:03:00", "seq": 1, "order_id": "o1", "type": "cancelled"},
           {"id": "e5", "ts": "2026-09-01T10:04:00", "seq": 1, "order_id": "o1", "type": "delivered"},
           {"id": "e6", "ts": "2026-09-01T10:05:00", "seq": 1, "order_id": "o2", "type": "created"},
           {"id": "e7", "ts": "2026-09-01T09:00:00", "seq": 1, "order_id": "o2", "type": "created"}],),
         [{"o1": "delivered", "o2": "created"}, ["e4", "e6"]]),
        (([{"id": "e1", "ts": "2026-09-01T10:00:00", "seq": 1, "order_id": "o1"}],), "ValueError"),
        (([],), [{}, []]),
     ]),
]
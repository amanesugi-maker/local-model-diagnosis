# -*- coding: utf-8 -*-
# 実作業 L5「英雄」。
#
# 梯子の物差し（code_tasks_ladder.py の先頭に全段の定義）:
#   L5 = 小さなサブシステム。文法を持つ入力の解析器＋評価器、複数の不変条件を同時に守る状態機械、
#        非自明なアルゴリズム（バックトラック・LCS・最長経路・ダイクストラ）のどれかを、
#        端の仕様まで含めて一度に作り切る。12〜15テスト。設計を誤ると後半のテストが連鎖して落ちる。
#   L4 との違い: L4 は要件の優先順位を決めれば書ける。L5 は「部品をどう分けるか」を決めないと書けない。
#
# 形式は L4 と同じ: (依頼文, 関数名, [(引数タプル, 期待値)], {任意: "forbid": [...], "timeout": 秒})
TASKS_L5 = [
    # 1. 正規表現の部分集合（バックトラック・選択・グループ・クラス・4種の文法エラー）
    ("正規表現の小さな実装 rx_match(pattern, s) を書いてください。s 全体が pattern に一致すれば True、しなければ False。"
     "対応する文法: 文字そのもの、'.'（任意の1文字）、'[abc]' '[a-z]' '[^x]'（文字クラス・範囲・否定）、"
     "'\\\\d' '\\\\w' '\\\\s'（数字・英数字と_・空白）、'\\\\' で次の文字をそのままの文字に、"
     "後置の '*' '+' '?'、'|' で選択、'(' ')' でグループ化（入れ子可）。'^' と '$' は先頭・末尾の印（全体一致なので省いてもよい）。"
     "文法エラー（対応しない括弧、繰り返す対象が無い '*a'、閉じていない '['、末尾の '\\\\'）は ValueError。"
     "re モジュールは使わないこと。",
     "rx_match", [
        (("a*b", "aaab"), True),
        (("a*b", "b"), True),
        (("a+b", "b"), False),
        (("(ab|a)(bc|c)", "abc"), True),
        (("(a|ab)(c|bcd)(d*)", "abcd"), True),
        (("[a-c]+\\d", "abc7"), True),
        (("[^x]y", "xy"), False),
        (("a.c", "abc"), True),
        (("a.c", "ac"), False),
        (("colou?r", "color"), True),
        (("^ab$", "ab"), True),
        (("(a*)*b", "aaaa"), False),
        (("\\.", "."), True),
        (("*a", "a"), "ValueError"),
        (("(a", "a"), "ValueError"),
        (("[a", "a"), "ValueError"),
     ], {"forbid": [r"\bimport\s+re\b", r"\bfrom\s+re\s+import", r"\bre\.(?:match|fullmatch|search|compile|sub|findall|finditer|split)\s*\(", r"\bsre_"]}),

    # 2. 表計算の評価（依存の解決・範囲関数・循環と誤りの伝播）
    ("小さな表計算 eval_sheet(cells) を書いてください。cells は {'A1': 文字列, ...}。"
     "文字列が '=' で始まれば式、そうでなければ値（整数の形なら int、小数の形なら float、それ以外は文字列のまま）。"
     "式: 数、セル参照（A1〜Z99）、+ - * / と丸括弧と単項マイナス、関数 SUM/MIN/MAX/COUNT（引数はカンマ区切りで、数・セル・範囲 'A1:B3' を混ぜてよい。COUNT は数のセルの個数）。"
     "空のセルを直接参照したら 0。範囲の中の空セルと文字列セルは関数では無視する。"
     "誤り: 文字列セルを計算に使う・ゼロ除算・式の文法違反・知らない関数 → そのセルは '#ERR'。"
     "参照が循環しているセルは全部 '#CIRC'。'#ERR' や '#CIRC' のセルに依存するセルも同じ印になる（両方に依存するなら '#CIRC'）。"
     "返すのは cells と同じキーで値を入れた辞書。eval は使わないこと。",
     "eval_sheet", [
        (({"A1": "1", "A2": "2", "A3": "=A1+A2"},), {"A1": 1, "A2": 2, "A3": 3}),
        (({"A1": "=B1*2", "B1": "=C1+1", "C1": "4"},), {"A1": 10, "B1": 5, "C1": 4}),
        (({"A1": "1", "A2": "2", "A3": "3", "B1": "=SUM(A1:A3)", "B2": "=MAX(A1:A3, 10)", "B3": "=COUNT(A1:A3)"},),
         {"A1": 1, "A2": 2, "A3": 3, "B1": 6, "B2": 10, "B3": 3}),
        (({"A1": "=A2", "A2": "=A1", "A3": "=A2+1", "A4": "5"},), {"A1": "#CIRC", "A2": "#CIRC", "A3": "#CIRC", "A4": 5}),
        (({"A1": "=1/0", "A2": "=A1+1"},), {"A1": "#ERR", "A2": "#ERR"}),
        (({"A1": "hello", "A2": "=A1+1"},), {"A1": "hello", "A2": "#ERR"}),
        (({"A1": "=(1+2)*3-4/2"},), {"A1": 7.0}),
        (({"A1": "=B9+1"},), {"A1": 1}),
        (({"A1": "=SUM(A2:A3)", "A2": "x", "A3": "2"},), {"A1": 2, "A2": "x", "A3": 2}),
        (({"A1": "=FOO(1)", "A2": "=1+"},), {"A1": "#ERR", "A2": "#ERR"}),
        (({"A1": "=-A2*2", "A2": "3"},), {"A1": -6, "A2": 3}),
        (({"A1": "=A2", "A2": "=A3", "A3": "=A1", "B1": "=A1", "C1": "=1/0", "D1": "=B1+C1"},),
         {"A1": "#CIRC", "A2": "#CIRC", "A3": "#CIRC", "B1": "#CIRC", "C1": "#ERR", "D1": "#CIRC"}),
        (({"A1": "2.5", "A2": "=A1*2"},), {"A1": 2.5, "A2": 5.0}),
     ], {"forbid": [r"\beval\s*\(", r"\bexec\s*\("]}),

    # 3. 三方マージ（両側の LCS・安定行で区切る・衝突ブロック）
    ("三方マージの関数 merge3(base, ours, theirs) を書いてください。3つとも行のリストで、結果も行のリスト。"
     "手順: base→ours と base→theirs の対応を最長共通部分列（LCS）で取る。base の行のうち両方で「変更なし」として対応づいた行を安定行とする。"
     "安定行はそのまま出力し、安定行と安定行の間（先頭の前・末尾の後も含む）は区間として、base 側・ours 側・theirs 側の3つの断片を比べる: "
     "ours 側が base 側と同じなら theirs 側を採用、theirs 側が base 側と同じなら ours 側を採用、ours 側と theirs 側が同じならそれを採用、"
     "どれでもなければ衝突として ['<<<<<<<'] + ours側 + ['======='] + theirs側 + ['>>>>>>>'] を出す。",
     "merge3", [
        ((["a", "b", "c"], ["a", "B", "c"], ["a", "b", "c"]), ["a", "B", "c"]),
        ((["a", "b", "c"], ["a", "b", "c"], ["a", "b", "C"]), ["a", "b", "C"]),
        ((["a", "b", "c", "d", "e"], ["a", "B", "c", "d", "e"], ["a", "b", "c", "d", "E"]), ["a", "B", "c", "d", "E"]),
        ((["a", "b"], ["a", "X"], ["a", "X"]), ["a", "X"]),
        ((["a", "b", "c"], ["a", "c"], ["a", "b", "c"]), ["a", "c"]),
        ((["a", "c"], ["a", "b", "c"], ["a", "d", "c"]), ["a", "<<<<<<<", "b", "=======", "d", ">>>>>>>", "c"]),
        ((["a"], ["a", "b"], ["a"]), ["a", "b"]),
        (([], ["x"], []), ["x"]),
        (([], ["x"], ["y"]), ["<<<<<<<", "x", "=======", "y", ">>>>>>>"]),
        ((["a", "b", "c"], ["a", "c"], ["a", "B", "c"]), ["a", "<<<<<<<", "=======", "B", ">>>>>>>", "c"]),
        ((["a", "b", "c"], ["a", "B", "c"], ["a", "b", "C"]), ["a", "<<<<<<<", "B", "c", "=======", "b", "C", ">>>>>>>"]),
        ((["a", "b", "c"], ["a", "b", "c"], ["a", "b", "c"]), ["a", "b", "c"]),
     ]),

    # 4. 小さな Lisp（字句・構文・環境の連鎖・クロージャ・再帰・3種のエラー）
    ("小さな Lisp の評価器 mini_lisp(src) を書いてください。src は複数の式を含む文字列で、順に評価して最後の値を返します。"
     "構文: 丸括弧、整数（負も）、記号、#t と #f。"
     "特殊形式: (define 名 式)、(define (関数名 引数...) 本体...)、(lambda (引数...) 本体...)、(if 条件 then else)、(let ((名 式)...) 本体...)。本体が複数なら最後の値。"
     "組み込み: + と * は可変長、- は1引数なら符号反転で2つ以上なら左から引く、< > = は2引数、list、car、cdr、cons、null?、not。"
     "#f だけが偽（空リストは真）。lambda は定義時の環境を閉じ込める（クロージャ）。再帰できること。"
     "返り値は Python の値に直す: 整数は int、#t/#f は True/False、リストは list（入れ子も）。"
     "未定義の記号・引数の数の不一致・関数でないものの呼び出し・括弧の不一致は ValueError。eval は使わないこと。",
     "mini_lisp", [
        (("(+ 1 2 3)",), 6),
        (("(define (sq x) (* x x)) (sq 7)",), 49),
        (("(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2))))) (fib 15)",), 610),
        (("(define (make-adder n) (lambda (x) (+ x n))) (define add5 (make-adder 5)) (add5 10)",), 15),
        (("(define (map f xs) (if (null? xs) (list) (cons (f (car xs)) (map f (cdr xs))))) (map (lambda (x) (* 2 x)) (list 1 2 3))",), [2, 4, 6]),
        (("(let ((a 2) (b 3)) (* a b))",), 6),
        (("(list (if #f 1 2) (if (list) 1 2) (not #f) (= 1 1))",), [2, 1, True, True]),
        (("(car (cdr (list 1 2 3)))",), 2),
        (("(list (- 5) (- 10 3 2))",), [-5, 5]),
        (("(define (len xs) (if (null? xs) 0 (+ 1 (len (cdr xs))))) (len (list 1 2 3 4))",), 4),
        (("(define x 10) (define (f) x) (let ((x 20)) (f))",), 10),
        (("(undefined 1)",), "ValueError"),
        (("((lambda (x) x))",), "ValueError"),
        (("(+ 1 2",), "ValueError"),
     ], {"forbid": [r"\beval\s*\(", r"\bexec\s*\("]}),

    # 5. 依存つきリストスケジューリング（最長経路優先・作業者の割当・決定的な同順位処理）
    ("仕事を作業者に割り当てる関数 schedule_tasks(tasks, workers) を書いてください。"
     "tasks は {名前: (所要時間, [依存する仕事の名前...])}、workers は作業者の人数（0〜workers-1 の番号）。時刻は整数で 0 から。"
     "各時刻で、空いている作業者に準備完了の仕事（依存が全てその時刻までに終わっている）を割り当てる。"
     "優先順位は「残り最長経路」が長い順（残り最長経路＝その仕事の所要時間＋後続の仕事の残り最長経路の最大。後続が無ければ所要時間）、同じなら名前の昇順。"
     "作業者は空いている中で番号の小さい方から使う。仕事は途中で止めない。"
     "返り値は (全体の完了時刻, {名前: (開始時刻, 作業者番号)})。tasks が空なら (0, {})。"
     "依存の循環・未知の依存・所要時間が0以下・workers が1未満は ValueError。",
     "schedule_tasks", [
        (({"a": (3, []), "b": (2, ["a"]), "c": (1, ["a"])}, 2), [5, {"a": [0, 0], "b": [3, 0], "c": [3, 1]}]),
        (({"a": (2, []), "b": (2, []), "c": (2, [])}, 1), [6, {"a": [0, 0], "b": [2, 0], "c": [4, 0]}]),
        (({"a": (1, []), "b": (5, []), "c": (1, ["a"]), "d": (1, ["c"])}, 2), [5, {"a": [0, 1], "b": [0, 0], "c": [1, 1], "d": [2, 1]}]),
        (({"s": (1, []), "l": (3, ["s"]), "r": (2, ["s"]), "e": (1, ["l", "r"])}, 2), [5, {"s": [0, 0], "l": [1, 0], "r": [1, 1], "e": [4, 0]}]),
        (({"a": (2, []), "b": (1, []), "c": (1, ["b"])}, 2), [2, {"a": [0, 0], "b": [0, 1], "c": [1, 1]}]),
        (({}, 3), [0, {}]),
        (({"a": (1, ["b"]), "b": (1, ["a"])}, 1), "ValueError"),
        (({"a": (1, ["z"])}, 1), "ValueError"),
        (({"a": (0, [])}, 1), "ValueError"),
        (({"a": (1, [])}, 0), "ValueError"),
     ]),

    # 6. SQL 風の問い合わせ（字句・構文・NULL の三値・LIKE・複数キー整列・LIMIT/OFFSET）
    ("辞書のリストに SQL 風の問い合わせをする関数 sql_query(rows, q) を書いてください。"
     "q の形: SELECT 列名（カンマ区切り）または * [WHERE 条件] [ORDER BY 列 [ASC|DESC], ...] [LIMIT n [OFFSET m]]。FROM は無い。キーワードは大文字小文字を区別しない。"
     "条件: 列 演算子 値（演算子は = != < <= > >=）、列 LIKE '型'（% は0文字以上、_ は1文字）、列 IN (値, ...)、列 IS NULL、列 IS NOT NULL。AND / OR / NOT と丸括弧、優先順位は NOT ＞ AND ＞ OR。"
     "値は数（整数・小数）か '文字列'（'' で ' を表す）。行に無い列は None。None との比較と LIKE は偽（IS NULL 以外）。"
     "ORDER BY は複数キー・安定。None は昇順でも降順でも末尾。"
     "返り値は選んだ列だけの辞書のリスト（列の順は SELECT の順、無い列は None）。* なら行の辞書をそのまま。文法違反は ValueError。eval は使わないこと。",
     "sql_query", [
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT name WHERE age > 26"), [{"name": "alice"}, {"name": "dave"}, {"name": "o'hara"}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "select id where city = 'tokyo' order by age desc"), [{"id": 1}, {"id": 3}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT id WHERE age IS NULL OR city IS NULL ORDER BY id"), [{"id": 2}, {"id": 4}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT id WHERE name LIKE '%a%' AND NOT city = 'tokyo' ORDER BY id"), [{"id": 4}, {"id": 5}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT id WHERE id IN (1, 3, 5) ORDER BY id DESC"), [{"id": 5}, {"id": 3}, {"id": 1}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT id, age ORDER BY age ASC, id DESC"), [{"id": 3, "age": 25}, {"id": 1, "age": 30}, {"id": 4, "age": 35}, {"id": 5, "age": 40}, {"id": 2, "age": None}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT id ORDER BY id LIMIT 2 OFFSET 1"), [{"id": 2}, {"id": 3}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}],
          "SELECT * WHERE id = 2"), [{"id": 2, "name": "bob", "age": None, "city": "osaka"}]),
        (([{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}, {"id": 5, "name": "o'hara"}],
          "SELECT id WHERE name LIKE 'b_b' OR name = 'o''hara' ORDER BY id"), [{"id": 2}, {"id": 5}]),
        (([{"id": 1, "name": "alice", "age": 30, "city": "tokyo"}, {"id": 2, "name": "bob", "age": None, "city": "osaka"}, {"id": 3, "name": "carol", "age": 25, "city": "tokyo"}, {"id": 4, "name": "dave", "age": 35, "city": None}, {"id": 5, "name": "o'hara", "age": 40, "city": "kobe"}],
          "SELECT id WHERE (age > 26 OR city = 'osaka') AND id != 4 ORDER BY id"), [{"id": 1}, {"id": 2}, {"id": 5}]),
        (([{"id": 1, "name": "alice"}], "SELECT id, nope"), [{"id": 1, "nope": None}]),
        (([{"id": 1}], "SELEC id"), "ValueError"),
        (([{"id": 1}], "SELECT id WHERE id ~ 3"), "ValueError"),
     ], {"forbid": [r"\beval\s*\(", r"\bexec\s*\(", r"\bsqlite"]}),

    # 7. 重み付き格子の最短路（ダイクストラ・ポータル・7種の検証）
    ("格子の最短コストを求める関数 grid_shortest(grid) を書いてください。grid は同じ長さの文字列のリスト。"
     "'S' 出発、'E' 目標、'#' 壁、'.' はコスト1、'1'〜'9' はそのマスに入るコスト、英小文字はポータル（同じ文字がちょうど2つ。入るコストは1で、入ったら相手側のマスへコスト0で飛べる。飛ばなくてもよい）。"
     "上下左右に動く。コストは「入るマスのコスト」の合計（S は0、E は1）。S から E への最小コストを返し、届かなければ None。"
     "S か E が1つでない・同じ小文字が2つでない・行の長さが揃っていない・知らない文字がある時は ValueError。",
     "grid_shortest", [
        ((["S.E"],), 2),
        ((["S#E"],), None),
        ((["S9E", ".1."],), 4),
        ((["Sa..", "####", "..aE"],), 2),
        ((["S..", "...", "..E"],), 4),
        ((["S", "E"],), 1),
        ((["S.a.E", "....a"],), 3),
        ((["S5E", "1.1"],), 4),
        ((["S..", "###", "..E"],), None),
        ((["SE", "E."],), "ValueError"),
        ((["Sa.", "..E"],), "ValueError"),
        ((["S..", "..", "..E"],), "ValueError"),
        ((["S.?E"],), "ValueError"),
     ]),

    # 8. JSONPath の部分集合（経路の構文解析・再帰下降・フィルタ式・文書順）
    ("JSONPath 風の問い合わせ json_query(data, path) を書いてください。data は辞書・リスト・数・文字列の入れ子、path は文字列。"
     "path は '$' で始まり、続けて: '.名前' または \"['名前']\"（子）、'[n]'（要素。負は末尾から）、'[a:b]'（スライス。片側は省略可）、"
     "'[*]' と '.*'（全ての要素。辞書なら値、リストなら要素）、'..名前'（全ての階層から名前のキーを文書順に）、"
     "'[?(条件)]'（フィルタ。条件は '@.項目 演算子 値' で演算子は == != < <= > >=、値は数か '文字列'、&& と || で結合、丸括弧可）。"
     "返り値は一致した値のリスト（文書順＝辞書は登録順、リストは添字順で深さ優先）。存在しない経路は空リスト。文法違反は ValueError。eval は使わないこと。",
     "json_query", [
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.books[0].title"), ["A"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.books[*].price"), [10, 25, 5]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$..price"), [10, 25, 5, 100, 1]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.books[?(@.price > 8 && @.price < 30)].title"), ["A", "B"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.books[-1].title"), ["C"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.books[0:2].title"), ["A", "B"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.books[?(@.title == 'C' || @.price == 25)].title"), ["B", "C"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.store.*.name"), ["Z"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$['store']['owner'].name"), ["Z"]),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$.nope.x"), []),
        (({"store": {"books": [{"title": "A", "price": 10, "tags": ["x", "y"]}, {"title": "B", "price": 25}, {"title": "C", "price": 5, "tags": ["y"]}], "owner": {"name": "Z", "price": 100}}, "price": 1},
          "$..tags[0]"), ["x", "y"]),
        (({"a": 1}, "$.a["), "ValueError"),
        (({"a": 1}, "a.b"), "ValueError"),
     ], {"forbid": [r"\beval\s*\(", r"\bexec\s*\("]}),

    # 9. 単一化（代入の伝播・出現検査・引数の数・一貫性）
    ("項の単一化 unify(a, b) を書いてください。項は: 変数（'?' で始まる文字列）、定数（それ以外の文字列と整数）、複合項（リスト。先頭が関手の文字列、続きが引数。例 ['f', '?x', 2]）。"
     "a と b を等しくする最も一般的な代入を {変数: 項} の辞書で返す（項の中の変数も代入を全て適用した形にする）。等しくできなければ None。"
     "同じ変数が2回出れば同じ項でなければならない。変数を自分を含む項に束縛するのは不可（出現検査）→ None。関手か引数の数が違えば None。"
     "変数どうし（?x と ?y）は左の変数を右の変数に束縛する。",
     "unify", [
        (("?x", 1), {"?x": 1}),
        ((["f", "?x", 2], ["f", 1, "?y"]), {"?x": 1, "?y": 2}),
        ((["f", "?x"], ["g", "?x"]), None),
        (("?x", ["f", "?x"]), None),
        ((["f", "?x", "?x"], ["f", 1, 2]), None),
        ((["f", "?x", "?y"], ["f", "?y", 3]), {"?x": 3, "?y": 3}),
        (("?x", "?y"), {"?x": "?y"}),
        ((["f", ["g", "?x"], "?y"], ["f", "?y", ["g", 1]]), {"?x": 1, "?y": ["g", 1]}),
        ((["f", 1], ["f", 1, 2]), None),
        (("a", "a"), {}),
        (("a", "b"), None),
        ((["f", "?x"], ["f", ["g", "?y"]]), {"?x": ["g", "?y"]}),
        ((["p", "?x", ["f", "?x"]], ["p", ["f", "?y"], ["f", ["f", "?y"]]]), {"?x": ["f", "?y"]}),
     ]),

    # 10. 会議室の割当（制約充足・重なりの半開区間・辞書順最小＝バックトラック必須）
    ("会議に部屋を割り当てる関数 assign_rooms(meetings, rooms) を書いてください。"
     "meetings は (名前, 開始, 終了, 人数, 必要な設備のリスト) のリスト、rooms は (名前, 収容人数, 設備のリスト) のリスト。時刻は整数で区間は [開始, 終了) の半開区間。"
     "各会議に、収容人数が人数以上で、必要な設備を全部持つ部屋を1つ割り当てる。時間が重なる2つの会議は同じ部屋を使えない。"
     "解が複数ある時は、meetings の順に部屋の名前を並べたタプルが辞書順で最小になる割当を返す（{会議名: 部屋名}）。解が無ければ None。"
     "開始が終了以上の会議があれば ValueError。meetings が空なら {}。",
     "assign_rooms", [
        (([("m1", 9, 10, 3, ["tv"])], [("A", 4, ["tv"]), ("B", 10, []), ("C", 10, ["tv", "phone"])]), {"m1": "A"}),
        (([("m1", 9, 10, 3, []), ("m2", 9, 10, 3, [])], [("A", 4, ["tv"]), ("B", 10, []), ("C", 10, ["tv", "phone"])]), {"m1": "A", "m2": "B"}),
        (([("m1", 9, 10, 3, []), ("m2", 10, 11, 3, [])], [("A", 4, ["tv"]), ("B", 10, []), ("C", 10, ["tv", "phone"])]), {"m1": "A", "m2": "A"}),
        (([("m1", 9, 10, 3, []), ("m2", 9, 10, 3, ["tv"])], [("A", 5, ["tv"]), ("B", 5, [])]), {"m1": "B", "m2": "A"}),
        (([("m1", 9, 10, 3, [])], [("A", 2, [])]), None),
        (([("m1", 9, 10, 3, [])], [("A", 3, [])]), {"m1": "A"}),
        (([("m1", 9, 12, 3, ["tv"]), ("m2", 9, 12, 3, ["tv", "phone"]), ("m3", 9, 12, 3, [])], [("A", 5, ["tv", "phone"]), ("B", 5, ["tv"]), ("C", 5, [])]), {"m1": "B", "m2": "A", "m3": "C"}),
        (([("m1", 9, 11, 3, []), ("m2", 10, 12, 3, []), ("m3", 11, 13, 3, [])], [("A", 5, []), ("B", 5, [])]), {"m1": "A", "m2": "B", "m3": "A"}),
        (([("m1", 10, 10, 3, [])], [("A", 5, [])]), "ValueError"),
        (([], [("A", 5, [])]), {}),
     ]),
]

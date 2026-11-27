# Phase 11G / 1.1.0-rc.1

ゲームと同時に利用しやすくするための負荷対策。検索モデル・候補・スキル判定は変更していません。

- デスクトップ版の「ゲーム優先（次の検索から）」を初期ONに設定。Windowsの検索子プロセスを BELOW_NORMAL_PRIORITY_CLASS で起動します。CPUの固定上限ではありません。高負荷時は検索時間が延び、時間制限内の候補数が減る場合があります。速度を優先する場合はOFFにしてください。従来のブラウザ起動は通常優先度です。
- Windows Job Object（KILL_ON_JOB_CLOSE）への検索ワーカー割当を追加。OSの制約等で失敗した場合は既存の終了・キャンセル処理を使用します。異常終了後の残留防止は割当成功時に限ります。
- DBの状態確認とスキル参照時に不要な武器名マップの読み込みを省略。ヘルス応答の集計結果を同じDBファイル識別情報で再利用します。ファイル変更・削除を検知する仕組みを残しています。
- ランチャーとトレイのイベント待機タイムアウトを250msから1000msに変更。起動要求はイベントで即時通知されますが、子プロセスの終了検知には最大約1秒の待機が発生し得ます。
- 更新が見つかった場合のみ、署名確認・差分/完全版取得・検証/入替の段階を示す簡易ウィンドウを表示。バーは進行段階の表示であり、実測パーセントではありません。バックグラウンド起動やGUI初期化失敗時はログのみで更新を継続します。通常の署名検証やロールバックは維持。

今回のソース更新は alpha.7 の開発フォルダへ手動上書きし、アプリ完全終了後に build_windows.bat で再ビルドしてください。DB再生成不要。旧ZIPは保存し、新しいZIPは別フォルダで先に確認すること。

検証: Linux上のPython 86件（84成功、Windows固有2件スキップ）、JavaScript 22件成功。実DBで検索・キャンセル・複数候補取得を確認。Windowsでの優先度・Job Object・Tk進捗UI・常駐時のCPU/RAMは未検証。本番の署名鍵およびGitHub配信は未設定。

# Phase 11F / 1.1.0-alpha.7

Windows用ソース版。alpha.6のタスクバー起動を維持し、保存データの世代管理、起動確認付きロールバック、更新履歴、自動更新設定を追加。
既存DBは再生成不要。固定ランチャーも変更したため、今回の更新はソースを上書きして再ビルドし、旧版を完全終了してから新しい配布ZIPを展開すること。新規版はまず別フォルダで試す。
詳細は [DESKTOP_GUIDE.md](DESKTOP_GUIDE.md) と [RELEASE_GUIDE.md](RELEASE_GUIDE.md)。自動更新には公開鍵を埋め込んだビルドが必要。
LinuxでPython 68件実行（67成功、Windows固有1件スキップ）、JavaScript 22件成功。実データDB使用。Windowsの実際のGUIブリッジ・更新配信は未検証。更新進捗はログに記録し、専用GUIは未実装。

# Phase 11E タスクバー修正 / 1.1.0-alpha.6

タスクバーから内部EXEが起動された場合、正規ランチャーに転送します。DBや保存領域を変更しません。Windows実機での再ピン留め・再起動は要確認です。

署名付き起動時更新・差分更新のソース実装。Windows実機・実際のGitHub配信は未検証。公開鍵がないビルドでは自動適用を行いません。[配布・署名ガイド](RELEASE_GUIDE.md) / [Windowsビルド](BUILD_WINDOWS.md)。

# DB同梱版について

このパッケージの新規導入手順は `QUICK_START.md` を参照してください。下記は開発履歴で、元ZIPが必要という記述はDB同梱版には該当しません。

# MHF-ZZ Skill Simulator — 1.0 RC2

Windowsの導入・更新は **[QUICK_START.md](QUICK_START.md)** を参照してください。以下は開発履歴です。

## RC2 安定化
- 同一タブの検索再接続・直前の条件復元、通信エラー表示、初期読み込み中の検索ボタン無効化。
- バージョン表示とキャッシュ更新。
- 更新マニフェストの適用元バージョン照合、VERSION照合、Windows予約デバイス名拒否。旧RC1では適用元照合なしのためRC1への手動上書き推奨。
- 統合DBを元データから再生成し、Python 22件・JavaScript 20件を実行し全件成功。実ブラウザのlocalhostアクセスは管理ポリシーで拒否。Windows・Rain実機未検証。
- 計算エンジンの仕様や検索範囲はRC1と同じ。第三者DBや元ZIPは同梱しない。

# MHF Skill Simulator — Phase 2 (local importer)

個人用・非公式。Python 3.11以上、標準ライブラリのみ。
元データ、ゲーム画像、翻訳資料、生成済みデータベースは同梱していません。
各自が利用条件を確認したうえで正規の配布元から取得したZIPを指定してください。

## 実行（PowerShell、1行）

```powershell
python import_data.py --ja "20191218+NI.zip" --en "MHSX2G Normal Dat_6620221058.zip" --pax "Pax-MHFZ-Data-Collection-main.zip" --out "mhf.sqlite"
```

既存出力は上書きしません。異なるファイルを指定する場合は同一の装備順序であることを別途確認してください。出力が失敗した場合はエラーが表示されます。

## 実装済み

- 日本語・英語のスキルID、閾値と装備ポイントの照合
- 5部位、装飾品、カフ、武器テンプレート、スキル、辿異スキル、レベル、特殊効果のSQLite登録
- Pax近接武器の元ID・性能・スロット値・強化派生の登録（武器種別ルール未判定）
- SHA-256出典管理、外部キー検査、整合性検査、Rain差分用テーブル
- 装備IDは現版のファイル種別・グループ位置・行位置から生成。同一データ版内で有効。将来版への自動引継ぎは未対応。

## 未実装・制約

- 装備の日本語・英語対応は行順、スキル、主要属性、レベルで照合している。同じ性能の別装備が並び替えられた場合は識別できないため、異なる版は自動対応を保証しない。
- 元の武器スロット値は通常装飾品の装着可否を保証しない。ダミー除外は候補フラグのみ。
- Feriasの武器・ガンナー・シジル統合、素材・費用・アイテム辞書、装備タグ体系は未実装。
- 特殊効果は保存のみ。発動枠・優先順位・武器条件・カフ装着条件・バウンティ判定・自動検索は未実装。
- Rainの現行ゲーム内データは未検証。既存値に一律補正は適用しない。
- データの再配布許諾は未確認。元ファイルや生成DBを再配布しない。プログラムだけの共有も各自の利用条件を確認する。

## 出典

- MHSX2G dat: https://hiroaki362.hatenablog.com/entry/2019/12/18/190746
- 英語版案内: https://leaps29.github.io/MHFZ-Guide/
- Pax: https://github.com/Paxlord/Pax-MHFZ-Data-Collection
- 今後の統合候補: https://github.com/xl3lackout/MHFZ-Ferias-English-Project
- バウンティ参照: https://docs.google.com/document/d/1PudqeBC0PhYS5MSk_1l0njpzwW_O985dR3_F_YvHHR8

## Phase 2B — Ferias 武器・シジル追加

依存関係をインストールして、前回のZIPに加えてFerias ZIPを指定します。既存のDBは上書きしません。

```powershell
python -m pip install -r requirements.txt
python import_data.py --ja "20191218+NI.zip" --en "MHSX2G Normal Dat_6620221058.zip" --pax "Pax-MHFZ-Data-Collection-main.zip" --ferias "MHFZ-Ferias-English-Project-main.zip" --out "mhf_v2b.sqlite"
python -m unittest -v
```

追加テーブル: `ferias_weapons` (武器種＋元ID)、`ferias_variants` (ページ・アンカー・Lv別性能)、`ferias_zenith` (辿異スキルID対応)、`ferias_issues` (不正な元アンカー隔離)、`sigil_recipes` と `sigil_reference_rows` (資料行)。Paxの近接IDは武器種も確認して関連付け、メイン一覧の攻撃力・スロット差異をフラグ化。名前は翻訳未完了のため原文を保持し、天廊強化表の名称を別フィールドに保持します。

### 注意事項

- 元データの重複・不整合を自動で修正せず隔離。`conflict=1` の武器は今後の検索で要確認扱いにすること。Paxとのリンクは候補であって完全な性能一致を保証しない。
- `validate_slots` は通常装飾品とシジルの共用・専用枠を検証する暫定関数。天廊石・装着制限・未確認の武器系統は別途判定が必要。通常スキル内包は原文の抽出のみ、発動判定未実装。
- シジルは元資料の行を格納する段階。個体・レシピ・抽選率・効果範囲の構造化は未実装。
- 個別武器の日本語名、素材・強化派生の完全な統合、Rain独自装備・ルール、バウンティ判定は未実装。Rainでの数値補正はしない。
- 参照した武器系統の仕様: https://w.atwiki.jp/giurasu/pages/938.html , https://w.atwiki.jp/giurasu/pages/1245.html , https://w.atwiki.jp/giurasu/pages/1416.html , https://w.atwiki.jp/giurasu/pages/676.html , https://w.atwiki.jp/giurasu/pages/1180.html
- ソースのみ配布。元ファイル・生成DB・実行ファイル・画像を同梱しない。

## Phase 3A — スキル計算エンジン

Python 3.11以上。既存Phase 2BのSQLiteを再生成せず利用できます。
初回インポートでは `--ferias` も指定してください（上記Phase 2B手順）。

```powershell
python -m pip install -r requirements.txt
python skill_engine.py --db mhf.sqlite --build example_build.json
```

入力JSONの `armor` は部位ごとの装備・強化レベル（例: `L1`）・珠、`weapon` はFerias武器のページ・アンカーまたはMHSX2Gテンプレート、`cuffs` はカフ一覧。`g_poogie` と `premium_poogie_clothes` は利用可能状態を明示する設定です。武器種は `SnS/DB/GS/LS/Hammer/HH/Lance/GL/SA/Tonfas/MS/HBG/LBG/Bow`。`job` は `剣士/ガンナー`、`sex` は `男/女`。`example_build.json` は17珠・シジル1個を仮配置した検証用マイセットであり、最適化済み装備や実際の所持品一覧ではありません。

### 実装済み
- DBの正負のポイント・発動閾値を直接使用。日英名称と装備別の加算内訳をJSON出力。
- 通常枠10、Ｇ級効果付き防具3部位で11、5部位で12、辿異枠拡張を加算。
- MHSX2GのスキルID昇順を発動順位に使用（DBの旧 `priority` 列はXML Noであり、優先順位ではない）。
- 秘伝カフの0スロット・対象スキル枠免除、通常カフ2スロット・合計2個まで。
- 武器・防具ごとの装飾品枠、強化レベル、性別・剣士ガンナー、SP珠の基本互換性検査。
- 辿異スキルの合算とXML上限、対象スキル到達、耳栓・風圧・耐震の段階強化。
- XMLの内包・無効化関係を出力。重複は発動枠を占有したまま `overlap` として表示。部分重複などは要検証。
- 遷悠防具の自動発動、遷悠武器の早食いを通常枠とは別に記録。

### 未実装・検証上の制約
`valid` は実装済みの装着制約の検査結果に限る。`no_known_issues` も完全性を保証しない。`fully_verified` と `rain_verified` は常に false。未検証の武器系統、始種等の条件付きランクアップ、武器固有スキル、天廊、スキル効果の部分重複・競合連鎖、自動発動と同系統ポイントの重複表示、武器種違いの秘伝の枠挙動、特殊スキルと辿異強化の全組合せ、装備入手可否、HR/GR制限、歌、クエスト制約、Rain差分適用は未完成。エラー時の数値は入力の診断用で、合法な装備構成ではない。自動検索には未実装仕様を含む結果を確定解として渡さない。

### テスト
```powershell
$env:MHF_TEST_DB = 'mhf.sqlite'
python -m unittest -v
```

ローカルDB指定がない場合はDB依存テストがスキップされます。

### 追加仕様参照
- https://w.atwiki.jp/giurasu/pages/512.html (MHSX2 dat ID)
- https://w.atwiki.jp/giurasu/pages/137.html (発動枠・効果重複)
- https://w.atwiki.jp/giurasu/pages/937.html (G級防具)
- https://w.atwiki.jp/giurasu/pages/860.html (秘伝カフ)
- https://w.atwiki.jp/giurasu/pages/1525.html (カフ装着個数)
- https://w.atwiki.jp/giurasu/pages/1415.html (辿異強化)

## Phase 4A — 自動装備検索（ローカルCLI）

Phase 2B の SQLite をそのまま利用します。SciPy/HiGHS の MILP を採用（今回の環境では OR-Tools をインストールできなかったため）。前工程の計算エンジンで全候補を再評価します。

```powershell
python -m pip install -r requirements.txt
python search_engine.py --db mhf.sqlite --request example_search.json --out result.json
python search_engine.py --db mhf.sqlite --request example_auto_search.json --out result_auto.json
$env:MHF_TEST_DB = 'mhf.sqlite'
python -m unittest -v
```

### 検索JSON仕様

- `weapon_type`, `sex`, `g_poogie`, `premium_poogie_clothes`: Phase 3と共通。武器種に応じて剣士/ガンナーを決定する。
- `weapon`: Phase 3形式で固定する。未指定は武器なし（武器枠・効果なし）。`sigils` 個分を確保し、装飾品の残り枠を検索する。物理武器の自動選択・除外は未対応。
- `required`: 発動名（日本語・英語）またはスキル系統名/IDと正の発動閾値。例 `[{"skill":"剛撃+6"},{"skill":"磁斬鎚技","points":30}]`。曖昧な名称はエラー。通常スキルはポイント由来かつ再評価で `active` を要求（内包・自動発動だけでは満たした扱いにしない）。辿異スキルは段階と既知の元スキルの有効性を確認する。
- `armor`: 部位別に固定装備・強化レベル・固定珠を指定。未指定部位は自動選択。レベル未指定なら最終レベルを使用する。固定珠はその位置に残し、空き枠に追加する。
- `cuffs`: 指定した場合は完全固定。空配列ならカフなし。キー自体を省略するとカフを自動選択する。
- `armor_candidates`: 部位別の許可リスト。`jewel_candidates` / `cuff_candidates`: 自動選択の許可リスト。名前または装備ID。空配列は候補なし。固定珠等は個別に指定する。
- `exclude`: 防具・珠・カフ・武器テンプレートの除外ID/日英名称。`exclude_classes`: XML由来の分類コードを完全一致で除外（例 `(祭GX)`）。全課金装備などを包括するタグ体系は未実装。
- `jewel_limits`: 珠ごとの使用上限、固定珠もカウントする。未登録の珠は無制限。所持品だけで探す場合は許可リストと併用する。
- `g_armor_only`: 既定 true（未固定・許可リスト未指定部位はG級効果のある防具に限定）。false にすると下位装備も探索する。
- `full_jewel_pool`: 既定 false（自動選択時、必須スキルへの正の寄与を持つ珠のみ）。true で対応可能な通常珠すべてを対象にする。カフの候補絞り込みは許可リストで変更できる。
- `limit`: 1〜30件、既定3。`seconds`: 0超〜300秒、既定15。DB読み込み・モデル構築・再評価・終了処理の時間は厳密な上限ではない。

### アルゴリズム

防具の選択、珠の個数、カフ選択を整数制約に変換する。負のスキルポイントを含め、各必須閾値、部位ごとの珠サイズ別の割当、武器・カフ枠を制約として設定する。目的関数は追加珠数を優先して最小化し、同数ならカフ数を少なくする。各候補は Phase 3 エンジンで発動順位・枠・効果無効・装着可否まで再評価し、必須条件を満たさないものを除外する。既出の選択ベクトルに no-good 制約を追加して別候補を探す（珠配置だけ違う同一構成を重複出力しない）。

### 未完成・保証範囲

`complete_game_search` は常に false。`model_exhausted` は設定されたモデルの探索終了であり、ゲーム内の実現不可能を意味しない。時間切れ・エラー・結果数上限は区別して出力する。SP・天廊特殊枠・始種ランクアップ・自動発動防具は現在の自動選択から除外。内包のみでの要求達成、全スキル枠を直接制約にすること、追加スキル最適化、火力最大化、武器自動選択、Rain差分、バウンティ、入手可否は未完成。Phase 3の未検証事項も継承。ソース差異等の警告は出力に保持する。レベル・装備IDは元データ版に依存する。フレンドへの再配布許可は未確認のため元データ・DB・検索結果JSONはZIPに含めない。

### 実データ試験

ローカルの Phase 2B DB を使い、前工程16件＋今回9件＝25件すべて成功。固定防具・武器・カフから必須5スキルを満たす2候補（各8珠）、防具・カフ自動選択で秘伝・不退・剛撃+6・豪放+3・三種耐性強化を満たす1候補を確認。これはゲーム内検証ではない。

## Phase 4B — 自動検索の高度化

既存Phase 2B SQLiteを再生成せず利用できます。引き続き SciPy/HiGHS MILP を使用します。

```powershell
python search_engine.py --db mhf.sqlite --request example_optional_search.json --out optional.json
python search_engine.py --db mhf.sqlite --request example_weapon_search.json --out weapons.json
python search_engine.py --db mhf.sqlite --request example_skill_probe.json --out probe.json
python search_engine.py --db mhf.sqlite --request example_max_skills.json --out max_skills.json
```

### 追加の検索条件

- `objective`: `minimal_jewels`（既定）、`optional`（任意スキルの加重得点最大）、`max_skills`（正の通常スキル系統の到達数を優先し任意スキル得点も考慮）、`surplus`（必須スキル合計余剰pt最小）。いずれも必須条件は変更しない。任意スキルは `optional` に `{ "skill": "幕無", "weight": 3 }` などで指定する（重み1〜100、発動名または系統ID＋閾値）。任意スキルは必須でなく、未発動でも候補を返す。異なる段階を指定した場合は各段階の得点を個別に加算する。
- `metrics`: 再評価後の任意スキル達成状況・加重得点・正の有効な通常スキル系統数（内包・自動発動のみのスキルは除く）・必須スキルの余剰pt・空き装飾品枠・追加珠数。`rank` は返却候補内で実際の評価値を比較した順位。
- `auto_weapon: true`: 指定武器種内で物理武器も選択。`weapon` には固定珠・予約シジル数だけ指定可能。`weapon_filters` で `categories`（例 `zenith`）、`min_rarity`、`max_rarity` を指定可能。`weapon_candidates` はページ・アンカーの許可リスト。`exclude` には物理武器名・文字列の元ID・`page#anchor` も指定できる。指定した物理武器の固定検索にもフィルターを適用。
- 武器候補を共用/専用枠・辿異スキル寄与・遷悠自動効果でグループ化。未処理の内包効果・特殊枠・ID競合は除外する。代表はPax/Ferias差異なしを優先し、その中で表示攻撃力が高いもの。属性や斬れ味などを考慮した火力順位ではない。代替一覧は最大20件、件数と省略フラグを付ける。`weapon_group_limit`（既定12、最大100）、`results_per_weapon_group`（既定1、最大30）で探索範囲を指定し、全体時間を各グループに配分する。
- `probe`: 追加発動スキルを個別に試行するモード。`candidates` を省略すると、初期候補のポイント不足が少ない次段階から自動抽出する。`candidate_limit`（既定12、1〜194）、`seconds`（既定30、最大300）。`found` には必須条件も満たす検証済み構成を返す。`already_required`、`not_found_in_budget`、`not_tested` を区別。候補を省略した場合は未選択件数も出す。複数の追加候補が個別に見つかっても同時達成できる保証はない。

### 探索・検証上の制限

- スキル寄与の疎行列を一度だけ作り、部位別候補を索引化し、同一武器効果の計算をまとめる。装飾品の配置順だけ異なる候補は正規化キーで除外する。速度向上率の比較ベンチマークは未実施。
- MILPの任意スキル・最大スキル数はポイント到達による緩和目的関数。発動枠、無効化、特殊効果を別の計算エンジンで再検証し、必須条件を満たした解だけを返す。実際の有効スキル数/得点で再順位付けするが、全ゲーム中の大域最適性は保証しない。`solver_optimal_for_relaxed_model` は緩和モデルのみの最適性。
- `max_skills` は通常珠の候補絞り込みを解除するので計算量が増える。制限時間は厳密な壁時計上限ではない。結果なしはゲーム内での不可能を意味しない。Rain実ゲームでの検証、入手可否、全特殊効果、バウンティ、火力計算、UI、保存機能は引き続き未完成。
- テスト: ローカルSQLiteを指定した既存25件＋追加10件を実行。全体実行は環境時間制限で途中終了したため、未終了の12件を別実行で確認し、合計35件の成功を確認した。データベース・元データ・実データ検索結果はZIPに含めない。

## Phase 5A — ローカルWeb版（試作）

Phase 4B の検索エンジンを FastAPI とブラウザ画面に接続しました。この環境に React のパッケージがないため、ビルド不要の HTML / CSS / JavaScript モジュールを採用しています。将来 React / TypeScript への移行が可能なように API は分離しています。

### Windows で起動する

Python 3.11以上を用意し、ZIPを展開します。既存の Phase 2B 以降のDBがある場合は再生成不要です。まだDBを作っていない場合は、元データZIP4点を同じフォルダに置きます。辿異版datは不要です。

```powershell
python -m pip install -r requirements.txt
python import_data.py --ja "20191218+NI.zip" --en "MHSX2G Normal Dat_6620221058.zip" --pax "Pax-MHFZ-Data-Collection-main.zip" --ferias "MHFZ-Ferias-English-Project-main.zip" --out "mhf.sqlite"
python web_api.py --db mhf.sqlite
```

起動中のターミナルは閉じずに、ブラウザで `http://127.0.0.1:8765/` を開きます。終了は Ctrl+C。ポートが使用中なら `--port 8766` で変更できます。DBは読み取り専用です。ローカル専用のため外部公開しないでください。

### 操作

1. 武器種、必要なら武器固定または自動選択、予約シジル数を設定。
2. スキルを日英の名前で絞り込み、必須・任意に追加。任意には1〜100の重みを指定。
3. 防具・珠・カフの固定と個別・分類の除外を設定。検索目的、最大候補数(1〜30)、時間を指定して検索。
4. 候補一覧は装備名・珠個数・発動数・空き枠・余剰と詳細ポイントを表示。各候補の詳細を展開できます。同じ装備でも異なる珠の組み合わせを別候補とし、配置順だけ違うものは従来エンジンで除外。
5. 「この防具で装飾品を再検索」で武器・防具・カフを固定し、珠だけ解除して検索画面へ戻ります（元の必須条件がなければ選択してください）。手動編集へ読み込み、単独で再計算することも可能。
6. お気に入り登録はブラウザの localStorage に保存。別ブラウザや別ポートには引き継がれません。構成JSONをコピーできます。保存済み評価は登録時のスナップショットで、DB更新時は手動再計算が必要です。
7. 追加スキル検索は個別に最大12候補を試行。途中経過は経過時間を表示し、中断時は別プロセスのソルバーを停止します。中断までの部分結果の取得は未対応です。

### 検証と未完了事項

- 実データを用いて新規API結合テスト4件成功（カタログ・日英検索・手動計算、複数候補検索、キャンセルと同時実行制限）。既存35件は前工程の確認結果で今回の全件再試験は未実施。
- JavaScript の構文検査成功。実行環境の Chromium はローカルHTTPナビゲーションを管理ポリシーで拒否したため、実ブラウザでの一連の操作・画面表示は未確認。Windowsで実際に試用して検証する必要があります。
- 検索結果は限定された候補・時間内の結果であり、完全な列挙ではありません。初期設定は5件・20秒。ゼロ件をゲーム内で不可能とは判断しません。
- 日本語を既定とし英語へ切り替え可能。元資料の分類コード、警告、未翻訳武器名などに日英混在が残ります。
- バウンティ自動制限、所持品編集UI、装備タグ補完、シジル個体効果、装備入手可否、特殊効果の完全計算、Rain実ゲームとの照合は未完成。
- 元データ・生成DB・ゲーム画像は同梱しません。再配布許可の未確認事項は引き継ぎます。

```powershell
python -m pip install httpx
$env:MHF_TEST_DB = 'mhf.sqlite'
python -m unittest -v test_web_api
```

## Phase 5B: 装備一覧と候補比較

Phase 5Aからの更新は、稼働中のPowerShellでCtrl+Cを押し、`mhf_phase5b_update.zip`を既存フォルダに上書き展開して `start_web.bat` で再起動してください。既存の `mhf.sqlite`・元データZIP・ブラウザの保存情報は不要な再生成をせず、そのまま使用できます。Ctrl+F5でブラウザを更新してください。

- 装備選択: 30/60/100件ずつのページング、総件数、前後移動・ページ番号指定、日英名検索（全角半角を正規化）。
- 防具: ランク（名称・種別から判定。不明はその他）、装備タイプ、性別、最終強化時の防御力、耐性、スロット、スキル・辿異スキル。
- 元データの `(未)` と `(不)` は初期設定で除外。課金系（ガ・キ・パ・ネ）、祭系は任意除外。Rainでの入手可否を判定するものではありません。頭防具の剣士/ガンナー判定は元データの共用区分に従います。
- 武器: 武器種での検索、レア度・名称・攻撃力順、辿異スキル。武器の件数は強化段階を含むレコード数です。装備選択画面のフィルターは自動検索エンジンの除外設定とは独立しています。
- 結果: 候補を最大4件選択して、装備・珠の必要個数・カフ・発動スキル・空き枠・余剰などを横並びで比較できます。
- API: `/api/catalog` を追加（従来の `/api/items` は維持）。DBスキーマの変更なし。
- 検証: `test_catalog` 8件、既存 `test_web_api` 4件が実データで成功。JavaScript構文検査成功。ブラウザのローカル接続は実行環境の管理者制限により通し操作を未確認。

## Phase 5C — 所持品・代替検索・検索条件の保存

Phase 5Bからの更新はサーバー停止後、更新ZIPの内容を既存フォルダへ上書きし、`start_web.bat` を起動、ブラウザを Ctrl+F5 で更新してください。既存 `mhf.sqlite`、元ZIP、Pythonライブラリの再構築・再導入は不要です。第三者データは配布しません。

- 自動検索の「防具5部位の構成が異なる候補のみ」: 検証済み候補が見つかるたびに防具組み合わせを除外する制約を追加します。武器グループ間も同じ防具組み合わせを重複除外します。全防具を固定すると最大1件です。探索秒数内の結果であり、全組み合わせの列挙や最適性は保証しません。
- 結果カードの「代替装備を検索」: 頭など1部位を選ぶと他部位・カフ・武器・他部位の珠を固定し、元の防具を除外します。交換部位の珠は再探索。珠を選ぶと、その珠の全個数を外して除外し、他の珠を固定します。評価結果の有効な通常・辿異スキルを必須条件に移します。外部効果、自動発動スキル、未解決の特殊効果などは完全には維持されません。現在の除外設定・所持品限定等を確認してから検索してください。候補の存在は保証しません。
- 「所持品」タブ: 防具、珠、カフを個数付きで登録・変更・削除。検索欄から絞り込めます。「所持品のみ」を有効にすると、登録数0や未登録の該当種類の装備は除外されます。固定品も所持数を消費します。武器の所持状況や防具の現強化レベルは管理対象外で、未固定防具は最終強化段階を使います。所持品のデータはブラウザの localStorage に保存されます。
- 「条件を保存」: 必須・任意スキル、優先度、武器・防具・カフ・固定珠、個別除外と分類、検索時間、結果件数、検索目的、所持品限定・防具重複除外の各設定を保存します。所持品そのものは最新登録数を使います。名前で復元し、同名は確認後に上書き、不要なら削除できます。
- お気に入り: 名前と分類を編集でき、分類で表示を切り替えられます。旧形式は未分類として読み込まれます。
- 保存は同一ブラウザ・同一オリジン（通常 http://127.0.0.1:8765/）のローカル保存です。ブラウザデータ削除や別PC、別URLには引き継がれません。DBの再インポート時に別データ版でIDが変化すると保存構成の再確認が必要です。

API/ソルバー: `diverse_armor: true` は防具構成の重複除外。`inventory: {"canonical-equipment-id": quantity}` は防具・珠・カフを所持品のみに制約します。既存候補制限と交差し、固定品もチェックします。未指定時は既存検索と同じ挙動です。カフには `cuff_limits` も指定可能です。

テスト（PowerShell、既存DBを使用）:

```powershell
# 実データの回帰テスト
$env:MHF_TEST_DB = (Resolve-Path .\mhf.sqlite).Path
python -m unittest -v test_phase5c test_web_api test_catalog
```

開発側のDBで新規6件および既存12件、計18件のテスト成功。JavaScript構文チェック成功。ブラウザの自動操作検証は実行環境のアクセス制限で未実施。Windowsで画面操作確認が必要です。バウンティの自動制限は未実装で次段階。現行Rainの規則・ゲーム内スキルは未検証です。

## Phase 7A — Rain バウンティ装備フィルター

- 5C に対する上書き更新。既存 `mhf.sqlite`、ライブラリ、ブラウザ保存データはそのまま使用。
- 自動検索で Rain バウンティのカテゴリ、番号、参加区分を指定する。武器は固定または自動選択が必要。通常検索へ戻すには「通常検索（制限なし）」を選ぶ。
- Bronze 01–21、Silver 01–20、Gold 01–21、ABYSS 22–24、Free 01–25、Event 15件の計105プリセットを選択可能。全条件の完全実装ではなく、資料とDBで判別できる条件の部分適用。警告も検索結果に残す。
- サーバー側で候補防具のランク・シリーズ・分類、カフ、武器系統・レア度・武器種、シジル禁止を適用。秘伝・不退の禁止は保守的に必要ポイント未満に制限し、発動結果も検査する。そのため発動枠外の禁止スキルポイントが許容される場合には候補を取り逃す可能性がある。
- 資料: https://docs.google.com/document/d/1PudqeBC0PhYS5MSk_1l0njpzwW_O985dR3_F_YvHHR8 （日本語訳、最終更新 2026-01-19）。資料本文の再配布はしない。Gold 18 のマグスパ制限は矛盾があるため暫定禁止。Free 09 の提出区分はソロ=G級・マルチ=上位。資料の共通禁止欄は両方に適用。
- 未対応/要手動確認: 最新Discord・イベント開催期間、NPC・人数・型・受注・提出条件、通常生産/課金/ネカフェ武器の完全分類、個別武器名・属性条件、一部のG級スキル禁止、未強化指定、貸与装備、天廊特殊仕様、特殊自動発動。Free/Event の個別条件は部分対応で、判別できない条件は資料確認の警告を表示。バウンティの適合を保証しない。
- バウンティ指定は自動検索と追加スキル検索に適用。手動編集やカタログ一覧は従来どおり（禁止装備は検索時に拒否）。保存した検索条件にはバウンティ指定も含む。
- 検証: `MHF_TEST_DB=/path/to/mhf.sqlite python -m unittest -v test_bounty test_catalog test_web_api test_phase5c`。Windows PowerShell は `$env:MHF_TEST_DB = 'mhf.sqlite'` を設定してから実行する。ブラウザの通し操作は未検証。

## Phase 7B: 装備共有・保存データの移行

Phase 7A のフォルダへ更新ZIPの中身を上書きしてください。既存の `mhf.sqlite`、元データZIP、ブラウザ保存データはそのままです。更新時はサーバーを停止し、起動し直した後に Ctrl+F5 で画面を更新してください。新しい依存ライブラリはありません。

### 装備構成の共有

- 検索結果・お気に入り・手動計算結果の「共有・エクスポート」から、JSONまたはMHSX2G風クリップをコピー／ファイル保存できます。
- 手動装備編集では「現在の手動装備を共有」から直接出力できます。
- 「装備構成を読み込む」からJSONを貼り付けるか、ファイルを選択し、再計算します。以前の「構成JSONをコピー」の形式にも対応します。
- JSONは装備ID、強化レベル、武器のバリアント、シジル予約数、装飾品配置、カフ、武器種、性別、プーギー設定を保持。元データ全体、所持品、過去の計算結果は含みません。同じ元データ版で生成したDB間で使用してください。バウンティ条件や検索条件は構成JSONには含まれません。
- 受信側でID・名称を解決し、ローカルDBから計算し直します。未知・曖昧な装備、不正な強化レベル、装着制限違反は拒否します。Rainでの適合性は保証しません。

### MHSX2G風クリップ

日本語の改行付きヘッダー、武器行、頭・胴・腕・腰・脚の5行（Lv必須）、服Pスロット行を扱います。公開クリップで見られる表記を参考に実装しました（https://ameblo.jp/ahiruteikoku/entry-12452732647.html など）。出力は閲覧・チャット共有向けの近似形式で、元MHSX2Gソフトへの貼り付け互換性は未検証です。英語のクリップや特殊装備の構文は未対応です。

クリップだけでは武器種、武器個体、シジル予約数、プーギー設定を確定できないことがあります。読み込み前に正しい武器種・武器・シジル枠・プーギー設定を手動で選択してください。武器スロットなしは武器なしとして取り込みます。記載されている発動スキル一覧は信頼せず、再計算します。厳密な構成共有にはJSONを使ってください。

### バックアップ

「保存データをバックアップ」でお気に入り、所持品、検索条件、言語、テーマを単一JSONファイルに保存できます。「バックアップを復元」は内容を検査し、確認後に保存データ全体を置き換えます（マージではありません）。先に既存のバックアップを取得してください。失敗時は可能な限り変更を戻します。バックアップには表示用データや個人の所持品情報が含まれるため、個人用として保管し、フレンド共有は構成JSONを使ってください。未保存の編集中構成やSQLite自体は対象外です。

### テスト

`$env:MHF_TEST_DB = 'D:\path\mhf.sqlite'` を設定し、`python -m unittest test_sharing test_web_api test_bounty test_phase5c test_catalog`。Node.js があれば `node --test test_backup.mjs`（開発用のみ、アプリ起動には不要）。ブラウザの通しテストは実行環境側のアクセス拒否のため未確認です。

## Phase 7C — weapon/sigil collection and Japanese weapon names

Update after Phase 7B Hotfix 1. No database migration or new dependencies.

- Inventory tab: register a physical weapon by weapon type, page and anchor (exact source upgrade variant); edit count and a personal display alias. Weapon aliases affect the inventory list only.
- Search: enable `所持武器のみ（強化段階も一致）` independently of the armor/jewel/cuff owned-only filter. Select fixed or automatic weapon mode. Fixed unowned weapons are rejected; automatic candidates and equivalent alternatives are restricted to owned variants. Existing bounty and other filters still apply.
- Sigils: register individual records with a label and up to three user-entered effect/value pairs. A reference list comes from the imported Ferias data (English, not verified for Rain). Select up to three records and apply their count to reserved weapon slots. This is a slot reservation only: it does not calculate attack, affinity, attribute, or weapon-specific effects, or assign the individual records to a saved build. No source maximum is enforced on manually entered Rain values.
- Japanese weapon names: read existing explicit and Japanese source names at query time, verifying a hexadecimal source prefix against the upstream ID before removing it. Conflicting names are not guessed. Where no Japanese name is available, preserve the source name. No full translation or invented name list. The existing test DB resolves 2,774 base weapons (19,421 variant rows); remaining names need verified source data.
- Backup: `mhf.collection` is included in version-1 backup JSON. Earlier backups lacking this field are accepted and restore an empty collection, as restore is replace-only. Back up before restoring older data. New records stay in browser local storage and are not included in a shared build JSON.
- Browser: the Phase 7B hotfix single-script approach and explicit JavaScript MIME type are retained. A cache-busting version is included.

Tests on the existing generated DB: 9 collection tests, 12 catalog/API tests and 18 bounty/sharing tests passed. Node backup tests: 8 passed, including three new cases. JavaScript syntax and HTML static ID checks passed. Playwright navigation was blocked by the execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`), so actual browser interaction requires Windows verification. Rain values and availability remain unverified. No third-party data or generated DB in the distributed archives.

```powershell
# Run the regression tests with an existing generated database
$env:MHF_TEST_DB = (Resolve-Path .\mhf.sqlite).Path
python -m unittest test_collection test_catalog test_web_api test_bounty test_sharing
# If Node.js is installed, verify backups
node --test test_backup.mjs
```

## Phase 8A — 防御力・属性耐性検索

Phase 7Cからの更新では既存の `mhf.sqlite` とブラウザ保存データを再利用できます。

- 防御力と火・水・雷・氷・龍耐性の最低値を個別に指定。空欄は制限なし、負の耐性も入力可能。
- 「防具の素の値」または「スキル補正込み（部分計算）」を判定対象として選択。
- 防具は指定された強化レベルの防御力、元XMLの属性耐性を使用。未固定防具は従来どおり最高記録レベルを探索。
- 補正は枠内で有効な通常スキル（防御±N、各耐性±N、各属性耐性±N）の明示された固定値を加算する。自動発動は計算エンジンが認識したもののみ。負の効果も反映。内包のみの効果、生命力等の別スキル、条件付き効果・未解決の複合スキルは対象外。
- 武器防御力、護符・爪、GR補正、クエスト難易度、狩煉道スキル、猟団料理、歌、シジル、Rain独自差分は含まない。ゲーム内表示値や実戦値の完全再現ではない。
- 防御力優先、5属性耐性合計優先の探索目的と、各値による検索結果の並び替え。必須スキルと併用可能。性能条件だけの検索も可能。
- 整数計画の補正モデルは正のスキル到達による上界を利用する緩和。返却前に計算エンジンで再検証し、最低値を満たさない候補は除外。時間制限と既存候補絞り込みのため最適性・完全列挙を保証しない。
- 手動計算・検索結果・比較画面で素の値、スキル補正、補正込みの値を参照。以前のお気に入りは手動編集で再計算。
- 検索条件の保存・バックアップに新しい設定を含める。

検証: `MHF_TEST_DB=... python -m unittest test_defense test_skill_engine test_web_api test_bounty`（Windows PowerShellでは環境変数を `$env:MHF_TEST_DB='mhf.sqlite'` で設定）。新規7件、既存23件成功。`node --test test_backup.mjs` 8件成功、`node --check web/app.js` 成功。ブラウザ通し操作・Rain実機照合は未実施。

## Phase 8B — 必要素材・進捗

Phase 8Aに上書きするだけで利用できます。DB再生成不要。DBと同じフォルダに、インポート時の日本語・英語通常版MHSX2GとFeriasのZIPを**元のファイル名のまま**置いてください。素材計算時にSHA-256を照合し、元データのXML/HTMLを読み取ります。第三者データは同梱しません。

検索結果・お気に入り・手動計算結果の「必要素材・進捗」を開きます。防具は強化元から指定段階まで展開し、所持・完了段階を選択するとその段階までの素材が除外されます。装飾品・カフは個数ごとに完了数を設定可能。所持品の登録済み珠・カフを反映するボタンもあります。複数の直接生産レシピは選択式で、初期状態は最初のレシピです。防具に直接生産と派生の両方がある場合、直接生産を優先します。G級武器は100%強化経路を対象とし、通常武器の明示された強化元リンクをたどります。

残り必要素材と所持素材を入力すると不足を集計します。所持数は素材名単位で保存し、実際には消費しません。素材が中間装備や装飾品であっても再帰的に展開しません。日英名称の対応が一意な場合のみ統合します。必要素材と警告をテキスト出力可能。素材所持数と構成別進捗はブラウザに保存し、既存バックアップに含めます。旧バックアップを復元すると素材情報は空になります。

旧公式ZZデータのレシピです。Rain交換レート・直接交換・精錬珠の精錬経路・進化/天廊武器・G級武器の60%強化・通貨・入手方法・中間素材展開は未対応。解析不能なレシピは警告付きで未集計。素材一覧が空でも全素材不要とは限りません。レシピ選択と工程完了は手動で、素材入手や消費を自動追跡しません。複数構成の必要素材は個別計画です。

検証: test_materials 9件（実データ込み）、test_web_apiのカタログ・評価2件、Nodeバックアップ11件、素材集計1件。全回帰テストの一括実行は環境制限で中断。ブラウザ通し操作は未検証。

## Phase 8C — Optional external effects / simplified materials

- No database rebuild or additional dependencies. Stop the local server, overwrite files in Phase 8B, restart and Ctrl+F5.
- Guild meal resistance: all +5/10/20, individual +10/20/30. Same-family explicit equipment resistance is not added twice. Composite and conditional effects are incomplete; food is not counted toward required skill points, only supported resistance totals.
- Road: attack and defense Lv0–5, all and each resistance Lv0–3. Old ZZ cost ceiling 130; individual unlocked capacity and other Road skills are not modeled. Road attack delta displayed separately. Search rejects Road modifiers on non-Road bounties.
- Sigil: reserve weapon slots and enter aggregate effects manually; no stock registration required. Raw attack and affinity are shown as deltas and approximate weapon-only values, elemental display delta ×10 (not a full element stat or gunner damage calculation). Defense delta is included. Special/UL effects, individual sigil legality, skill/affinity interactions and final damage are not modeled.
- Search basis: base, supported equipment skills, or external effects. Solver uses optimistic food overlap relaxation; actual results are replayed. JSON build and search profiles preserve settings; text clips do not.
- Materials default to total requirements without stock/progress; optional checkbox re-enables existing management. Each material has a help disclosure and search link; acquisition sources are not yet verified/indexed. No automatic acquisition or stock tracking.
- Song, GR, charms/talons and Rain-specific weapon adjustments are not added. Third-party data are not bundled.
- References: https://w.atwiki.jp/giurasu/pages/1464.html ; https://w.atwiki.jp/giurasu/pages/406.html ; https://w.atwiki.jp/giurasu/pages/1244.html ; https://wikiwiki.jp/nenaiko/システム/武器倍率
- Tests: 16 Python unit tests, 12 Node tests, 8 real DB/API regression tests; manual real DB external search and JSON canonicalization succeeded. JavaScript syntax and HTML IDs checked. Actual browser workflow and Rain game comparison not tested.

## Phase 8D — 検索精度・発動枠の改善

Phase 8Cから差分上書き。SQLite、元ZIP、Python依存関係、ブラウザ保存データの変更は不要です。

- 辿異スキルを必須・任意指定した場合、XMLのTargetに基づく元スキルおよびContainedSkillsに基づく複合スキルを重点探索候補へ含める。元スキルが未発動の結果は従来どおり計算エンジンで再検証する。
- 「装飾品・カフを広く探索」を有効にすると、対応済みのカフも正の寄与による候補制限を解除する。固定・除外・装備制限・所持数は維持。
- 必須通常スキルが発動枠外になった場合、先行する非免除スキルの発動数に関する必要条件を追加する。負の発動条件も含む。条件は12基本枠・未上限処理の拡張値・潜在的な枠免除を使った楽観的上界であり、最終判定は独立した計算エンジンが行う。既存判定で受理される構成をこの条件だけで除外しない。速度向上の保証はない。
- 結果画面に咆哮・風圧・振動の元スキル、辿異強化、実効段階を表示。固定武器検索の候補プール件数・試行回数・再検証除外数・追加制約数を表示する。
- 検索結果がない場合に広域探索や探索時間変更を案内する。全件探索や最適性は保証しない。
- 猟団飯・狩煉道・シジル、必要素材の初期表示、任意の所持素材管理を維持。歌・護符・爪、Rain独自補正は追加しない。

検証: 実データ新規4件、追加の既存テスト4件、回帰36件（重複するテストあり）、Nodeテスト12件、JS構文検査が成功。実ブラウザとRain実機での照合は未実施。始種等の未対応仕様や素材入手先の構造化データは引き続き未対応。

```powershell
# ローカルDBで新規テストを実行
$env:MHF_TEST_DB = 'mhf.sqlite'
python -m unittest -v test_search_quality
```

## Phase 8E — スキル選択・禁止条件・参照

- 220系統を用途別に分類し、435の正ポイント発動段階を条件選択できます。分類はUI上の便宜的な区分です。
- `?` ボタンで全段階（負の段階を含む）、必要ポイント、元XMLの内包効果・無効化関係・辿異強化対象を確認できます。同じDBフォルダに元のFerias ZIPがあれば、英語の段階名・ポイントを一致照合した説明原文も表示します（日本語訳は未実装）。ZIP不在時はXMLだけで動作します。
- 不退・非不退・武器種別の推奨・辿異三種対策プリセットを追加。既存条件への追加で、矛盾する必須/禁止条件は拒否します。武器種別推奨は任意スキルであり、別途必須条件が必要です。おすすめは戦法に応じて調整してください。
- 禁止条件は選択した正ポイント段階以上への到達を避ける保守的な制約です。枠外・重複無効でも除外し、通常/辿異ポイントと自動発動段階を再検証します。複合スキルの間接効果の禁止やマイナススキルの禁止ではありません。検索条件・バックアップに保存されます。
- 結果の次段階までの不足ポイントは、加算済みの正ポイント系統の次段階について表示。実際の追加可否は別途検索が必要です。
- 結果の「この防具で追加スキル探索」は武器、防具5部位、強化段階、カフを固定し、装飾品を再配置して元の有効な通常/辿異スキルを保つ追加候補を個別探索します。特殊な自動効果は別途確認してください。元の珠配置や複数候補の同時発動は保証しません。
- DB再生成不要。以前のプロフィールも読み込み可能。Windowsでのブラウザ通し操作とRain実機は未検証（ChromiumへのURLアクセスが管理ポリシーで拒否）。

## Phase 8F — スキルヘルプ・日本語データ・素材経路

- `？` を各スキル候補・選択済み条件・検索結果・不足ポイントの横へ配置。40件ずつ閲覧。選択段階をヘルプ内で強調する。
- 78段階の主要スキルについて日本語の効果要約を追加。その他は元XMLの関連効果、Feriasの英語原文、未登録表示を使用する。解説は計算エンジンの追加ルールではない。
- 日本語名称はローカルFerias ZIPの `sozai/buki_sozai.js` 内の `setBukiJP` と `setBuki` の対応表を、武器種・ID・英語名の一致で照合する。既存のDBを変更しない。英語名の括弧/引用符表記と空白の差だけ許容。名前が異なる進化段階は推測で上書きしない。確認例：トリド・ウジ、極神剣ガラティーン、ファントムディバイン。実データで18,744/18,831武器、145,661/145,861強化段階レコードに日本語名を取得。残りは旧ロジックまたは英語表示。
- 必要素材の `？` を開いた際に、元Ferias ZIPの `sozai/item.js`, `mos_sozai.js`, `que_sozai.js` から完全一致する一意の素材名の入手先を表示。入手情報は英語原文。JavaScriptを実行せず、JSON文字列/配列の限定パーサーで取得。クエスト確率、交換、採集、Rain独自入手経路は未対応。未照合は検索リンクを残す。
- 直接生産素材がない精錬珠は、元XMLにあるG級防具の精錬元が一意に解決でき、Lv7までの素材経路が完全に取得できる場合のみ、防具作成→精錬の必要素材を集計。複数経路は選択式（1防具あたり組み合わせ上限64）。別の経路の素材を合算しない。ラヴィ珠3種の例で60/60工程を取得。精錬手数料・Rainの交換経路は含めない。直接生産可能な珠は直接生産を優先。新たな精錬経路により既存素材計画のIDが変わる場合は旧進捗が引き継がれない（登録済み素材数は維持）。
- 反復MILPの既存疎行列を再利用し、新しい制約を追加する。新規変数が増えた場合は再構築。装備ID解決のキャッシュはエンジンのインスタンス内だけ。実際の高速化は探索条件次第。
- 任意設定「同じ防具・武器で効果とポイントが同じ候補を省く」を追加。デフォルトOFF。防具・武器、ポイント、発動状態、枠、防御・耐性が等しい候補の表示重複を抑える。異なる装飾品の入手しやすさを比較する場合はOFF推奨。探索自体の最適性は保証しない。
- 元ZIPはデータベースと同じフォルダに置く。既存DBやローカルストレージの再生成・初期化は不要。元ZIPがない場合は追加データを利用できないが、元のスキル検索と日本語名表示は維持される。

参照（旧公式仕様の確認、効果説明は独自要約）:
- ローカルのFerias `koneta/skill.htm`, `koneta/skill_zenith.htm`、元MHSX2G XML。
- https://w.atwiki.jp/giurasu/pages/137.html （スキル選択）
- https://dengekionline.com/elem/000/001/805/1805538/ （磁星）
- https://w.atwiki.jp/giurasu/pages/1308.html （ラヴィのGXLv7精錬）
- https://monhanonline.com/mhf/guard-ornament/g-class_ornament.html （精錬珠）

検証コマンド（元DBと元ZIPが必要）:
```
# Windows PowerShell
$env:MHF_TEST_DB = (Resolve-Path mhf.sqlite).Path
$env:MHF_MATERIAL_DB = $env:MHF_TEST_DB
python -m unittest test_phase8f test_materials test_skill_catalog test_web_api test_collection test_search_quality
node --test test_backup.mjs test_material_ui.mjs
node --check web/app.js
```

## Phase 8G（2026-11-26）

Phase 8Fの上書き更新。既存の `mhf.sqlite` とブラウザ保存データは変更不要。元ZIPをDBと同じディレクトリに置く。

- スキル参照：日本語の短い効果要約を拡張。元ZIPの英語名称・ポイントで照合できる段階に追加し、英語原文も併記。既存78段階を含め、検証時348/523段階。未確認の説明は追加しない。
- スキル名の横の「？」：同名の `skillLabel` 関数が後から上書きされる不具合を修正。結果を通常・辿異・自動発動の3グループに分類。防具選択用のポイント表示は別関数。
- 素材：クエスト名の `Name : {"...` 形式を読めなかった不具合を修正。検証時3,225件のクエスト名を取得。既知のモンスター名、部位名・報酬方法・個数を日本語化。確率は原文のまま。クエスト名・未知の語は原文を維持。Rainの入手可否・交換レートは未検証。
- シジル：所持品登録不要の検索可能な効果参照画面。130種類中57種類に日本語の説明用ラベルと要約。特殊効果は参照のみで、自動補正しない。既存の手動合計値設定は維持。
- 検索：既存疎行列を使用して候補の線形制約をベクトル化検証。明示的な防具候補・固定部位ではその候補だけを走査。整数性と独立したスキル計算による最終検証を維持。全体速度の改善率や大規模最適性は保証しない。
- 未実装：特殊シジルの数値計算、追加の料理・道スキル、歌、護符・爪、Rain独自補正、Windows簡易インストーラー。Rain実機照合はユーザー環境で必要。
- ソースZIPには第三者の元データ、DB、ユーザー保存データを含めない。

検証：`python -m unittest test_phase8g`（`MHF_TEST_DB` はローカルの元ZIPとDBがある場所）、`node --check web/app.js`、`node --test test_backup.mjs test_material_ui.mjs`。ChromiumのローカルURLアクセスは管理ポリシーで拒否され、通し操作は未検証。

## Phase 8H — Road extensions and returned-result filters

Update from 8G by stopping the server, extracting the update into the existing application directory, restarting, and hard-reloading the browser. No database migration or additional dependency is required. Keep original input ZIPs and database. Existing browser data and older profiles remain compatible.

- Road: advance (floor-dependent), last stand, revival, Road point and initial Gm bonuses. Cost includes all selected levels. These are separate reported effects, not a full damage or reward prediction. Last stand disables the revival bonus. Floor is a user-selected scenario; unlock prerequisites are not checked. Source: https://w.atwiki.jp/giurasu/pages/1464.html and https://mhwiki.axibug.com/MHFZCNZ2_20181125/%E8%B5%A4%C3%97%E5%B1%8B/bake2sa.blog.fc2.com/blog-entry-36.html
- Guild meals: 12 additional selectable meal families with reference effects by outcome (failure/success/great success). Only resistance meals affect stat constraints. Other meals are shown separately and do not satisfy required armor skills, confer protection tiers, or participate in overlap rules; those need verification. Source: https://w.atwiki.jp/giurasu/pages/406.html
- Returned-result filters: equipment/active skill text (all whitespace-delimited terms), minimum free jewel slots, number of elements at resistance 55 or higher (original search basis), all three effective super protections, all optional skills achieved. Original rank and comparison selections are preserved. Filters reset on a new search. Missing values do not pass numeric filters. Sorting places missing values last.
- Copy a JSON verification report from a result for manual comparison with actual game skills, points, slot use and defense/resistance. It does not read game memory or verify Rain automatically.
- Cache immutable point/ability rows within the evaluator; no change to thresholds or solver rules. Added 24 Japanese summaries of matched local English descriptions (372 of 523 tiers in the tested database). Remaining unknown effects are not guessed.
- Scope: old official ZZ baseline; Rain-specific modifiers, songs, charms/talons and additional special sigil calculations remain excluded or pending. Actual game comparison is not performed. No third-party archives or generated DB are distributed.

Tests: two Python regression runs (36/36 and 34/34, overlapping tests), JS 16/16, syntax/HTML reference checks. A real fixed-armor search with new Road settings returned a valid result. Chromium local URL was blocked by administrator policy; no browser end-to-end claim.


## Phase 8I — スキル判定の改善

- 猟団料理の選択済みスキル（元DBに一致する正ポイント段階）を、通常の発動枠とは別の自動発動として扱います。必須・任意・禁止条件の判定対象です。食事による体力増加は参考表示のみです。
- 食事のみで得たスキルは辿異スキルの元スキルにはなりません。豪放飯と装備側の豪放を分けて咆哮・風圧・振動の実効段階を表示します。
- 元DBに自動発動能力が明記された遷悠防具などを検索候補に含めます。スキルポイントとは別に評価し、既存の禁止条件も検査します。
- 紅焔の威光など、XMLの直接内包効果にある防御・耐性補正を採用し、同一系統の重複加算を避けます。耐性飯・道スキルの補正は従来どおり外部値に表示します。
- 青魂も喝強化の元スキルとして評価します。ただし青魂そのものの負ポイント必須検索は未実装です。
- 始種防具の条件付きランクアップ、複合スキル同士の部分的な重複・特殊な発動条件、Rain実機との照合は未完了です。直接指定したスキル名を満たす検索であり、複合スキルの内包効果全般を代替必須条件とする検索ではありません。
- 旧公式相当仕様の参照先: https://w.atwiki.jp/giurasu/pages/137.html 、https://w.atwiki.jp/giurasu/pages/406.html 。

更新は Phase 8H のファイルへ上書きし、サーバー再起動後に Ctrl+F5。既存DB・元ZIP・ブラウザ保存データはそのまま利用できます。第三者データは配布ZIPに含めません。

検証: `MHF_TEST_DB` にローカルDBのパスを設定し `python -m unittest test_phase8i`。`node --test test_backup.mjs test_material_ui.mjs test_phase8h_ui.mjs`。

## Phase 8J — スキル説明と青魂検索

Phase 8Iからの更新。SQLite再生成・依存追加不要。サーバーを停止して更新ZIPを既存フォルダーへ展開し、再起動後Ctrl+F5。元データZIPは引き続き必要。

- Feriasの英語名とMHSX2Gの英語名の既知の表記差を明示的な対応表で解消。スキル種別・符号付き必要ポイントの一致を必須とし、曖昧検索による自動照合はしない。日本語説明（要約を含む）は実データで372→495/523段階。28段階は未確認または閾値等の相違があり、従来のDB閾値を変更しない。説明は旧公式相当の参考で、全数値の実機確認を意味しない。
- 青魂（喝-10以下）を必須・任意・禁止条件に追加。赤魂との方向の違いを探索制約・結果検証・余剰ポイント計算に反映。赤魂と青魂の同時必須は拒否。同一系統を正負両方向で同時禁止するAPI指定は未対応。その他の負ポイントスキルは参照のみ。喝強化の元スキルとして青魂を含む候補も探索対象にする。
- 追加・代替検索で有効な青魂を保持。青魂の戦闘中の効果値の新規計算は行わない。
- 始種防具の条件付きランクアップ、複合スキルの内包効果を代替必須条件とする検索、部分的な重複、Rain実機照合は残課題。
- 検証: MHF_TEST_DBで `python -m unittest test_phase8j test_phase8i test_phase8g test_phase8h test_skill_engine test_defense test_web_api` 46件成功（新規5件を含む）。`node --check web/app.js`、`node --test test_backup.mjs test_material_ui.mjs test_phase8h_ui.mjs` 16件成功。今回のブラウザー通し操作は未実施。
- 次工程: 統合マスターDB。第三者データおよび生成済みDBの同梱は許諾確認まで行わない。

## Phase 8J2 — 防具強化Lvの簡略化

- 防具の選択・自動検索の画面では初期値をLv1とし、全防具を最大Lv（多くはLv7）へ切り替え可能。Z/ZF/ZY/ZX/ZP、G/GF/GXなどは別装備IDなので、統合しない。
- 装備ごとのLvは内部に保持し、共有JSON、素材計画、既存のお気に入り・検索条件と互換性を維持。保存済みの中間Lvは勝手に変更せず、個別設定の折りたたみ内に保持する。旧設定でLvが未指定だった装備は従来の最大Lvを採用する。
- 結果の「Lv1・最大Lvの防御力比較」を開くと、同じ装備の両端点の防御力とスロットを比較できる。Lv7がない場合は元データの最大Lvを採用。比較操作では装備の指定Lv・素材計画は変更しない。古い保存結果は再計算が必要。
- スキルポイントは装備ID単位。Lvにより装飾品枠が増える防具では、Lv1と最大Lvの構成が同じとは限らない。比較時にスロット超過があればスキル補正後の防御力を表示しない。
- 最低防御力等の検索条件は選択中のLvで判定する。旧APIの `armor_level_mode` 省略時は互換性のため最大Lv、ブラウザからは `first` または `max` を明示。固定部位の明示Lvを優先する。
- 元XMLと実SQLiteでグリディZXメイルのLv1=400/Lv7=441（どちらも3枠）を確認。例示の5部位構成のLv1=1954、最大Lv=2077で通常・辿異スキルが同一。
- 更新時にデータベースを作り直す必要なし。第三者データは配布ZIPに含めない。統合DB、最終調整、Windowsセットアップは後続工程。

## Phase 8K — 統合マスターDB（バージョン1）

### 既存のPhase 8J2から移行（初回のみ）

1. サーバーを停止（Ctrl+C）。更新ZIPを既存フォルダーへ上書き。
2. `mhf.sqlite` と、そのDBの生成に使用した日本語・英語・Ferias ZIPを同じフォルダーに置く。DBの `sources` に記録されたファイル名とSHA-256を照合する。Paxのデータは既存DBから引き継ぐため、移行ではPax ZIPを再読込しない。
3. `build_master.bat` をダブルクリックし、完了メッセージを確認する。`mhf_master.sqlite` が作られる。既存DB・ZIPは変更しない。約204MiBの新規DBに加え、生成時の一時領域を確保する（空き容量1GB程度を推奨）。
4. `start_web.bat` で起動し、ブラウザーでCtrl+F5。ヘッダーに「統合DB / Master DB」が出ることを確認する。従来と同じURL、ポート、装備IDで動作するためブラウザー保存内容を引き継ぐ。
5. 生成と動作確認後は元ZIPを別フォルダーに移動しても利用できる。ただし将来の再生成用として保管する。従来の `mhf.sqlite` もバックアップとして保管を推奨。

コマンドで実行する場合（Python・依存パッケージは以前の環境を使用）：

```powershell
python build_master.py --db mhf.sqlite --out mhf_master.sqlite
python web_api.py --db mhf_master.sqlite
```

元ZIPを別フォルダーに置く場合は `--archives "D:\MHF\data"` を追加。既存の出力ファイルを上書きしない。マスター更新は旧DBと元ZIPを使って別名に生成し、検証後にサーバー停止状態で入れ替える。`mhf_master.sqlite` が無ければ `start_web.bat` は従来の `mhf.sqlite` を使用する。新規環境では従来のインポート手順の後にマスター生成を実施する。元データ・生成DBはこの配布ZIPに含めない。

### データ構造と品質

- 既存SQLiteのテーブルをバックアップAPIで複製する。装備ID・スキル閾値・武器ID・強化段階・既存の競合/隔離レコードは変更しない。`master_*` テーブルに武器名称対応表、日英素材名、装備と武器のレシピ、スキル説明、素材入手先を保存する。レシピは必要な項目だけを構造化し、元XML/HTMLの全体や実行可能ファイルを格納しない。
- 食事・狩煉道・バウンティの参照用スナップショットも `master_rule_reference` に保存する。実際の判定は従来のアプリ内ルールを利用する。ルール変更時はDBとアプリのバージョンを合わせること。
- `master_manifest` に生成日時、出典、元ファイルのSHA-256、件数、カバー範囲、旧公式相当・Rain未検証の情報を保存。`GET /api/master` から確認できる。参照元の照合・既存件数・外部キー・SQLite整合性の検査を行い、成功した場合だけ新規ファイルを公開する。
- 実測：装備48,387件（うち素材用レコード48,360件、武器テンプレート27件を除く）、武器強化段階145,861件、素材用武器レコード65,726件、日英素材名対応9,236件、入手先を1件以上取得した素材8,226名称、スキル参照523段階（日本語説明495）。これらはレコード数であり、全レシピや全入手先の確定を意味しない。特殊武器・曖昧な対応・Rain独自入手法の欠損は残る。従来の素材入手先表示上限100件も維持する。
- 旧DBとの一致検証：スキル・シジル参照、素材入手先、日本語武器検索、バウンティ、素材計画（plan_idを含む）、装備評価。統合DBのみを置いたフォルダーで実検索・共有等の回帰検証を実施。旧ZIPへのアクセスを例外にするテストでも参照・素材計画・評価が成功。
- スキル判定の追加仕様はこの工程では変更していない。未対応の効果・Rain実機との照合は引き続き残課題。Windowsバッチとブラウザー通し操作は実Windowsでは未検証。

### 検証コマンド（PowerShell）

```powershell
$env:MHF_MASTER_DB = "$PWD\mhf_master.sqlite"
$env:MHF_LEGACY_DB = "$PWD\mhf.sqlite"
$env:MHF_TEST_DB = $env:MHF_MASTER_DB
$env:MHF_MATERIAL_DB = $env:MHF_MASTER_DB
python -m unittest test_master test_materials test_phase8f test_web_api test_armor_levels
python -m unittest test_bounty test_defense test_sharing test_phase5c test_phase8i test_phase8j test_phase8h test_skill_catalog test_catalog
node --check web/app.js
node --test test_backup.mjs test_material_ui.mjs test_phase8h_ui.mjs
```

実行環境で上記のPython計92件とJavaScript16件が成功。旧テスト `test_phase8g.Phase8GData.test_quest_source_index` は元ZIPの直接解析を確認するテストなので、実行する場合は従来DBを指定する。

## Phase 8L — 検索性能・UI最終調整

- 自動検索の標準は優先探索。防具は各部位240件前後、珠300件前後、カフ100件前後をスキル寄与で選び、個別必須スキルの候補も追加する。固定・明示許可リストはこの候補削減の対象外。指定結果数に不足し、時間が残っていれば対応済み全候補に拡張して検索する。最初の探索結果は保持する。
- 詳細条件の「全候補を最初から探索」を有効にすれば、優先候補への絞り込みを行わない。指定した装備制限、G級防具限定、所持品限定などは維持する。全探索を保証するものではなく、時間、件数、対応済みのモデル・データに制約される。
- 自動武器選択の従来の暗黙の12グループ制限を廃止。優先探索では指定件数に達した段階で終了する。全候補モードは時間内に各グループを探索する。未探索のグループ数を表示する。
- スキル制約の上下界を防具の排他選択、珠のスロット総数、カフの個数から安全に引き締め、冗長な制約を削減。独立した発動計算での検証を維持。
- UIはスキル選択、武器・防具・カフ、詳細条件・耐性、猟団飯・狩煉道・シジルに分割。武器種・性別・指定件数の概要と検索ボタンは共通。各スキル横から必須・任意・禁止を直接追加できる。共有・バックアップは折りたたみ。既存の保存データ形式・統合DBは変更しない。
- 測定例: 統合DB、example_auto_search.json、Lv1、検索上限12秒、結果1件。8Kで1.004秒、8L優先探索で0.474秒（エンジン内の計測、初期DB読込・プロセス起動を除く）。候補や環境に依存し、全条件の高速化は保証しない。
- 検証: 新規6件を含むPython36件成功、JavaScript16件成功、Chromiumオフラインテストで実HTML/JSの初期化・タブ切替・必須追加・条件保持・リクエスト生成・手動編集との移動を確認。オフラインではAPI応答をテスト用に置き換えており実際の検索リクエストのブラウザ経由通信は未検証。追加回帰一括実行は時間制限により中断。残り28段階の日本語効果説明と未解決の発動仕様は未変更。

更新: アプリ停止後、8L更新用ZIPを8K環境へ上書きし、start_web.batを起動してCtrl+F5。DB再生成不要。元データやDBは配布ZIPに同梱しない。

## Phase 9 — 実データ回帰検証と単一武器グループ修正

- 統合DBを再生成して検証。既存DBの再生成は更新利用者には不要。
- 全候補探索で武器自動選択の対象が単一グループの場合、既定の探索件数を全体の指定件数に合わせる。明示的な `results_per_weapon_group` は尊重する。
- `verify_phase9.py` は同梱例の通常16＋辿異3条件を再現し、固定・自由・優先・全候補探索を測定する。`mhf_master.sqlite` を配置したフォルダから `python verify_phase9.py` で実行可能。結果の全必須条件は再評価する。
- 一回の測定では固定防具の全候補探索2.144秒、防具自由の優先探索5.490秒、全候補探索9.011秒。初期読み込みを除く。並行テスト実行中の測定であり、性能保証ではない。
- 広い候補集合では複数件要求が時間切れになる場合がある。結果件数上限・時間制限・未対応仕様があるため、全ゲーム構成を網羅したことは保証しない。
- 実ゲームの計算値、武器データ間の差異、始種等の特殊効果、Windows実機は未検証。
- 生成済みDBと第三者元ZIPは配布用アーカイブに含めない。

## Version 1.0 RC3 — 配布前の安定化

- 検索開始前にブラウザ側でジョブIDを発行し、sessionStorageに保持。POSTの応答が途切れても同じIDで実行状況を確認できる。APIは同じID・同じ条件の再送を重複起動せず受け付け、異なる条件の再利用は拒否する。明示的な4xx拒否時は保留状態を解除する。
- `diagnose_windows.bat`（`python windows_setup.py doctor`）で依存関係・DBの整合性と件数・必要ファイル・ポートを読み取り専用で確認。データは送信しない。
- 更新ZIPのmanifest構造とハッシュ形式を検査。不正なmanifestは更新前に拒否。
- 既存DB・ブラウザ保存形式・スキル計算モデルは変更なし。元ZIPと生成DBは同梱しない。
- Windows実機・Rain実機との完全照合は未完了。始種などの特殊仕様、時間制限付き検索の網羅性、日本語説明28段階は残課題。正式版ではなくRC3として配布する。


## Phase 11A
Windows専用ウィンドウ試験版。導入は [DESKTOP_GUIDE.md](DESKTOP_GUIDE.md) を参照。従来のWeb版は維持。

## Phase 11B (1.1.0-alpha.2)
通知領域、任意の閉じると常駐、ユーザー単位のログイン時起動、同一セッションの二重起動時の表示要求を追加。`setup_desktop.bat` を再実行してください。詳しくは [DESKTOP_GUIDE.md](DESKTOP_GUIDE.md)。Windows実機未検証。DB再生成不要。EXE化・オンライン更新は後工程。


## Phase 11C (1.1.0-alpha.3)
EXEビルド手順は [BUILD_WINDOWS.md](BUILD_WINDOWS.md) を参照。Windows上での実ビルドが必要。

## Phase 11D (1.1.0-alpha.4)
GitHub Releases 更新確認・配布メタデータ生成を追加。配布先は未設定で外部通信なし。手順は RELEASE_GUIDE.md。Windows EXE・実際のRelease登録・自動適用は未実施。

## Phase 11H / 1.1.0-rc.1
同一バイナリからDB同梱の個人検証版と公開用DBなし版を生成する `--pair` を追加。初回鍵生成、公開ファイルの選別、署名・完全/差分アーカイブの検査を追加。詳細は RELEASE_CHECKLIST.md。Windows実機のRC1動作確認およびRC2への実通信による更新試験は未実施。


### RC3 起動・更新表示

RC2からの移行と実機テストは [RC3_STARTUP_GUIDE.md](RC3_STARTUP_GUIDE.md) を参照。ランチャー自身の変更は初回のみ手動交換する。署名鍵・DB・保存データを維持すること。


RC4: see [RC4_LAUNCHER_GUIDE.md](RC4_LAUNCHER_GUIDE.md) for signed launcher updates, consent and one-time migration.

## v1.1.0-rc.6

Windows版のヘッダーから「設定・バージョン情報」を開き、実行中のランチャーと本体の版、更新履歴、バックアップ状況、更新設定を確認できます。手動の更新確認は配布候補の確認のみで、実際の更新は次回の通常起動時に署名検証と同意を経て実施します。RC6の移行と最終試験は `RC6_RELEASE_GUIDE.md` を参照してください。

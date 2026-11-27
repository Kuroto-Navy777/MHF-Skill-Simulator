# Phase 11E — Windows x64 ポータブル版の生成

現在は EXE を生成するためのソースとビルド手順です。Windowsの実行ファイルはビルド成功後に生成されます。

## ビルド担当者のみ（Windows 10/11 x64）

1. Python 3.12 x64 を https://www.python.org/downloads/windows/ からインストール（py launcherを含む）。
2. ソースZIPをすべて展開。DB同梱版を作る場合のみ、既存の `mhf_master.sqlite` を同じ場所に置く。
3. `build_windows.bat` を実行。DBを含める場合は再配布権を確認して Y を選択。
4. `release/` に ZIP、SHA-256、スモークテスト結果が作られる。失敗時はZIPを公開しない。

Python環境は `.build-venv` に分離します。PyInstallerはWindows上で実行します。
新規ビルドは既存releaseファイルを上書きしません。再試行時は別出力ディレクトリを使ってください。

手動例（ビルド環境を作成済みの場合）:

```powershell
.\.build-venv\Scripts\python.exe build_windows.py --db mhf_master.sqlite --out release-test
```

DBなしの場合は `--db` を省略。DBなしZIPには利用者が既存DBを配置する必要があります。

## 利用者

生成したZIPを展開して `MHFSimulator.exe` を起動。Python / pip不要。
WebView2がなければ公式Runtimeを導入。Windows固有の動作は実機で確認してください。

## 検証

ビルドはEXE自体の依存モジュール読み込み、MILP計算、同梱UIを検証します。
DB同梱時はDB整合性、ローカルAPI、実際の別プロセス検索も確認します。
ウィンドウ表示、タスクバーのアイコン、常駐、二重起動、ログイン起動、検索キャンセル、保存復元は別途Windows実機確認が必要です。
未署名の試験版です。自動更新は署名付きポータブル版のみ対応し、旧ソース用アップデーターをEXE版に適用しないでください。

## GitHub Actions（任意）

`ci/windows-build.yml` をリポジトリの `.github/workflows/windows-build.yml` に配置すると、手動実行でWindowsランナー上でDBなしZIPをビルドできます。公開リポジトリやReleaseへのアップロードは自動で行いません。DBをコミットしないでください。

## 更新確認（Phase 11E）
配布先設定・Release登録については [RELEASE_GUIDE.md](RELEASE_GUIDE.md) を参照。署名付き自動適用は公開鍵を組み込んだポータブル版のみ有効です。


## Phase 11E の変更
トップレベルの `MHFSimulator.exe` は固定ランチャー、`app/` は更新対象です。DBはランチャーと同じ場所に配置します。公開鍵を埋め込むビルドと署名方法は [RELEASE_GUIDE.md](RELEASE_GUIDE.md) を参照してください。

Phase 11G（alpha.8）ではランチャーが変更されたため、固定ランチャーも再ビルドが必要。TkinterはWindows用Python標準インストールのTcl/Tkを使用します。ビルド後は署名付き更新の進捗画面をWindows実機で確認してください。

## Phase 11H
`setup_release_key.bat`（初回のみ）を実行してからビルドすると公開鍵入りランチャーになる。Yを選択すると同一ビルドから2種類のZIPを生成する。配布前は `RELEASE_CHECKLIST.md` と `prepare_release.bat` を利用。公開前検査にはDB/API検索が成功した署名鍵入りのビルド報告が必要。


### RC3 起動・更新表示

RC2からの移行と実機テストは [RC3_STARTUP_GUIDE.md](RC3_STARTUP_GUIDE.md) を参照。ランチャー自身の変更は初回のみ手動交換する。署名鍵・DB・保存データを維持すること。


RC4: see [RC4_LAUNCHER_GUIDE.md](RC4_LAUNCHER_GUIDE.md) for signed launcher updates, consent and one-time migration.

## v1.1.0 インストーラー

新規導入用Setupの生成は [INSTALLER_GUIDE.md](INSTALLER_GUIDE.md) を参照。既存ポータブル版は自動更新を継続する。

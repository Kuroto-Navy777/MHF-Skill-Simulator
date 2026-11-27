# 1.1.2以降の開発・公開

既存のREADMEとGit履歴を保ち、1.1.1の原本ソースの取り込みと1.1.2の修正を別コミットにしています。
DB、元データZIP、秘密鍵、パスワード、ユーザープロファイルはGit管理・公開対象外です。
`update_public_key.bin`は既存の公開鍵であり、秘密鍵ではありません。

## 普段の変更

ソースを編集してコミット・プッシュすると、GitHub ActionsがWindows/LinuxのPythonテストとJavaScriptテストを実行します。
DBを必要とするテストは公開CIではスキップされます。公開前にはローカル統合DBでの検証が必須です。
Actionsの「Windows build」はDBなしの開発用ビルドです。正式配布には使いません。

## 署名を含む一括公開

WindowsのPython 3.12 x64、Node.js、Git、認証済みGitHub CLI、Inno Setup 6.3以降を使います。
`requirements_build.txt`と`requirements_test.txt`をインストールし、`python -m playwright install chromium`を実行します。
テストで参照する元データZIPは、必要に応じてローカルDBと同じフォルダに置きます。

```powershell
python ci/release.py --version 1.1.2 `
  --db 'D:\path\mhf_master.sqlite' `
  --public-key update_public_key.bin `
  --private-key "$env:USERPROFILE\MHF-release-keys\release-private.pem" `
  --previous 'D:\path\MHF_SkillSimulator_1.1.1_win_x64_no_DB.zip' `
  --push
```

前バージョンのZIPに加え、同じ場所の`.zip.update.json`と`.zip.update.json.sig`も必要です。
パスワードは端末で伏字入力します。既存秘密鍵と公開鍵の一致、および前配布物の署名を確認してから処理します。
無人実行環境では`MHF_SIGNING_PASSWORD`を安全なシークレット管理から渡せます。子プロセスへは引き継ぎません。
チャット、コマンド行引数、Git、バッチファイルへのパスワード直書きは不要です。

処理順は、バージョン更新 → 全テスト → 実ブラウザー回帰 → WindowsビルドとEXE検証 →
既存Ed25519鍵での署名・更新マニフェスト・差分生成 → 完全更新と差分更新の再構成検証 →
DBなしインストーラー生成と分離署名 → ソースの秘密情報監査 → コミット・プッシュ → Release登録です。
エラー時はその場で停止します。`--push`の既定は下書きReleaseで、検証済み配布物を正式公開する場合は`--publish`も指定します。
`--push`を付けない場合はローカルコミット・検証済み配布物の生成までです。

この署名は既存アップデーター互換のEd25519署名です。Windows Authenticode証明書によるEXEの発行元表示とは別です。
インストーラーの分離署名は次のコマンドで確認できます。

```powershell
python ci/verify_installer.py 'D:\path\MHF_SkillSimulator_1.1.2_Setup_win_x64_no_DB.exe'
```

公開CIに秘密鍵や許諾未確認のDBを渡す構成にはしていません。
署名付きの正式公開まで完全無人で動かす場合は、専用の信頼できるWindows実行環境とシークレット管理を先に設定してください。
GitHubの公開リポジトリ向けCIと署名環境の分離については[GitHub公式の安全な利用ガイド](https://docs.github.com/en/actions/reference/security/secure-use)も参照してください。

## 再現と診断

```powershell
$env:MHF_TEST_DB = 'D:\path\mhf_master.sqlite'
python -m unittest discover -v
$tests = Get-ChildItem test_*.mjs -File | ForEach-Object Name
node --test @tests
python verify_v112_browser.py
python ci/benchmark_search.py --db $env:MHF_TEST_DB --out local-benchmark.json
```

ベンチマーク出力には装備構成が含まれます。個人の条件・所持品を扱う出力は公開しないでください。
検索レスポンスの`rejection_reasons`は理由別件数、`rejection_log`は全除外試行の理由、
`rejection_samples`は再現用構成（最大20件）です。武器グループと探索パスの情報もログに付けます。
画面の「再検証の除外理由」からサンプルを確認できます。

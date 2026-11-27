# Phase 11E — 署名付き自動更新・配布担当者ガイド

バージョン: 1.1.0-rc.1（Windowsビルド・実機検証前のソース）。
配布先: https://github.com/Kuroto-Navy777/MHF-Skill-Simulator/releases

## 初回のみ：署名鍵を準備する

開発者のPCで `build_windows.bat` を一度実行するか、Python 3.12 x64の専用環境に `requirements_build.txt` をインストールします。初回の試験ビルドは署名鍵なしでも可能ですが、そのEXEでは自動適用が無効です。

秘密鍵はリポジトリ外に保管します。以下はPowerShellでの例です。保存先は自分で作成し、他人がアクセスできない場所に変更してください。

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\MHF-release-keys"
.\.build-venv\Scripts\python.exe release_sign.py keygen --private "$env:USERPROFILE\MHF-release-keys\release-private.pem" --public update_public_key.bin
```

12文字以上のパスワードを設定します。秘密鍵とパスワードは安全にバックアップし、GitHub・配布ZIP・チャットへ送らないでください。公開鍵 `update_public_key.bin` は配布可能で、ランチャーEXEに埋め込みます。失ったり変更した場合は新しい信頼鍵を含むランチャーを手動で配布し直す必要があります。テストの一時鍵は本番に使いません。

## ビルド・公開（毎回）

1. `VERSION` を更新し、Windowsで `build_windows.bat` を実行（`update_public_key.bin` があれば自動使用）。GitHub Actionsの場合は `ci/windows-build.yml` を `.github/workflows/windows-build.yml` に配置し公開鍵を登録。秘密鍵は不要。
2. `release/` に出力された **no_DB.zip** をWindowsで検証する。DBを使用するテストはローカルでのみ行い、DBや元ZIPは公開しない。
3. 開発者PCで下記のように署名する。例は正式版1.1.0。前版のZIPがある場合は `--previous` を追加し、差分を作成する。

```powershell
.\.build-venv\Scripts\python.exe release_sign.py sign --private "$env:USERPROFILE\MHF-release-keys\release-private.pem" --archive release\MHF_SkillSimulator_1.1.0_win_x64_no_DB.zip
```

例えば次回の1.1.1では、`--archive release\MHF_SkillSimulator_1.1.1_win_x64_no_DB.zip --previous release\MHF_SkillSimulator_1.1.0_win_x64_no_DB.zip` とする。

4. GitHub Releasesで `v` + VERSION のタグを作成。試験版は prerelease にする。ZIP、対応する `.zip.update.json`、`.zip.update.json.sig`、差分ZIP（生成された場合）を全て同じReleaseへ登録する。`.sha256` と `.smoke.json` は参考として任意登録。電子署名は `.sig` であり、単なるSHA-256とは別。
5. 同じタグの配布物は差し替えない。修正はバージョンを上げて公開。現時点でGitHubには未登録。

## 利用側

トップレベルの `MHFSimulator.exe` を起動する。`app/MHFDesktop.exe` は直接起動しない。タスクバーにピン留めする場合もトップレベルを指定する。公開鍵が組み込まれたランチャーは起動前に正式版のみを検出し、Ed25519署名、サイズ、SHA-256、全ファイルのハッシュを検証する。差分が使えなければno_DB完全ZIPを取得する。DBはどちらも更新対象外。ランチャー自身の更新は手動（信頼鍵・プロトコル変更を含む）。

トップレベルの `release_source.json` の `check_on_startup` を false にすると起動時確認・適用を停止する。既定は true、stable。配布先は固定。オフラインや署名不一致なら旧版で起動する。ログは `%LOCALAPPDATA%\MHFSkillSimulator\launcher.log`。更新完了時は `app` のみを入れ替え、旧版は `.app_previous` に残る。アプリの起動前スモークテストが失敗した場合は復元し、未完了の入れ替えは次回起動時に復旧する。実ゲーム動作の不具合まで自動検出するわけではない。

旧版のアプリ直接起動型（Phase 11D以前）は自動移行しない。新しい構成を別フォルダへ展開してDBをコピーし、トップレベルのEXEにピン留めし直す。

注意: 電子署名は更新データの署名であり、Windows Authenticode署名とは異なる。Windows SmartScreen警告やWebView2環境は実機検証が必要。第三者データを公開する前に再配布条件を確認すること。

## Phase 11F：更新確定・復元
固定ランチャーを再ビルドする必要があるため、alpha.6からの移行は手動です。以降の更新対象は引き続き app/ のみ。更新時は従来のスモークテスト後も保留マーカーを残し、新版の専用ウィンドウ内でDBとUI初期化が完了した通知を最大90秒待ちます。正常通知後に確定し、起動失敗時は旧版に戻して再起動します。正常起動後の不具合は自動判定できません。実際の署名付きGitHub配信・Windows実機での確認は未実施。

## Phase 11G：更新進捗
新しいリリースがあるときのみ、通常起動では更新段階を表示します（割合ではない）。Tkを初期化できない場合とバックグラウンド起動では従来どおりログを使用します。署名検証や復元処理は変えません。Windowsの凍結ビルドではTkも含まれるか確認してください。

## Phase 11H — RC1 の配布前検査

`RELEASE_CHECKLIST.md` を参照。`setup_release_key.bat` は初回のみ。既存鍵は上書きしない。
`build_windows.bat` で Y を選ぶと `--pair` により同じビルドから with_DB / no_DB の両方を生成し、両方にDB/API検索のビルド検査結果を付ける。with_DB は個人検証用のみ。`prepare_release.bat` は初回（差分なし）用。公開対象だけを `release/upload-v<version>/` にコピーする。

次回は前版の no_DB ZIP を保存し、同じ鍵で下記を実行する（例：RC2 のビルド後）。

```powershell
.\.build-venv\Scripts\python.exe release_sign.py sign --private "$env:USERPROFILE\MHF-release-keys\release-private.pem" --archive release\MHF_SkillSimulator_1.1.0-rc.2_win_x64_no_DB.zip --previous release\MHF_SkillSimulator_1.1.0-rc.1_win_x64_no_DB.zip
.\.build-venv\Scripts\python.exe release_preflight.py --archive release\MHF_SkillSimulator_1.1.0-rc.2_win_x64_no_DB.zip --previous release\MHF_SkillSimulator_1.1.0-rc.1_win_x64_no_DB.zip --public-key update_public_key.bin --out release\upload-v1.1.0-rc.2
```

差分ZIPを実際に展開して前版からの復元結果を検査する。公開前検査は Windows GUI 動作・GitHub 通信そのものを保証しない。ローカルのビルド報告は開発者の信頼する環境で生成したものを使う。


### RC3 起動・更新表示

RC2からの移行と実機テストは [RC3_STARTUP_GUIDE.md](RC3_STARTUP_GUIDE.md) を参照。ランチャー自身の変更は初回のみ手動交換する。署名鍵・DB・保存データを維持すること。


RC4: see [RC4_LAUNCHER_GUIDE.md](RC4_LAUNCHER_GUIDE.md) for signed launcher updates, consent and one-time migration.

RC6 の準備は `prepare_rc6.bat`。RC5の元の no_DB.zip を維持し、RC6の no_DB.zip と同じ既存鍵を使用する。詳細は `RC6_RELEASE_GUIDE.md`。RC6は正式版前の検証版であり、本番公開済みとは扱わない。

## v1.1.0 インストーラー

正式版の署名・Setup作成・実機確認は [INSTALLER_GUIDE.md](INSTALLER_GUIDE.md) を参照。

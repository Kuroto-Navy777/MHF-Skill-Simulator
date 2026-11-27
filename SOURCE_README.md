# MHF Skill Simulator — v1.1.1

非公式の MHF-ZZ / Rain 向けローカル装備シミュレーター / Unofficial local MHF-ZZ / Rain equipment simulator.

## Windows 10 / 11 (x64)

[Releases / 最新版](https://github.com/Kuroto-Navy777/MHF-Skill-Simulator/releases/latest)

- 初めて使う方は `MHF_SkillSimulator_1.1.1_Setup_win_x64_with_DB.exe` が公開されている場合のみ、そのインストーラーを選択してください。公開されていない場合は `..._Setup_win_x64_no_DB.exe` と、正規に入手・生成した `mhf_master.sqlite` が必要です。
- セットアップを実行してインストールします。PythonやGitは不要です。スタートメニューの MHF Skill Simulator から起動し、必要に応じてタスクバーにピン留めしてください。
- 以降は起動時の更新通知に同意するだけで、ランチャーと本体を更新します。設定画面でバージョンと更新チャンネルを確認できます。
- DB非同梱版は、インストール後 `%LOCALAPPDATA%\Programs\MHFSkillSimulator` の `MHFSimulator.exe` と同じ場所に `mhf_master.sqlite` を配置してから起動してください。
- WebView2 Evergreen Runtime と .NET Framework 4.6.2以降が必要です。[WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)。インストーラーはこれらを自動導入しません。
- Windowsの「設定 → アプリ → インストールされているアプリ」からアンインストールできます。DBとユーザーデータは保持されます。
- 旧ポータブル版を使用中の場合は、まず従来の自動更新を利用してください。インストーラーは新規導入向けです。移行手順は [INSTALLER_GUIDE.md](INSTALLER_GUIDE.md)。

## English

Run the Windows x64 Setup executable from Releases. The with-DB edition is available only if authorized for redistribution. Otherwise, use the no-DB installer and place a lawfully obtained/generated `mhf_master.sqlite` next to `MHFSimulator.exe` in `%LOCALAPPDATA%\Programs\MHFSkillSimulator`. Launch from Start, then optionally pin to the taskbar. Python and Git are not needed. Confirm updates when prompted on startup. WebView2 Evergreen and .NET Framework 4.6.2+ are prerequisites; install them separately if missing. Uninstall through Windows Settings; the database and profile remain. Existing portable installations can use the signed updater without reinstalling.

## v1.1.1 — リアルタイム装備検索 / Live search

- 初期状態から候補を探索し、必須スキルを追加・削除すると自動で再探索。候補一覧と件数を随時更新します。不要ならリアルタイム検索をOFFにして従来のボタン検索を利用できます。
- スキル一覧の `2/5` は、取得済み5構成のうち、そのスキルを必須にしても残る構成が2件という意味です。件数はサンプル数（上限付き）であり、全組合せの総数ではありません。新規探索で増加する場合もあり、0件は実現不可能を意味しません。
- 自動検索と手動装備編集の作業状態・選択中のページ・スクロール位置を分離。終了後の復元にはローカル保存を利用し、検索結果の全データはメモリ内のみ保持します。
- Live search starts with baseline candidates, reuses independently verified matching builds and searches again after a condition change. Counts refer to bounded samples, not all possible combinations. Turn it off for traditional on-demand search. Search and set builder drafts are independent.

## Notes

旧公式ZZデータ基準です。Rain固有仕様・ゲーム内発動・入手可否を保証するものではありません。本ツールはCAPCOM、Rain Serverと無関係の非公式ツールです。第三者データ・依存ライブラリの再配布条件は公開前に確認してください。署名付きアップデートはEd25519を利用しますが、WindowsのAuthenticode署名とは別物です。インストーラーとEXEにはAuthenticode署名を付与していません。

開発者向け: [正式版インストーラー生成ガイド](INSTALLER_GUIDE.md) / [過去の開発履歴](DEVELOPMENT_HISTORY.md) / [署名と更新](RELEASE_GUIDE.md)

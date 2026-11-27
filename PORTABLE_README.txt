MHF Skill Simulator 1.4.0 — Windows x64
非公式 / Unofficial MHF-ZZ / Rain local tool

ZIP版: 全ファイルを展開し、MHFSimulator.exe を起動してください。
インストーラー版: スタートメニューの MHF Skill Simulator から起動してください。
DB非同梱版: 正規に入手・生成した mhf_master.sqlite を MHFSimulator.exe と同じ場所に配置してください。
インストーラーの既定配置先: %LOCALAPPDATA%\Programs\MHFSkillSimulator
PythonやGitは不要。WebView2 Evergreen Runtimeと.NET Framework 4.6.2以上が必要です。
https://developer.microsoft.com/microsoft-edge/webview2/

起動時に更新があれば確認ダイアログが表示されます。はいを押すと署名確認後にランチャーとアプリ本体を更新します。いいえを押すと既存版で起動します。
設定・バージョン情報で更新設定・更新履歴・バックアップ状況を確認できます。Stableは正式版、Previewは開発版を含みます。
DBとユーザーデータは更新しません。保存先: %LOCALAPPDATA%\MHFSkillSimulator
初回起動時にローカル検索索引を生成し、成立構成を保存してスキル操作時に再利用します。
未確定条件は低負荷時に追加探索します。緑は成立確認、赤は対応範囲内で不成立を証明、灰色は未確定です。
元DB・派生計算DBの再配布許諾は未確認のため含みません。計算データはお手元のDBから生成します。
アンインストール後もDB・保存データ・更新設定を保持します。
アプリは完全終了してからインストール／アンインストールしてください。
インストーラーとEXEはAuthenticode未署名です。Ed25519の自動更新署名とは異なります。配布元を確認してください。
旧公式ZZデータ基準。Rain固有のゲーム内発動・入手可否は保証しません。

English: Extract the ZIP or run Setup. Launch MHFSimulator.exe or use the Start menu.
For the no-DB edition, place a lawfully obtained/generated mhf_master.sqlite next to the launcher.
Confirm signed updates on startup; the launcher and application update automatically.
WebView2 Evergreen and .NET Framework 4.6.2+ are required. No Python/Git installation is needed.
Uninstall retains the local database, profile and update configuration. Close the app before installing/uninstalling.
The app and Setup are not Authenticode-signed. Verify the distribution source.

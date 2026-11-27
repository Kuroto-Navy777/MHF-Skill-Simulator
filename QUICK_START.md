# Phase 11H（1.1.0 RC1）
ソース版は従来の setup_windows.bat / setup_desktop.bat / start_desktop.bat を使用してください。
EXE版の作成は [BUILD_WINDOWS.md](BUILD_WINDOWS.md)。作成済みEXEは本ソースZIPには含まれません。

## 更新確認（Phase 11E）
配布先設定・Release登録については [RELEASE_GUIDE.md](RELEASE_GUIDE.md) を参照。署名付き自動適用は公開鍵を組み込んだポータブル版のみ有効です。


## Phase 11E の変更
トップレベルの `MHFSimulator.exe` は固定ランチャー、`app/` は更新対象です。DBはランチャーと同じ場所に配置します。公開鍵を埋め込むビルドと署名方法は [RELEASE_GUIDE.md](RELEASE_GUIDE.md) を参照してください。

ゲーム優先のON/OFFは通知領域メニューから設定できます。


開発者の署名鍵準備・配布前チェックは `RELEASE_CHECKLIST.md` を参照してください。


### RC3 起動・更新表示

RC2からの移行と実機テストは [RC3_STARTUP_GUIDE.md](RC3_STARTUP_GUIDE.md) を参照。ランチャー自身の変更は初回のみ手動交換する。署名鍵・DB・保存データを維持すること。

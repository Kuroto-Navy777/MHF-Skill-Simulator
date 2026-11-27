# MHF-Skill-Simulator
An unofficial skill and equipment simulator for Monster Hunter Frontier ZZ (MHF-ZZ), featuring build optimization, skill calculations, and Hunting Road support.

## Version 1.2.0

- [検索エンジン・操作性の調査と検証結果](V120_REPORT.md)
- [候補プール、仮想武器枠、ビルド・公開の手順](V120_GUIDE.md)
- [再現可能な性能測定結果](ci/v120_performance.json)

確認済み構成を蓄積してスキルで絞り込み、不足分を背景探索する方式です。
結果は防具5部位でグループ化し、同じ防具の装飾品・カフ構成を展開できます。
武器名を指定しない0～3枠の仮想武器も使用できます。

## Version 1.1.2

- [修正・調査・検証レポート](V112_REPORT.md)
- [テスト・署名・自動公開の手順](V112_AUTOMATION.md)
- [既存ソース版の詳細ドキュメント](SOURCE_README.md)

実行にはご自身で用意した統合DBが必要です。DB・元データ・秘密鍵・個人設定はこのリポジトリに含めません。
既存の署名付き自動アップデートに対応しています。
## Version 1.3.0

完全自動検索を追加しました。武器・防具・装飾品・カフを同じMILPで選び、武器の辿異スキルとカフを相互補完させます。追加スキル検索の表示不具合を修正し、全スキル段階の継続探索を追加しました。スキル画面から固定条件・武器・シジル予約・所持制限を変更できます。

[調査・性能比較・テスト・未対応仕様](V130_REPORT.md)

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

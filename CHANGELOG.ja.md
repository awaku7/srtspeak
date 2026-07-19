# 変更履歴

このプロジェクトの主な変更を記録する。

## [0.1.2] - 2026-07-19

### ドキュメント
- `DESIGN.md` / `README.md` / `README.ja.md` を現行実装に同期（ja_yomi は Grok Chat API、timeline モジュール、パイプライン順、extras、終了コード）。
- `docs/SRT_TRANSLATE_DESIGN.md` v0.5 を追加: SRT→SRT 翻訳設計（言語以外同一 / P0 構造ロック、multi-target、progress、TDD Phase 1）。翻訳は TTS ビルドパイプラインに埋め込まない。

## [0.1.1] - 以前

### 変更
- バージョン 0.1.0 → 0.1.1。

## [0.1.0] - 以前

### 追加
- Apache-2.0 リリース準備と PyPI メタデータ。
- 多言語 SRT TTS パイプライン（parse → ja_yomi → TTS → fit → timeline）。
- CLI / GUI エントリポイント。

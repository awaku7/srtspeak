# 変更履歴

このプロジェクトの主な変更を記録する。

## [0.1.3] - 2026-03-22

### 追加
- OS 資格情報ストアによる API キー永続化（`keyring`）: Windows Credential Locker / macOS Keychain / Linux Secret Service・KWallet。
- GUI **Save on this PC** / **Clear saved**（`gui_settings.json` に平文を書かない）。
- 旧 Windows DPAPI ファイルは読取・移行フォールバックとして維持（`%LOCALAPPDATA%\srtspeak\`）。
- ファイル名言語推定: 現地語ラベル（`日本語` / `ไทย` / `中文` 等）とトークン単位コード（`_en` / `-ja`）。`tenku` 内の `en` 誤爆なし。
- GUI は Browse / パス確定時にファイル名から言語を反映（Build の Language と Translate の元言語）。

### 変更
- `glossary.json` を固有名詞中心に薄型化（翻訳プロンプト高速化）。
- GUI 翻訳進捗をスレッド安全キュー経由にし、Chat 待機中もステータス更新。
- 診断用 GUI 進捗ログは既定 OFF。有効時のみ `work/gui_progress.log`。
- optional: `[gui]` / `[dev]` に `keyring>=25`。
- 翻訳キャッシュ再設計: `work/translate/by_out/{tgt}__{out_name}.json`（index→`{src,tgt}`）、既存出力 SRT からシード。旧キュー単位 sha256 キーは不使用。

### 修正
- Translate タブが Grok Chat 待ち中に「実行中…」のまま固まる問題。
- 本番で翻訳キャッシュヒットが常に 0（ハッシュキー不一致）→ 出力ファイル名キー + SRT シードで解消。

## [0.1.2] - 2026-07-19

### 追加
- `srtspeak translate`: Grok Chat による多ターゲット SRT→SRT 翻訳（タイミング固定、`TranslateConfig`）。
- `srtspeak glossary-suggest`: ソース SRT から用語集 JSON を提案。
- GUI **Translate** タブ（ターゲット、glossary + Suggest、length mode、naming、fail-fast、no-cache）。
- build/translate の `--no-cache`（読みスキップ、成功後は書き込み）。
- build の `--strip-emoticons` / `--no-strip-emoticons`（既定オン）: TTS 発話テキストのみ顔文字除去。絵文字保持。SRT 不変（`core/text_sanitize.py`）。

### 変更
- `BuildConfig.strip_emoticons` 既定 **True**（旧ドキュメントの MVP no-op 記述を廃止）。
- GUI 設定ファイル: `gui_settings.json`（`gui.json` ではない）。
- `doctor` が translate / glossary-suggest を表示。

### ドキュメント
- `DESIGN.md` / `README.md` / `README.ja.md` を現行実装に同期（translate、glossary-suggest、strip_emoticons、no_cache、GUI タブ、パッケージ構成）。
- `docs/SRT_TRANSLATE_DESIGN.md`: 実装済み CLI/GUI/設定フィールドを反映（naming、no_cache、fail_fast、heartbeat）。

## [0.1.1] - 以前

### 変更
- バージョン 0.1.0 → 0.1.1。

## [0.1.0] - 以前

### 追加
- Apache-2.0 リリース準備と PyPI メタデータ。
- 多言語 SRT TTS パイプライン（parse → ja_yomi → TTS → fit → timeline）。
- CLI / GUI エントリポイント。

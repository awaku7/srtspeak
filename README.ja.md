# srtspeak

SRT 多言語 TTS。各キューの開始・終了時刻へ音声を強制フィットしたナレーションを生成する（xAI Grok TTS + ffmpeg）。

加えて **SRT→SRT 翻訳**（`translate`）と **用語集提案**（`glossary-suggest`）を Grok Chat（同一 `XAI_API_KEY`）で提供する。

仕様の正本は `DESIGN.md`（実装準拠）。  
翻訳設計: `docs/SRT_TRANSLATE_DESIGN.md`。

**言語:** [English](README.md) | [日本語](README.ja.md)

## 必要環境

| 項目 | 内容 |
|------|------|
| OS | Windows / macOS / Linux（開発・検証は Windows） |
| Python | 3.11 以上 |
| ffmpeg / ffprobe | PATH 上を推奨。無ければ optional `imageio-ffmpeg` |
| API キー | 実 TTS / 翻訳 / 用語集 / ja_yomi 時のみ `XAI_API_KEY`（Chat を使わない dry-run なら不要） |

パッケージ版: **0.1.4**（`pyproject.toml`）。

## インストール

[PyPI](https://pypi.org/project/srtspeak/) から:

```bat
python -m pip install srtspeak
```

ffmpeg を pip 経由で補う場合（任意・フォールバック）:

```bat
python -m pip install "srtspeak[ffmpeg]"
```

本体依存に **PySide6**（GUI）と **keyring**（OS 資格情報）を含む。

インストール後は `srtspeak` コマンドが使える:

```bat
srtspeak --help
srtspeak doctor
```

### ソースから（開発）

リポジトリを clone し、直下で editable インストール:

```bat
git clone https://github.com/awaku7/srtspeak.git
cd srtspeak
python -m pip install -e ".[ffmpeg,dev]"
```

開発用 extra（`[dev]`）: pytest / ruff / Babel / keyring。

未インストール（checkout のみ）:

```bat
set PYTHONPATH=src
python -m srtspeak --help
```

**`[ja]` extra は無い。** 日本語よみ前処理（`ja_yomi`、漢字→ひらがな）は **Grok Chat API** を同じ `XAI_API_KEY` で使う（`lang=ja` のとき既定オン）。

## 起動

`pip install`（PyPI または editable）後は entry point `srtspeak` を使う:

```bat
srtspeak gui
srtspeak doctor
srtspeak --help
srtspeak dry-run --srt GRAN_TENKU_japan.srt --lang ja
```

```bat
python -m srtspeak gui
```

## ffmpeg が無いとき

解決順（`core/ffmpeg_resolve.py`）:

1. PATH 上の `ffmpeg` / `ffprobe`（`shutil.which`）
2. optional `imageio-ffmpeg` 同梱バイナリ（`get_ffmpeg_exe()`）
3. それ以外は `FFmpegNotFoundError`

| 状況 | 挙動 |
|------|------|
| `srtspeak doctor` | `ffmpeg: MISSING (...)` を表示。終了コード **0**（診断のみ） |
| `dry-run`（build） | ffmpeg **不要**（パース + 文字数 + コスト見積もりのみ） |
| 実 `build` / `build-all` | fit 段階で失敗。CLI 終了コード **2** |
| `translate` / `glossary-suggest` | ffmpeg **不要** |
| `imageio-ffmpeg` のみ | 動作可。ただし `ffprobe` が `(none)` になり得る。PATH の ffmpeg を推奨 |

### インストール例（Windows）

WinGet（推奨）:

```bat
winget install Gyan.FFmpeg
```

**新しい**端末で:

```bat
ffmpeg -version
ffprobe -version
srtspeak doctor
```

PATH を変えたくない場合:

```bat
python -m pip install "srtspeak[ffmpeg]"
srtspeak doctor
```

`doctor` はシステム ffmpeg なら `source: path`、pip 同梱なら `source: imageio_ffmpeg` を表示する。

## xAI（Grok TTS / Chat）アカウントと API キー

TTS は **xAI Grok のみ**（`POST https://api.x.ai/v1/tts`）。  
日本語よみ・SRT 翻訳・用語集提案は Grok Chat（`/v1/chat/completions`）。キーはコンソールで作成する。

### 1. アカウント

1. [https://console.x.ai/](https://console.x.ai/) を開く
2. サインアップ / ログイン
3. 利用規約と課金・クレジット設定に従う  
   - TTS は従量。dry-run 見積もりは **$15 / 1M characters**（実装上の単価）
   - ja_yomi / translate / glossary の Chat 呼び出しは別途従量

### 2. API キー作成

1. コンソールの **API Keys**（相当）を開く
2. 新規キーを作成
3. 値をコピー（多くは `xai-` で始まる）  
   - **再表示されない**ことがある → すぐ環境変数へ
4. キーをチャット・Git・`report.json`・スクリーンショットに載せない

公式ドキュメント:

- [Text to Speech](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech)
- [Voice](https://docs.x.ai/developers/model-capabilities/audio/voice)
- API: `https://api.x.ai/v1/tts` / voices: `https://api.x.ai/v1/tts/voices`

### 3. 本ツールのキー読み取り

| 規則 | 内容 |
|------|------|
| 変数 | **`XAI_API_KEY` のみ** |
| CLI フラグ | `--api-key` なし（シェル履歴回避） |
| 永続化 | `.env` なし。report/ログ/`gui_settings.json` に平文キーを書かない |
| 解決順 | env → セッション → **OS keyring** → 旧 Windows DPAPI（移行） → CLI `getpass` / GUI マスク |
| dry-run | キー任意（Chat API はスキップ） |
| 実 TTS / 翻訳 / 用語集 | 解決チェーン。無ければ終了コード 2 |
| GUI | **Save on this PC** / **Clear saved**（keyring。本体依存） |

Windows cmd（現在のウィンドウのみ）:

```bat
set "XAI_API_KEY=xai-..."
srtspeak doctor
```

PowerShell:

```powershell
$env:XAI_API_KEY = "xai-..."
srtspeak doctor
```

新しい端末にも残す例（cmd）:

```bat
setx XAI_API_KEY "xai-..."
```

`doctor` の表示は有無と取得元:

```text
XAI_API_KEY: set (env)
```

```text
XAI_API_KEY: set (keyring)
```

```text
XAI_API_KEY: set (dpapi)
```

または:

```text
XAI_API_KEY: missing
```

キー無効・残高不足などは実行中に `TTS error: ...` / `translate error: ...`（終了コード 1）。

## 起動・サブコマンド

```bat
srtspeak --help
srtspeak doctor
srtspeak languages
srtspeak voices
srtspeak gui
srtspeak build --help
srtspeak build-all --help
srtspeak dry-run --help
srtspeak translate --help
srtspeak glossary-suggest --help
```

| コマンド | 用途 |
|----------|------|
| `doctor` | `XAI_API_KEY`、ffmpeg/ffprobe、ja_yomi、translate、glossary-suggest、PySide6 |
| `languages` | API に送れる言語コード候補 |
| `voices` | Grok ボイス一覧（キーがあれば API、無ければ builtin。男女とも） |
| `dry-run` | パース + 文字数・TTS 概算コストのみ（ffmpeg 不要） |
| `build` | 1 言語を生成（TTS） |
| `build-all` | 複数言語を順に生成 |
| `translate` | SRT→SRT 多ターゲット翻訳（Grok Chat・タイミング固定） |
| `glossary-suggest` | ソース SRT から用語集 JSON を提案 |
| `gui` | PySide6 GUI（Build + Translate タブ） |

グローバルオプション:

```text
--locale en|ja     UI ロケール（既定: SRTSPEAK_LOCALE → LC_ALL/LANG → システム → en）
--verbose / --quiet
```

`--quiet` / `--verbose` はサブコマンドの**前**に置く。

```bat
srtspeak --locale ja doctor
srtspeak --verbose build --srt sample.srt --lang ja --dry-run
```

## 入出力レイアウト

### TTS ビルド

`--out` は**出力ルート**。成果物は常に `{out}/{lang}/` 配下。

```text
out/{lang}/
  cues/                 キュー単位（正規化後）
  fitted/               尺合わせ後
  GRAN_TENKU_{lang}.wav 完成トラック（名前固定）
  GRAN_TENKU_{lang}.mp3 --also-mp3 時
  report.json
work/{lang}/
  raw/
  cache/
  ja_yomi_cache.json    ja かつ ja_yomi 時
```

- 既定ルート: `out` → 例 `out/ja/`
- `--out out/en` かつ `--lang en` → `out/en/`（二重化しない）
- `--out artifacts` かつ `--lang pt` → `artifacts/pt/`
- `build-all` の `summary.json` は out ルート直下

### 翻訳

`--out` 既定: `srt_gen`。作業キャッシュは `work/translate/by_out/`（出力 SRT ファイル名キー）。

```text
srt_gen/
  translate_report.json
  {target}/                         # BCP-47 トークン（例: en, pt-BR）
    {source_stem}_{target}.srt      # naming=stem（既定）
    GRAN_TENKU_{target}.srt         # naming=gran_tenku
work/translate/by_out/
  {target}__{out_srt_name}.json   # 例: en__GRAN_TENKU_en.srt.json
```

## 基本的な使い方

### 環境確認

```bat
srtspeak doctor
```

期待の目安:

- `XAI_API_KEY: set (env)`（実 TTS / 翻訳前）
- `ffmpeg:` にパスと `source: path`（または `imageio_ffmpeg`）
- `ja_yomi: grok-chat (Grok Chat API)`
- `translate: grok-chat (same XAI_API_KEY)`
- `glossary-suggest: grok-chat (same XAI_API_KEY)`

### コスト見積もり（ffmpeg 不要）

```bat
srtspeak dry-run --srt GRAN_TENKU_japan.srt --lang ja
```

### 1 言語ビルド

```bat
set "XAI_API_KEY=xai-..."

srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --voice-id leo
srtspeak build --srt GRAN_TENKU_English.srt --lang en --voice-id leo --out out
srtspeak build --srt GRAN_TENKU_Portugus.srt --lang pt --voice-id leo
```

主なオプション:

| オプション | 意味 | 既定 |
|------------|------|------|
| `--srt` | 入力 SRT | 必須 |
| `--lang` | 内部キー `ja` / `en` / `pt` など | ファイル名から推定可 |
| `--language-code` | API へ送る BCP-47 | lang のデフォルト（`pt`→`pt-BR`） |
| `--out` | 出力ルート（lang を付与） | `out` |
| `--work-dir` | 作業ルート | `work` |
| `--voice-id` | ボイス ID（build-all は `lang=id` 可） | `leo` |
| `--short-mode` | `pad` / `stretch` | `pad` |
| `--max-speed` | atempo 積の上限。超過は hard_trim | なし |
| `--tail-pad-ms` | 最終キュー end 後の無音（base_wav 無し時） | `0` |
| `--base-wav` | 既存 WAV にナレーションをミックス（base の rate/ch 維持） | なし |
| `--ja-yomi` / `--no-ja-yomi` | 日本語 漢字→ひらがな（Grok Chat） | **オン** |
| `--strip-emoticons` / `--no-strip-emoticons` | TTS 用のみ顔文字除去。絵文字は保持。SRT は変更しない | **オン** |
| `--no-cache` | 既存 TTS/ja_yomi キャッシュを無視（成功後は新規書き込み） | off |
| `--limit N` | 先頭 N キューのみ | 全件 |
| `--dry-run` | 生成せず見積もり | off |
| `--also-mp3` | 完成トラックの mp3 も出力 | off |
| `--jobs` | 並列（MVP は **1** のみ） | `1` |

試しに数キューだけ:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --limit 3 --voice-id leo
```

ポルトガル語を pt-PT にする例:

```bat
srtspeak build --srt GRAN_TENKU_Portugus.srt --lang pt --language-code pt-PT --voice-id leo
```

既存ベッドにミックス:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --base-wav bed.wav --voice-id leo
```

よみ前処理を切る:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --no-ja-yomi --voice-id leo
```

キャッシュ無視で再生成:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --no-cache --voice-id leo
```

### 複数言語一括

```bat
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=GRAN_TENKU_English.srt ^
  --map pt=GRAN_TENKU_Portugus.srt ^
  --voice-id leo ^
  --out out
```

言語別ボイス:

```bat
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=GRAN_TENKU_English.srt ^
  --voice-id ja=leo --voice-id en=orion
```

### 翻訳（SRT→SRT）

タイミング固定の多ターゲット翻訳。キュー数 / index / start-end ms は同一で、テキストのみ変更。プロバイダは Grok Chat structured JSON（既定 `grok-4.5`）。TTS パイプラインとは分離。

```bat
set "XAI_API_KEY=xai-..."

srtspeak translate ^
  --srt GRAN_TENKU_japan.srt ^
  --source-lang ja ^
  --to en --to pt-BR --to es ^
  --out srt_gen ^
  --glossary glossary.json ^
  --length-mode hint
```

| オプション | 意味 | 既定 |
|------------|------|------|
| `--srt` | 元 SRT | 必須 |
| `--source-lang` | 元言語 | ファイル名推定 / `ja` |
| `--to` | 対象 BCP-47（繰り返し or カンマ区切り） | 必須（1 件以上） |
| `--out` | 出力ルート | `srt_gen` |
| `--work-dir` | 作業ルート | `work` |
| `--glossary` | 用語集 JSON | なし |
| `--length-mode` | `off` / `hint` / `enforce` / `report-only` | `hint` |
| `--on-empty` | `fail` / `keep-source` | `fail` |
| `--batch-size` | Chat 1 バッチのキュー数 | `8` |
| `--model` | Grok Chat モデル ID | `grok-4.5` |
| `--limit N` | 先頭 N キューのみ | 全件 |
| `--dry-run` | 見積もりのみ（Chat なし） | off |
| `--fail-fast` | 最初の対象言語エラーで停止 | off |
| `--no-cache` | 既存翻訳キャッシュを無視（成功後は書き込み） | off |
| `--naming` | `stem` → `{source_stem}_{lang}.srt` / `gran_tenku` → `GRAN_TENKU_{lang}.srt` | `stem` |

dry-run:

```bat
srtspeak translate --srt GRAN_TENKU_japan.srt --to en,pt-BR --dry-run
```

生成 SRT を TTS する例:

```bat
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=srt_gen/en/GRAN_TENKU_japan_en.srt ^
  --voice-id leo --out out
```

（`--naming gran_tenku` なら `srt_gen/en/GRAN_TENKU_en.srt`）

### 用語集提案

```bat
srtspeak glossary-suggest ^
  --srt GRAN_TENKU_japan.srt ^
  --source-lang ja ^
  --to en --to pt-BR ^
  --out glossary.json
```

| オプション | 意味 | 既定 |
|------------|------|------|
| `--srt` | 元 SRT | 必須 |
| `--source-lang` | 元言語 | ファイル名推定 / `ja` |
| `--to` | 対象 BCP-47（繰り返し or カンマ区切り） | 必須 |
| `--out` | 出力用語集 JSON | `glossary.json` |
| `--merge` | 既存用語集へマージ（衝突時は既存優先） | なし |
| `--force` | マージせず `--out` を上書き | off |
| `--min-count` | ローカル候補の最小出現回数 | `2` |
| `--model` | Grok Chat モデル ID | `grok-4.5` |
| `--limit N` | 先頭 N キューのみ | 全件 |

`--out` が既に存在し `--force` が無い場合、既存 terms とマージ（既存優先）。

### GUI

```bat
srtspeak gui
```

- タブ: **Build**（TTS）と **Translate**
- Build: SRT、言語（BCP-47 + Detect）、ボイス、**絶対パス**出力フォルダ + ディレクトリ選択、Base WAV、Max cues、dry-run、ja_yomi、顔文字除去、no-cache
- Translate: ソース SRT、元言語、多ターゲット選択、**絶対パス**出力フォルダ + ディレクトリ選択、glossary パス + Suggest、length mode、batch size、naming（`stem` / `gran_tenku`）、fail-fast、no-cache、dry-run
- 共有: API キー（マスク）+ 読み込み元を示すステータス/プレースホルダ（env / keyring / DPAPI / session）+ **Save on this PC** / **Clear saved**
- キー入力: 空白・改行を除去（`normalize_api_key`）。言語検出も build/translate と同じ解決チェーン
- 完了: 非モーダル結果ダイアログ。メイン窓は開いたまま
- Browse / パス確定: ファイル名から元言語推定（`guess_lang_from_filename`）
- 進捗: 下部ステータス + バー（0–1000）。worker → スレッド安全 queue + 約 80ms drain。Cancel は `CancellationToken`
- 診断（任意）: `SRTSPEAK_GUI_PROGRESS_LOG=1` → `work/gui_progress.log` のみ
- 非シークレットは **`gui_settings.json`**（キー平文は保存しない）
- UTF-8 既定: CLI/GUI は未設定時に `PYTHONUTF8=1` と `PYTHONIOENCODING=utf-8` をセット

## 処理の要点

### TTS ビルド

- パイプライン: parse → limit → **ja_yomi**（ja）→ TTS/cache → 正規化 → fit → timeline → report
- TTS: xAI Grok unary REST のみ（`speed` は常に 1.0）
- ja_yomi: Grok Chat の structured JSON、バッチ 5、`work/{lang}/` にキャッシュ
- strip_emoticons: **TTS 発話テキストのみ**顔文字除去。絵文字は保持。SRT キュー本文は変更しない。既定 **オン**
- 尺合わせ: ffmpeg CLI のみ（`atempo` 0.5–2.0 多段、不足は pad 既定）
- タイムライン: 無音キャンバスまたは base_wav。配置区間は半開 `[start, end)`。**PCM 加算ミックス**（±32767 クリップ）
- トラック長: 最終キュー end + `tail_pad_ms`。`--base-wav` 時は base の長さ
- 音声（base 無し）: mono s16le 24 kHz WAV。base 有り時は base の rate/ch を維持
- 料金目安（dry-run）: $15 / 1M chars（TTS 文字。Chat よみ分は含まない）
- ボイス: builtin に男女あり。既定 `leo`
- `--no-cache`: TTS/ja_yomi キャッシュ読みをスキップ。成功後は書き込む

### 翻訳

- パイプライン: parse → limit → ターゲット毎: cache → Chat バッチ → 構造ロック → SRT 書き出し → `translate_report.json`
- 構造ロック: キュー数 / index / start_ms / end_ms がソースと同一
- glossary 任意（`terms` / `do_not_translate` / `tone`）
- length_mode `hint`（既定）は予算をプロンプトへ。`enforce` は 2nd compress pass 可
- モデル既定 `grok-4.5`、batch_size 既定 8

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 成功（`doctor` は ffmpeg 欠落でも 0） |
| 1 | 実行時エラー（TTS / 翻訳 / 用語集など） |
| 2 | 設定・引数・不正 SRT・**ffmpeg 欠落**・キー欠落 |
| 130 | キャンセル（Ctrl+C） |

## 開発

```bat
git clone https://github.com/awaku7/srtspeak.git
cd srtspeak
python -m pip install -e ".[dev,ffmpeg]"
set PYTHONPATH=src
python -m pytest -q
python -m ruff check src tests
python -m ruff format src tests
```

i18n（メッセージ変更時）:

```bat
python scripts/update_i18n.py
```

## サンプル入力（リポジトリ横に置く想定）

| ファイル | lang | 備考 |
|----------|------|------|
| `GRAN_TENKU_japan.srt` | `ja` | ja_yomi 既定オン |
| `GRAN_TENKU_English.srt` | `en` | |
| `GRAN_TENKU_Portugus.srt` | `pt` | 未指定時 API 既定 `pt-BR` |

3 ファイルのタイムコードは揃っている想定（設計時: 293 キュー、`00:00:07,600`–`00:12:44,000`）。

## ライセンス

Apache License 2.0（`LICENSE` 参照）

## 作者

Hirofumi Ukawa <hirofumi@ukawa.biz>

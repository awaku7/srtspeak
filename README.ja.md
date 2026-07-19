# srtspeak

SRT 多言語 TTS。各キューの開始・終了時刻へ音声を強制フィットしたナレーションを生成する（xAI Grok TTS + ffmpeg）。

仕様の正本は `DESIGN.md`（実装準拠）。

**言語:** [English](README.md) | [日本語](README.ja.md)

## 必要環境

| 項目 | 内容 |
|------|------|
| OS | Windows / macOS / Linux（開発・検証は Windows） |
| Python | 3.11 以上 |
| ffmpeg / ffprobe | PATH 上を推奨。無ければ optional `imageio-ffmpeg` |
| API キー | 実 TTS 時のみ `XAI_API_KEY`（dry-run で ja_yomi API を使わないなら不要） |

## インストール

リポジトリ直下で:

```bat
python -m pip install -e .
```

GUI も使う場合:

```bat
python -m pip install -e ".[gui]"
```

開発用（pytest / ruff / Babel）:

```bat
python -m pip install -e ".[dev]"
```

ffmpeg を pip 経由で補う場合（任意・フォールバック）:

```bat
python -m pip install -e ".[ffmpeg]"
```

まとめて入れる例:

```bat
python -m pip install -e ".[gui,ffmpeg,dev]"
```

editable インストール後は `srtspeak` コマンドが使える。未インストールなら:

```bat
set PYTHONPATH=src
python -m srtspeak --help
```

**`[ja]` extra は無い。** 日本語よみ前処理（`ja_yomi`、漢字→ひらがな）は **Grok Chat API** を同じ `XAI_API_KEY` で使う（`lang=ja` のとき既定オン）。

## 起動（Windows）

リポジトリ直下でダブルクリック、またはコマンド実行:

| スクリプト | 内容 |
|------------|------|
| `run_gui.bat` | GUI 起動 |
| `run_doctor.bat` | 環境診断 |
| `run_srtspeak.bat …` | CLI 透過（`srtspeak` と同じ引数） |

例:

```bat
run_gui.bat
run_doctor.bat
run_srtspeak.bat --help
run_srtspeak.bat dry-run --srt GRAN_TENKU_japan.srt --lang ja
```

bat を使わない場合:

```bat
srtspeak gui
python -m srtspeak gui
```

補足:

- スクリプトは自動でリポジトリ直下へ `cd` する。
- `srtspeak` が PATH に無いときは `PYTHONPATH=src` を付けて `python -m srtspeak` を使う。
- `XAI_API_KEY` 未設定かつ `UAGENT_GROK_API_KEY` がある場合のみ、そのセッションへコピーする（永続化しない）。

## ffmpeg が無いとき

解決順（`core/ffmpeg_resolve.py`）:

1. PATH 上の `ffmpeg` / `ffprobe`（`shutil.which`）
2. optional 依存 `imageio-ffmpeg` の同梱バイナリ（`get_ffmpeg_exe()`）
3. どちらも無ければ `FFmpegNotFoundError`

| 場面 | 挙動 |
|------|------|
| `srtspeak doctor` | `ffmpeg: MISSING (...)` と表示。終了コードは 0（診断のみ） |
| `dry-run` | ffmpeg **不要**（パースと文字数・概算のみ） |
| 実 `build` / `build-all` | フィット段階で失敗。CLI 終了コード **2** |
| `imageio-ffmpeg` のみ | 動作可。ただし `ffprobe` が `(none)` になり得る。フル機能は **PATH のフルビルド ffmpeg 推奨** |

### 入れ方（Windows 例）

WinGet（推奨）:

```bat
winget install Gyan.FFmpeg
```

入れたあと新しいターミナルで:

```bat
ffmpeg -version
ffprobe -version
srtspeak doctor
```

PATH を触りたくない場合のフォールバック:

```bat
python -m pip install -e ".[ffmpeg]"
srtspeak doctor
```

`doctor` で `source: path` ならシステム ffmpeg、`source: imageio_ffmpeg` なら pip 同梱側。

## xAI（Grok TTS）の登録と API キー

TTS は **xAI Grok** のみ（`POST https://api.x.ai/v1/tts`）。日本語よみも Grok Chat（`/v1/chat/completions`）を使う。キーはコンソールで発行する。

### 1. アカウント

1. [https://console.x.ai/](https://console.x.ai/) を開く
2. サインアップ / ログイン（xAI アカウント）
3. 利用規約・課金（クレジット / 請求）をコンソールの案内に従って設定  
   - TTS は従量。dry-run の目安は **$15 / 1M characters**（実装の概算単価）
   - ja_yomi 有効時は Chat 分が別途かかる

### 2. API キー発行

1. コンソールの **API Keys**（または同等のキー管理画面）へ
2. 新しいキーを作成
3. 表示されたキー（多くの場合 `xai-` で始まる）をコピー  
   - **再表示できないことがある**のでその場で環境変数へ
4. キーの値をチャット・Git・`report.json`・スクリーンショットに載せない

公式ドキュメント（エンドポイント・音声）:

- [Text to Speech](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech)
- [Voice](https://docs.x.ai/developers/model-capabilities/audio/voice)
- API: `https://api.x.ai/v1/tts` / voices: `https://api.x.ai/v1/tts/voices`

### 3. このツールへの渡し方

| ルール | 内容 |
|--------|------|
| 変数名 | **`XAI_API_KEY` のみ** |
| CLI 引数 | `--api-key` は無い（シェル履歴に残るため） |
| 永続化 | `.env` 読み書きなし / report・ログに値を出さない |
| dry-run | キー無し可（ja_yomi API はキー無しならスキップ） |
| 実 TTS | env →（CLI）`getpass` 対話 → それでも無ければ終了コード 2 |
| GUI | env 優先。無ければマスク入力（セッションのみ） |

Windows cmd（現在のウィンドウだけ）:

```bat
set "XAI_API_KEY=xai-..."
srtspeak doctor
```

PowerShell:

```powershell
$env:XAI_API_KEY = "xai-..."
srtspeak doctor
```

ユーザー環境変数に残す例（cmd・新しい端末から有効）:

```bat
setx XAI_API_KEY "xai-..."
```

`doctor` の表示は有無だけ:

```text
XAI_API_KEY: set (env)
```

または:

```text
XAI_API_KEY: missing
```

キーが無効・残高不足などの API エラーはビルド中に `TTS error: ...`（終了コード 1）になる。

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
```

| コマンド | 用途 |
|----------|------|
| `doctor` | `XAI_API_KEY` 有無、ffmpeg/ffprobe、ja_yomi、PySide6 |
| `languages` | API に送れる言語コード候補 |
| `voices` | Grok ボイス一覧（キーがあれば API、無ければ builtin。男女とも） |
| `dry-run` | パース + 文字数・概算コストのみ（ffmpeg 不要） |
| `build` | 1 言語を生成 |
| `build-all` | 複数言語を順に生成 |
| `gui` | PySide6 GUI |

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

## 基本的な使い方

### 環境確認

```bat
srtspeak doctor
```

期待の目安:

- `XAI_API_KEY: set (env)`（実 TTS 前）
- `ffmpeg:` にパスと `source: path`（または `imageio_ffmpeg`）
- `ja_yomi: grok-chat (Grok Chat API)`

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

### GUI

```bat
python -m pip install -e ".[gui]"
srtspeak gui
```

- 言語コンボは API の BCP-47。内部の out 用 `lang` は自動導出
- out 欄は**ルート**（既定 `out`）。実行時に lang が付く
- Base WAV、ja_yomi チェック（既定オン）、limit、dry-run
- API キーは環境変数優先。未設定時のみマスク入力
- 非シークレットは `gui.json` に保存可（キーは保存しない）

## 処理の要点

- パイプライン: parse → limit → **ja_yomi**（ja）→ TTS/cache → 正規化 → fit → timeline → report
- TTS: xAI Grok unary REST のみ（`speed` は常に 1.0）
- ja_yomi: Grok Chat の structured JSON、バッチ 5、`work/{lang}/` にキャッシュ
- 尺合わせ: ffmpeg CLI のみ（`atempo` 0.5–2.0 多段、不足は pad 既定）
- タイムライン: 無音キャンバスまたは base_wav。配置区間は半開 `[start, end)`。**PCM 加算ミックス**（±32767 クリップ）
- トラック長: 最終キュー end + `tail_pad_ms`。`--base-wav` 時は base の長さ
- 音声（base 無し）: mono s16le 24 kHz WAV。base 有り時は base の rate/ch を維持
- 料金目安（dry-run）: $15 / 1M chars（TTS 文字。Chat よみ分は含まない）
- ボイス: builtin に男女あり。既定 `leo`

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | 成功（`doctor` は ffmpeg 欠落時も 0） |
| 1 | TTS など実行時エラー |
| 2 | 設定・引数・SRT 不正・**ffmpeg 未検出**・キー未設定など |
| 130 | キャンセル（Ctrl+C） |

## 開発

```bat
python -m pip install -e ".[dev]"
set PYTHONPATH=src
python -m pytest -q
python -m ruff check src tests
python -m ruff format src tests
```

i18n（メッセージ更新時）:

```bat
python scripts/update_i18n.py
```

## サンプル入力（同梱想定）

| ファイル | lang | 備考 |
|----------|------|------|
| `GRAN_TENKU_japan.srt` | `ja` | ja_yomi 既定オン |
| `GRAN_TENKU_English.srt` | `en` | |
| `GRAN_TENKU_Portugus.srt` | `pt` | 未指定時 API は `pt-BR` |

3 本はタイムコード一致前提（設計時 293 キュー、`00:00:07,600`–`00:12:44,000`）。

## ライセンス

Apache License 2.0（`LICENSE` 参照）

## 作者

Hirofumi Ukawa <hirofumi@ukawa.biz>

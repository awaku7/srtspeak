# srtspeak 設計書（実装準拠）

**状態:** 実装済み（パッケージ版 `0.1.1`）。本ドキュメントはコードと同期した仕様の正本。  
**目的:** 多言語 SRT を xAI Grok TTS で音声化し、各キューの開始・終了時刻へ **強制フィット** したナレーション WAV を生成する。

関連:

- 利用者向け: [README.md](README.md) / [README.ja.md](README.ja.md)
- 実装: `src/srtspeak/`

---

## 1. 概要

| 項目 | 内容 |
|------|------|
| 入力 | SRT（UTF-8 / BOM 可） |
| TTS | xAI Grok unary REST のみ `POST https://api.x.ai/v1/tts` |
| フィット | ffmpeg CLI（`atempo` 0.5–2.0 多段 + pad/stretch + hard_trim/pad） |
| タイムライン | 無音キャンバス（または base WAV）へ PCM 配置・加算ミックス |
| UI | CLI（argparse）+ optional GUI（PySide6） |
| 認証 | **`XAI_API_KEY` のみ**（`--api-key` なし / `.env` なし / report・ログに値を出さない） |
| Python | 3.11+ |
| ライセンス | Apache-2.0 |

### 1.1 データフロー

```text
cli.py / gui/app.py
        │
        ▼
core/pipeline.py  (run_build / dry_run_build / BuildService)
  srt_parser → ja_yomi → tts_xai(+cache) → normalize → fit → timeline → report
```

### 1.2 非スコープ（当面）

- Voice Agent realtime / WebSocket
- Custom voice clone
- 動画 mux
- 文章リライト（ja_yomi の漢字→ひらがな以外）
- Web UI
- `jobs > 1` の並列 TTS

---

## 2. 言語

### 2.1 内部キーと API コード

- **内部キー `lang`:** 出力ディレクトリ名・完成ファイル名に使う短いキー（例: `ja`, `en`, `pt`, `zh`）。
- **API `language_code`:** Grok に送る BCP-47（例: `ja`, `en`, `pt-BR`, `pt-PT`, `zh`）。

解決（`core/languages.py`）:

1. CLI/GUI の明示 `--language-code` / コンボ選択
2. `--lang` のデフォルトマップ（`DEFAULT_LANGUAGE_CODE`）
3. SRT ファイル名ヒント（`japan`→`ja`, `english`→`en`, `portug`→`pt` 等）
4. 不明ならエラー

`pt` の API 既定は **`pt-BR`**。`pt-PT` は候補に含め明示指定可能。

GUI は **BCP-47 を1つ選ぶ** UI。内部 `lang` は `internal_lang_from_code()` で導出（`pt-BR`/`pt-PT`→`pt`）。

### 2.2 候補（builtin）

`srtspeak languages` で一覧。代表:

- `ja`, `en`, `pt-BR`, `pt-PT`
- `es`, `fr`, `de`, `it`, `ko`, `zh`, `hi`, `ar`, `ru`, `tr`, `nl`, `pl`, `sv`, `id`, `vi`, `th`
- ほか公式対応分は `languages.py` の定数が正

---

## 3. 声（Grok voices）

### 3.1 カタログ

- **builtin**（`core/voices.py`）: オフライン / dry-run / GUI 初期表示。男性・女性の双方を含む。
- **ライブ** `GET /v1/tts/voices`: キーがあるとき取得し merge。

既定 `voice_id`: **`leo`**（ツール側。API 省略時の eve には依存しない。常に明示送信）。

### 3.2 決定優先

1. CLI `--voice-id` / GUI コンボ（単一値 or `lang=voice` を複数回）
2. GUI 前回設定（`gui.json`、シークレット以外）
3. `DEFAULT_VOICE_ID = leo`

### 3.3 バリデーション

| 状況 | 挙動 |
|------|------|
| dry-run で未知 id | **エラー**（builtin にも API にも無い） |
| 実 build で未知 id | **警告**のうえ API に試し、失敗したら TTS エラー |
| API 一覧取得成功 | API 側を正として merge |
| API 失敗 | builtin + 警告 |

`voice_id` は小文字正規化（case-insensitive）。

---

## 4. 認証

```text
優先: env XAI_API_KEY
  → CLI: getpass（実 TTS 時のみ）
  → GUI: マスク入力のセッション値（ディスク非保存）
```

- `BuildConfig` に `api_key` フィールドは **無い**
- bat: `XAI_API_KEY` 未設定かつ `UAGENT_GROK_API_KEY` があるときセッションへコピーのみ
- dry-run: キー任意（ja_yomi の API 変換はキー無しならスキップ）

---

## 5. BuildConfig（`core/models.py`）

実装フィールド（要約）:

| フィールド | 既定 | 説明 |
|------------|------|------|
| `srt_path` | 必須 | 入力 SRT |
| `lang` | 必須 | 内部キー |
| `language_code` | 必須 | API BCP-47 |
| `out_dir` | 解決後パス | **言語付き最終ディレクトリ**（`resolve_out_dir` 済み） |
| `work_dir` | `work` | 作業ルート。実体は `work/{lang}/` |
| `provider` | `xai_grok` | 固定想定 |
| `voice_id` | `leo` | |
| `tts_model` | `None` | 予約。**リクエストに載せない** |
| `sample_rate` | `24000` | base_wav 無し時の内部レート |
| `codec` | `wav` | |
| `tts_speed` | `1.0` | API へ常に 1.0 |
| `text_normalization` | `True` | API へ明示 true |
| `fit` | `force` | |
| `short_mode` | `pad` | `pad` \| `stretch` |
| `max_speed` | `None` | atempo 積の上限。超過は hard_trim + `extreme_speed` |
| `limit` | `None` | 出現順先頭 N キュー |
| `dry_run` | `False` | |
| `keep_raw` | `True` | |
| `also_mp3` | `False` | 完成トラックのみ MP3（128 kbps mono） |
| `strip_emoticons` | `False` | **MVP no-op + warning** |
| `jobs` | `1` | **1 以外はエラー** |
| `tail_pad_ms` | `0` | 完成尺 = last_end + tail（base_wav 無し時） |
| `ja_yomi` | `True` | `lang=="ja"` のとき漢字→ひらがな前処理 |
| `base_wav` | `None` | 既存 WAV にナレーションをミックス |

`out_dir` 解決（`util.resolve_out_dir`）:

- CLI/GUI の `--out` は **ルート**
- 常に `/{lang}` を付与。既に末尾が同じ lang なら二重化しない  
  例: `out`+`ja`→`out/ja`、`out/ja`+`ja`→`out/ja`

---

## 6. 日本語よみ（ja_yomi）

実装: `core/ja_yomi.py`（**kanjiconv 依存なし**。`pyproject` に `[ja]` extra は無い）。

| 項目 | 内容 |
|------|------|
| 条件 | `ja_yomi=True` かつ `lang=="ja"` かつ API キーあり |
| 手段 | Grok Chat `POST /v1/chat/completions`、model `grok-4.5`、structured JSON |
| 単位 | 漢字を含む cue のみ。バッチサイズ 5 |
| キャッシュ | `work/{lang}/ja_yomi_cache.json`（SRT テキストハッシュで無効化） |
| ログ | `work/{lang}/srtspeak_ja_yomi.log`（任意） |
| CLI | `--ja-yomi` / `--no-ja-yomi`（既定オン） |
| GUI | チェックボックス（既定オン、`gui.json` に保存可） |
| doctor | `ja_yomi: grok-chat (Grok Chat API)` |
| dry-run | キー無しなら変換スキップ（原文のまま文字数カウント） |

パイプライン上は **parse → limit → ja_yomi → TTS**。キャッシュキー材料の text はよみ適用後。

---

## 7. TTS（`core/tts_xai.py`）

### 7.1 リクエスト固定

```json
{
  "text": "<cue text>",
  "voice_id": "<resolved>",
  "language": "<language_code>",
  "speed": 1.0,
  "text_normalization": true,
  "output_format": {
    "codec": "wav",
    "sample_rate": 24000
  }
}
```

- 成功ボディ: **生 WAV バイト**（`with_timestamps` 不使用）
- タイムアウト目安: 接続 30s / 読み取り 180s
- 空テキスト: パース段階でエラー
- 15,000 文字超: キュー単位エラー（分割しない）

### 7.2 リトライ

| HTTP | 動作 |
|------|------|
| 200 | 保存 |
| 400 / 401 / 404 | 即失敗 |
| 429 / 500 / 503 | 指数バックオフ最大 3 回（1s, 2s, 4s + ジッタ） |
| 他 | 即失敗 |

### 7.3 キャッシュ（`core/cache.py`）

| 項目 | 値 |
|------|-----|
| 場所 | `work/{lang}/cache/{sha256}.wav` |
| キー材料 | provider, voice_id, language_code, text, sample_rate, codec, tts_speed, text_normalization |
| ハッシュ | キーソート JSON の SHA-256 |
| ヒット | TTS ステージ 1 cue 完了として進捗カウント |

HTTP は **stdlib `urllib`** のみ。

---

## 8. フィット（`core/fit.py`）

`force_fit_wav`:

- 長い: `atempo` 連鎖（各段 0.5–2.0）
- 短い: 既定 `pad`、または `stretch`（減速）
- 許容: fitted が window ±10ms なら合格。外れは hard_trim / hard_pad
- `max_speed`: 指定時は必要速度が上限超なら hard_trim + フラグ
- API `speed` は使わず **ffmpeg のみ**で尺合わせ
- pydub / av / ffmpeg-python は使わない

---

## 9. タイムライン（`core/timeline.py`）

> 実装の正は `timeline.py`。`timeline_new.py` は副次/実験用でパイプライン非参照。

### 9.1 base_wav 無し

1. 無音キャンバス長 = `last_end_ms + tail_pad_ms`（sample 換算）
2. 各 fitted を `[start_ms, end_ms)` に配置
3. フォーマット: mono / s16le / `sample_rate`（既定 24 kHz）
4. 配置は **サンプル加算ミックス**（クリップ ±32767）。窓外は書かない

### 9.2 base_wav 有り（`--base-wav` / GUI）

1. base の PCM・**sample_rate / channels / sampwidth を維持**
2. キャンバス = base 全長（tail_pad で伸ばさない）
3. fitted は base と同じ rate の mono s16le 前提でミックス
4. ナレーションが base 長を超える start はスキップ

完成トラック名: **`GRAN_TENKU_{lang}.wav` 固定**（入力 stem 非依存）。

---

## 10. ffmpeg 解決（`core/ffmpeg_resolve.py`）

1. PATH の `ffmpeg` / `ffprobe`
2. optional `imageio-ffmpeg.get_ffmpeg_exe()`
3. どちらも無ければ `FFmpegNotFoundError`

| 場面 | 挙動 |
|------|------|
| doctor | MISSING 表示でも終了 0 |
| dry-run | ffmpeg 不要 |
| 実 build | 終了コード 2 |

---

## 11. 進捗・中断

- `ProgressEvent`: percent, stage, current, total, message, lang, cue_index
- stage 例: `parse` / `ja_yomi` / `tts` / `fit` / `timeline` / `report` / `done` / `cancelled` / `error`
- `CancellationToken` + cue 境界 check。GUI 中断ボタン / CLI Ctrl+C → 130
- 部分 raw/fitted は残してよい。report `status: cancelled` 可

重み（1 言語 = 100%、実装で微調整可）: parse 小 + tts 大 + fit 中 + timeline/report 小。build-all は言語数で等分。

---

## 12. 入出力レイアウト

```text
{out}/
  summary.json              # build-all
  {lang}/
    cues/{index:04d}.wav    # 正規化後
    fitted/{index:04d}.wav
    GRAN_TENKU_{lang}.wav
    GRAN_TENKU_{lang}.mp3   # --also-mp3
    report.json
work/{lang}/
  raw/{index:04d}.wav
  cache/{sha256}.wav
  ja_yomi_cache.json        # ja かつ ja_yomi 時
  srtspeak_ja_yomi.log      # ja_yomi ログ
```

- `{index:04d}` は SRT 元 index（limit でも詰めない）
- 上書き可。cancel/limit で欠番可

---

## 13. report.json（要点）

| フィールド | 内容 |
|------------|------|
| `status` | `ok` / `error` / `cancelled` / `dry_run` |
| `lang` / `language_code` / `voice_id` / `provider` | |
| `ja_yomi` | 実際に適用対象だったか（bool） |
| `base_wav` | 使った場合パス |
| `sample_rate` / `short_mode` / `fit` / `limit` | |
| `cue_count` / `processed_count` / `total_chars` | |
| `estimated_cost_usd` | dry-run 等。単価 **$15 / 1M chars** |
| `track_path` / duration 系 | |
| `cues[]` | index, window, raw/fitted ms, ratio, cache_hit, hard_trim/pad, extreme_speed, flags |
| シークレット | **一切書かない** |

`summary.json`（build-all）: 言語リストと各 `report.json` パス。

---

## 14. CLI

```text
srtspeak [--locale en|ja] [--verbose|--quiet] <command>
```

| コマンド | 役割 |
|----------|------|
| `doctor` | キー有無・ffmpeg・ja_yomi・PySide6 |
| `languages` | 言語候補 |
| `voices` [--voice-filter …] | ボイス一覧 |
| `dry-run` | パース + 文字数 + 概算（ffmpeg 不要） |
| `build` | 1 言語 |
| `build-all` | `--map lang=file` 複数 |
| `gui` | PySide6 |

### build / build-all 主なオプション

| オプション | 既定 | 説明 |
|------------|------|------|
| `--srt` | 必須 (build) | |
| `--map L=path` | build-all 必須 | 複数可 |
| `--lang` | ファイル名推定可 | 内部キー |
| `--language-code` | lang 既定 | BCP-47 |
| `--out` | `out` | 出力ルート |
| `--work-dir` | `work` | |
| `--voice-id` | `leo` | 単一 or `lang=id` 複数 |
| `--short-mode` | `pad` | `pad`\|`stretch` |
| `--max-speed` | なし | |
| `--tail-pad-ms` | `0` | |
| `--base-wav` | なし | ミックス先 WAV |
| `--ja-yomi` / `--no-ja-yomi` | オン | |
| `--limit N` | 全件 | |
| `--dry-run` | off | build サブコマンド内でも可 |
| `--also-mp3` | off | |
| `--jobs` | `1` | 1 のみ |

終了コード: `0` 成功 / `1` 実行時 / `2` 設定・ffmpeg・キー・SRT / `130` キャンセル。  
`doctor` は欠落があっても **0**。

---

## 15. GUI（`gui/app.py`）

- SRT・Language（BCP-47 + Detect）・Voice・Output root・Base WAV・Max cues・Dry-run・ja_yomi・API キー（マスク）
- 進捗バー + Cancel（`CancellationToken`）
- 非シークレットを `gui.json` に保存。キーは保存しない
- extra: `pip install -e ".[gui]"`

---

## 16. パッケージ構成（実装）

```text
src/srtspeak/
  __init__.py
  __main__.py
  cli.py
  i18n.py
  gui/app.py
  core/
    models.py
    languages.py
    voices.py
    srt_parser.py
    ja_yomi.py
    tts_xai.py
    secrets.py
    cache.py
    ffmpeg_resolve.py
    progress.py
    cancel.py
    fit.py
    timeline.py
    timeline_new.py   # パイプライン非使用
    report.py
    pipeline.py
    util.py
```

Windows: `run_gui.bat` / `run_doctor.bat` / `run_srtspeak.bat`

optional extras（`pyproject.toml`）:

- `gui` → PySide6
- `ffmpeg` → imageio-ffmpeg
- `dev` → pytest / ruff / Babel  
- **`ja` extra は存在しない**（旧記述の kanjiconv は廃止。よみは Grok Chat）

---

## 17. 品質・依存方針

- pytest / ruff、行幅 88、py311、LF
- 必須: stdlib 中心。numpy/scipy/requests **禁止**
- シークレット非保存・非ログ
- 言語解決・config に api_key が無いことのテストを推奨

---

## 18. 正規化パイプライン順序（1 言語）

```text
1. validate config / cancel.check
2. parse SRT → apply limit
3. ja_yomi（条件付き）
4. resolve ffmpeg（dry-run 以外）
5. per cue:
   cancel.check → cache → TTS → mono s16le 正規化
   → cues/ + raw/ + cache → force_fit → fitted/
6. timeline（± base_wav）→ GRAN_TENKU_{lang}.wav → optional mp3
7. report.json
```

---

## 19. 受け入れ条件（実装済みの目安）

- CLI/GUI で language_code と voice_id を指定できる
- キーは env / getpass / GUI セッションのみ
- report に language_code を残しキーを残さない
- fitted ±10ms、完成尺目標 ±50ms（base 無し）
- short_mode 既定 pad
- ffmpeg PATH → imageio-ffmpeg
- 全体進捗と GUI 中断
- ja_yomi 既定オン（ja）
- base_wav ミックス可
- jobs=1、API speed=1.0、生 WAV 保存

---

## 20. 既知リスク

| リスク | 対策 |
|--------|------|
| キー漏洩 | env 優先・非引数・非ファイル・非ログ |
| 429 | jobs=1、backoff、cache |
| 短尺×長文 | 警告、pad 既定 |
| 不明 voice | dry-run エラー / build は警告後 API |
| 同梱 ffmpeg フィルタ不足 | PATH フルビルド推奨 |
| ja_yomi API 失敗 | バッチ単位エラー。キャッシュで再開 |
| base と fitted の rate 不一致 | fit/正規化側で base rate に合わせる前提。不一致はエラー |

---

## 改訂

| 版 | 内容 |
|----|------|
| 設計初期 | 要件・凍結仕様 |
| 0.1.x 同期 | 実装反映: 多言語、男女 voice、ja_yomi（Grok Chat）、base_wav、CLI 全フラグ、out ルート解決、timeline 加算ミックス、extras 修正 |

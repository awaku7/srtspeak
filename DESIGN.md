# SRT → 多言語 TTS タイミング同期 設計

## 目的

既存 SRT（JA / EN / PT）を入力に、各キューの開始・終了時刻へ音声を強制フィットした
ナレーション音声を生成する。

- 言語ごとに **完成トラック 1 本**
- 言語ごとに **キュー単位の分割音声**
- 尺合わせは **ffmpeg 必須**（強制フィット）
- 声は **全言語とも男性**
- TTS は **xAI Grok Text-to-Speech**（`https://api.x.ai/v1/tts`）
- UI は **CLI と GUI（PySide6）の両方**
- **API 言語コードは SRT 内に無い。プログラムが候補を保持し、CLI/GUI で決める**
- **API キーは環境変数 `XAI_API_KEY` を優先**。無い場合は CLI が対話入力、GUI はマスク付き入力欄
- **声質は Grok が提供する voice を CLI/GUI で選択**（一覧はプログラム保持 + API 取得）
- 本ドキュメント時点では **生成しない（設計のみ）**

## 入力

| ファイル | 内部 lang キー | キュー数 | 時間範囲 |
|---|---|---|---|
| `GRAN_TENKU_japan.srt` | `ja` | 293 | 00:00:07,600 → 00:12:44,000 |
| `GRAN_TENKU_English.srt` | `en` | 293 | 同上 |
| `GRAN_TENKU_Portugus.srt` | `pt` | 293 | 同上 |

前提（検証済み）:

- 3 言語のインデックス・タイムコードは完全一致
- 構文エラー / 空テキスト / オーバーラップなし
- 最短キュー 300ms、最長 11.1s、ギャップ 0 が多数
- **SRT 本文に language メタデータは無い**（ファイル名とユーザー指定で決める）

## 言語コード方針（重要）

### 結論

- SRT から言語コードは読めない
- **プログラムがあらかじめ「使える言語コード一覧」を知っている**
- **実際に API へ送る値は CLI 引数または GUI で決める**
- 未指定時のみ、ファイル名/内部キーからの **推定デフォルト** を使う

### プログラムが保持する知識

```python
# core/languages.py 相当
from dataclasses import dataclass

@dataclass(frozen=True)
class LanguageOption:
    code: str           # API に送る BCP-47
    label: str          # GUI 表示
    aliases: tuple[str, ...] = ()


SUPPORTED_LANGUAGE_OPTIONS: list[LanguageOption] = [
    LanguageOption("ja", "Japanese", ("jp", "japanese")),
    LanguageOption("en", "English", ("eng", "english")),
    LanguageOption("pt-BR", "Portuguese (Brazil)", ("pt_br", "ptbr", "brazilian")),
    LanguageOption("pt-PT", "Portuguese (Portugal)", ("pt_pt", "ptpt", "european_pt")),
]

DEFAULT_LANGUAGE_CODE = {
    "ja": "ja",
    "en": "en",
    "pt": "pt-BR",   # 未指定時の仮。CLI/GUI で pt-PT に変更可
}

FILENAME_LANG_HINTS = {
    "japan": "ja",
    "japanese": "ja",
    "english": "en",
    "portugus": "pt",
    "portuguese": "pt",
    "pt": "pt",
}
```

ポイント:

- **`pt` は内部キー**。API には `pt-BR` か `pt-PT` を送る
- プログラムは両方を知っている
- ユーザーが明示指定すればそれが最優先

### 決定優先順位

```text
1. CLI/GUI の明示指定  （最優先）
2. プロファイル/前回 GUI 設定（APIキー以外）
3. 内部 lang キーの DEFAULT_LANGUAGE_CODE
4. 解決不能ならエラー（推測で黙って進めない）
```

### CLI での指定

```text
python -m srtspeak build --srt GRAN_TENKU_Portugus.srt --lang pt --language-code pt-PT

python -m srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=GRAN_TENKU_English.srt ^
  --map pt=GRAN_TENKU_Portugus.srt ^
  --language-code pt=pt-PT

python -m srtspeak languages
```

| オプション | 意味 |
|---|---|
| `--lang` | 内部キー（`ja`/`en`/`pt`） |
| `--language-code` | API に送る BCP-47。単体は値、一括は `pt=pt-PT` |
| `languages` | プログラムが知っている候補を表示 |

### GUI での指定

- 各 SRT 行に **Language コンボ**
- 候補はプログラム保持（`ja`, `en`, `pt-BR`, `pt-PT`, …）
- 推定デフォルトを初期選択し、ユーザーが変更可能
- 前回値は `gui.json` に保存可（**シークレットは保存しない**）

## シークレット / 環境変数

| 変数 | 必須 | 用途 |
|---|---|---|
| `XAI_API_KEY` | 推奨（実 TTS 時） | Grok TTS 認証。最優先ソース |

### 取得優先順位

```text
1. 環境変数 XAI_API_KEY（最優先）
2. 無ければ UI 経路で取得
   - CLI: 対話プロンプトでユーザーに聞く（エコー無し / getpass）
   - GUI: 入力欄に入れる（値がある場合は ******* 表示）
3. それでも無ければ実 TTS はエラー
```

### ルール

- CLI に `--api-key` 引数は **用意しない**（シェル履歴に残るため）
- GUI は **マスク付き入力欄を持つ**
  - `QLineEdit.EchoMode.Password`
  - 値が入っているとき画面上は `*******`（実際の文字は出さない）
  - プレースホルダ例: `環境変数未設定時のみ入力`
  - env にキーがある場合:
    - 入力欄は空のまま、横に `環境変数を使用中` と表示してよい
    - または入力欄にダミーを入れて `*******` 表示し、実体は env を使う（編集したらセッション値を優先）
- **永続保存しない**
  - `gui.json` に API キーを書かない
  - report / ログ / 例外メッセージにキーを出さない
- `BuildConfig` に api_key を載せないのが基本
  - 実行時は `SecretStore` / メモリ上のセッション値として `BuildService` へ渡す
  - プロセス終了で破棄
- `.env` ファイルの直読みはしない（OS 環境に載った値のみ）
- `doctor` はキーの **有無とソース** のみ表示
  - 例: `XAI_API_KEY: set (env)` / `missing`
  - 値・末尾も出さない
- `dry-run` はキー無しでも可
- 実 TTS / `voices` はキー必須

## TTS プロバイダ: xAI Grok

### エンドポイント

| 項目 | 値 |
|---|---|
| Unary TTS | `POST https://api.x.ai/v1/tts` |
| Voices 一覧 | `GET https://api.x.ai/v1/tts/voices` |
| 認証 | `Authorization: Bearer $XAI_API_KEY` |
| 料金目安 | $15.00 / 1M chars |
| 1 リクエスト上限 | 15,000 characters |

補足:

- unary TTS に model 名は不要（Grok TTS サービス）
- バッチ用途は `/v1/tts`。`grok-voice-latest`（realtime）は使わない
- `--tts-model` は将来予約（未指定時は送らない）

### リクエスト（unary）

```json
{
  "text": "高野山 来ました。",
  "voice_id": "leo",
  "language": "ja",
  "speed": 1.0,
  "text_normalization": true,
  "output_format": {
    "codec": "wav",
    "sample_rate": 24000
  }
}
```

| フィールド | 必須 | 本ツール既定 | 説明 |
|---|---|---|---|
| `text` | ✓ | キュー本文 | 最大 15,000 文字 |
| `voice_id` | | `leo` | 男性既定 |
| `language` | ✓ | CLI/GUI で決定 | BCP-47 |
| `speed` | | `1.0` | 0.7–1.5。精密フィットは ffmpeg |
| `output_format.codec` | | `wav` | 編集向け |
| `output_format.sample_rate` | | `24000` | 24 kHz |
| `text_normalization` | | `true` | 数字・記号の安定化 |

### 声質選択（Grok voices）

Grok TTS が提供する `voice_id` を、**CLI / GUI で選択可能**にする。

#### プログラムが知っていること

1. **内蔵カタログ**（オフライン/dry-run/GUI 初期表示用）
2. **ライブ一覧** `GET /v1/tts/voices`（キーがあるとき最新化）

```python
# core/voices.py 相当
@dataclass(frozen=True)
class VoiceOption:
    voice_id: str
    name: str
    description: str
    tags: tuple[str, ...] = ()  # male, narration, calm, ...


# 公式ドキュメント記載の代表 voice（実装時に定数化。API 取得で上書き拡張）
BUILTIN_VOICES: list[VoiceOption] = [
    VoiceOption("leo", "Leo", "Authoritative and strong", ("male", "narration")),
    VoiceOption("rex", "Rex", "Confident and clear", ("male", "clear")),
    VoiceOption("sal", "Sal", "Smooth and balanced", ("male", "calm")),
    VoiceOption("orion", "Orion", "Rich, cinematic, resonant", ("male", "narration")),
    VoiceOption("perseus", "Perseus", "Strong, confident, trustworthy", ("male", "narration")),
    VoiceOption("atlas", "Atlas", "Confident, commanding, reassuring", ("male",)),
    VoiceOption("lux", "Lux", "Grounded, calm, quietly wise", ("male", "calm")),
    VoiceOption("zagan", "Zagan", "Powerful, dramatic", ("male", "character")),
    VoiceOption("helix", "Helix", "Bold, dynamic", ("male", "podcast")),
    VoiceOption("kepler", "Kepler", "Inventive, charismatic", ("male", "podcast")),
    VoiceOption("rigel", "Rigel", "Precise, professional", ("male", "assistant")),
    VoiceOption("castor", "Castor", "Charismatic, easygoing", ("male",)),
    VoiceOption("naksh", "Naksh", "Warm, thoughtful, wise", ("male", "assistant")),
    VoiceOption("eve", "Eve", "Energetic and upbeat", ("female",)),
    VoiceOption("ara", "Ara", "Warm and friendly", ("female",)),
    VoiceOption("carina", "Carina", "Soft, empathetic", ("female",)),
    VoiceOption("luna", "Luna", "Gentle, patient", ("female",)),
    VoiceOption("iris", "Iris", "Friendly, upbeat", ("female",)),
    # 公式追加分は API 取得で合流
]

DEFAULT_VOICE_ID = "leo"  # 男性ナレーション既定
```

#### 決定優先順位

```text
1. CLI/GUI の明示指定（--voice-id / コンボ選択）
2. 前回 GUI 設定（voice_id は保存可）
3. DEFAULT_VOICE_ID（leo）
```

- 全言語で同じ voice を使うのが既定
- 必要なら言語別に上書き可: `--voice-id ja=leo --voice-id en=rex`

#### CLI

```text
python -m srtspeak voices              # 一覧（可能なら API、だめなら builtin）
python -m srtspeak build --voice-id leo
python -m srtspeak build-all --voice-id orion
python -m srtspeak build-all --voice-id ja=leo --voice-id pt=sal
```

| オプション | 説明 |
|---|---|
| `--voice-id` | Grok の voice_id。単一値 or `lang=voice` |
| `--voice-filter male` | `voices` 表示時の絞り込み（任意） |

バリデーション:

- 指定 voice が builtin にも API 一覧にも無ければ **エラー**
- API 取得成功時は API 側を正とする
- API 失敗時は builtin で検証し、警告を出す

#### GUI

- **Voice コンボボックス**（必須 UI）
  - 表示: `leo — Authoritative and strong`
  - 初期値: `leo` または前回値
  - 起動時: builtin を即表示
  - キー解決後: `GET /v1/tts/voices` でリスト更新（失敗しても builtin のまま）
  - 任意フィルタ: すべて / 男性寄り / ナレーション
- 言語ごとに別 voice を選ぶ UI は Phase 2 でも可。MVP は全言語共通 1 つでよい
- 選択した `voice_id` は `gui.json` に保存してよい（シークレットではない）

#### 既定方針

- 既定は男性ナレーション **`leo`**
- ただし **選択対象は Grok の全提供 voice**（女性声も含む）
- 「全部男性」は運用上の初期推奨であり、UI で変更可能

### エラーとリトライ

| HTTP | 対応 |
|---|---|
| 400 | リトライしない |
| 401 | キー不正。即失敗 |
| 404 | 不明 `voice_id` |
| 429/500/503 | 指数バックオフ（既定 3 回） |

### 認証実装

```python
# 擬似コード
def resolve_api_key(*, prompt: bool, session_key: str | None = None) -> str | None:
    env = os.environ.get("XAI_API_KEY")
    if env:
        return env
    if session_key:
        return session_key
    if prompt:  # CLI のみ
        import getpass
        return getpass.getpass("XAI_API_KEY: ")
    return None

api_key = resolve_api_key(prompt=is_cli and not config.dry_run, session_key=gui_session_key)
if not api_key and not config.dry_run:
    raise SystemExit("XAI_API_KEY is not set")
api_base = "https://api.x.ai/v1"
headers = {"Authorization": f"Bearer {api_key}"}
```

- CLI: env 無しなら `getpass` で質問（入力文字は非表示）
- GUI: env 無しなら入力欄のセッション値を使う。表示は常にマスク（`*******`）
- どちらもディスクへ保存しない

## UI 方針（CLI + GUI）

### 原則

- ビジネスロジックは `core.pipeline` に集約
- CLI/GUI は同じ `BuildConfig` / `BuildService`
- 進捗・中断も **core 側の共通契約**（UI は表示とトークン操作のみ）
- 非シークレット設定は CLI 引数優先
- シークレットは **env 優先 + 不足時のみ UI で補完**（保存しない）
- GUI は optional（`pip install -e .[gui]`）

```text
CLI:
  env XAI_API_KEY → 無ければ getpass で質問 → BuildService
GUI:
  env XAI_API_KEY → 無ければマスク入力欄のセッション値 → BuildService
BuildConfig 自体には api_key を載せない
```

### 技術選定

| 層 | 採用 |
|---|---|
| CLI | argparse |
| GUI | PySide6 |
| TTS | xAI Grok `/v1/tts` |
| フィット | ffmpeg/ffprobe（subprocess。PATH → optional imageio-ffmpeg） |
| 配置 | Python PCM（無音キャンバス） |
| 言語候補 | `core/languages.py` |
| 声候補 | `core/voices.py` |
| キー解決 | `core/secrets.py`（env / getpass / GUI session） |
| 進捗 | `ProgressEvent` + callback（CLI/GUI 共通） |
| 中断 | `CancellationToken`（協調的。GUI 必須 / CLI は Ctrl+C） |

## 進捗と中断

### 目的

- CLI / GUI とも **全体のうち何 % か** を常に把握できる
- GUI は実行中に **中断** できる
- 進捗計算と中断判定は UI に散らさず `BuildService` / `pipeline` が担う

### ProgressEvent（共通）

```python
@dataclass(frozen=True)
class ProgressEvent:
    percent: float          # 0.0–100.0（全体）
    stage: str              # parse | resolve | tts | fit | timeline | report | done | cancelled | error
    current: int            # 現ステージ内の完了数（例: cue index）
    total: int              # 現ステージ内の総数
    message: str            # 人間向け短文（キー値を含めない）
    lang: str | None = None # build-all 時の対象言語
    cue_index: int | None = None
```

### 全体 % の計算

1 言語ビルドを 100% とする。重み（初期値、実装で微調整可）:

| ステージ | 重み | 内訳 |
|---|---:|---|
| parse / resolve | 2% | 固定 |
| tts（cue 単位） | 55% | `done_cues / N` |
| fit（cue 単位） | 30% | `done_cues / N` |
| timeline | 10% | 固定 or 部分更新 |
| report / finalize | 3% | 固定 |

- `N` = 対象 cue 数（`limit` 適用後）
- TTS と fit を cue ごとに交互に進める場合は、cue 完了ごとに  
  `2 + (55+30) * (i/N) + …` のように更新してよい
- **build-all**: 言語数 `L` で等分  
  `overall = ((lang_i - 1) + lang_local/100) / L * 100`
- dry-run: parse/resolve/推定のみ。TTS/fit 重みは 0 として 100% まで進める
- キャッシュヒットの TTS も「完了 1 cue」としてカウント（高速でも % は進む）

### コールバック契約

```python
ProgressCallback = Callable[[ProgressEvent], None]

class CancellationToken:
    def cancel(self) -> None: ...
    @property
    def is_cancelled(self) -> bool: ...
    def check(self) -> None:
        """キャンセル済みなら CancelledError を送出"""
```

- `BuildService.run(config, *, on_progress=None, cancel_token=None, api_key=...)`
- ステージ境界と **各 cue の TTS 前後・fit 前後** で `on_progress` と `cancel_token.check()`
- ffmpeg 実行中はプロセス単位。中断要求時は:
  1. 次のチェック点で停止（既定）
  2. 可能なら実行中 subprocess に terminate（タイムアウト後 kill）
- 中断後:
  - 例外: `CancelledError`（または専用）
  - 部分成果（raw/fitted 済み）は残す
  - `report.json` に `"status": "cancelled"` と進捗スナップショットを書いてよい
  - 全体 % は最後に報告した値のまま（100 にしない）

### CLI 表示

- 既定: 1 行更新または段階ログ  
  例: `[ 34.2%] tts  101/293  ja  cue=101`
- Windows でも動く単純実装を優先（`\r` 更新 or 数 cue ごとの改行）
- `--verbose` で cue 詳細、`--quiet` で最終結果のみ
- Ctrl+C → token.cancel() 相当 → 協調終了（可能なら部分 report）

### GUI 表示・中断

- `QProgressBar`（0–100）+ ラベル（stage / current/total / message）
- build-all 時は「言語 i/L」も表示
- 実行は `QThread` + Signal で `ProgressEvent` を UI スレッドへ
- **中断ボタン**（実行中のみ有効）:
  - 押下で `CancellationToken.cancel()`
  - ボタン文言を「中断中…」にし二重実行しない
  - 完了/エラー/中断後に「開始」を再有効化
- 中断・完了・エラーはダイアログまたはログ欄に明示（キーは出さない）

### 実装置き場

- `core/progress.py` … `ProgressEvent`, 重み計算ヘルパ
- `core/cancel.py` または `progress.py` 内 … `CancellationToken`
- `pipeline.py` / `BuildService` … 発火と check
- `cli.py` … テキスト進捗 + SIGINT
- `gui/` … バー / ラベル / 中断ボタン / Worker

## 出力レイアウト

```text
out/{lang}/cues/
out/{lang}/fitted/
out/{lang}/GRAN_TENKU_{lang}.wav
out/{lang}/report.json
work/{lang}/raw/
summary.json
```

report には `lang` と実際の `language_code` を記録。キーは記録しない。

## 全体パイプライン

```text
SRT parse
  → resolve language_code (CLI/GUI > default)
  → Grok TTS (env key or session prompt/input) + cache
  → ffmpeg force-fit
  → PCM timeline
  → report
```

### 強制フィット

- 長い: `atempo` 連鎖（0.5–2.0 を複数段）
- 短い: 既定 `pad`（`--short-mode pad|stretch`）
- 許容: fitted ±10ms、完成尺 ±50ms
- 超過時: hard_trim / hard_pad + report フラグ
- API `speed` は常に `1.0`。精密フィットは **ffmpeg のみ**
- pydub / av / ffmpeg-python は使わない（フィルタは ffmpeg CLI 直叩き）

### ffmpeg / ffprobe 解決

実行は常に **subprocess**。Python で再実装しない。

解決順:

1. `shutil.which("ffmpeg")` / `shutil.which("ffprobe")`（PATH 上のシステムバイナリ）
2. 任意依存 `imageio-ffmpeg` がある場合のみ `imageio_ffmpeg.get_ffmpeg_exe()`（同梱静的バイナリのパス取得。ラッパ再実装ではない）
3. どちらも無ければ `doctor` / 実行時エラー

方針:

- 既定は **PATH のフルビルド ffmpeg**（本機例: 8.1.1 WinGet）
- `imageio-ffmpeg` は optional フォールバック。必須依存にしない
- 同梱バイナリはフィルタが少ない場合がある → 可能なら PATH 優先を推奨
- `doctor` は解決できたパスと版情報を表示（キー値は出さない）
- タイムライン合成は巨大 amix を避け、**無音キャンバス + Python PCM 配置**

実装置き場の目安: `core/ffmpeg_resolve.py` または `core/util.py` の resolve 関数。`fit.py` は解決済みパスを受け取る。

## 共通設定モデル

```python
@dataclass(frozen=True)
class BuildConfig:
    srt_path: Path
    lang: str
    language_code: str
    out_dir: Path
    provider: str = "xai_grok"
    voice_id: str = "leo"
    tts_model: str | None = None
    # api_key は持たない。実行時に env / CLI getpass / GUI セッションから解決
    sample_rate: int = 24000
    codec: str = "wav"
    tts_speed: float = 1.0
    text_normalization: bool = True
    fit: str = "force"
    short_mode: str = "pad"
    max_speed: float | None = None
    limit: int | None = None
    dry_run: bool = False
    keep_raw: bool = True
    also_mp3: bool = False
    strip_emoticons: bool = False
    jobs: int = 1
    tail_pad_ms: int = 0
```

## CLI 設計

```text
set XAI_API_KEY=...          # 推奨。未設定なら CLI が対話で尋ねる
python -m srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --voice-id leo --out out/ja
python -m srtspeak build-all --map ja=... --map en=... --map pt=... --language-code pt=pt-PT
python -m srtspeak languages
python -m srtspeak voices
python -m srtspeak doctor
python -m srtspeak gui
```

CLI のキー入力:

- 実 TTS 開始時、env が無ければ `XAI_API_KEY:` を `getpass` で尋ねる
- 空入力ならエラー終了
- 聞いた値はプロセスメモリのみ。履歴・ファイルに残さない
- `--api-key` オプションは作らない

| コマンド | 役割 |
|---|---|
| `build` / `build-all` | 生成 |
| `dry-run` | 解析のみ（キー不要） |
| `languages` | 言語候補 |
| `voices` | Grok voice 一覧（API 優先、失敗時 builtin。キー無ければ builtin のみ） |
| `doctor` | ffmpeg/ffprobe 解決結果と版 / キー有無（値は出さない） / PySide6 |
| `gui` | GUI 起動 |

**禁止:** `--api-key` オプション。

## GUI 設計（PySide6）

- **API キー入力欄あり**（Password echo）
  - 値がある場合の表示: `*******`（実文字は見せない）
  - env がある場合: `環境変数を使用中` を表示。入力欄は空でもよい
  - env が無く入力欄も空なら、実ビルド時にエラー
  - 入力値はセッションメモリのみ。`gui.json` に保存しない
  - ウィンドウを閉じたら破棄
- **Voice コンボ**で Grok 声質を選択（builtin + API 更新）
- Language / Voice / Limit など非シークレットのみ記憶
- ログにキーを出さない
- **進捗バー + パーセント + ステージ文言**（`ProgressEvent` を Signal で受信）
- **中断ボタン**（`CancellationToken`）。実行中のみ有効。協調的停止
- 実行中は設定変更をロック。終了後に解除

## パッケージ構成

```text
src/srtspeak/
  cli.py
  gui/
  core/
    models.py
    languages.py
    voices.py        # Grok voice カタログ / API 取得
    srt_parser.py
    tts_xai.py
    secrets.py      # env / CLI getpass / GUI session 解決
    ffmpeg_resolve.py  # PATH → imageio-ffmpeg フォールバック
    progress.py     # ProgressEvent / 全体%計算
    cancel.py       # CancellationToken（progress に統合可）
    fit.py
    timeline.py
    report.py
    pipeline.py
    util.py
```

## 品質ルール

- `python -m py_compile` と `pytest`
- LF
- シークレット非保存・非ログ
- Ruff/Black 88、py311
- 言語解決テスト必須
- 「config に api_key が無いこと」をテストで固定してもよい

## 既知リスクと対策

| リスク | 対策 |
|---|---|
| SRT に言語が無い | CLI/GUI + プログラム候補 |
| pt-BR/pt-PT 取り違え | 両方候補化、report に実コード |
| キー漏洩 | env 優先。CLI は getpass、GUI はマスク表示。ファイル/引数/ログ禁止。GUI はセッションのみ |
| 429 | jobs=1、backoff、キャッシュ |
| 短尺×長文 | 警告。short_mode 既定 pad |
| 不明 voice_id | builtin/API で検証。未知はエラー |
| ffmpeg 不在 | PATH → optional imageio-ffmpeg。doctor で明示 |
| 同梱 ffmpeg のフィルタ不足 | PATH フルビルド優先を推奨 |
| 長時間で進捗不明 | 全体% + stage + cue 進捗を CLI/GUI 共通発火 |
| GUI から止められない | CancellationToken。cue 境界で停止。ffmpeg は terminate 可 |

## 実装フェーズ

1. languages + voices カタログ + SRT + dry-run
2. fit/timeline
3. tts_xai（env 認証）
4. CLI
5. PySide6 GUI
6. limit 20 試作
7. フル生成

## 受け入れ条件

- 言語コードを CLI/GUI で指定できる
- Grok の voice_id を CLI/GUI で選択できる（一覧表示あり）
- プログラムが言語候補を保持
- API キーは env 優先。CLI は未設定時に質問、GUI はマスク入力。設定ファイル・引数・ログに残さない
- report に `language_code` を残し、キーは残さない
- fitted ±10ms、完成尺 ±50ms
- short_mode 既定は `pad`
- ffmpeg は PATH 優先、無ければ optional `imageio-ffmpeg`、どちらも無ければ doctor/実行エラー
- CLI/GUI とも全体進捗（0–100%）を表示できる
- GUI から実行を中断でき、部分成果と cancelled 状態を残せる

## 非スコープ（当面）

- Voice Agent realtime
- Custom voice clone
- 動画 mux
- 文章リライト
- Web UI

## 実装確定（Grok 前提・凍結）

> 本節は実装着手前の **凍結仕様**。公式 docs（Text to Speech / Voices）と整合。  
> 変更する場合は本節を先に直し、コードを追従させる。

### A. TTS レスポンス（unary `POST /v1/tts`）

| 項目 | 確定値 |
|---|---|
| 成功時ボディ | **生の音声バイト**（`response.content` をそのまま保存） |
| 既定 Content-Type | `audio/wav`（`output_format.codec=wav` 時） |
| `with_timestamps` | **常に送らない / false**（JSON envelope にしない） |
| `optimize_streaming_latency` | **送らない**（バッチ品質優先） |
| 失敗時 | HTTP ステータス + 本文テキスト（キーはログに出さない） |
| タイムアウト | 接続 30s / 読み取り 180s（cue 単位。15 分上限の API より短く） |

```python
# 成功パス（概念）
body = http_post_bytes(...)  # Content-Type: application/json ではない
path.write_bytes(body)       # work/{lang}/raw/{index:04d}.wav
```

- `with_timestamps=true` は **非スコープ**（将来の字幕同期用に予約のみ）
- WebSocket / realtime / Voice Agent は **使わない**

### B. リクエスト固定フィールド

```json
{
  "text": "<cue text>",
  "voice_id": "<resolved>",
  "language": "<language_code BCP-47>",
  "speed": 1.0,
  "text_normalization": true,
  "output_format": {
    "codec": "wav",
    "sample_rate": 24000
  }
}
```

| フィールド | 本ツール |
|---|---|
| `speed` | **常に 1.0**（精密フィットは ffmpeg のみ） |
| `text_normalization` | **true**（API 既定 false だが本ツールは true を明示送信） |
| `voice_id` 省略時 API 既定 | eve。**本ツールは常に voice_id を明示**（既定 `leo`） |
| `language` | 必須。`auto` は使わない（再現性のため明示コード） |
| 空テキスト | パース段階でエラー（API に送らない） |
| 15,000 文字超 | キュー単位でエラー（分割しない） |

### C. 音声フォーマット（パイプライン内部）

| 段階 | フォーマット |
|---|---|
| Grok 出力（要求） | WAV / 24 kHz |
| raw 保存後の正規化 | ffmpeg で **mono / s16le / 24000 Hz** に統一 |
| fitted | 同上 |
| タイムライン・キャンバス | **mono / s16le / 24000 Hz** の無音 PCM |
| 完成トラック | WAV（同上）。`also_mp3` 時は追加で MP3 |

正規化フィルタ例（概念）:

```text
ffmpeg -i in.wav -ac 1 -ar 24000 -c:a pcm_s16le out.wav
```

- チャンネル: **mono 固定**（stereo が来ても downmix）
- sample format: **signed 16-bit little-endian**
- sample rate: **24000**（`BuildConfig.sample_rate` と一致。変更時は全段同じ値）
- タイムライン実装: stdlib `array.array("h")` または `bytearray`（numpy 非依存）
- 配置: `start_sample = round(start_ms * sample_rate / 1000)` に **上書き配置**（加算しない）

### D. キュー窓クリップ方針（隣接キュー）

前提: ギャップ 0 が多数。**次キューへはみ出さない**。

| 規則 | 内容 |
|---|---|
| 窓 | cue `i` の有効区間は `[start_ms, end_ms)`（半開） |
| 目標尺 | `window_ms = end_ms - start_ms` |
| fit 後 | fitted 長を `window_ms` に合わせる（atempo / pad / stretch） |
| 許容 | fitted 長が `window_ms ± 10ms` なら合格 |
| 超過 | **hard_trim** で `window_ms` に切り詰め + report フラグ |
| 不足 | **hard_pad**（無音）で `window_ms` に伸ばす + フラグ（short_mode=pad 経路と整合） |
| 配置 | タイムライン上 `start_ms` から **最大 window_ms 分だけ** 書く |
| 次キュー | cue `i+1` の `start_ms` 以降は cue `i` が一切書かない |
| 最終端 | 完成尺 = `last_end_ms + tail_pad_ms`。目標 ±50ms |

ゼロギャップでも cue 境界で PCM が重ならない（後勝ち上書きも避けるため、各 cue は自分の窓内のみ）。

### E. キャッシュ

| 項目 | 確定値 |
|---|---|
| 有効 | 常時（`dry_run` 以外）。無効化フラグは当面無し |
| 置き場 | `work/{lang}/cache/{sha256_hex}.wav` |
| キー材料 | `provider`, `voice_id`, `language_code`, `text`（正規化後の送信用文字列）, `sample_rate`, `codec`, `tts_speed`, `text_normalization` |
| ハッシュ | 上記を **UTF-8 JSON（キーソート・区切り固定）** にした SHA-256 hex |
| ヒット時 | cache → `work/{lang}/raw/{index:04d}.wav` へコピー（または同一内容を書き出し） |
| ミス時 | API → raw 保存 → cache へもコピー |
| 進捗 | ヒットも TTS ステージ 1 cue 完了としてカウント |
| 破棄 | ユーザーが `work/` を消す運用。ツール側 GC はしない |

`keep_raw=false` でも cache は残してよい（再実行コスト削減）。`cues/` はユーザー向け成果として `out/` 側。

### F. ファイル命名・ディレクトリ

```text
out/
  summary.json                 # build-all 時のみ（単体 build でも書いてよい）
  {lang}/
    cues/{index:04d}.wav       # TTS 後・正規化済み（ユーザー配布用 raw 相当）
    fitted/{index:04d}.wav     # 窓フィット後
    GRAN_TENKU_{lang}.wav      # 完成トラック（本プロジェクト固定名）
    GRAN_TENKU_{lang}.mp3      # --also-mp3 時のみ
    report.json
work/
  {lang}/
    raw/{index:04d}.wav        # API/cache 直後（正規化前でも可。正規化後を推奨）
    cache/{sha256}.wav
```

| 規則 | 内容 |
|---|---|
| `{index:04d}` | SRT のキュー番号（1 始まり）。`limit` 時も **元の index** を使う（詰めない） |
| `{lang}` | 内部キー `ja` / `en` / `pt` |
| 完成トラック名 | **`GRAN_TENKU_{lang}.wav` 固定**（入力 stem に依存しない） |
| `out_dir` | CLI `--out` のルート。既定 `out` |
| 上書き | 同 path は上書き。部分実行（limit/cancel）で欠番があってよい |

### G. `report.json` 最小スキーマ

```json
{
  "status": "ok",
  "lang": "ja",
  "language_code": "ja",
  "voice_id": "leo",
  "provider": "xai_grok",
  "srt_path": "GRAN_TENKU_japan.srt",
  "sample_rate": 24000,
  "short_mode": "pad",
  "fit": "force",
  "limit": null,
  "cue_count": 293,
  "processed_count": 293,
  "track_path": "out/ja/GRAN_TENKU_ja.wav",
  "track_duration_ms": 764000,
  "target_duration_ms": 764000,
  "duration_error_ms": 0,
  "started_at": "2026-01-01T00:00:00+00:00",
  "finished_at": "2026-01-01T00:10:00+00:00",
  "cancelled_at_percent": null,
  "warnings": [],
  "cues": [
    {
      "index": 1,
      "start_ms": 7600,
      "end_ms": 9200,
      "window_ms": 1600,
      "text_chars": 12,
      "raw_duration_ms": 1800,
      "fitted_duration_ms": 1600,
      "ratio": 0.8889,
      "cache_hit": false,
      "hard_trim": false,
      "hard_pad": false,
      "extreme_speed": false,
      "flags": []
    }
  ]
}
```

| フィールド | 規則 |
|---|---|
| `status` | `ok` / `error` / `cancelled` / `dry_run` |
| シークレット | **一切書かない** |
| `ratio` | `raw_duration_ms / window_ms`（raw が無い dry-run は null 可） |
| `extreme_speed` | 必要 atempo 積が 2.0 超または 0.5 未満、または `max_speed` 超過 |
| `warnings` | 文字列配列（短尺×長文、ゼロギャップ密集、ffmpeg フォールバック使用など） |
| dry-run | `cues` に text_chars / window_ms / 推定警告。音声 path は null |

`summary.json`（build-all）:

```json
{
  "status": "ok",
  "languages": ["ja", "en", "pt"],
  "reports": {
    "ja": "out/ja/report.json",
    "en": "out/en/report.json",
    "pt": "out/pt/report.json"
  }
}
```

### H. HTTP クライアント・依存

| 項目 | 確定 |
|---|---|
| HTTP | **stdlib** `urllib.request`（必須依存に `requests`/`httpx` を増やさない） |
| JSON | stdlib `json` |
| WAV 読取（配置） | stdlib `wave` + `array` |
| GUI | optional extra: `PySide6` |
| ffmpeg フォールバック | optional extra: `imageio-ffmpeg` |
| 数値 | numpy / scipy **禁止**（テストも stdlib） |

### I. 並列・limit・その他フラグ

| 項目 | 確定 |
|---|---|
| `jobs` | **MVP は 1 のみ**。`jobs!=1` は警告して 1 に落とすかエラー（実装はエラー推奨） |
| `limit` | **先頭から index 昇順の N 件**（1..N ではなく「出現順の最初の N」。通常は index 1..N） |
| `also_mp3` | 完成トラックのみ。`libmp3lame`、**128 kbps**、24 kHz mono |
| `tail_pad_ms` | 完成トラック末尾に無音を追加。cue 窓には影響しない |
| `strip_emoticons` | 予約。true でも **MVP は no-op + warning** |
| `max_speed` | 予約。設定時は atempo 積の上限。超過は hard_trim + `extreme_speed` |
| `tts_model` | 予約。**リクエストに載せない** |
| dry-run | キー不要。parse + 解決 + 推定 report。TTS/fit/timeline なし |

### J. リトライ・エラー

| HTTP | 動作 |
|---|---|
| 200 | 生バイト保存 |
| 400 | 即失敗（リトライなし） |
| 401 | 即失敗（キー不正） |
| 404 | 即失敗（不明 voice_id） |
| 429 / 500 / 503 | 指数バックオフ **最大 3 回**（待ち 1s, 2s, 4s + 少量ジッタ） |
| それ以外 | 即失敗 |

専用例外:

- `BuildCancelled` … ユーザー中断（stdlib `asyncio.CancelledError` と混同しない）
- `TtsError` / `FitError` / `ConfigError` … 必要最小限

### K. 終了コード（CLI）

| code | 意味 |
|---|---:|
| 0 | 成功（dry-run 含む） |
| 1 | 実行時エラー（TTS/fit/IO） |
| 2 | 設定・引数・解決不能（キー無し、不明 voice、SRT 不正） |
| 130 | キャンセル（Ctrl+C / GUI 中断の CLI ラッパ） |

### L. 推定コスト（dry-run）

- 単価: **$15.00 / 1,000,000 characters**（公式目安）
- 文字数: 各 cue の **API 送信テキスト** の Unicode コードポイント数合計（キャッシュヒット想定は別表示可）
- report / コンソールに `estimated_cost_usd` を出してよい（課金保証ではない旨は不要な長文にしない）

### M. Voices / Languages カタログ（公式同期）

- 内蔵 voice は docs 記載分を定数化。API `GET /v1/tts/voices` の `voices[].voice_id` / `name` で上書き拡張
- 追加で docs に出ている例: `altair`, `zenith`, `helios`, `cosmo`, `celeste`, `ursa`, `sirius`, `lumen` 等 → **builtin に含める**
- voice_id は **case-insensitive**（保存・送信は小文字に正規化）
- 言語: 公式 20 言語 + 本ツール既定マップ。`pt` → `pt-BR`。候補に `pt-PT` を必ず含める
- カスタム voice ID: ユーザー明示時のみ許可。builtin に無くても **API 検証成功なら通す**（API 失敗時は警告付きで通すかエラー → **エラー**）

### N. 正規化パイプライン順序（1 cue）

```text
1. cancel.check
2. cache lookup
3. miss → POST /v1/tts → raw bytes
4. 正規化 WAV (mono s16le 24k) → work/.../raw + out/.../cues + cache
5. ffprobe duration
6. ffmpeg force-fit → out/.../fitted
7. cancel.check / progress
```

全 cue 後:

```text
8. silence canvas [0, last_end_ms + tail_pad_ms)
9. 各 fitted を start_ms に配置（窓内のみ）
10. WAV 書き出し → 任意 MP3
11. report.json / summary.json
```

### O. 受け入れ（本節追加分）

- TTS 成功ボディは生 WAV バイトとして保存できる
- 内部 PCM は mono/s16le/24k で統一
- 隣接キューへ音声がはみ出さない
- 同一 text+voice+lang 再実行で cache ヒットする
- report が上記スキーマを満たしキーを含まない
- `jobs=1`、`with_timestamps` 未使用、API base 固定

## 次のアクション

1. **設計承認**（「実装確定」節含む）
2. コア + CLI（Phase 1–2: languages/voices/parser/dry-run → fit/timeline テスト）
3. GUI（任意 extra）
4. 明示指示後のみ `--limit 20` で TTS 実生成 → 問題なければ 3 言語フル

**凍結完了。実装は承認後に着手。**

## 参考

- `https://docs.x.ai/developers/model-capabilities/audio/voice`
- `https://docs.x.ai/developers/model-capabilities/audio/text-to-speech`
- `POST https://api.x.ai/v1/tts`

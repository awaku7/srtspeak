# 多言語 SRT 生成 — 設計と srtspeak アダプト方針

**状態:** 設計（未実装）・版 0.5  
**目的:** 入力 SRT 1 本から、**タイムコードを保持したまま**他言語 SRT を高精度に生成し、既存の `build` / `build-all`（Grok TTS + 強制フィット）へそのまま流す。  
**関連:** [DESIGN.md](DESIGN.md)（TTS パイプライン正本）
**必須:** TDD（P9）・progress（P5）・multi-target（P5b）・**言語以外同一（P0）**
**成果物契約:** 生成 SRT はソースと **キュー本文（言語）以外すべて同一**（件数・index・start/end・半開区間・並び）。

---

## 1. 現状とギャップ

### 1.1 今の srtspeak

| できること | できないこと |
|------------|--------------|
| 言語ごとの **既存 SRT** → TTS → 尺フィット → 完成 WAV | SRT テキストの **翻訳・生成** |
| `ja_yomi`（ja のみ・漢字→ひらがな・意味非変更） | 言語間の意味転送 |
| `build-all --map ja=… --map en=…` | ソース 1 本から map 用 SRT を自動生成 |

前提ワークフロー（現状）:

```text
人手 or 外部ツールで ja/en/pt SRT を揃える
        → srtspeak build-all --map …
```

### 1.2 欲しいもの

```text
source.srt（例: ja）
        → [本機能] 他言語 SRT を正確に生成
        → srtspeak build / build-all
```

「正確」の定義（本設計の優先順位）:

1. **構造同一（言語以外同一）** — キュー数・index・`start`/`end`・並びがソースと **完全一致**。変わるのは各キューの **text（言語）のみ**
2. **意味正確** — 各キューの発話意図・固有名詞・トーンを保持
3. **発話可能** — その窓長で TTS が破綻しにくい長さ（過長→extreme_speed / hard_trim を減らす）
4. **形式正確** — 合法 SRT、空行・空テキストなし、15,000 文字/キュー以下

時間を動かして「読みやすくする」再タイミングは **非スコープ（v1）**。  
キュー分割・結合・index 振り直しも **禁止**。  
（必要なら将来 `retime` サブコマンドを分離。TTS フィット前提では **タイムロック＋構造同一が正**。）

---

## 2. 設計原則

| ID | 原則 | 理由 |
|----|------|------|
| P0 | **Language-only delta** | 生成 SRT はソースと **text（言語）以外すべて同一**。件数・index・時刻・並び不変。ファイル中身の差分は翻訳文のみ |
| P1 | **Timing-lock** | 映像・既存多言語 SRT と同期。`Cue.start_ms/end_ms/index` は翻訳で不変 |
| P2 | **Cue-atomic** | 1 キュー = 1 翻訳単位。結合・分割しない（index 対応が壊れる） |
| P3 | **Context-aware** | 前後キュー・作品 glossary を渡し、用語ゆれを抑える |
| P4 | **Length-aware（推奨オン）** | 窓 ms と言語別話速から予算文字数を渡し、過長を抑制 |
| P5 | **ja_yomi と同型** | Grok Chat + structured JSON + バッチ + ディスクキャッシュ + **progress 必須** + cancel |
| P5a | **Progress 必須** | 全長時間処理で `ProgressEvent` を必ず発火。CLI 進捗表示・cancel 連携の前提。省略・サイレント実行は不可 |
| P5b | **Multi-target 必須** | 1 実行で N 言語。直列・キャッシュ分離・部分失敗継続。progress は全 tgt 合算 |
| P6 | **TTS パイプライン非侵襲** | 翻訳は **前段コマンド or 明示ステージ**。既存 `BuildConfig` の必須経路を壊さない |
| P7 | **シークレット方針共通** | `XAI_API_KEY` のみ。SRT・report にキーを書かない |
| P8 | **決定論に寄せる** | temperature 低 / キャッシュキーに model・prompt 版・src hash・tgt lang |
| P9 | **TDD 必須** | 実装前に失敗するテストを書く。本番コードは赤→緑→リファクタのみ。モックで API を隔離 |

---

## 3. 入出力仕様

### 3.1 入力

| 項目 | 内容 |
|------|------|
| `--srt` | ソース SRT（UTF-8 / BOM 可）。既存 `parse_srt` を通す |
| `--source-lang` | ソース言語 BCP-47 または内部キー（例: `ja`） |
| `--to` | ターゲット。**複数必須対応（v1）**。繰り返し指定（`en`, `pt-BR`, `es` …）。1 件だけも可 |
| `--out` | 出力ルート（下記レイアウト） |
| 任意 | glossary、tone、length モード、model、limit、dry-run |

ソース言語はファイル名ヒントでも推定可（既存 `guess_lang_from_filename`）。明示優先。

### 3.1-A) 複数ターゲット（v1 必須）

1 回の `translate` で **複数言語をまとめて生成**する。単一言語は `targets` 長さ 1 の特殊ケース。

**CLI 形（いずれも可・実装は list に正規化）:**

```text
# 推奨: 繰り返し
srtspeak translate --srt src.srt --source-lang ja --to en --to pt-BR --to es --out srt_gen

# 任意: カンマ区切りも受け付けるなら同一 list へ
srtspeak translate --srt src.srt --source-lang ja --to en,pt-BR,es --out srt_gen
```

| 規則 | 内容 |
|------|------|
| 順序 | CLI 出現順。report・progress もこの順 |
| 重複 | 正規化後に同一コードが二度出たら **エラー**（黙ってユニーク化しない） |
| ソース言語除外 | `target == source_lang` は **スキップ + warning**（ja→ja コピーしない）。全部スキップならエラー |
| 未知コード | `normalize_language_code` 失敗で **即エラー**（他 tgt に進まない）— 設定ミスを早期発見 |
| 実行順 | **直列**（tgt を一つずつ）。並列 Chat は非スコープ（レート制限） |
| キャッシュ | **ターゲット別ファイル** `cache_{tgt}.json`。言語間で共有しない |
| 成果物 | `{out}/{tgt}/…srt` を言語ごとに独立書き出し。1 言語成功分は残す |
| 失敗ポリシー | 既定 **continue**: 1 tgt 失敗 → report に error、他 tgt 続行、終了コードは部分失敗（例: 1）。`--fail-fast` で即中断 |
| progress | 分母 = 全 tgt の対象キュー合計。`lang=` に現在 tgt。message 例: `en batch 3/12 (target 1/4)` |
| glossary | ファイル 1 つを全 tgt で共有。エントリに言語キーがあればその tgt 用訳を優先 |
| report | `targets: { "en": {ok, path, cues, errors}, "pt-BR": … }, "summary": {ok, failed, skipped}` |

`TranslateConfig.targets: list[str]` は **空禁止・1 件以上**。GUI は複数チェックボックス → 同じ list。

**build-all 接続:** 出力ディレクトリを並べて `--map` するだけ。translate が `maps.example.txt` を吐くのは Phase 3 任意。

### 3.2 出力（提案）

```text
{out}/
  translate_report.json          # 全体サマリ
  {target_lang}/                 # 内部キー or BCP-47 正規化名
    GRAN_TENKU_{lang}.srt        # または {source_stem}_{lang}.srt
    translate_cues.jsonl         # 任意: デバッグ用 原文/訳/flags
work/translate/{src_hash}/
  cache_{target}.json            # キュー単位キャッシュ
  translate.log
```

命名方針（実装時に1つに固定）:

- **A（推奨）:** `GRAN_TENKU_{lang}.srt` — 既存成果物名と揃え、`build-all` と対応しやすい
- **B:** `{source_stem}_{lang}.srt` — ソース複数作品向け

`build-all` 接続例:

```bat
srtspeak translate --srt GRAN_TENKU_japan.srt --source-lang ja --to en --to pt-BR --out srt_gen
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=srt_gen/en/GRAN_TENKU_en.srt ^
  --map pt=srt_gen/pt/GRAN_TENKU_pt.srt ^
  --voice-id leo --out out
```

### 3.3 SRT 書き出し規則（言語以外同一）

**契約:** 生成ファイルを parse した結果は、ソース parse 結果と **text 以外フィールドが全一致**。

| 項目 | 規則 |
|------|------|
| キュー数 | ソースと同一（増減禁止） |
| index | ソース同一・欠番/重複禁止 |
| start_ms / end_ms | ソース同一（ms 整数）。半開区間の意味も同一 |
| 並び | ソース順 |
| text | **唯一の差分** = ターゲット言語の訳文 |
| タイムスタンプ表記 | `HH:MM:SS,mmm --> HH:MM:SS,mmm`（カンマ ms。ソース値を ms 経由で再フォーマット → 正規化表記は可、**値は不変**） |
| キュー内改行 | 訳文の可読性で 1〜2 行に正規化可（text の一部）。**キュー境界の空行構造は format_srt がソースと同型で出力** |
| HTML タグ | ソース側は parse 時除去済み。訳文にタグを新規生成しない |
| 空 text | 禁止（validate で落とす） |
| 終端 | LF 推奨（リポジトリ方針） |

ライターは **`srt_parser` に `format_srt(cues) -> str` を追加**するのが最小侵襲（現在は parse のみ）。

**検証（必須）:** 書き出し後に `parse_srt` し直し、全 cue で `index/start_ms/end_ms` がソースと一致、`len(cues)` 一致を assert。不一致は書き込み失敗扱い。

---

## 4. 「正確さ」の技術設計

### 4.1 言語以外同一 + タイムロック（必須・機械保証）

```text
len(out_cues)    = len(src_cues)
out_cue.index    = src_cue.index
out_cue.start_ms = src_cue.start_ms
out_cue.end_ms   = src_cue.end_ms
out_cue.text     = translated_text only   # 唯一の差分
```

モデルに時刻・index を再出力させない。JSON スキーマは `index` + `text` のみ（ja_yomi と同型）。  
時刻・index は常にソース `Cue` から復元 → **時刻ハルシネーションを構造的に排除**。  
merge 後に件数・index 集合・各 ms をソースと突合。不一致は再試行 or 失敗。

### 4.2 意味正確（モデル + 制約）

**API:** 既存と同じ Grok Chat  
`POST https://api.x.ai/v1/chat/completions`  
**model（案）:** `grok-4.5`（ja_yomi と共通。変更時は cache キーに model id を含める）

**structured output:** ja_yomi と同型スキーマ。

```json
{
  "type": "object",
  "properties": {
    "cues": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "index": { "type": "integer" },
          "text": { "type": "string" }
        },
        "required": ["index", "text"],
        "additionalProperties": false
      }
    }
  },
  "required": ["cues"],
  "additionalProperties": false
}
```

**system 指示の核（要約）:**

1. 指定ターゲット言語へ翻訳。解説・前置き禁止。訳文のみ
2. キュー数・index を維持。結合・分割禁止
3. 固有名詞は glossary 優先。無ければソース表記維持 or 標準的な現地表記（設定で切替）
4. 字幕向け短さ。口語・ナレーショントーンをソースに合わせる
5. 数字・単位の扱い規則（そのまま / ローカライズ）を指定
6. （length-aware 時）各キューの `max_chars` を超えない。意味を落とさず圧縮

**コンテキスト窓（バッチ）:**

- バッチサイズ: 既定 **5〜10**（ja_yomi=5。翻訳は文脈が重要なので **8** 前後を初期値に検証）
- 各バッチに **オーバーラップ文脈**: 直前 1〜2 キューの原文（訳さない・参照のみ）を prompt に付与
- 作品全体 glossary を毎バッチ添付（短い bullet）

### 4.3 用語集（glossary）

```yaml
# glossary.yaml 例
terms:
  - source: "グラン天空"
    keep: "GRAN TENKU"          # 全言語で固定
  - source: "結界"
    en: "barrier"
    "pt-BR": "barreira"
tone: "documentary narration"
do_not_translate:
  - "GRAN_TENKU"
```

CLI: `--glossary path`  
未指定時は空。GUI は後回し可。

### 4.4 長さ制御（発話可能性）

TTS 後段が `force_fit` するため、**過長訳は音質劣化の主因**。

#### 予算の見積もり（v1 ヒューリスティック）

```text
budget_chars ≈ floor(window_ms / 1000 * chars_per_sec[lang] * safety)
```

| 言語グループ | chars_per_sec 初期値（要実測調整） | 備考 |
|--------------|-------------------------------------|------|
| ja | 7–9 | ひらがな化後は見た目文字数≠モーラ。ja は yomi 後長も考慮 |
| en | 14–18 | |
| pt/es/fr/de/it | 13–17 | |
| zh/ko | 5–8 | |

`safety` 既定 0.85。`--length-mode`:

| モード | 挙動 |
|--------|------|
| `off` | 予算を渡さない（意味優先） |
| `hint`（既定案） | prompt に max_chars を渡すのみ |
| `enforce` | 超過キューを **第二パス圧縮翻訳**（同一 index、指示を「短縮」に変更） |
| `report-only` | 翻訳後に超過フラグだけ report |

第二パスも structured JSON・キャッシュキー別（`pass=compress`）。

#### TTS 連携メトリクス（将来）

`build` の report の `ratio` / `extreme_speed` を translate にフィードバックするループは v2。  
v1 は文字予算 + 人間が `translate_report` を見て glossary/手動修正。

### 4.5 検証ゲート（機械）

翻訳マージ後、書き出し前:

| チェック | 失敗時 |
|----------|--------|
| キュー数一致 | バッチ再試行 1 回 → だめならエラー |
| 全 index がソース集合と一致 | 同上 |
| 空テキスト | エラー or 原文フォールバック（`--on-empty fail|keep-source`） |
| 15,000 文字超 | エラー |
| ソースと start/end 不一致 | 実装バグ扱い（ライターがソース時刻のみ使うので通常発生しない） |
| length enforce 後も予算大幅超過 | warning を report |

**原文フォールバック**は「止めない」用途。正確さ優先なら既定 `fail`。

### 4.6 キャッシュ

```text
key = sha256(json({
  "v": 1,                         # prompt/schema 版
  "model": "grok-4.5",
  "src_lang": "ja",
  "tgt": "en",
  "index": 12,
  "text": "<source text>",
  "glossary_hash": "...",
  "length_mode": "hint",
  "max_chars": 42                 # 使う場合
}))
```

ファイル: `work/translate/.../cache_{tgt}.json`  
SRT 全体 hash で無効化（ja_yomi の `_srt_hash` と同パターン）。

---

## 5. 処理フロー

### 5.1 単体コマンド（推奨エントリ）

```text
srtspeak translate
  1. parse_srt(source) → apply_limit
  2. resolve source_lang / targets
  3. load glossary
  4. for each target:
       a. load cache
       b. pending cues をバッチ化
       c. Chat API（context + glossary + budget）
          ※ 各バッチ前後で ProgressEvent 必須
       d. validate batch → merge
       e. optional compress pass（ここも progress）
       f. format_srt → write
       g. per-target stats
  5. translate_report.json
```

dry-run: パース + 予算超過見込み + 概算トークン/コスト（Chat 単価は TTS の $15/1M chars と別。**実価格は xAI の Chat 料金表を参照し report に model 名のみでも可**）。v1 は「キュー数・文字数・バッチ数」必須、USD は任意。dry-run でも progress（parse/budget 集計）を出してよい。

### 5.1-A) Progress（必須・実装契約）

長時間処理のため **progress はオプションではない。必須。**

既存 `core/progress.py` の `ProgressEvent` をそのまま使う（新規イベント型を増やさない）。

| フィールド | translate での使い方 |
|------------|----------------------|
| `percent` | 0–100。全ターゲット合算 or ターゲット内。**実装は「全ターゲット × pending キュー」を分母にした全体 % を推奨**（CLI が一本のバーで足りる） |
| `stage` | 固定文字列: `translate` / `translate_compress` / `translate_write`（必要最小） |
| `current` / `total` | 処理済みキュー数 / 対象キュー総数（キャッシュヒット分も「処理済み」に含めて % が戻らないようにする） |
| `message` | 人間可読。例: `en batch 3/12` / `pt-BR compress 2/4` / `cache hit 40/200` |
| `lang` | 現在の **target** 言語コード |

**発火タイミング（必須）:**

1. ターゲット開始時（message に tgt）
2. **各 Chat バッチの直前または直後**（ja_yomi と同じ。バッチ単位が最小粒度）
3. compress 第二パスの各バッチ
4. ターゲット完了・全完了（percent=100）
5. cancel_token.check() はバッチ境界で必須（progress と対）

**禁止:**

- `progress_cb=None` のまま本番経路を通すこと（テスト以外）
- API 待ち中に一切イベントが無いこと（バッチ前に必ず 1 回）
- percent の逆行（cache 再計算で current が減る等）

**CLI:**

- 既存 build と同様、stderr または標準の進捗表示に `progress_cb` を接続
- `--json-progress` 等が既存にあれば同じチャネルを共有（無ければ build 側踏襲で行表示）

**GUI（Phase 3）:**

- Worker が同じ `ProgressEvent` をシグナル化。stage/lang/message をステータス行へ

**関数シグネチャ契約（案）:**

```text
run_translate(
    config: TranslateConfig,
    *,
    api_key: str,
    progress_cb: Callable[[ProgressEvent], None],  # 必須（Optional にしない）
    cancel_token: CancelToken | None = None,
) -> TranslateResult
```

テストでは no-op コールバック `lambda e: None` を渡す。本番 CLI は必ず表示用 cb を渡す。

### 5.2 パイプライン内蔵（オプション・後段）

```text
run_build 先頭:
  parse → [optional translate_to_self?] → ja_yomi → TTS …
```

**v1 では推奨しない。** 理由:

- 翻訳成果物（SRT）を人がレビュー・修正してから TTS する流れが「正確さ」に効く
- build がネットワーク・コスト・失敗面で重くなる
- 既存 `BuildConfig` を肥大化させない

代わりに:

```text
translate（レビュー可）→ build-all
```

を正規パスにする。  
どうしても一発なら v2 で `build --translate-from ja` を薄いラッパに。

### 5.3 ja 向け特記

| ケース | 方針 |
|--------|------|
| ソース ja → 他言語 | 本機能の主対象。**漢字のまま翻訳**（先に yomi しない）。yomi は TTS 直前の ja ビルド専用 |
| ソース他言語 → ja | 翻訳で日本語 SRT 生成。その後 `build --lang ja` が **ja_yomi** を適用 |
| ソース ja → ja | no-op（コピー）or 禁止 |

---

## 6. srtspeak へのアダプト（モジュール配置）

### 6.1 新規・変更ファイル（案）

```text
src/srtspeak/
  cli.py                          # subcommand translate
  core/
    srt_parser.py                 # + format_srt / write_srt
    srt_translate.py              # NEW: 本体（ja_yomi 兄弟）
    translate_glossary.py         # NEW: yaml/json 読み込み（stdlib のみなら json 既定）
    languages.py                  # target 正規化・話速テーブル
    models.py                     # TranslateConfig（BuildConfig と分離）
    pipeline.py                   # 触らない or 極薄ラッパのみ（v1 は触らない）
  gui/app.py                      # v1 任意。CLI 優先
tests/
  test_srt_format_roundtrip.py
  test_srt_translate_merge.py     # モック HTTP
  test_translate_length_budget.py
```

依存: **追加パッケージなし**（ja_yomi 同様 urllib + json）。  
glossary を YAML にしたい場合のみ optional `pyyaml` — **v1 は JSON で十分**（stdlib）。

### 6.2 `TranslateConfig`（BuildConfig と分離）

```text
srt_path, source_lang, targets: list[str]
out_dir, work_dir
model, batch_size
glossary_path: Path | None
length_mode: off|hint|enforce|report-only
on_empty: fail|keep-source
limit, dry_run
prompt_version: int
```

シークレットは持たない。`api_key` は実行時引数（ja_yomi / tts と同じ）。

### 6.3 CLI 案

```text
srtspeak translate \
  --srt GRAN_TENKU_japan.srt \
  --source-lang ja \
  --to en --to pt-BR --to es \
  --out srt_gen \
  --glossary glossary.json \
  --length-mode hint \
  --limit 20
```

| オプション | 既定 | 意味 |
|------------|------|------|
| `--srt` | 必須 | ソース |
| `--source-lang` | ファイル名推定 | |
| `--to` | 必須（**複数回可** / カンマ区切り可）。1 件以上。正規化後 list |
| `--out` | `srt_gen` | |
| `--glossary` | なし | |
| `--length-mode` | `hint` | |
| `--on-empty` | `fail` | |
| `--batch-size` | `8` | |
| `--model` | `grok-4.5` | |
| `--limit` | 全件 | |
| `--dry-run` | off | |
| `--work-dir` | `work` | |

終了コード: 既存踏襲（0/1/2/130）。

### 6.4 ja_yomi とのコード共有

| 共通化するもの | 分離するもの |
|----------------|--------------|
| Chat 呼び出しヘルパ（URL・Authorization・json_schema・リトライ） | system prompt |
| バッチループ + cancel + progress stage | スキーマ名 / キャッシュファイル名 |
| キャッシュの hash 無効化パターン | length 第二パス |
| Cue replace マージ | ソース≠ターゲット言語マトリクス |

提案: `core/grok_chat.py` に `_call_chat_json` を抽出。  
`ja_yomi.py` / `srt_translate.py` がそれを呼ぶ。  
（リファクタは translate 実装時に小さくやる。巨大リライト禁止。）

### 6.5 doctor

```text
translate: grok-chat (same XAI_API_KEY)
```

一行追加程度。

### 6.6 GUI（優先度低）

v1 は CLI のみでよい。v1.1:

- ソース SRT、ターゲット複数チェック、glossary、out、実行、ログ
- 生成 SRT をビルド画面に渡すパス表示

### 6.7 i18n

CLI ヘルプ・エラーは既存 gettext。**訳文本体はユーザーコンテンツ**であり locales と無関係。

---

## 7. 品質保証

### 7.0 TDD（必須）

本機能は **TDD で開発する**（P9）。

| 規則 | 内容 |
|------|------|
| 順序 | **Red → Green → Refactor** のみ。実装コードを先に書かない |
| 単位 | 1 振る舞い = 1（または少数の）失敗テスト → 最小実装 → 整理 |
| API | 実 Grok 呼び出しはテストに入れない。Chat 層をモック/フェイク注入 |
| ゲート | Phase 完了条件 = 該当テスト緑 + 既存スイート非破壊 |
| 配置 | `tests/` 配下（既存 pytest 構成に合わせる）。新規 `test_srt_translate*.py` 等 |
| 禁止 | 「あとでテスト」・手動確認のみでの Phase 完了宣言 |

推奨サイクル（Phase 1 例）:

1. `format_srt` roundtrip テスト（赤）→ 実装（緑）
2. merge/validate（index ずれ検出）テスト → 実装
3. **言語以外同一** + timing-lock テスト（件数/index/ms 全一致・text のみ差）→ 出力組み立て
4. 書き出し後 re-parse 検証 → 実装
5. cache ヒットで API ゼロコール → cache 層
6. multi-target 直列・部分失敗・progress 非逆行 → `run_translate`
7. CLI パース（`--to` 複数）は subprocess or parser 単位テスト

### 7.1 自動テスト

| テスト | 内容 | TDD 時点 |
|--------|------|----------|
| roundtrip | `parse_srt(format_srt(cues))` が index/時刻/テキスト一致 | Phase 1 最初 |
| merge | モック API 応答で index ずれ・件数ずれを検出して Error | Phase 1 |
| timing lock / 言語以外同一 | 件数・index・全 ms がソース同一。text のみ差可。re-parse 後も構造一致 | Phase 1 |
| cache | 同一入力で API ゼロコール | Phase 1 |
| multi-target | 2+ tgt で個別 SRT/cache、1 tgt 失敗時の continue/`fail_fast` | Phase 1 |
| progress | 必須 cb 呼び出し・percent 非逆行・バッチ境界 | Phase 1 |
| budget | `window_ms` → `max_chars` の境界 | Phase 2 |
| glossary | keep 指定語が訳文に残る（モック応答側を固定する契約テスト） | Phase 2 |

### 7.2 人手受け入れ（正確さ）

1. ソース ja 全件 → en / pt-BR  
2. スポットチェック: 固有名詞、数字、 indents な短キュー、長文キュー  
3. `build --limit 20` で ratio / hard_trim 率を翻訳前後で比較  
4. glossary 更新 → キャッシュ部分無効化を確認  

### 7.3 失敗時運用

| 症状 | 対処 |
|------|------|
| 用語ゆれ | glossary 追加、該当 index の cache キー削除 |
| 特定キューだけ悪い | SRT を手直し（タイムコード触らない）→ build |
| バッチ丸ごと失敗 | batch-size 下げ、再実行（成功分は cache 済み） |
| 過長で音が速い | `--length-mode enforce` or 手動短縮 |

---

## 8. 非スコープ（v1）

- キュー分割・結合・時刻の自動シフト（retime）
- 機械翻訳 API の複数プロバイダ抽象（DeepL 等）— 必要なら v2 で `provider=`  
- 動画焼き込み・字幕プレビュー GUI
- 翻訳と TTS の完全自動閉ループ最適化
- 方言・ルビ付き SRT
- `jobs > 1` の並列 Chat（レート制限。v1 は直列 + 既存 backoff 思想）

---

## 9. リスクと対策

| リスク | 対策 |
|--------|------|
| 意訳過多・字幕として長い | length hint/enforce、トーン指示、レビュー工程 |
| 固有名詞崩壊 | glossary keep、サンプル回帰 |
| index 欠落・重複 | schema strict + 件数/集合検証 + 1 回再試行 |
| コスト | キャッシュ、`--limit`、dry-run バッチ数表示 |
| ja_yomi と二重課金 | 翻訳は漢字のまま。yomi は ja TTS 時のみ |
| プロンプト変更で訳質が変わる | `prompt_version` を cache キーへ |
| 「正確」の主観 | タイムロックは機械保証。意味は glossary + 人レビューをプロセスに含める |

---

## 10. 実装フェーズ

### Phase 0 — 合意（実装前）

- [x] **成果物契約: 言語（text）以外はソースと同一**（P0・§3.3・§4.1）— 合意済
- [ ] 出力ファイル名 A/B（中身の同一性とは別。パス命名のみ）
- [ ] length 既定 `hint` でよいか
- [ ] glossary 形式 JSON でよいか
- [ ] ターゲット初期リスト（en, pt-BR, …）
- [ ] **TDD 方針合意**（P9・§7.0。pytest + Chat モック）

### Phase 1 — 基盤（**TDD**: 各項目はテスト赤→実装緑）

- [ ] `format_srt` / roundtrip テスト → 実装
- [ ] merge/validate（index・件数）テスト → 実装
- [ ] **言語以外同一** + timing-lock テスト（件数/index/ms 全一致・text のみ差）→ 出力組み立て
- [ ] 書き出し後 re-parse 検証テスト → 実装
- [ ] cache ゼロコール テスト → cache 層
- [ ] `grok_chat.py` 抽出（ja_yomi から）※注入点をテスト可能に
- [ ] `srt_translate.py`: **複数 `targets` ループ（v1 必須）**、cache、validate
- [ ] multi-target / 部分失敗 / `--fail-fast` テスト → 実装
- [ ] progress 必須・非逆行・バッチ境界テスト → 実装
- [ ] 全体 progress 分母 = Σ(各 tgt の対象キュー数)（キャッシュ込み）
- [ ] `cancel_token` バッチ境界チェック
- [ ] `srtspeak translate` CLI（`--to` 複数回）+ パーサ/CLI テスト
- [ ] `translate_report.json`（ターゲット別セクション + 全体サマリ）
- [ ] Phase 1 ゲート: 新規+既存 pytest 全緑

### Phase 2 — 正確さ強化（TDD 継続）

- [ ] glossary
- [ ] バッチ文脈オーバーラップ
- [ ] length-mode hint/enforce
- [ ] doctor 行
- [ ] （任意）`--to-all-supported` でカタログ全言語一括

### Phase 3 — 接続・UX

- [ ] README / DESIGN 追記
- [ ] `build-all` 用の生成 map 例・ヘルパ（`translate` が `maps.env` や shell 断片を吐く程度で可）
- [ ] （任意）GUI
- [ ] （任意）`build --translate-from` ラッパ

### Phase 4 — 品質ループ（v2）

- [ ] build report の extreme_speed を translate にフィードバック
- [ ] 話速テーブルを実データで校正

---

## 11. 既存 DESIGN.md への位置づけ

| 文書 | 役割 |
|------|------|
| DESIGN.md | TTS・フィット・タイムラインの正本（実装済み） |
| **本ドキュメント** | SRT 多言語生成の正本（設計）。実装後に DESIGN.md へ「前段: translate」節を短くリンク |

DESIGN.md §1.2 非スコープの「文章リライト」は次のように更新予定:

- 維持: 意味改変リライト一般は TTS 本体の仕事ではない  
- 追加: **別サブコマンド `translate` がタイミングロック翻訳を担当**（本設計）

---

## 12. まとめ（アダプト方針・一行ずつ）

1. **翻訳は TTS に混ぜない。** `srtspeak translate` を前段に置き、成果 SRT を人が見られるようにする。  
2. **言語以外同一。** 件数・index・時刻・並びはソース固定。変わるのは text のみ。  
3. **時刻・index はコードがロック。** モデルは text のみ。  
4. **実装パターンは ja_yomi の複製進化。** Chat + JSON schema + batch + cache + **progress 必須** + cancel。  
5. **正確さ = 構造同一 + glossary + 長さ予算 + 検証ゲート + 人レビュー。** モデル一発任せにしない。  
6. **stdlib のみ・`XAI_API_KEY` 共通・BuildConfig 非侵襲。** 既存 build を壊さない。  
7. **生成 SRT → 既存 `build-all --map` が正規の接続。**
8. **progress なしの本番経路は作らない。** `run_translate(..., progress_cb=...)` 必須引数。
9. **複数ターゲットは v1 必須。** `--to` 繰り返し → 直列実行・言語別 cache/SRT・合算 progress・部分失敗継続。
10. **TDD 必須。** Red→Green→Refactor。Chat はモック。Phase 完了 = テスト緑。

---

## 改訂

| 版 | 内容 |
|----|------|
| 0.1 | 初版。要件・正確さ定義・モジュール配置・フェーズ |
| 0.2 | Progress 必須を原則・§5.1-A 契約・Phase1・まとめに明記 |
| 0.3 | 複数ターゲットを v1 必須化（§3.1-A・P5b・Phase1・CLI） |
| 0.4 | TDD 必須（P9・§7.0・Phase0/1 ゲート・§7.1 時点列・まとめ） |
| 0.5 | **言語以外同一（P0）** を成果物契約に固定。§3.3 書き出し・§4.1 検証・Phase0 合意済 |

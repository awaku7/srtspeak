# srtspeak

Multilingual SRT TTS. Forces each cue into its exact start/end window (xAI Grok TTS + ffmpeg).

Also includes **SRT→SRT translation** (`translate`) and **glossary suggestion** (`glossary-suggest`) via Grok Chat (same `XAI_API_KEY`).

Authoritative design: `DESIGN.md` (implementation-aligned).  
Translate design: `docs/SRT_TRANSLATE_DESIGN.md`.

**Languages:** [English](README.md) | [日本語](README.ja.md)

## Requirements

| Item | Detail |
|------|--------|
| OS | Windows / macOS / Linux (developed and verified on Windows) |
| Python | 3.11+ |
| ffmpeg / ffprobe | Prefer on `PATH`; optional fallback via `imageio-ffmpeg` |
| API key | `XAI_API_KEY` only for real TTS / translate / glossary / ja_yomi (not needed for dry-run without Chat) |

Package version: **0.1.4** (`pyproject.toml`).

## Install

From [PyPI](https://pypi.org/project/srtspeak/):

```bat
python -m pip install srtspeak
```

Optional ffmpeg fallback via pip:

```bat
python -m pip install "srtspeak[ffmpeg]"
```

Core install already includes **PySide6** (GUI) and **keyring** (OS credential store).

After install, the `srtspeak` command is available:

```bat
srtspeak --help
srtspeak doctor
```

### From source (development)

Clone the repository, then editable install from the repo root:

```bat
git clone https://github.com/awaku7/srtspeak.git
cd srtspeak
python -m pip install -e ".[ffmpeg,dev]"
```

Dev extras (`[dev]`): pytest / ruff / Babel / keyring.

Without install (repo checkout only):

```bat
set PYTHONPATH=src
python -m srtspeak --help
```

There is **no** `[ja]` extra. Japanese kanji→hiragana preprocess (`ja_yomi`) uses the **Grok Chat API** with the same `XAI_API_KEY` (default on for `lang=ja`).

## Launch

After `pip install` (PyPI or editable), use the `srtspeak` entry point:

```bat
srtspeak gui
srtspeak doctor
srtspeak --help
srtspeak dry-run --srt GRAN_TENKU_japan.srt --lang ja
```

```bat
python -m srtspeak gui
```

## When ffmpeg is missing

Resolution order (`core/ffmpeg_resolve.py`):

1. `ffmpeg` / `ffprobe` on `PATH` (`shutil.which`)
2. Optional dependency `imageio-ffmpeg` bundled binary (`get_ffmpeg_exe()`)
3. Otherwise `FFmpegNotFoundError`

| Situation | Behavior |
|-----------|----------|
| `srtspeak doctor` | Prints `ffmpeg: MISSING (...)`. Exit code **0** (diagnostics only) |
| `dry-run` (build) | ffmpeg **not required** (parse + char count + cost estimate only) |
| Real `build` / `build-all` | Fails at fit stage. CLI exit code **2** |
| `translate` / `glossary-suggest` | ffmpeg **not required** |
| `imageio-ffmpeg` only | Works, but `ffprobe` may be `(none)`. Full PATH ffmpeg is **recommended** |

### Install examples (Windows)

WinGet (recommended):

```bat
winget install Gyan.FFmpeg
```

Then in a **new** terminal:

```bat
ffmpeg -version
ffprobe -version
srtspeak doctor
```

If you prefer not to change PATH:

```bat
python -m pip install "srtspeak[ffmpeg]"
srtspeak doctor
```

`doctor` shows `source: path` for system ffmpeg, or `source: imageio_ffmpeg` for the pip bundle.

## xAI (Grok TTS / Chat) signup and API key

TTS is **xAI Grok only** (`POST https://api.x.ai/v1/tts`).  
Japanese yomi, SRT translate, and glossary-suggest use Grok Chat (`/v1/chat/completions`). Create the key in the console.

### 1. Account

1. Open [https://console.x.ai/](https://console.x.ai/)
2. Sign up / log in (xAI account)
3. Accept terms and set up billing / credits as guided  
   - TTS is usage-based. dry-run estimate uses **$15 / 1M characters** (implementation unit price)
   - ja_yomi / translate / glossary Chat calls are additional usage when enabled

### 2. Create an API key

1. Open **API Keys** (or equivalent) in the console
2. Create a new key
3. Copy the value (often starts with `xai-`)  
   - It may **not be shown again** — put it in an env var immediately
4. Do not put the key in chat, Git, `report.json`, or screenshots

Official docs:

- [Text to Speech](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech)
- [Voice](https://docs.x.ai/developers/model-capabilities/audio/voice)
- API: `https://api.x.ai/v1/tts` / voices: `https://api.x.ai/v1/tts/voices`

### 3. How this tool reads the key

| Rule | Detail |
|------|--------|
| Variable | **`XAI_API_KEY` only** |
| CLI flag | No `--api-key` (avoids shell history) |
| Persistence | No `.env`; never written to report/logs/`gui_settings.json` |
| Resolve order | env → session → **OS keyring** → legacy Windows DPAPI (migrate) → CLI `getpass` / GUI mask |
| dry-run | Key optional (Chat APIs skipped if missing) |
| Real TTS / translate / glossary | resolve chain; missing → exit code 2 |
| GUI | **Save on this PC** / **Clear saved** via keyring (core dependency) |

Windows cmd (current window only):

```bat
set "XAI_API_KEY=xai-..."
srtspeak doctor
```

PowerShell:

```powershell
$env:XAI_API_KEY = "xai-..."
srtspeak doctor
```

Persist for new terminals (cmd):

```bat
setx XAI_API_KEY "xai-..."
```

`doctor` shows presence only (source label):

```text
XAI_API_KEY: set (env)
```

```text
XAI_API_KEY: set (keyring)
```

```text
XAI_API_KEY: set (dpapi)
```

or:

```text
XAI_API_KEY: missing
```

Invalid key / insufficient balance surfaces as `TTS error: ...` / `translate error: ...` during run (exit code 1).

## Commands

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

| Command | Purpose |
|---------|---------|
| `doctor` | Check `XAI_API_KEY`, ffmpeg/ffprobe, ja_yomi, translate, glossary-suggest, PySide6 |
| `languages` | Language codes sendable to the API |
| `voices` | Grok voices (API if key present, else builtin; male + female) |
| `dry-run` | Parse + char count + TTS cost estimate (no ffmpeg) |
| `build` | Generate one language (TTS) |
| `build-all` | Generate multiple languages in sequence |
| `translate` | SRT→SRT multi-target translation (Grok Chat; timing-locked) |
| `glossary-suggest` | Propose glossary JSON from source SRT via Grok Chat |
| `gui` | PySide6 GUI (Build + Translate tabs) |

Global options:

```text
--locale en|ja     UI locale (default: SRTSPEAK_LOCALE → LC_ALL/LANG → system → en)
--verbose / --quiet
```

Place `--quiet` / `--verbose` **before** the subcommand:

```bat
srtspeak --locale ja doctor
srtspeak --verbose build --srt sample.srt --lang ja --dry-run
```

## Input / output layout

### TTS build

`--out` is the **output root**. Artifacts always go under `{out}/{lang}/`.

```text
out/{lang}/
  cues/                  per-cue audio (normalized)
  fitted/                duration-fitted audio
  GRAN_TENKU_{lang}.wav  final track (fixed name)
  GRAN_TENKU_{lang}.mp3  if --also-mp3
  report.json
work/{lang}/
  raw/
  cache/
  ja_yomi_cache.json     when ja + ja_yomi
```

- Default root: `out` → e.g. `out/ja/`
- `--out out/en` with `--lang en` → `out/en/` (no double nesting)
- `--out artifacts` with `--lang pt` → `artifacts/pt/`
- `build-all` writes `summary.json` at the out root

### Translate

`--out` default: `srt_gen`. Work cache under `work/translate/by_out/` (keyed by output SRT file name).

```text
srt_gen/
  translate_report.json
  {target}/                         # BCP-47 token (e.g. en, pt-BR)
    {source_stem}_{target}.srt      # naming=stem (default)
    GRAN_TENKU_{target}.srt         # naming=gran_tenku
work/translate/by_out/
  {target}__{out_srt_name}.json   # e.g. en__GRAN_TENKU_en.srt.json
```

## Usage

### Environment check

```bat
srtspeak doctor
```

Before a real build you typically want:

- `XAI_API_KEY: set (env)`
- `ffmpeg:` path with `source: path` (or `imageio_ffmpeg`)
- `ja_yomi: grok-chat (Grok Chat API)`
- `translate: grok-chat (same XAI_API_KEY)`
- `glossary-suggest: grok-chat (same XAI_API_KEY)`

### Cost estimate (no ffmpeg)

```bat
srtspeak dry-run --srt GRAN_TENKU_japan.srt --lang ja
```

### Single-language build

```bat
set "XAI_API_KEY=xai-..."

srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --voice-id leo
srtspeak build --srt GRAN_TENKU_English.srt --lang en --voice-id leo --out out
srtspeak build --srt GRAN_TENKU_Portugus.srt --lang pt --voice-id leo
```

Main options:

| Option | Meaning | Default |
|--------|---------|---------|
| `--srt` | Input SRT | required |
| `--lang` | Internal key `ja` / `en` / `pt` … | may be guessed from filename |
| `--language-code` | BCP-47 sent to API | lang default (`pt`→`pt-BR`) |
| `--out` | Output root (lang appended) | `out` |
| `--work-dir` | Work root | `work` |
| `--voice-id` | Voice ID (or `lang=id` for build-all) | `leo` |
| `--short-mode` | `pad` / `stretch` | `pad` |
| `--max-speed` | Cap on atempo product; over → hard_trim | none |
| `--tail-pad-ms` | Silence after last cue end (no base_wav) | `0` |
| `--base-wav` | Mix narration onto this WAV (keeps base rate/ch) | none |
| `--ja-yomi` / `--no-ja-yomi` | JA kanji→hiragana via Grok Chat | **on** |
| `--strip-emoticons` / `--no-strip-emoticons` | Strip kaomoji for TTS only; emoji kept; SRT unchanged | **on** |
| `--no-cache` | Ignore existing TTS/ja_yomi caches (still write after success) | off |
| `--limit N` | First N cues only | all |
| `--dry-run` | Estimate only | off |
| `--also-mp3` | Also write mp3 of final track | off |
| `--jobs` | Parallelism (MVP: **1** only) | `1` |

Smoke a few cues:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --limit 3 --voice-id leo
```

Portuguese as pt-PT:

```bat
srtspeak build --srt GRAN_TENKU_Portugus.srt --lang pt --language-code pt-PT --voice-id leo
```

Mix onto an existing bed:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --base-wav bed.wav --voice-id leo
```

Disable Japanese yomi:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --no-ja-yomi --voice-id leo
```

Force fresh TTS (ignore caches):

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --no-cache --voice-id leo
```

### Multi-language batch

```bat
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=GRAN_TENKU_English.srt ^
  --map pt=GRAN_TENKU_Portugus.srt ^
  --voice-id leo ^
  --out out
```

Per-language voices:

```bat
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=GRAN_TENKU_English.srt ^
  --voice-id ja=leo --voice-id en=orion
```

### Translate (SRT→SRT)

Timing-locked multi-target translation. Cue count / index / start-end ms stay identical; only text changes. Provider: Grok Chat structured JSON (`grok-4.5` default). Separate from the TTS pipeline.

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

| Option | Meaning | Default |
|--------|---------|---------|
| `--srt` | Source SRT | required |
| `--source-lang` | Source language | filename guess / `ja` |
| `--to` | Target BCP-47 (repeat or comma-separated) | required (≥1) |
| `--out` | Output root | `srt_gen` |
| `--work-dir` | Work root | `work` |
| `--glossary` | Glossary JSON path | none |
| `--length-mode` | `off` / `hint` / `enforce` / `report-only` | `hint` |
| `--on-empty` | `fail` / `keep-source` | `fail` |
| `--batch-size` | Cues per Chat batch | `8` |
| `--model` | Grok Chat model id | `grok-4.5` |
| `--limit N` | First N cues only | all |
| `--dry-run` | Estimate only (no Chat) | off |
| `--fail-fast` | Stop on first target error | off |
| `--no-cache` | Ignore existing translate caches (still write) | off |
| `--naming` | `stem` → `{source_stem}_{lang}.srt` / `gran_tenku` → `GRAN_TENKU_{lang}.srt` | `stem` |

Dry-run:

```bat
srtspeak translate --srt GRAN_TENKU_japan.srt --to en,pt-BR --dry-run
```

Then TTS the generated SRT:

```bat
srtspeak build-all ^
  --map ja=GRAN_TENKU_japan.srt ^
  --map en=srt_gen/en/GRAN_TENKU_japan_en.srt ^
  --voice-id leo --out out
```

(With `--naming gran_tenku`, paths become `srt_gen/en/GRAN_TENKU_en.srt`.)

### Glossary suggest

```bat
srtspeak glossary-suggest ^
  --srt GRAN_TENKU_japan.srt ^
  --source-lang ja ^
  --to en --to pt-BR ^
  --out glossary.json
```

| Option | Meaning | Default |
|--------|---------|---------|
| `--srt` | Source SRT | required |
| `--source-lang` | Source language | filename guess / `ja` |
| `--to` | Target BCP-47 (repeat or comma-separated) | required |
| `--out` | Output glossary JSON | `glossary.json` |
| `--merge` | Merge into existing glossary (existing wins on conflict) | none |
| `--force` | Overwrite `--out` without merge | off |
| `--min-count` | Min local term frequency for candidates | `2` |
| `--model` | Grok Chat model id | `grok-4.5` |
| `--limit N` | First N cues only | all |

If `--out` already exists and `--force` is not set, new suggestions are merged with existing terms (existing preferred).

### GUI

```bat
srtspeak gui
```

- Tabs: **Build** (TTS) and **Translate**
- Build: SRT, language (BCP-47 + Detect), voice, **absolute** output folder + directory picker, base WAV, max cues, dry-run, ja_yomi, strip kaomoji, no-cache
- Translate: source SRT, source lang, multi-target checkboxes, **absolute** output folder + directory picker, glossary path + Suggest, length mode, batch size, naming (`stem` / `gran_tenku`), fail-fast, no-cache, dry-run
- Shared: API key (masked) + status/placeholder showing load source (env / keyring / DPAPI / session) + **Save on this PC** / **Clear saved**
- Key input: whitespace/newlines stripped (`normalize_api_key`); language detect uses the same resolve chain as build/translate
- Completion: non-modal result dialog; main window stays open
- Browse / path confirm: filename → source language guess (`guess_lang_from_filename`)
- Progress: bottom status + bar (0–1000); worker → thread-safe queue + ~80ms drain; Cancel via `CancellationToken`
- Optional diag: `SRTSPEAK_GUI_PROGRESS_LOG=1` → `work/gui_progress.log` only
- Non-secret settings in **`gui_settings.json`** (never the key plaintext)
- UTF-8 defaults: CLI/GUI set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` when unset

## Processing notes

### TTS build

- Pipeline: parse → limit → **ja_yomi** (ja) → TTS/cache → normalize → fit → timeline → report
- TTS: xAI Grok unary REST only (`speed` always 1.0)
- ja_yomi: Grok Chat structured JSON, batch 5, cache under `work/{lang}/`
- strip_emoticons: kaomoji stripped for **TTS speak text only**; emoji kept; stored SRT cues unchanged; default **on**
- Fit: ffmpeg CLI only (`atempo` 0.5–2.0 multi-stage; short cues default to pad)
- Timeline: silence canvas or base_wav; place in half-open `[start, end)`; **PCM add-mix** (clip ±32767)
- Track length: last cue end + `tail_pad_ms`, or base_wav length when `--base-wav` is set
- Audio (no base): mono s16le 24 kHz WAV; with base: base native rate/channels preserved
- Cost estimate (dry-run): $15 / 1M chars (TTS text; Chat yomi not included in that figure)
- Voices: builtin catalog includes male and female; default `leo`
- `--no-cache`: skip reading TTS/ja_yomi caches; still write after success

### Translate

- Pipeline: parse → limit → per target: cache → Chat batches → structure lock → write SRT → `translate_report.json`
- Structure lock: cue count / index / start_ms / end_ms identical to source
- Glossary optional (`terms` / `do_not_translate` / `tone`)
- length_mode `hint` (default) injects budget into prompt; `enforce` may run a 2nd compress pass
- Model default `grok-4.5`; batch_size default 8

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (`doctor` is 0 even if ffmpeg is missing) |
| 1 | Runtime errors (e.g. TTS / translate / glossary) |
| 2 | Config/args/invalid SRT/**ffmpeg missing**/key missing |
| 130 | Cancelled (Ctrl+C) |

## Development

```bat
git clone https://github.com/awaku7/srtspeak.git
cd srtspeak
python -m pip install -e ".[dev,ffmpeg]"
set PYTHONPATH=src
python -m pytest -q
python -m ruff check src tests
python -m ruff format src tests
```

i18n (when messages change):

```bat
python scripts/update_i18n.py
```

## Sample inputs (expected alongside the repo)

| File | lang | Notes |
|------|------|-------|
| `GRAN_TENKU_japan.srt` | `ja` | ja_yomi default on |
| `GRAN_TENKU_English.srt` | `en` | |
| `GRAN_TENKU_Portugus.srt` | `pt` | API default `pt-BR` if unspecified |

Timecodes are assumed aligned across the three files (design-time: 293 cues, `00:00:07,600`–`00:12:44,000`).

## License

Apache License 2.0 (see `LICENSE`)

## Author

Hirofumi Ukawa <hirofumi@ukawa.biz>

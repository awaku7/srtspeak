# srtspeak

Multilingual SRT TTS. Forces each cue into its exact start/end window (xAI Grok TTS + ffmpeg).

Authoritative design: `DESIGN.md`.

**Languages:** [English](README.md) | [日本語](README.ja.md)

## Requirements

| Item | Detail |
|------|--------|
| OS | Windows / macOS / Linux (developed and verified on Windows) |
| Python | 3.11+ |
| ffmpeg / ffprobe | Prefer on `PATH`; optional fallback via `imageio-ffmpeg` |
| API key | `XAI_API_KEY` only for real TTS (not needed for dry-run) |

## Install

From the repository root:

```bat
python -m pip install -e .
```

With GUI:

```bat
python -m pip install -e ".[gui]"
```

Dev extras (pytest / ruff / Babel):

```bat
python -m pip install -e ".[dev]"
```

Optional ffmpeg fallback via pip:

```bat
python -m pip install -e ".[ffmpeg]"
```

After editable install, the `srtspeak` command is available. Without install:

```bat
set PYTHONPATH=src
python -m srtspeak --help
```

Japanese yomi preprocess (kanji→hiragana via kanjiconv):

```bat
python -m pip install -e ".[ja]"
```

Combined extras example:

```bat
python -m pip install -e ".[gui,ja]"
```

## Launch (Windows)

Double-click or run from the repo root:

| Script | Action |
|--------|--------|
| `run_gui.bat` | Start GUI |
| `run_doctor.bat` | Environment check |
| `run_srtspeak.bat …` | CLI passthrough (same args as `srtspeak`) |

Examples:

```bat
run_gui.bat
run_doctor.bat
run_srtspeak.bat --help
run_srtspeak.bat dry-run --srt GRAN_TENKU_japan.srt --lang ja
```

Equivalent without bat:

```bat
srtspeak gui
python -m srtspeak gui
```

Notes:

- Scripts `cd` to the repo root automatically.
- If `srtspeak` is not on `PATH`, they set `PYTHONPATH=src` and use `python -m srtspeak`.
- If `XAI_API_KEY` is unset and `UAGENT_GROK_API_KEY` is set, it is copied for the session only (not persisted).

## When ffmpeg is missing

Resolution order (`core/ffmpeg_resolve.py`):

1. `ffmpeg` / `ffprobe` on `PATH` (`shutil.which`)
2. Optional dependency `imageio-ffmpeg` bundled binary (`get_ffmpeg_exe()`)
3. Otherwise `FFmpegNotFoundError`

| Situation | Behavior |
|-----------|----------|
| `srtspeak doctor` | Prints `ffmpeg: MISSING (...)`. Exit code **0** (diagnostics only) |
| `dry-run` | ffmpeg **not required** (parse + char count + cost estimate only) |
| Real `build` / `build-all` | Fails at fit stage. CLI: `error: ffmpeg not found on PATH and imageio-ffmpeg is unavailable`, exit code **2** |
| `imageio-ffmpeg` only | Works, but `ffprobe` may be `(none)`. Full PATH ffmpeg build is **recommended** |

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
python -m pip install -e ".[ffmpeg]"
srtspeak doctor
```

`doctor` shows `source: path` for system ffmpeg, or `source: imageio_ffmpeg` for the pip bundle.

## xAI (Grok TTS) signup and API key

TTS is **xAI Grok only** (`POST https://api.x.ai/v1/tts`). Create the key in the console.

### 1. Account

1. Open [https://console.x.ai/](https://console.x.ai/)
2. Sign up / log in (xAI account)
3. Accept terms and set up billing / credits as guided  
   - TTS is usage-based. dry-run estimate uses **$15 / 1M characters** (implementation unit price)

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
| Persistence | No `.env` read/write; never written to report/logs |
| dry-run | Key optional |
| Real TTS | env → (CLI) `getpass` prompt → else exit code 2 |
| GUI | env first; masked session input if missing |

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

`doctor` shows presence only:

```text
XAI_API_KEY: set (env)
```

or:

```text
XAI_API_KEY: missing
```

Invalid key / insufficient balance surfaces as `TTS error: ...` during build (exit code 1).

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
```

| Command | Purpose |
|---------|---------|
| `doctor` | Check `XAI_API_KEY`, ffmpeg/ffprobe, PySide6 |
| `languages` | Language codes sendable to the API |
| `voices` | Grok voices (API if key present, else builtin) |
| `dry-run` | Parse + char count + cost estimate (no key, no ffmpeg) |
| `build` | Generate one language |
| `build-all` | Generate multiple languages in sequence |
| `gui` | PySide6 GUI |

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

`--out` is the **output root**. Artifacts always go under `{out}/{lang}/`.

```text
out/{lang}/
  cues/                  per-cue audio
  fitted/                duration-fitted audio
  GRAN_TENKU_{lang}.wav  final track (fixed name)
  report.json
work/{lang}/
  raw/
  cache/
```

- Default root: `out` → e.g. `out/ja/`
- `--out out/en` with `--lang en` → `out/en/` (no double nesting)
- `--out artifacts` with `--lang pt` → `artifacts/pt/`
- `build-all` writes `summary.json` at the out root

## Usage

### Environment check

```bat
srtspeak doctor
```

Before a real build you typically want:

- `XAI_API_KEY: set (env)`
- `ffmpeg:` path with `source: path` (or `imageio_ffmpeg`)

### Cost estimate (no key, no ffmpeg)

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
| `--voice-id` | Voice ID | `leo` |
| `--short-mode` | `pad` / `stretch` | `pad` |
| `--limit N` | First N cues only | all |
| `--dry-run` | Estimate only | off |
| `--also-mp3` | Also write mp3 | off |
| `--jobs` | Parallelism (MVP: 1 only) | `1` |

Smoke a few cues:

```bat
srtspeak build --srt GRAN_TENKU_japan.srt --lang ja --limit 3 --voice-id leo
```

Portuguese as pt-PT:

```bat
srtspeak build --srt GRAN_TENKU_Portugus.srt --lang pt --language-code pt-PT --voice-id leo
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

### GUI

```bat
python -m pip install -e ".[gui]"
srtspeak gui
```

- Out field is the **root** (default `out`); lang is appended at run time
- API key: env preferred; masked session input if unset

## Processing notes

- TTS: xAI Grok unary REST only (`speed` always 1.0)
- Fit: ffmpeg CLI only (`atempo` 0.5–2.0 multi-stage; short cues default to pad)
- Timeline: silence canvas + PCM placement; half-open window `[start, end)`
- Track length: aligned to last cue end (±50 ms)
- Audio: mono s16le 24 kHz WAV
- Cost estimate (dry-run): $15 / 1M chars

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (`doctor` is 0 even if ffmpeg is missing) |
| 1 | Runtime errors (e.g. TTS) |
| 2 | Config/args/invalid SRT/**ffmpeg missing**/key missing |
| 130 | Cancelled (Ctrl+C) |

## Development

```bat
python -m pip install -e ".[dev]"
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
| `GRAN_TENKU_japan.srt` | `ja` | |
| `GRAN_TENKU_English.srt` | `en` | |
| `GRAN_TENKU_Portugus.srt` | `pt` | API default `pt-BR` if unspecified |

Timecodes are assumed aligned across the three files (design-time: 293 cues, `00:00:07,600`–`00:12:44,000`).

## License

Apache License 2.0 (see `LICENSE`)

## Author

Hirofumi Ukawa <hirofumi@ukawa.biz>

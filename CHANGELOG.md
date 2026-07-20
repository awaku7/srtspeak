# Changelog

All notable changes to this project are documented in this file.

## [0.1.3] - 2026-03-22

### Added
- Secure API key persistence via OS credential store (`keyring`): Windows Credential Locker, macOS Keychain, Linux Secret Service/KWallet.
- GUI **Save on this PC** / **Clear saved** for the API key (no plaintext in `gui_settings.json`).
- Legacy Windows DPAPI file store kept as read/migrate fallback under `%LOCALAPPDATA%\srtspeak\`.
- Filename language guess: native labels (`日本語`, `ไทย`, `中文`, …) and whole-token codes (`_en`, `-ja`); no false `en` match inside `tenku`.
- GUI applies filename language guess on Browse / path commit (Build language + Translate source language).

### Changed
- `glossary.json` thinned to proper-noun-centric terms (faster translate prompts).
- GUI translate progress uses a thread-safe queue so Chat heartbeats update the status bar live.
- Diagnostic GUI progress log default OFF; when enabled writes `work/gui_progress.log` only.
- Optional deps: `keyring>=25` on `[gui]` and `[dev]`.
- Translate cache redesigned: `work/translate/by_out/{tgt}__{out_name}.json` (index→`{src,tgt}`), seed from existing output SRT; old per-cue sha256 keys unused.

### Fixed
- Translate tab status stuck on “Running…” while Grok Chat was in flight.
- Live translate cache hits were always 0 (hash key mismatch); fixed by out-filename cache + SRT seed.

## [0.1.2] - 2026-07-19

### Added
- `srtspeak translate`: multi-target SRT→SRT translation via Grok Chat (timing-locked; `TranslateConfig`).
- `srtspeak glossary-suggest`: glossary JSON proposal from source SRT.
- GUI **Translate** tab (targets, glossary + Suggest, length mode, naming, fail-fast, no-cache).
- Build/translate `--no-cache` (skip read; still write after success).
- Build `--strip-emoticons` / `--no-strip-emoticons` (default on): kaomoji stripped for TTS speak text only; emoji kept; SRT unchanged (`core/text_sanitize.py`).

### Changed
- `BuildConfig.strip_emoticons` default **True** (was documented as MVP no-op).
- GUI settings file: `gui_settings.json` (not `gui.json`).
- `doctor` reports translate and glossary-suggest backends.

### Documentation
- Align `DESIGN.md`, `README.md`, and `README.ja.md` with the current implementation (translate, glossary-suggest, strip_emoticons, no_cache, GUI tabs, package layout).
- `docs/SRT_TRANSLATE_DESIGN.md`: mark implemented CLI/GUI/config fields (naming, no_cache, fail_fast, heartbeat).

## [0.1.1] - prior

### Changed
- Version bump 0.1.0 → 0.1.1.

## [0.1.0] - prior

### Added
- Initial Apache-2.0 release prep and PyPI metadata.
- Multilingual SRT TTS pipeline (parse → ja_yomi → TTS → fit → timeline).
- CLI and GUI entry points.

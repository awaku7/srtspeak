# Changelog

All notable changes to this project are documented in this file.

## [0.1.2] - 2026-07-19

### Documentation
- Align `DESIGN.md`, `README.md`, and `README.ja.md` with the current implementation (ja_yomi via Grok Chat API, timeline module, pipeline order, extras, exit codes).
- Add `docs/SRT_TRANSLATE_DESIGN.md` v0.5: SRT-to-SRT translation design (language-only delta / P0 structure lock, multi-target, progress, TDD Phase 1). Translation stays outside the TTS build pipeline.

## [0.1.1] - prior

### Changed
- Version bump 0.1.0 → 0.1.1.

## [0.1.0] - prior

### Added
- Initial Apache-2.0 release prep and PyPI metadata.
- Multilingual SRT TTS pipeline (parse → ja_yomi → TTS → fit → timeline).
- CLI and GUI entry points.

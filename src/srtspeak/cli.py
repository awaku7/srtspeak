"""srtspeak CLI (argparse)."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path
from typing import Sequence

from srtspeak.core.cancel import BuildCancelled, CancellationToken
from srtspeak.core.ffmpeg_resolve import (
    FFmpegNotFoundError,
    ffmpeg_version,
    resolve_ffmpeg,
)
from srtspeak.core.languages import (
    guess_lang_from_filename,
    list_language_options,
    resolve_language_code,
)
from srtspeak.core.models import BuildConfig
from srtspeak.core.pipeline import BuildService
from srtspeak.core.progress import ProgressEvent
from srtspeak.core.report import write_json
from srtspeak.core.secrets import api_key_status, resolve_api_key
from srtspeak.core.tts_xai import TtsError, fetch_voices, merge_voice_catalog
from srtspeak.core.util import resolve_out_dir, DEFAULT_OUT_ROOT, DEFAULT_WORK_DIR, DEFAULT_SRT_GEN_DIR
from srtspeak.core.voices import (
    builtin_voice_ids,
    list_builtin_voices,
    resolve_voice_id,
    validate_voice_id,
)
from srtspeak.i18n import _, setup_i18n
from srtspeak.progress_i18n import localize_message, localize_stage


class _CliState:
    quiet: bool = False
    verbose: bool = False
    last_line_len: int = 0


_STATE = _CliState()
_CANCEL = CancellationToken()


def _progress_printer(ev: ProgressEvent) -> None:
    if _STATE.quiet:
        return
    stage = localize_stage(ev.stage)
    msg = localize_message(ev.message) if ev.message else ""
    line = (
        f"[{ev.percent:5.1f}%] {stage:8s} "
        f"{ev.current}/{ev.total}"
        + (f"  {ev.lang}" if ev.lang else "")
        + (f"  cue={ev.cue_index}" if ev.cue_index is not None else "")
        + (f"  {msg}" if msg else "")
    )
    if _STATE.verbose:
        print(line, flush=True)
    else:
        pad = max(0, _STATE.last_line_len - len(line))
        sys.stdout.write("\r" + line + (" " * pad))
        sys.stdout.flush()
        _STATE.last_line_len = len(line)


def _finish_progress_line() -> None:
    if not _STATE.quiet and not _STATE.verbose and _STATE.last_line_len:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _STATE.last_line_len = 0


def _install_sigint() -> None:
    def _handler(signum: int, frame: object) -> None:  # noqa: ARG001
        _CANCEL.cancel()

    try:
        signal.signal(signal.SIGINT, _handler)
    except Exception:
        pass


def _parse_voice_map(values: list[str] | None) -> dict[str, str] | str | None:
    """Return single voice str, or lang->voice map, or None."""
    if not values:
        return None
    if len(values) == 1 and "=" not in values[0]:
        return values[0]
    out: dict[str, str] = {}
    single: str | None = None
    for v in values:
        if "=" in v:
            lang, vid = v.split("=", 1)
            out[lang.strip().lower()] = vid.strip()
        else:
            single = v.strip()
    if out and single:
        out["*"] = single
    if out:
        return out
    return single


def _voice_for_lang(
    spec: dict[str, str] | str | None,
    lang: str,
) -> str:
    if spec is None:
        return resolve_voice_id(None)
    if isinstance(spec, str):
        return resolve_voice_id(spec)
    if lang in spec:
        return resolve_voice_id(spec[lang])
    if "*" in spec:
        return resolve_voice_id(spec["*"])
    return resolve_voice_id(None)


def _parse_map_args(values: list[str] | None) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not values:
        return result
    for item in values:
        if "=" not in item:
            raise SystemExit(
                _("invalid --map (expected lang=path): {item}").format(item=item)
            )
        lang, path = item.split("=", 1)
        result[lang.strip().lower()] = Path(path.strip())
    return result


def _parse_lang_code_map(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not values:
        return result
    for item in values:
        if "=" not in item:
            raise SystemExit(
                _(
                    "invalid --language-code (expected lang=code): {item}"
                ).format(item=item)
            )
        lang, code = item.split("=", 1)
        result[lang.strip().lower()] = code.strip()
    return result


def cmd_languages(_args: argparse.Namespace) -> int:
    for opt in list_language_options():
        aliases = ", ".join(opt.aliases) if opt.aliases else "-"
        label = _(opt.label)
        print(f"{opt.code:8s}  {label:28s}  {_('aliases={aliases}').format(aliases=aliases)}")
    return 0


def cmd_voices(args: argparse.Namespace) -> int:
    live = None
    key = resolve_api_key(prompt=False)
    if key:
        try:
            live = fetch_voices(api_key=key)
        except TtsError as exc:
            print(
                _("warning: voices API failed ({exc}); using builtin").format(
                    exc=exc
                ),
                file=sys.stderr,
            )
    voices = merge_voice_catalog(list_builtin_voices(), live)
    filt = (args.voice_filter or "").strip().lower()
    for v in voices:
        if filt and filt not in {t.lower() for t in v.tags} and filt not in v.voice_id:
            if filt not in v.description.lower() and filt not in v.name.lower():
                continue
        tags = ",".join(v.tags) if v.tags else ""
        print(f"{v.voice_id:12s}  {v.name:16s}  {_(v.description)}  [{tags}]")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    print(_("XAI_API_KEY: {status}").format(status=api_key_status()))
    try:
        tools = resolve_ffmpeg()
        ver = ffmpeg_version(tools.ffmpeg)
        print(_("ffmpeg: {path}").format(path=tools.ffmpeg))
        print(_("  source: {source}").format(source=tools.source))
        print(_("  version: {version}").format(version=ver))
        none_label = _("(none)")
        print(_("ffprobe: {path}").format(path=tools.ffprobe or none_label))
    except FFmpegNotFoundError as exc:
        print(_("ffmpeg: MISSING ({exc})").format(exc=exc))
    try:
        from srtspeak.core.ja_yomi import apply_ja_yomi  # noqa: F401

        print(
            _("ja_yomi: grok-chat (Grok Chat API)").format()
        )
    except Exception as exc:
        print(_("ja_yomi: error ({exc})").format(exc=exc))
    try:
        from srtspeak.core.srt_translate import run_translate  # noqa: F401

        print(_("translate: grok-chat (same XAI_API_KEY)"))
    except Exception as exc:
        print(_("translate: error ({exc})").format(exc=exc))
    try:
        from srtspeak.core.translate_glossary import suggest_glossary  # noqa: F401

        print(_("glossary-suggest: grok-chat (same XAI_API_KEY)"))
    except Exception as exc:
        print(_("glossary-suggest: error ({exc})").format(exc=exc))
    try:
        import PySide6  # type: ignore  # noqa: F401

        print(_("PySide6: available"))
    except Exception:
        print(_("PySide6: not installed (core dependency)"))
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    try:
        from srtspeak.gui.app import main as gui_main
    except Exception as exc:
        print(
            _("GUI unavailable: {exc}\nInstall with: pip install srtspeak").format(
                exc=exc
            ),
            file=sys.stderr,
        )
        return 2
    return int(gui_main() or 0)


def _build_one(
    *,
    srt_path: Path,
    lang: str,
    language_code: str,
    out_dir: Path,
    voice_id: str,
    args: argparse.Namespace,
    api_key: str | None,
) -> dict:
    cfg = BuildConfig(
        srt_path=srt_path,
        lang=lang,
        language_code=language_code,
        out_dir=out_dir,
        voice_id=voice_id,
        short_mode=args.short_mode,
        limit=args.limit,
        dry_run=bool(args.dry_run),
        keep_raw=not bool(getattr(args, "no_keep_raw", False)),
        also_mp3=bool(args.also_mp3),
        jobs=1,
        tail_pad_ms=int(args.tail_pad_ms),
        work_dir=Path(args.work_dir) if args.work_dir else None,
        max_speed=args.max_speed,
        ja_yomi=bool(getattr(args, "ja_yomi", True)),
        strip_emoticons=bool(getattr(args, "strip_emoticons", True)),
        base_wav=Path(args.base_wav) if getattr(args, "base_wav", None) else None,
        no_cache=bool(getattr(args, "no_cache", False)),
    )
    cfg.validate()
    # validate voice against builtin when dry-run or no live list
    try:
        validate_voice_id(voice_id, known_ids=builtin_voice_ids())
    except ValueError:
        if cfg.dry_run:
            raise SystemExit(
                _("unknown voice_id: {voice_id}").format(voice_id=voice_id)
            ) from None
        # full build: still attempt; API may accept custom
        print(
            _(
                "warning: voice_id {voice_id!r} not in builtin; will try API"
            ).format(voice_id=voice_id),
            file=sys.stderr,
        )

    svc = BuildService(
        cfg,
        api_key=api_key,
        progress_cb=None if _STATE.quiet else _progress_printer,
        cancel_token=_CANCEL,
    )
    try:
        report = svc.run()
    except BuildCancelled:
        _finish_progress_line()
        print(_("cancelled"), file=sys.stderr)
        raise SystemExit(130) from None
    except TtsError as exc:
        _finish_progress_line()
        print(_("TTS error: {exc}").format(exc=exc), file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, FileNotFoundError, FFmpegNotFoundError) as exc:
        _finish_progress_line()
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        code = 2 if isinstance(exc, (ValueError, FFmpegNotFoundError)) else 1
        raise SystemExit(code) from None
    _finish_progress_line()
    return report


def cmd_build(args: argparse.Namespace) -> int:
    srt = Path(args.srt)
    if not srt.is_file():
        print(_("SRT not found: {path}").format(path=srt), file=sys.stderr)
        return 2

    lang = args.lang or guess_lang_from_filename(srt) or "ja"
    try:
        language_code = resolve_language_code(lang=lang, explicit=args.language_code)
    except ValueError as exc:
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        return 2

    voice_spec = _parse_voice_map(args.voice_id)
    voice_id = _voice_for_lang(voice_spec, lang)

    out_dir = resolve_out_dir(args.out, lang)

    api_key = None
    if not args.dry_run:
        api_key = resolve_api_key(prompt=True)
        if not api_key:
            print(_("XAI_API_KEY is not set"), file=sys.stderr)
            return 2

    report = _build_one(
        srt_path=srt,
        lang=lang,
        language_code=language_code,
        out_dir=out_dir,
        voice_id=voice_id,
        args=args,
        api_key=api_key,
    )
    print(
        _(
            "status={status} lang={lang} cues={processed}/{total} track={track}"
        ).format(
            status=report.get("status"),
            lang=report.get("lang"),
            processed=report.get("processed_count"),
            total=report.get("cue_count"),
            track=report.get("track_path", report.get("track")),
        )
    )
    if report.get("status") == "cancelled":
        return 130
    return 0


def cmd_build_all(args: argparse.Namespace) -> int:
    mapping = _parse_map_args(args.map)
    if not mapping:
        print(
            _("build-all requires at least one --map lang=path"),
            file=sys.stderr,
        )
        return 2
    code_map = _parse_lang_code_map(args.language_code)
    voice_spec = _parse_voice_map(args.voice_id)

    api_key = None
    if not args.dry_run:
        api_key = resolve_api_key(prompt=True)
        if not api_key:
            print(_("XAI_API_KEY is not set"), file=sys.stderr)
            return 2

    out_root = Path(args.out) if args.out else DEFAULT_OUT_ROOT
    # summary.json stays at out root; per-lang artifacts under {root}/{lang}/
    reports: dict[str, str] = {}
    langs: list[str] = []
    overall_status = "ok"

    for lang, srt in mapping.items():
        if not srt.is_file():
            print(
                _("SRT not found for {lang}: {path}").format(lang=lang, path=srt),
                file=sys.stderr,
            )
            return 2
        explicit = code_map.get(lang)
        try:
            language_code = resolve_language_code(lang=lang, explicit=explicit)
        except ValueError as exc:
            print(_("error: {exc}").format(exc=exc), file=sys.stderr)
            return 2
        voice_id = _voice_for_lang(voice_spec, lang)
        out_dir = resolve_out_dir(out_root, lang)
        report = _build_one(
            srt_path=srt,
            lang=lang,
            language_code=language_code,
            out_dir=out_dir,
            voice_id=voice_id,
            args=args,
            api_key=api_key,
        )
        langs.append(lang)
        reports[lang] = str(out_dir / "report.json")
        if report.get("status") == "cancelled":
            overall_status = "cancelled"
            break
        if report.get("status") not in ("ok", "dry_run"):
            overall_status = str(report.get("status"))

    summary = {
        "status": overall_status,
        "languages": langs,
        "reports": reports,
    }
    write_json(out_root / "summary.json", summary)
    print(
        _("summary status={status} languages={languages}").format(
            status=overall_status,
            languages=langs,
        )
    )
    if overall_status == "cancelled":
        return 130
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    args.dry_run = True
    return cmd_build(args)



def _parse_to_list(values: list[str] | None) -> list[str]:
    """Normalize --to repeats and comma-separated values into a list."""
    if not values:
        return []
    out: list[str] = []
    for v in values:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def cmd_translate(args: argparse.Namespace) -> int:
    from srtspeak.core.languages import normalize_language_code
    from srtspeak.core.models import TranslateConfig
    from srtspeak.core.srt_translate import TranslateError, run_translate

    srt = Path(args.srt)
    if not srt.is_file():
        print(_("SRT not found: {path}").format(path=srt), file=sys.stderr)
        return 2

    source = args.source_lang or guess_lang_from_filename(srt) or "ja"
    try:
        source = normalize_language_code(source)
    except ValueError as exc:
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        return 2

    targets = _parse_to_list(args.to)
    if not targets:
        print(_("translate requires at least one --to"), file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else DEFAULT_SRT_GEN_DIR
    work_dir = Path(args.work_dir) if args.work_dir else DEFAULT_WORK_DIR
    glossary = Path(args.glossary) if getattr(args, "glossary", None) else None

    try:
        cfg = TranslateConfig(
            srt_path=srt,
            source_lang=source,
            targets=targets,
            out_dir=out_dir,
            work_dir=work_dir,
            model=str(getattr(args, "model", None) or "grok-4.5"),
            batch_size=int(getattr(args, "batch_size", 8) or 8),
            glossary_path=glossary,
            length_mode=str(getattr(args, "length_mode", "hint") or "hint"),
            on_empty=str(getattr(args, "on_empty", "fail") or "fail"),
            limit=(args.limit if args.limit not in (None, 0) else None),
            dry_run=bool(args.dry_run),
            fail_fast=bool(getattr(args, "fail_fast", False)),
            naming=str(getattr(args, "naming", "stem") or "stem"),
            no_cache=bool(getattr(args, "no_cache", False)),
        )
        cfg.validate()
    except ValueError as exc:
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        return 2

    api_key = ""
    if not cfg.dry_run:
        resolved = resolve_api_key(prompt=True)
        if not resolved:
            print(_("XAI_API_KEY is not set"), file=sys.stderr)
            return 2
        api_key = resolved

    try:
        report = run_translate(
            cfg,
            api_key=api_key,
            progress_cb=_progress_printer,
            cancel_token=_CANCEL,
        )
    except BuildCancelled:
        _finish_progress_line()
        print(_("cancelled"), file=sys.stderr)
        return 130
    except TranslateError as exc:
        _finish_progress_line()
        print(_("translate error: {exc}").format(exc=exc), file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, OSError) as exc:
        _finish_progress_line()
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        return 2
    _finish_progress_line()

    summary = report.get("summary") or {}
    print(
        _(
            "translate status={status} ok={ok} failed={failed} skipped={skipped} warnings={warnings} report={report}"
        ).format(
            status=report.get("status"),
            ok=summary.get("ok"),
            failed=summary.get("failed"),
            skipped=summary.get("skipped"),
            warnings=summary.get("warnings", 0),
            report=str(report.get("report_path") or (out_dir / "translate_report.json")),
        )
    )
    targets = report.get("targets") or {}
    if isinstance(targets, dict):
        for tgt, info in targets.items():
            if not isinstance(info, dict):
                continue
            for w in info.get("warnings") or []:
                print(
                    _("warning [{tgt}]: {msg}").format(tgt=tgt, msg=w),
                    file=sys.stderr,
                )
            if not info.get("ok"):
                for e in info.get("errors") or []:
                    print(
                        _("error [{tgt}]: {msg}").format(tgt=tgt, msg=e),
                        file=sys.stderr,
                    )
    failed = int(summary.get("failed") or 0)
    ok = int(summary.get("ok") or 0)
    if failed and ok:
        return 1
    if failed and not ok:
        return 1
    return 0



def cmd_glossary_suggest(args: argparse.Namespace) -> int:
    from srtspeak.core.languages import normalize_language_code
    from srtspeak.core.srt_parser import apply_limit, parse_srt, read_srt_text
    from srtspeak.core.translate_glossary import (
        GlossaryError,
        load_glossary,
        merge_glossary,
        save_glossary,
        suggest_glossary,
    )

    srt = Path(args.srt)
    if not srt.is_file():
        print(_("SRT not found: {path}").format(path=srt), file=sys.stderr)
        return 2

    source = args.source_lang or guess_lang_from_filename(srt) or "ja"
    try:
        source = normalize_language_code(source)
    except ValueError as exc:
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        return 2

    raw_targets = _parse_to_list(args.to)
    if not raw_targets:
        print(_("glossary-suggest requires at least one --to"), file=sys.stderr)
        return 2
    targets: list[str] = []
    seen_t: set[str] = set()
    for t in raw_targets:
        try:
            code = normalize_language_code(t)
        except ValueError as exc:
            print(_("error: {exc}").format(exc=exc), file=sys.stderr)
            return 2
        if code in seen_t:
            print(
                _("error: duplicate target language: {code}").format(code=code),
                file=sys.stderr,
            )
            return 2
        seen_t.add(code)
        targets.append(code)

    out_path = Path(args.out) if args.out else Path("glossary.json")
    api_key = resolve_api_key(prompt=True)
    if not api_key:
        print(_("XAI_API_KEY is not set"), file=sys.stderr)
        return 2

    limit = args.limit if getattr(args, "limit", None) not in (None, 0) else None

    try:
        cues = parse_srt(read_srt_text(srt)[0])
        cues = apply_limit(cues, limit)
        suggested = suggest_glossary(
            cues,
            source_lang=source,
            targets=targets,
            api_key=api_key,
            model=str(getattr(args, "model", None) or "grok-4.5"),
            min_count=max(1, int(getattr(args, "min_count", 2) or 2)),
            progress_cb=_progress_printer,
        )
        if getattr(args, "merge", None):
            base = load_glossary(Path(args.merge))
            suggested = merge_glossary(base, suggested, prefer="base")
        elif out_path.is_file() and not bool(getattr(args, "force", False)):
            # default: merge into existing out if present
            base = load_glossary(out_path)
            if base:
                suggested = merge_glossary(base, suggested, prefer="base")
        save_glossary(out_path, suggested)
    except BuildCancelled:
        _finish_progress_line()
        print(_("cancelled"), file=sys.stderr)
        return 130
    except GlossaryError as exc:
        _finish_progress_line()
        print(_("glossary error: {exc}").format(exc=exc), file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        _finish_progress_line()
        print(_("error: {exc}").format(exc=exc), file=sys.stderr)
        return 2
    _finish_progress_line()
    n = len((suggested.get("terms") or []))
    print(
        _("glossary written: {path} terms={n}").format(path=out_path, n=n)
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="srtspeak",
        description=_(
            "SRT multilingual TTS with forced cue-window timing (xAI Grok)"
        ),
    )
    p.add_argument("--verbose", action="store_true", help=_("verbose progress"))
    p.add_argument("--quiet", action="store_true", help=_("suppress progress"))
    p.add_argument(
        "--locale",
        default=None,
        help=_(
            "UI locale (en/ja). Default: SRTSPEAK_LOCALE / system / en"
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_build_flags(sp: argparse.ArgumentParser, *, multi: bool) -> None:
        if multi:
            sp.add_argument(
                "--map",
                action="append",
                help=_("lang=path (repeatable)"),
            )
            sp.add_argument(
                "--language-code",
                action="append",
                default=None,
                help=_("lang=BCP47 (repeatable)"),
            )
        else:
            sp.add_argument("--srt", required=True, help=_("input SRT path"))
            sp.add_argument(
                "--lang",
                default=None,
                help=_("internal lang key ja/en/pt"),
            )
            sp.add_argument(
                "--language-code",
                default=None,
                help=_("BCP-47 language code override"),
            )
        sp.add_argument(
            "--out",
            default=None,
            help=_(
                "output root directory (lang id always appended; default: out)"
            ),
        )
        sp.add_argument(
            "--work-dir",
            default=None,
            help=_("work directory root (default: out/work)"),
        )
        sp.add_argument(
            "--voice-id",
            action="append",
            default=None,
            help=_("voice id or lang=voice (repeatable)"),
        )
        sp.add_argument(
            "--short-mode",
            choices=("pad", "stretch"),
            default="pad",
            help=_("short cue fit mode (default: pad)"),
        )
        sp.add_argument(
            "--limit",
            type=int,
            default=None,
            help=_("process only the first N cues"),
        )
        sp.add_argument(
            "--also-mp3",
            action="store_true",
            help=_("also write MP3 alongside WAV"),
        )
        sp.add_argument(
            "--tail-pad-ms",
            type=int,
            default=0,
            help=_("extra silence after last cue (ms)"),
        )
        sp.add_argument(
            "--base-wav",
            type=str,
            default=None,
            help=_("base WAV file to mix narration onto (default: silence)"),
        )
        sp.add_argument(
            "--max-speed",
            type=float,
            default=None,
            help=_("maximum atempo speed factor"),
        )
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help=_("estimate only, no TTS"),
        )
        sp.add_argument(
            "--jobs",
            type=int,
            default=1,
            help=_("MVP must be 1"),
        )
        sp.add_argument(
            "--ja-yomi",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=_(
                "JA only: convert kanji to hiragana via Grok Chat API before TTS "
                "(default: on)"
            ),
        )
        sp.add_argument(
            "--strip-emoticons",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=_(
                "Strip kaomoji for TTS only; emoji kept; SRT unchanged (default: on)"
            ),
        )
        sp.add_argument(
            "--no-cache",
            action="store_true",
            help=_("ignore existing TTS/ja_yomi caches; still write fresh"),
        )

    sp_build = sub.add_parser("build", help=_("build one language"))
    add_build_flags(sp_build, multi=False)
    sp_build.set_defaults(func=cmd_build)

    sp_all = sub.add_parser("build-all", help=_("build multiple languages"))
    add_build_flags(sp_all, multi=True)
    sp_all.set_defaults(func=cmd_build_all)

    sp_dry = sub.add_parser("dry-run", help=_("parse + cost estimate only"))
    add_build_flags(sp_dry, multi=False)
    sp_dry.set_defaults(func=cmd_dry_run, dry_run=True)

    sp_lang = sub.add_parser("languages", help=_("list language options"))
    sp_lang.set_defaults(func=cmd_languages)

    sp_voices = sub.add_parser("voices", help=_("list Grok voices"))
    sp_voices.add_argument(
        "--voice-filter",
        default=None,
        help=_("filter voices by id/name/tag"),
    )
    sp_voices.set_defaults(func=cmd_voices)

    sp_doc = sub.add_parser("doctor", help=_("environment check"))
    sp_doc.set_defaults(func=cmd_doctor)

    sp_gui = sub.add_parser("gui", help=_("launch GUI"))
    sp_gui.set_defaults(func=cmd_gui)

    sp_tr = sub.add_parser("translate", help=_("translate SRT to other languages"))
    sp_tr.add_argument("--srt", required=True, help=_("source SRT path"))
    sp_tr.add_argument(
        "--source-lang",
        default=None,
        help=_("source language (default: filename guess / ja)"),
    )
    sp_tr.add_argument(
        "--to",
        action="append",
        required=True,
        help=_("target language BCP-47 (repeatable or comma-separated)"),
    )
    sp_tr.add_argument(
        "--out",
        default=str(DEFAULT_SRT_GEN_DIR),
        help=_("output root directory (default: out/srt_gen)"),
    )
    sp_tr.add_argument(
        "--work-dir",
        default=str(DEFAULT_WORK_DIR),
        help=_("work directory root (default: out/work)"),
    )
    sp_tr.add_argument(
        "--glossary",
        default=None,
        help=_("glossary JSON path"),
    )
    sp_tr.add_argument(
        "--length-mode",
        choices=("off", "hint", "enforce", "report-only"),
        default="hint",
        help=_("length control mode (default: hint)"),
    )
    sp_tr.add_argument(
        "--on-empty",
        choices=("fail", "keep-source"),
        default="fail",
        help=_("empty translation policy (default: fail)"),
    )
    sp_tr.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help=_("cues per Chat batch (default: 8)"),
    )
    sp_tr.add_argument(
        "--model",
        default="grok-4.5",
        help=_("Grok Chat model id"),
    )
    sp_tr.add_argument(
        "--limit",
        type=int,
        default=None,
        help=_("process only the first N cues"),
    )
    sp_tr.add_argument(
        "--dry-run",
        action="store_true",
        help=_("estimate only, no Chat API"),
    )
    sp_tr.add_argument(
        "--fail-fast",
        action="store_true",
        help=_("stop on first target failure"),
    )
    sp_tr.add_argument(
        "--no-cache",
        action="store_true",
        help=_("ignore existing translate caches; still write fresh"),
    )
    sp_tr.add_argument(
        "--naming",
        choices=("stem", "gran_tenku"),
        default="stem",
        help=_("output SRT naming (default: stem)"),
    )
    sp_tr.set_defaults(func=cmd_translate)

    sp_gs = sub.add_parser(
        "glossary-suggest",
        help=_("suggest glossary JSON from SRT via Grok Chat"),
    )
    sp_gs.add_argument("--srt", required=True, help=_("source SRT path"))
    sp_gs.add_argument(
        "--source-lang",
        default=None,
        help=_("source language (default: filename guess / ja)"),
    )
    sp_gs.add_argument(
        "--to",
        action="append",
        required=True,
        help=_("target language BCP-47 (repeatable or comma-separated)"),
    )
    sp_gs.add_argument(
        "--out",
        default="glossary.json",
        help=_("output glossary JSON path (default: glossary.json)"),
    )
    sp_gs.add_argument(
        "--merge",
        default=None,
        help=_("existing glossary to merge (base wins on conflict)"),
    )
    sp_gs.add_argument(
        "--force",
        action="store_true",
        help=_("overwrite --out without merging existing file"),
    )
    sp_gs.add_argument(
        "--min-count",
        type=int,
        default=2,
        help=_("min term frequency for local candidates (default: 2)"),
    )
    sp_gs.add_argument(
        "--model",
        default="grok-4.5",
        help=_("Grok Chat model id"),
    )
    sp_gs.add_argument(
        "--limit",
        type=int,
        default=None,
        help=_("use only the first N cues"),
    )
    sp_gs.set_defaults(func=cmd_glossary_suggest)

    return p


def _peek_locale(argv: list[str] | None) -> str | None:
    """Extract --locale before full parse so help strings can be translated."""
    if not argv:
        return None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--locale" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--locale="):
            return a.split("=", 1)[1]
        i += 1
    return None


def _enable_utf8_stdio_defaults() -> None:
    """Prefer UTF-8 on Windows consoles unless the user already set env vars."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    _enable_utf8_stdio_defaults()
    argv_list = list(argv) if argv is not None else None
    setup_i18n(_peek_locale(argv_list))
    parser = build_parser()
    args = parser.parse_args(argv_list)
    _STATE.quiet = bool(getattr(args, "quiet", False))
    _STATE.verbose = bool(getattr(args, "verbose", False))
    # Re-apply in case parse defaults differ (should match peek).
    setup_i18n(getattr(args, "locale", None))
    if getattr(args, "jobs", 1) not in (1, None) and int(args.jobs) != 1:
        print(_("error: jobs must be 1 in MVP"), file=sys.stderr)
        return 2
    _install_sigint()
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        return int(func(args))
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        _CANCEL.cancel()
        _finish_progress_line()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

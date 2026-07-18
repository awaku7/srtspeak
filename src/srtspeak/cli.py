"""srtspeak CLI (argparse)."""

from __future__ import annotations

import argparse
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
from srtspeak.core.util import resolve_out_dir
from srtspeak.core.voices import (
    builtin_voice_ids,
    list_builtin_voices,
    resolve_voice_id,
    validate_voice_id,
)
from srtspeak.i18n import _, setup_i18n


class _CliState:
    quiet: bool = False
    verbose: bool = False
    last_line_len: int = 0


_STATE = _CliState()
_CANCEL = CancellationToken()


def _progress_printer(ev: ProgressEvent) -> None:
    if _STATE.quiet:
        return
    line = (
        f"[{ev.percent:5.1f}%] {ev.stage:8s} "
        f"{ev.current}/{ev.total}"
        + (f"  {ev.lang}" if ev.lang else "")
        + (f"  cue={ev.cue_index}" if ev.cue_index is not None else "")
        + (f"  {ev.message}" if ev.message and _STATE.verbose else "")
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
        print(f"{opt.code:8s}  {label:28s}  aliases={aliases}")
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
    print(f"XAI_API_KEY: {api_key_status()}")
    try:
        tools = resolve_ffmpeg()
        ver = ffmpeg_version(tools.ffmpeg)
        print(f"ffmpeg: {tools.ffmpeg}")
        print(_("  source: {source}").format(source=tools.source))
        print(_("  version: {version}").format(version=ver))
        none_label = _("(none)")
        print(f"ffprobe: {tools.ffprobe or none_label}")
    except FFmpegNotFoundError as exc:
        print(_("ffmpeg: MISSING ({exc})").format(exc=exc))
    try:
        from srtspeak.core.ja_yomi import kanjiconv_available

        if kanjiconv_available():
            status = _("available")
        else:
            status = _('not available (pip install -e ".[ja]")')
        print(f"kanjiconv: {status}")
    except Exception as exc:
        print(_("kanjiconv: error ({exc})").format(exc=exc))
    try:
        import PySide6  # type: ignore  # noqa: F401

        print(_("PySide6: available"))
    except Exception:
        print(_("PySide6: not installed (optional extra [gui])"))
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    try:
        from srtspeak.gui.app import main as gui_main
    except Exception as exc:
        print(
            _("GUI unavailable: {exc}\nInstall with: pip install -e .[gui]").format(
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

    out_root = Path(args.out) if args.out else Path("out")
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
            help=_("work directory root"),
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
                "JA only: convert kanji to hiragana via kanjiconv before TTS "
                "(default: on)"
            ),
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


def main(argv: Sequence[str] | None = None) -> int:
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

"""Language catalog and resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from srtspeak.i18n import _


@dataclass(frozen=True)
class LanguageOption:
    code: str
    label: str
    aliases: tuple[str, ...] = ()


SUPPORTED_LANGUAGE_OPTIONS: list[LanguageOption] = [
    LanguageOption("ja", "Japanese", ("jp", "japanese")),
    LanguageOption("en", "English", ("eng", "english")),
    LanguageOption("pt-BR", "Portuguese (Brazil)", ("pt_br", "ptbr", "brazilian")),
    LanguageOption("pt-PT", "Portuguese (Portugal)", ("pt_pt", "ptpt", "european_pt")),
    LanguageOption("es", "Spanish", ("spa", "spanish")),
    LanguageOption("fr", "French", ("fra", "french")),
    LanguageOption("de", "German", ("deu", "german")),
    LanguageOption("it", "Italian", ("ita", "italian")),
    LanguageOption("ko", "Korean", ("kor", "korean")),
    LanguageOption("zh", "Chinese", ("zho", "chinese", "zh-CN", "zh-TW")),
    LanguageOption("hi", "Hindi", ("hin", "hindi")),
    LanguageOption("ar", "Arabic", ("ara", "arabic")),
    LanguageOption("ru", "Russian", ("rus", "russian")),
    LanguageOption("tr", "Turkish", ("tur", "turkish")),
    LanguageOption("nl", "Dutch", ("nld", "dutch")),
    LanguageOption("pl", "Polish", ("pol", "polish")),
    LanguageOption("sv", "Swedish", ("swe", "swedish")),
    LanguageOption("id", "Indonesian", ("ind", "indonesian")),
    LanguageOption("vi", "Vietnamese", ("vie", "vietnamese")),
    LanguageOption("th", "Thai", ("tha", "thai")),
]

DEFAULT_LANGUAGE_CODE: dict[str, str] = {
    "ja": "ja",
    "en": "en",
    "pt": "pt-BR",
}

FILENAME_LANG_HINTS: dict[str, str] = {
    "japan": "ja",
    "japanese": "ja",
    "english": "en",
    "portugus": "pt",
    "portuguese": "pt",
    "pt": "pt",
    "ja": "ja",
    "en": "en",
}

_INTERNAL_LANGS = frozenset(DEFAULT_LANGUAGE_CODE.keys())


def _alias_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for opt in SUPPORTED_LANGUAGE_OPTIONS:
        m[opt.code.lower()] = opt.code
        for a in opt.aliases:
            m[a.lower()] = opt.code
    return m


_ALIASES = _alias_map()


def list_language_options() -> list[LanguageOption]:
    return list(SUPPORTED_LANGUAGE_OPTIONS)


def guess_lang_from_filename(path: str | Path) -> str | None:
    stem = Path(path).stem.lower()
    # longest hint first to prefer specific tokens
    for hint, lang in sorted(FILENAME_LANG_HINTS.items(), key=lambda x: -len(x[0])):
        if hint in stem:
            return lang
    return None


def normalize_language_code(value: str) -> str:
    key = value.strip().lower().replace("_", "-")
    # try exact / alias
    if key in _ALIASES:
        return _ALIASES[key]
    # ptbr style without hyphen
    compact = key.replace("-", "")
    for alias, code in _ALIASES.items():
        if alias.replace("-", "").replace("_", "") == compact:
            return code
    raise ValueError(_("unknown language code: {value}").format(value=value))


def resolve_language_code(*, lang: str, explicit: str | None) -> str:
    if explicit:
        return normalize_language_code(explicit)
    lang_key = lang.strip().lower()
    if lang_key in DEFAULT_LANGUAGE_CODE:
        return DEFAULT_LANGUAGE_CODE[lang_key]
    # allow using BCP-47 directly as lang
    try:
        return normalize_language_code(lang_key)
    except ValueError as exc:
        raise ValueError(_("unknown lang key: {lang}").format(lang=lang)) from exc


def internal_lang_from_code(language_code: str) -> str:
    """Map API BCP-47 code to internal out-dir / pipeline lang key.

    Examples: ``ja``→``ja``, ``pt-BR``/``pt-PT``→``pt``, ``zh``→``zh``.
    """
    code = normalize_language_code(language_code)
    primary = code.split("-", 1)[0].lower()
    if primary == "pt":
        return "pt"
    if primary in DEFAULT_LANGUAGE_CODE:
        return primary
    return primary

"""Language catalog and resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from srtspeak.i18n import _, N_


@dataclass(frozen=True)
class LanguageOption:
    code: str
    label: str
    aliases: tuple[str, ...] = ()


SUPPORTED_LANGUAGE_OPTIONS: list[LanguageOption] = [
    LanguageOption("ja", N_("Japanese"), ("jp", "japanese")),
    LanguageOption("en", N_("English"), ("eng", "english")),
    LanguageOption("pt-BR", N_("Portuguese (Brazil)"), ("pt_br", "ptbr", "brazilian")),
    LanguageOption("pt-PT", N_("Portuguese (Portugal)"), ("pt_pt", "ptpt", "european_pt")),
    LanguageOption("es", N_("Spanish"), ("spa", "spanish")),
    LanguageOption("fr", N_("French"), ("fra", "french")),
    LanguageOption("de", N_("German"), ("deu", "german")),
    LanguageOption("it", N_("Italian"), ("ita", "italian")),
    LanguageOption("ko", N_("Korean"), ("kor", "korean")),
    LanguageOption("zh", N_("Chinese"), ("zho", "chinese", "zh-CN", "zh-TW")),
    LanguageOption("hi", N_("Hindi"), ("hin", "hindi")),
    LanguageOption("ar", N_("Arabic"), ("ara", "arabic")),
    LanguageOption("ru", N_("Russian"), ("rus", "russian")),
    LanguageOption("tr", N_("Turkish"), ("tur", "turkish")),
    LanguageOption("nl", N_("Dutch"), ("nld", "dutch")),
    LanguageOption("pl", N_("Polish"), ("pol", "polish")),
    LanguageOption("sv", N_("Swedish"), ("swe", "swedish")),
    LanguageOption("id", N_("Indonesian"), ("ind", "indonesian")),
    LanguageOption("vi", N_("Vietnamese"), ("vie", "vietnamese")),
    LanguageOption("th", N_("Thai"), ("tha", "thai")),
]

DEFAULT_LANGUAGE_CODE: dict[str, str] = {
    "ja": "ja",
    "en": "en",
    "pt": "pt-BR",
}

FILENAME_LANG_HINTS: dict[str, str] = {
    # Latin / English labels (matched as whole tokens only)
    "japan": "ja",
    "japanese": "ja",
    "english": "en",
    "portugus": "pt",
    "portuguese": "pt",
    "brazil": "pt",
    "brasil": "pt",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "korean": "ko",
    "chinese": "zh",
    "hindi": "hi",
    "arabic": "ar",
    "russian": "ru",
    "turkish": "tr",
    "dutch": "nl",
    "polish": "pl",
    "swedish": "sv",
    "indonesian": "id",
    "vietnamese": "vi",
    "thai": "th",
    "pt-br": "pt",
    "pt_br": "pt",
    "pt-pt": "pt",
    "pt_pt": "pt",
    "ptbr": "pt",
    "ptpt": "pt",
    "pt": "pt",
    "ja": "ja",
    "jp": "ja",
    "en": "en",
    "es": "es",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "ko": "ko",
    "zh": "zh",
    "hi": "hi",
    "ar": "ar",
    "ru": "ru",
    "tr": "tr",
    "nl": "nl",
    "pl": "pl",
    "sv": "sv",
    "id": "id",
    "vi": "vi",
    "th": "th",
}

# Native / local script labels in original case (substring OK; not ASCII short codes)
FILENAME_NATIVE_HINTS: tuple[tuple[str, str], ...] = (
    ("日本語", "ja"),
    ("日本", "ja"),
    ("英語", "en"),
    ("タイ語", "th"),
    ("ไทย", "th"),
    ("中文", "zh"),
    ("中国語", "zh"),
    ("한국어", "ko"),
    ("韓国語", "ko"),
    ("조선어", "ko"),
    ("Tiếng Việt", "vi"),
    ("ベトナム語", "vi"),
    ("Bahasa", "id"),
    ("インドネシア語", "id"),
    ("Português", "pt"),
    ("ポルトガル語", "pt"),
    ("Español", "es"),
    ("スペイン語", "es"),
    ("Français", "fr"),
    ("フランス語", "fr"),
    ("Deutsch", "de"),
    ("ドイツ語", "de"),
    ("Русский", "ru"),
    ("ロシア語", "ru"),
)

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


def _filename_tokens(stem: str) -> list[str]:
    """Split stem into tokens; keep ASCII alnum runs and non-ASCII runs separately."""
    import re

    # underscores/hyphens/spaces split; also split camel-ish boundaries lightly
    parts = re.split(r"[_\-\s.]+", stem)
    tokens: list[str] = []
    for p in parts:
        if not p:
            continue
        tokens.append(p)
        # also yield lower ASCII-only form for matching
        tokens.append(p.lower())
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def guess_lang_from_filename(path: str | Path) -> str | None:
    """Guess internal/BCP-ish lang key from filename.

    Uses whole-token match for short Latin codes (avoids ``en`` in ``tenku``).
    Native-script labels may match as substring on the original stem.
    """
    raw_stem = Path(path).stem
    stem_lower = raw_stem.lower()

    # 1) Native / local labels on original stem (longest first)
    for label, lang in sorted(FILENAME_NATIVE_HINTS, key=lambda x: -len(x[0])):
        if label in raw_stem or label.lower() in stem_lower:
            return lang

    tokens = _filename_tokens(raw_stem)
    token_set = {t.lower() for t in tokens}

    # 2) Whole-token Latin hints (longest first)
    for hint, lang in sorted(FILENAME_LANG_HINTS.items(), key=lambda x: -len(x[0])):
        h = hint.lower()
        if h in token_set:
            return lang

    # 3) Multi-part tokens like en-US already covered; try primary of BCP token
    for t in token_set:
        if t in _ALIASES:
            code = _ALIASES[t]
            # map to internal-ish short key used by callers
            primary = code.split("-", 1)[0].lower()
            if primary == "pt":
                return "pt"
            return primary

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

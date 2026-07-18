"""Extract/update/compile gettext catalogs with Babel.

Usage (from repo root)::

    python scripts/update_i18n.py extract
    python scripts/update_i18n.py update
    python scripts/update_i18n.py compile
    python scripts/update_i18n.py all

English msgids are the source language. Catalogs live under
``src/srtspeak/locales/``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src" / "srtspeak" / "locales"
DOMAIN = "srtspeak"
BABEL_CFG = ROOT / "babel.cfg"
POT = LOCALES / f"{DOMAIN}.pot"
LANGS = ("en", "ja")

AUTHOR = "Hirofumi Ukawa"
AUTHOR_EMAIL = "hirofumi@ukawa.biz"
COPYRIGHT_HOLDER = "Hirofumi Ukawa"
LICENSE_LINE = (
    "This file is distributed under the Apache License, Version 2.0."
)


def _run(args: list[str]) -> None:
    print("+", " ".join(args))
    subprocess.check_call(args, cwd=str(ROOT))


def _header_comment(*, is_pot: bool, lang: str | None) -> str:
    if is_pot:
        title = "# Translations template for srtspeak."
    else:
        lang_name = {
            "en": "English",
            "ja": "Japanese",
        }.get(lang or "", "Translations")
        title = f"# {lang_name} translations for srtspeak."
    return "\n".join(
        [
            title,
            f"# Copyright (C) 2026 {COPYRIGHT_HOLDER}",
            f"# {LICENSE_LINE}",
            f"# {AUTHOR} <{AUTHOR_EMAIL}>, 2026.",
            "#",
            "",
        ]
    )


def _fix_catalog_headers(
    path: Path, *, lang: str | None = None, is_pot: bool = False
) -> None:
    """Normalize pot/po headers to Apache-2.0 + project author."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].strip() == ""):
        if lines[i].startswith("#,") or lines[i].startswith("msgid"):
            break
        i += 1
    body = "".join(lines[i:])

    team = (
        f"srtspeak <{AUTHOR_EMAIL}>"
        if is_pot or not lang
        else f"{lang} <{AUTHOR_EMAIL}>"
    )
    replacements = {
        "Report-Msgid-Bugs-To: EMAIL@ADDRESS\\n": (
            f"Report-Msgid-Bugs-To: {AUTHOR_EMAIL}\\n"
        ),
        "Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n": (
            f"Last-Translator: {AUTHOR} <{AUTHOR_EMAIL}>\\n"
        ),
        "Language-Team: LANGUAGE <LL@li.org>\\n": f"Language-Team: {team}\\n",
        "Language-Team: en <LL@li.org>\\n": f"Language-Team: en <{AUTHOR_EMAIL}>\\n",
        "Language-Team: ja <LL@li.org>\\n": f"Language-Team: ja <{AUTHOR_EMAIL}>\\n",
        "Copyright (C) 2026 ORGANIZATION": f"Copyright (C) 2026 {COPYRIGHT_HOLDER}",
        "FIRST AUTHOR <EMAIL@ADDRESS>": f"{AUTHOR} <{AUTHOR_EMAIL}>",
        "This file is distributed under the same license as the srtspeak project.": (
            LICENSE_LINE
        ),
    }
    for old, new in replacements.items():
        body = body.replace(old, new)

    body = re.sub(
        r"Report-Msgid-Bugs-To: .*\\n",
        f"Report-Msgid-Bugs-To: {AUTHOR_EMAIL}\\n",
        body,
        count=1,
    )
    body = re.sub(
        r"Last-Translator: .*\\n",
        f"Last-Translator: {AUTHOR} <{AUTHOR_EMAIL}>\\n",
        body,
        count=1,
    )
    body = re.sub(
        r"Language-Team: .*\\n",
        f"Language-Team: {team}\\n",
        body,
        count=1,
    )

    path.write_text(
        _header_comment(is_pot=is_pot, lang=lang) + body,
        encoding="utf-8",
        newline="\n",
    )


def cmd_extract() -> None:
    LOCALES.mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "babel.messages.frontend",
            "extract",
            "-F",
            str(BABEL_CFG),
            "-o",
            str(POT),
            "-k",
            "_",
            "-k",
            "N_",
            "-k",
            "ngettext:1,2",
            "--project",
            "srtspeak",
            "--version",
            "0.1.0",
            "--copyright-holder",
            COPYRIGHT_HOLDER,
            "--msgid-bugs-address",
            AUTHOR_EMAIL,
            "src/srtspeak",
        ]
    )
    _fix_catalog_headers(POT, is_pot=True)


def cmd_update() -> None:
    if not POT.is_file():
        cmd_extract()
    else:
        _fix_catalog_headers(POT, is_pot=True)
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / f"{DOMAIN}.po"
        po.parent.mkdir(parents=True, exist_ok=True)
        if not po.is_file():
            _run(
                [
                    sys.executable,
                    "-m",
                    "babel.messages.frontend",
                    "init",
                    "-i",
                    str(POT),
                    "-d",
                    str(LOCALES),
                    "-l",
                    lang,
                    "-D",
                    DOMAIN,
                ]
            )
        else:
            _run(
                [
                    sys.executable,
                    "-m",
                    "babel.messages.frontend",
                    "update",
                    "-i",
                    str(POT),
                    "-d",
                    str(LOCALES),
                    "-l",
                    lang,
                    "-D",
                    DOMAIN,
                    "--no-fuzzy-matching",
                ]
            )
        _fix_catalog_headers(po, lang=lang, is_pot=False)


def cmd_compile() -> None:
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / f"{DOMAIN}.po"
        if po.is_file():
            _fix_catalog_headers(po, lang=lang, is_pot=False)
        _run(
            [
                sys.executable,
                "-m",
                "babel.messages.frontend",
                "compile",
                "-d",
                str(LOCALES),
                "-l",
                lang,
                "-D",
                DOMAIN,
                "--use-fuzzy",
            ]
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command",
        choices=("extract", "update", "compile", "all"),
    )
    args = p.parse_args(argv)
    if args.command == "extract":
        cmd_extract()
    elif args.command == "update":
        cmd_update()
    elif args.command == "compile":
        cmd_compile()
    else:
        cmd_extract()
        cmd_update()
        cmd_compile()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

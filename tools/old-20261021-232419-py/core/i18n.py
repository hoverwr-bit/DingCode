"""UI strings for zh, en, and vi. The catalog is tools/dingcode/i18n/strings.json."""

import json
from pathlib import Path

from core.paths import env

LANGS = ("zh", "en", "vi")


def catalog_path():
    return Path(__file__).resolve().parents[1] / "i18n" / "strings.json"


def catalog():
    return json.loads(catalog_path().read_text(encoding="utf-8"))


def lang():
    value = (env("DINGCODE_LANG", "DINGAI_LANG", default="zh") or "zh").strip().lower()[:2]
    return value if value in LANGS else "zh"


def t(key):
    row = catalog().get(key) or {}
    return row.get(lang()) or row.get("zh") or key

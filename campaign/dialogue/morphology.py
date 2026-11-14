"""Нормализация и токенизация русского ввода.

Морфология на первом этапе словарная: формы приходят из лексикона.
Здесь только детерминированная подготовка текста.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

_TOKEN = re.compile(
    r"[A-Za-zА-Яа-яЁё0-9]+(?:-[A-Za-zА-Яа-яЁё0-9]+)*|[«»\"]"
)


def normalize_text(text: str) -> str:
    """Привести текст к сравнимому виду, не теряя слов."""

    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.replace("Ё", "Е").replace("ё", "е")
    value = value.replace("—", " ").replace("–", " ")
    value = value.replace("“", "«").replace("”", "»")
    value = value.replace("„", "«")
    value = value.strip().lower()
    return value


def tokenize(text: str) -> List[str]:
    """Разбить текст на токены; пунктуация служит границей."""

    return _TOKEN.findall(normalize_text(text))


def surface(text: str) -> str:
    """Нормализованная поверхностная форма для сопоставления."""

    return " ".join(tokenize(text))

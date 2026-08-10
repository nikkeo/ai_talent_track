"""Маскирование персональных данных до любых внешних вызовов."""

import re

from .contracts import RedactedText


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)),
    ("TOKEN", re.compile(r"(?<![\w-])(?:sk-[A-Za-z0-9_-]{8,}|[A-Fa-f0-9]{32,})(?![\w-])")),
    ("PASSPORT", re.compile(r"(?<!\d)\d{2}\s+\d{2}\s+\d{6}(?!\d)")),
    ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")),
    (
        "PHONE",
        # Разделителем бывает не только пробел и дефис: интерпункт, неразрывные
        # пробелы и типографские тире встречаются в реальных обращениях.
        re.compile(
            r"(?<!\d)(?:\+7|8)"
            r"[\s. · ‐-―• -]*\(?\d{3}\)?"
            r"[\s. · ‐-―• -]*\d{3}"
            r"[\s. · ‐-―• -]*\d{2}"
            r"[\s. · ‐-―• -]*\d{2}(?!\d)"
        ),
    ),
)
_PLACEHOLDER = re.compile(r"<(CARD|PHONE|EMAIL|PASSPORT|TOKEN)_(\d+)>")


def _luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    parity = len(digits) % 2
    total = 0
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def redact(text: str) -> tuple[RedactedText, dict[str, str]]:
    """Возвращает маскированный текст и карту масок.

    Карта масок никогда не попадает в audit и в LLM.
    """
    redacted = text
    mask_map: dict[str, str] = {}
    existing = _PLACEHOLDER.findall(text)
    found_types: list[str] = [pii_type for pii_type, _ in existing]
    counters = {
        pii_type: max((int(number) for found, number in existing if found == pii_type), default=0)
        for pii_type, _ in _PATTERNS
    }

    for pii_type, pattern in _PATTERNS:
        counter = counters[pii_type]

        def replace(match: re.Match[str]) -> str:
            nonlocal counter
            original = match.group(0)
            if pii_type == "CARD" and not _luhn_valid(original):
                return original
            counter += 1
            placeholder = f"<{pii_type}_{counter}>"
            mask_map[placeholder] = original
            found_types.append(pii_type)
            return placeholder

        redacted = pattern.sub(replace, redacted)

    result = RedactedText(
        text=redacted,
        found_types=list(dict.fromkeys(found_types)),
        placeholders=len(existing) + len(mask_map),
    )
    return result, mask_map

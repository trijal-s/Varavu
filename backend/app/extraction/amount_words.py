"""Turn an amount written in words into a number, using the Indian system (lakh, crore).

"Three Thousand One Hundred And Seventy Rupees Only" -> 3170.0
"One Lakh Twenty Five Thousand Rupees and Fifty Paise" -> 125000.5
"""
import re

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
SCALES = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
          "crore": 10_000_000, "crores": 10_000_000}
IGNORED = {"and", "only", "rs", "inr", "rupee", "rupees"}


def _parse_words(words: list[str]) -> int | None:
    """Parse one number, e.g. ['three', 'thousand', 'one', 'hundred', 'seventy']."""
    total, current, seen_number = 0, 0, False
    for word in words:
        if word in UNITS:
            current += UNITS[word]
            seen_number = True
        elif word == "hundred":
            current = (current or 1) * 100
            seen_number = True
        elif word in SCALES:
            total += (current or 1) * SCALES[word]
            current = 0
            seen_number = True
        elif word in IGNORED:
            continue
        else:
            return None  # an unknown word: don't guess
    return total + current if seen_number else None


def words_to_amount(text: str | None) -> float | None:
    """Return the amount, or None if the text can't be read as a number."""
    if not text:
        return None
    words = re.findall(r"[a-z]+", text.lower())
    if "paise" in words or "paisa" in words:
        end = words.index("paise") if "paise" in words else words.index("paisa")
        # Rupees end at the word 'rupees'/'rupee'; the words after it (before 'paise') are paise.
        split = next((i for i, w in enumerate(words[:end]) if w in ("rupee", "rupees")), None)
        if split is None:
            return None
        rupees, paise = _parse_words(words[:split]), _parse_words(words[split + 1:end])
        if rupees is None or paise is None:
            return None
        return rupees + paise / 100
    value = _parse_words(words)
    return float(value) if value is not None else None

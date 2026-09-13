import re

_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}
_TEN_MULTIPLES = {
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_HUNDRED_PATTERN = re.compile(r"\bone hundred\b")
_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

_ATTRIBUTE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(seats?|users?|licen[sc]es?)\b"), "seat_count"),
    (re.compile(r"\bbudget\b"), "budget"),
    (re.compile(r"\bclose(?:ing)? date\b"), "close_date"),
    (re.compile(r"\bpricing tier|plan tier\b"), "pricing_tier"),
    (re.compile(r"\bcontract length|term length\b"), "contract_length"),
]

_LEADING_NUMBER = re.compile(r"^(\d+)")


def normalize_text(text: str) -> str:
    lowered = text.strip().lower()
    lowered = _HUNDRED_PATTERN.sub("100", lowered)
    for word, digit in _NUMBER_WORDS.items():
        lowered = re.sub(rf"\b{word}\b", digit, lowered)
    for word, value in _TEN_MULTIPLES.items():
        lowered = re.sub(rf"\b{word}\b", str(value), lowered)
    lowered = _PUNCTUATION.sub("", lowered)
    return _WHITESPACE.sub(" ", lowered).strip()


def slugify(text: str) -> str:
    normalized = normalize_text(text)
    slug = re.sub(r"\s+", "_", normalized)
    return slug


def classify_fact_key(predicate: str, object_text: str) -> str:
    normalized = normalize_text(object_text)
    for pattern, key in _ATTRIBUTE_PATTERNS:
        if pattern.search(normalized):
            return key
    return slugify(object_text)


def extract_leading_number(text: str) -> int | None:
    normalized = normalize_text(text)
    match = _LEADING_NUMBER.search(normalized)
    if match:
        return int(match.group(1))
    return None

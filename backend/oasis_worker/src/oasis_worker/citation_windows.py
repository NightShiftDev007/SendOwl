"""Normalize model-selected quotes to unique bounded source windows."""

MAX_CITATION_CHARACTERS = 500


def _occurrence_starts(source: str, quote: str) -> tuple[int, ...]:
    starts: list[int] = []
    cursor = 0
    while True:
        start = source.find(quote, cursor)
        if start < 0:
            return tuple(starts)
        starts.append(start)
        cursor = start + 1


def normalize_unique_quote(source: str, selected_quote: str) -> str:
    selected_quote = selected_quote.strip()
    if not selected_quote:
        raise ValueError("citation is empty after trimming")
    starts = _occurrence_starts(source, selected_quote)
    if not starts:
        raise ValueError("citation is not present in the frozen source")
    if len(selected_quote) <= MAX_CITATION_CHARACTERS and len(starts) == 1:
        return selected_quote
    if len(selected_quote) > MAX_CITATION_CHARACTERS:
        offsets = (
            0,
            len(selected_quote) - MAX_CITATION_CHARACTERS,
            (len(selected_quote) - MAX_CITATION_CHARACTERS) // 2,
        )
        for start in starts:
            for offset in offsets:
                candidate = source[
                    start + offset : start + offset + MAX_CITATION_CHARACTERS
                ].strip()
                if len(_occurrence_starts(source, candidate)) == 1:
                    return candidate
    for start in starts:
        width = min(MAX_CITATION_CHARACTERS, len(source))
        left = max(0, start - (width - len(selected_quote)) // 2)
        right = min(len(source), left + width)
        left = max(0, right - width)
        candidate = source[left:right].strip()
        if selected_quote in candidate and len(_occurrence_starts(source, candidate)) == 1:
            return candidate
    raise ValueError("citation cannot be normalized to one unique bounded source window")

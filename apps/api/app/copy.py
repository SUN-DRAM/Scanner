"""Small English-copy helpers shared by finding templates and scanner modules
that interpolate numbers into prose (docs/PDF_FIXES.md polish: "A 83-day"
appeared twice in the google.com report, should read "An 83-day").
"""

from __future__ import annotations

_VOWEL_SOUND_ONES = frozenset({8})  # "eight" is the only 1-digit cardinal with a vowel sound
_VOWEL_SOUND_TEENS = frozenset({11, 18})  # "eleven", "eighteen"
_VOWEL_SOUND_TENS = frozenset({8})  # "eighty-..."


def _leads_with_vowel_sound(n: int) -> bool:
    """Whether the English cardinal reading of `n` starts with a vowel sound
    ("an eight-day", "an eighty-three-day", "an eleven-day") rather than a
    consonant one ("a ninety-day", "a one-hundred-day" — "one" is spelled
    with a vowel but pronounced with a leading "w" sound).

    English always names the leftmost nonzero digit group first, so for
    `n >= 100` the same single-digit rule that applies to `n < 10` decides
    it ("eight hundred...", "one hundred eighty...") — there's no teens/tens
    exception once a hundreds place is involved.
    """
    n = abs(n)
    if n < 10:
        return n in _VOWEL_SOUND_ONES
    if n < 20:
        return n in _VOWEL_SOUND_TEENS
    if n < 100:
        return (n // 10) in _VOWEL_SOUND_TENS
    leading_digit = int(str(n).lstrip("0")[0])
    return leading_digit in _VOWEL_SOUND_ONES


def article_for(n: int) -> str:
    """"a" or "an", matched to how `n` is actually read aloud."""
    return "an" if _leads_with_vowel_sound(n) else "a"

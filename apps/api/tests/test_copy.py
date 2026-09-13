"""docs/PDF_FIXES.md polish: "A 83-day" appeared twice in the google.com
report — should read "An 83-day". `app.copy.article_for` picks "a"/"an" to
match how the number is actually read aloud, not its written first digit.
"""

from __future__ import annotations

import pytest

from app.copy import article_for


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, "a"),  # "one" — vowel-spelled, consonant "w" sound
        (2, "a"),
        (7, "a"),
        (8, "an"),  # "eight"
        (9, "a"),
        (10, "a"),  # "ten"
        (11, "an"),  # "eleven"
        (12, "a"),  # "twelve"
        (18, "an"),  # "eighteen"
        (19, "a"),  # "nineteen"
        (20, "a"),  # "twenty"
        (47, "a"),  # "forty-seven" — the readiness.py doctest example
        (80, "an"),  # "eighty"
        (83, "an"),  # "eighty-three" — the reported bug
        (89, "an"),
        (90, "a"),  # "ninety"
        (98, "a"),
        (100, "a"),  # "one hundred"
        (398, "a"),  # "three hundred ninety-eight" — Phase 1 acceptance example
        (800, "an"),  # "eight hundred"
        (825, "an"),  # "eight hundred twenty-five"
        (1000, "a"),  # "one thousand"
    ],
)
def test_article_for_matches_the_spoken_number(n: int, expected: str) -> None:
    assert article_for(n) == expected

"""services/listing: the two helpers every list and search endpoint shares."""

from agenticops.services.listing import like_pattern, ref_number


def test_like_pattern_matches_what_was_typed_literally():
    assert like_pattern("ssh") == "%ssh%"
    assert like_pattern("100%") == "%100\\%%"
    assert like_pattern("web_tier") == "%web\\_tier%"
    assert like_pattern("a\\b") == "%a\\\\b%"            # the escape character itself
    assert like_pattern("") == "%%"


def test_ref_number_reads_a_reference_with_or_without_its_letter():
    for text in ("I#12", "i#12", "I12", "i12", "12", " 12 "):
        assert ref_number(text, "Ii") == 12, text
    assert ref_number("C#3", "Cc") == 3 and ref_number("c3", "Cc") == 3


def test_ref_number_is_none_for_anything_else():
    for text in ("", "I", "I#", "I#0", "0", "012", "I#-1", "12a", "I 12", "1234567890", "C#12", "I##12", "１２"):
        assert ref_number(text, "Ii") is None, text


def test_a_reference_whose_letter_is_required():
    # a resource's inventory number: «R#7» / «r7» — a bare «7» is not one (it would shadow every native id search)
    assert ref_number("R#7", "Rr", bare=False) == 7
    assert ref_number("r7", "Rr", bare=False) == 7
    assert ref_number("7", "Rr", bare=False) is None
    assert ref_number("#7", "Rr", bare=False) is None
    assert ref_number("7", "Rr") == 7                    # the default still takes the bare number

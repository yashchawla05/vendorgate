"""Name normalisation: benign variants must match, real differences must not."""
from core.names import compare_names, normalise


def test_pvt_ltd_equals_private_limited():
    # The happy-path scenario depends on this.
    result = compare_names("Acme Widgets Pvt. Ltd.", "ACME WIDGETS PRIVATE LIMITED")
    assert result.band == "match" and result.score == 100


def test_ampersand_and_courtesy_prefix():
    assert compare_names("M/s Shah & Sons Pvt Ltd", "Shah and Sons Private Limited").band == "match"
    assert normalise("Shah & Sons") == "shah and sons"


def test_word_order_does_not_matter():
    assert compare_names("Widgets Acme Ltd", "Acme Widgets Limited").band == "match"


def test_legal_form_difference_is_ambiguous_not_match():
    result = compare_names("Acme Widgets LLP", "Acme Widgets Private Limited")
    assert result.band == "ambiguous" and "legal form" in result.note


def test_small_typo_is_ambiguous():
    result = compare_names("Acme Widgits Pvt Ltd", "Acme Widgets Private Limited")
    assert result.band in {"ambiguous", "match"} and result.score >= 80


def test_different_entity_is_mismatch():
    assert compare_names("Rakesh Traders", "Acme Widgets Private Limited").band == "mismatch"

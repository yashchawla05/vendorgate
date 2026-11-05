"""Unit tests for format and checksum validators.

Test vectors were checked against the published algorithms and independent online validators.
"""
import pytest

from core.validators import india, uk, us


# ---------------------------------------------------------------- GSTIN checksum
def test_gstin_checksum_known_valid():
    assert india.gstin_check_char("27AAPFU0939F1Z") == "V"
    assert india.validate_gstin("27AAPFU0939F1ZV").ok


def test_gstin_spec_vector_is_actually_invalid():
    # The spec listed 29AABCT1332L1ZS as valid; the mod-36 check character is 'A'.
    assert india.gstin_check_char("29AABCT1332L1Z") == "A"
    assert not india.validate_gstin("29AABCT1332L1ZS").ok
    assert india.validate_gstin("29AABCT1332L1ZA").ok


@pytest.mark.parametrize("gstin", ["27ZZZPZ9999Z1ZS", "29ZZZCZ0001Z1ZW", "07ZZZFZ0002Z1ZV"])
def test_gstin_synthetic_valid(gstin):
    assert india.validate_gstin(gstin).ok


def test_gstin_detects_every_single_char_typo():
    good = "27AAPFU0939F1ZV"
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for i in range(15):
        for ch in alphabet:
            if ch == good[i]:
                continue
            assert not india.validate_gstin(good[:i] + ch + good[i + 1:]).ok


@pytest.mark.parametrize("gstin,reason", [
    ("25AAPFU0939F1ZV", "not valid for a vendor"),  # legacy Daman & Diu code
    ("28AAPFU0939F1ZV", "not valid for a vendor"),
    ("9917USA29016OS6", "not valid for a vendor"),  # OIDAR
    ("27AAPFU0939F1DV", "14th character"),
    ("27AAPFU0939F1Z", "15 characters"),
])
def test_gstin_rejections(gstin, reason):
    result = india.validate_gstin(gstin)
    assert not result.ok and reason in result.reason


def test_gstin_helpers():
    assert india.gstin_embedded_pan("27AAPFU0939F1ZV") == "AAPFU0939F"
    assert india.gstin_state("29AABCT1332L1ZA") == "Karnataka"


# ---------------------------------------------------------------- PAN
@pytest.mark.parametrize("pan", ["AAPFU0939F", "ZZZCZ0001Z", "zzzpz9999z"])
def test_pan_valid(pan):
    assert india.validate_pan(pan).ok


def test_pan_common_placeholder_is_invalid():
    result = india.validate_pan("ABCDE1234F")  # 'D' is not a holder type
    assert not result.ok and "holder type" in result.reason


def test_pan_entity_letters():
    assert india.pan_holder_type("ZZZCZ0001Z") == "Company"
    assert india.pan_matches_entity("ZZZCZ0001Z", "company")
    assert not india.pan_matches_entity("ZZZPZ0001Z", "company")
    assert india.pan_matches_entity("ZZZFZ0001Z", "llp_partnership")
    assert india.pan_matches_entity("ZZZPZ0001Z", "proprietorship")


# ---------------------------------------------------------------- IFSC / account
def test_ifsc():
    assert india.validate_ifsc("HDFC0001234").ok
    assert not india.validate_ifsc("HDFCO001234").ok  # letter O instead of zero
    assert "5th character" in india.validate_ifsc("HDFCO001234").reason
    assert not india.validate_ifsc("HDF0001234").ok


def test_ifsc_bank_consistency():
    assert india.check_ifsc_bank("HDFC0001234", "HDFC Bank Ltd").ok
    mismatch = india.check_ifsc_bank("HDFC0001234", "ICICI Bank")
    assert not mismatch.ok and mismatch.soft
    assert india.check_ifsc_bank("SBIN0000001", "SBI").ok
    unknown = india.check_ifsc_bank("ZZZZ0000001", "Some Co-op Bank")
    assert unknown.ok and unknown.soft


def test_indian_account():
    assert india.validate_in_account("000123456789").ok
    assert india.validate_in_account("000123456789").normalized == "000123456789"  # keeps leading zeros
    assert not india.validate_in_account("12345678").ok
    assert not india.validate_in_account("1234567890123456789").ok
    assert not india.validate_in_account("12345ABC901").ok


def test_cin():
    assert india.validate_cin("U72200KA2019PTC123456").ok
    assert not india.validate_cin("U72200KA2019PTC12345").ok


# ---------------------------------------------------------------- US
@pytest.mark.parametrize("routing", ["011000015", "021000021", "121000358", "026009593"])
def test_aba_valid(routing):
    assert us.validate_aba(routing).ok


def test_aba_invalid():
    assert "checksum" in us.validate_aba("021000022").reason
    assert "Federal Reserve" in us.validate_aba("500000005").reason
    assert not us.validate_aba("12345").ok


def test_ein():
    assert us.validate_ein("12-3456789").ok
    assert us.validate_ein("123456789").normalized == "12-3456789"
    assert "never been issued" in us.validate_ein("07-1234567").reason
    assert not us.validate_ein("12-345678").ok


# ---------------------------------------------------------------- UK
def test_sort_code():
    assert uk.validate_sort_code("12-34-56").normalized == "12-34-56"
    assert not uk.validate_sort_code("12345").ok


def test_uk_account():
    assert uk.validate_uk_account("12345678").ok
    assert uk.validate_uk_account("1234567").normalized == "01234567"
    long = uk.validate_uk_account("1234567890")
    assert not long.ok and long.soft


@pytest.mark.parametrize("vat", ["GB104252813", "370152133", "GB980780684", "GBGD001"])
def test_uk_vat_valid(vat):
    assert uk.validate_uk_vat(vat).ok


def test_uk_vat_invalid():
    bad = uk.validate_uk_vat("GB123456789")
    assert not bad.ok and bad.soft
    assert not uk.validate_uk_vat("GB12345").ok


def test_company_number():
    assert uk.validate_company_number("1234567").normalized == "01234567"
    assert uk.validate_company_number("SC123456").ok
    assert not uk.validate_company_number("XX123456").ok

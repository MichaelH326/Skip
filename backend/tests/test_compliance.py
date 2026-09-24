from adpress import compliance
from adpress.formats import get_format
from adpress.kit import Kit, Offer, apply_industry_defaults


def kit(industry="real_estate", **kw):
    k = Kit(name="Harbor", never_words=["cheap"], facts=[{"claim": "Serving Tacoma since 2004"}],
            offers=[Offer(headline="Save 20% on staging", proof="", cta="Book")], **kw)
    k.compliance.industry = industry
    return apply_industry_defaults(k)


def ad(text, **extra):
    return {"fields": {"primary_text": text, "headline": "Harbor", "description": "Homes"}, "cta": "Go",
            "hashtags": [], **extra}


def rules(flags):
    return {(f["rule"], f["severity"]) for f in flags}


FB = get_format("facebook_feed")
EHO = " Equal Housing Opportunity"


def test_clean_ad_has_no_blocking_flags():
    flags = compliance.code_checks(ad("Serving Tacoma since 2004." + EHO), kit(), FB, [])
    assert compliance.blocking_open(flags) == []


def test_never_word_matches_stems():
    flags = compliance.code_checks(ad("Cheaper than you think." + EHO), kit(), FB, [])
    assert ("never_word", "blocking") in rules(flags)


def test_number_not_in_kit_is_blocking_and_kit_numbers_pass():
    flags = compliance.code_checks(ad("500 happy clients and 20% off staging, open 24/7." + EHO), kit(), FB, [])
    words = [f["words"] for f in flags if f["rule"] == "unsupported_claim"]
    assert words == ["500"]


def test_protected_trait_blocking_only_in_regulated_industries():
    text = "Perfect for families near great schools." + EHO
    assert ("protected_trait", "blocking") in rules(compliance.code_checks(ad(text), kit(), FB, []))
    general = compliance.code_checks(ad(text), kit("restaurant"), FB, [])
    assert ("protected_trait", "warning") in rules(general)


def test_missing_disclaimer():
    flags = compliance.code_checks(ad("A lovely porch."), kit(), FB, [])
    assert ("missing_disclaimer", "blocking") in rules(flags)


def test_limits_hard_and_recommended():
    long = "word " * 500
    flags = compliance.code_checks(ad(long + EHO), kit(), FB, [])
    assert ("over_limit", "blocking") in rules(flags)
    medium = "a" * 150 + EHO
    flags = compliance.code_checks(ad(medium), kit(), FB, [])
    assert ("over_recommended", "warning") in rules(flags)
    assert ("over_limit", "blocking") not in rules(flags)


def test_google_multi_field_counts():
    fmt = get_format("google_search")
    content = {"fields": {"headlines": ["One", "Two"], "descriptions": ["A" + EHO, "B"]}, "cta": "", "hashtags": []}
    flags = compliance.code_checks(content, kit(), fmt, [])
    assert any(f["rule"] == "missing_field" and f["field"] == "headlines" for f in flags)


def test_third_party_copy_detected():
    src = "the quick brown fox jumps over the lazy dog near the river bank today"
    flags = compliance.code_checks(ad("The quick brown fox jumps over the lazy dog near the river." + EHO), kit(), FB, [src])
    assert ("third_party_copy", "blocking") in rules(flags)


def test_superlative_warning():
    flags = compliance.code_checks(ad("The best agents in town." + EHO), kit(), FB, [])
    assert ("superlative", "warning") in rules(flags)


def test_merge_keeps_overrides():
    code = compliance.code_checks(ad("500 homes sold." + EHO), kit(), FB, [])
    code[0]["overridden"] = True
    code[0]["override_reason"] = "verified"
    again = compliance.code_checks(ad("500 homes sold." + EHO), kit(), FB, [])
    merged = compliance.merge_flags(again, [], previous=code)
    assert compliance.blocking_open(merged) == []

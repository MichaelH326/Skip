import csv
import io

from adpress import exporter, kit_markdown
from adpress.kit import Kit, Location, Offer, PlatformTheme, apply_industry_defaults


def test_markdown_roundtrip():
    k = Kit(name="Harbor Realty", core_voice="Warm", always_words=["home"], never_words=["cheap"],
            platform_themes={"linkedin": PlatformTheme(voice_shift="formal")},
            locations=[Location(name="North Tacoma", references=["Point Defiance"])],
            offers=[Offer(headline="Free valuation", cta="Book")])
    k.compliance.industry = "real_estate"
    k = apply_industry_defaults(k)
    md = kit_markdown.to_markdown(k)
    assert "## Voice" in md and "Equal Housing Opportunity" in md and "North Tacoma" in md
    assert kit_markdown.from_markdown(md) == k


def test_import_rejects_plain_markdown():
    try:
        kit_markdown.from_markdown("# Hello")
    except ValueError as e:
        assert "no Adpress kit block" in str(e)
    else:
        raise AssertionError


def _ad(platform, fields):
    return {"id": "a1", "platform": platform, "audience": "Buyers", "location": "Tacoma", "offer": None,
            "angle": "Local", "status": "approved",
            "content": {"fields": fields, "cta": "Learn more", "hashtags": ["#home"], "image_direction": "Porch"}}


def test_csv_per_platform():
    cases = {
        "facebook": {"primary_text": "Hi", "headline": "H", "description": "D"},
        "instagram": {"caption": "Hi"},
        "linkedin": {"intro_text": "Hi", "headline": "H"},
        "google": {"headlines": ["A", "B", "C"], "descriptions": ["D1", "D2"]},
        "x": {"post": "Hi", "card_headline": "H"},
    }
    for platform, fields in cases.items():
        out = exporter.to_csv(platform, "Harbor Realty", "https://harbor.example", "HOUSING", [_ad(platform, fields)])
        rows = list(csv.DictReader(io.StringIO(out)))
        assert len(rows) == 1
        assert rows[0]["Adpress Ad ID"] == "a1"
        assert set(exporter.COMMON + exporter.PLATFORM_COLUMNS[platform]) == set(rows[0])
    rows = list(csv.DictReader(io.StringIO(exporter.to_csv("facebook", "Harbor Realty", "u", "HOUSING",
                                                            [_ad("facebook", cases["facebook"])]))))
    assert rows[0]["Primary Text"] == "Hi\n\n#home"
    assert rows[0]["Special Ad Category"] == "HOUSING"
    assert rows[0]["Ad Name"] == "harbor-realty_facebook_buyers_tacoma_local_01"


def test_special_category_mapping():
    assert exporter.special_ad_category("real_estate", True) == "HOUSING"
    assert exporter.special_ad_category("restaurant", False) == "NONE"

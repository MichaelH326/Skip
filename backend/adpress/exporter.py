"""CSV export for ad-manager bulk upload (PRD: CSV export).

Column names are the working set; match each to the platform's current bulk-upload template before launch.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

COMMON = ["Adpress Ad ID", "Brand", "Audience", "Location", "Offer", "Angle", "Status", "Image Direction"]

PLATFORM_COLUMNS: dict[str, list[str]] = {
    "facebook": ["Ad Name", "Primary Text", "Headline", "Description", "Call to Action", "Website URL", "Special Ad Category"],
    "instagram": ["Ad Name", "Primary Text", "Headline", "Description", "Call to Action", "Website URL", "Special Ad Category"],
    "linkedin": ["Ad Name", "Introductory Text", "Headline", "Destination URL", "CTA"],
    "google": ["Campaign", "Ad Group", *[f"Headline {i}" for i in range(1, 16)], *[f"Description {i}" for i in range(1, 5)],
               "Final URL", "Path 1", "Path 2"],
    "x": ["Post Text", "Card Headline", "Website URL"],
}


SPECIAL_AD_CATEGORIES = {"real_estate": "HOUSING", "credit": "CREDIT", "employment": "EMPLOYMENT"}


def special_ad_category(industry: str, required: bool) -> str:
    """Meta special ad category value for an industry."""
    return SPECIAL_AD_CATEGORIES.get(industry, "NONE") if required else "NONE"


def _slug(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "all").lower()).strip("-") or "all"


def ad_name(brand: str, ad: dict[str, Any], n: int) -> str:
    return "_".join([_slug(brand), ad["platform"], _slug(ad.get("audience")), _slug(ad.get("location")),
                     _slug(ad.get("angle"))[:30], f"{n:02d}"])


def _with_hashtags(text: str, tags: list[str]) -> str:
    return (text + ("\n\n" + " ".join(tags) if tags else "")).strip()


def platform_row(platform: str, ad: dict[str, Any], name: str, website_url: str, special_category: str,
                 campaign: str) -> dict[str, str]:
    c = ad["content"]
    f = c.get("fields") or {}
    tags = c.get("hashtags") or []
    cta = c.get("cta", "")
    if platform in ("facebook", "instagram"):
        primary = f.get("primary_text") or f.get("caption") or ""
        return {"Ad Name": name, "Primary Text": _with_hashtags(primary, tags), "Headline": f.get("headline", ""),
                "Description": f.get("description", ""), "Call to Action": cta, "Website URL": website_url,
                "Special Ad Category": special_category}
    if platform == "linkedin":
        return {"Ad Name": name, "Introductory Text": _with_hashtags(f.get("intro_text", ""), tags),
                "Headline": f.get("headline", ""), "Destination URL": website_url, "CTA": cta}
    if platform == "google":
        row = {"Campaign": campaign, "Ad Group": name, "Final URL": website_url, "Path 1": "", "Path 2": ""}
        if "headlines" in f:
            heads, descs = f.get("headlines") or [], f.get("descriptions") or []
        else:
            heads = [h for h in (f.get("short_headline"), f.get("long_headline")) if h]
            descs = [f["description"]] if f.get("description") else []
        for i in range(15):
            row[f"Headline {i + 1}"] = heads[i] if i < len(heads) else ""
        for i in range(4):
            row[f"Description {i + 1}"] = descs[i] if i < len(descs) else ""
        return row
    if platform == "x":
        return {"Post Text": _with_hashtags(f.get("post", ""), tags), "Card Headline": f.get("card_headline", ""),
                "Website URL": website_url}
    raise ValueError(f"unsupported platform: {platform}")


def to_csv(platform: str, brand_name: str, website_url: str, special_category: str, ads: list[dict[str, Any]]) -> str:
    if platform not in PLATFORM_COLUMNS:
        raise ValueError(f"unsupported platform: {platform}")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COMMON + PLATFORM_COLUMNS[platform], extrasaction="ignore")
    writer.writeheader()
    campaign = f"{brand_name} - Adpress"
    for n, ad in enumerate(ads, start=1):
        name = ad_name(brand_name, ad, n)
        row = {
            "Adpress Ad ID": ad["id"], "Brand": brand_name, "Audience": ad.get("audience") or "",
            "Location": ad.get("location") or "", "Offer": ad.get("offer") or "", "Angle": ad.get("angle") or "",
            "Status": ad["status"], "Image Direction": ad["content"].get("image_direction", ""),
        }
        row.update(platform_row(platform, ad, name, website_url, special_category, campaign))
        writer.writerow(row)
    return buf.getvalue()

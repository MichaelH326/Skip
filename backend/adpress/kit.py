"""Brand kit schema (PRD: Brand kit schema) and industry defaults."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Industry = Literal["real_estate", "credit", "employment", "restaurant", "retail", "local_services", "saas", "general"]
REGULATED_INDUSTRIES: frozenset[str] = frozenset({"real_estate", "credit", "employment"})
PLATFORMS = ("facebook", "instagram", "linkedin", "google", "x")


class VoiceDials(BaseModel):
    formal: int = Field(3, ge=1, le=5)
    playful: int = Field(3, ge=1, le=5)
    bold: int = Field(3, ge=1, le=5)
    technical: int = Field(3, ge=1, le=5)
    warm: int = Field(3, ge=1, le=5)


class Fact(BaseModel):
    claim: str
    source_url: str = ""


class Color(BaseModel):
    hex: str
    role: Literal["primary", "secondary", "accent", "background"] = "primary"

    @field_validator("hex")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("#"):
            v = "#" + v
        if len(v) not in (4, 7) or any(c not in "0123456789abcdefABCDEF" for c in v[1:]):
            raise ValueError(f"not a hex color: {v}")
        return v.upper()


class Typography(BaseModel):
    heading: str = ""
    body: str = ""


class Compliance(BaseModel):
    industry: Industry = "general"
    special_ad_category: bool = False
    required_disclaimers: list[str] = []
    rules: list[str] = []


class PlatformTheme(BaseModel):
    audience: str = ""
    voice_shift: str = ""
    length: str = ""
    hashtags: str = ""
    emoji: str = ""
    cta_style: str = ""
    colors: list[str] = []


class Audience(BaseModel):
    name: str
    who: str = ""
    goals: list[str] = []
    objections: list[str] = []
    key_message: str = ""
    best_platforms: list[str] = []
    ctas: list[str] = []


class Location(BaseModel):
    name: str
    references: list[str] = []
    phrasing: str = ""
    seasonal_hooks: list[str] = []
    avoid: list[str] = []


class Offer(BaseModel):
    headline: str
    proof: str = ""
    cta: str = ""
    expires_on: str | None = None


class Example(BaseModel):
    text: str
    platform: str = ""
    rating: Literal["good", "bad"] = "good"


class Kit(BaseModel):
    name: str
    core_voice: str = Field("", max_length=300)
    voice_dials: VoiceDials = VoiceDials()
    always_words: list[str] = []
    never_words: list[str] = []
    facts: list[Fact] = []
    colors: list[Color] = []
    typography: Typography = Typography()
    compliance: Compliance = Compliance()
    platform_themes: dict[str, PlatformTheme] = {}
    audiences: list[Audience] = []
    locations: list[Location] = []
    offers: list[Offer] = []
    examples: list[Example] = []
    # Field path -> reason, for every AI-inferred field the user has not confirmed yet.
    guessed: dict[str, str] = {}

    @field_validator("platform_themes")
    @classmethod
    def _platforms(cls, v: dict[str, PlatformTheme]) -> dict[str, PlatformTheme]:
        unknown = set(v) - set(PLATFORMS)
        if unknown:
            raise ValueError(f"unknown platforms: {sorted(unknown)}")
        return v

    def audience(self, name: str | None) -> Audience | None:
        return next((a for a in self.audiences if a.name == name), None) if name else None

    def location(self, name: str | None) -> Location | None:
        return next((loc for loc in self.locations if loc.name == name), None) if name else None

    def offer(self, headline: str | None) -> Offer | None:
        return next((o for o in self.offers if o.headline == headline), None) if headline else None


# Words that are banned by default per industry, merged into never_words on kit build.
INDUSTRY_NEVER_WORDS: dict[str, list[str]] = {
    "real_estate": ["guaranteed", "exclusive neighborhood", "safe neighborhood", "family-friendly", "perfect for families"],
    "credit": ["guaranteed approval", "no credit check", "risk-free", "instant approval"],
    "employment": ["young", "recent graduate", "digital native", "able-bodied", "manpower"],
    "general": ["guaranteed"],
}

INDUSTRY_DISCLAIMERS: dict[str, list[str]] = {
    "real_estate": ["Equal Housing Opportunity"],
    "credit": [],
    "employment": [],
}

INDUSTRY_RULES: dict[str, list[str]] = {
    "real_estate": [
        "Describe the property and location, never the people who should live there.",
        "Never mention or imply preference based on race, color, religion, sex, disability, familial status, or national origin.",
    ],
    "credit": [
        "Never promise approval or specific rates unless stored in the kit facts.",
        "Never target or exclude by age, race, sex, marital status, or national origin.",
    ],
    "employment": [
        "Describe the job and its requirements, never the kind of person who should apply.",
        "Never mention or imply age, sex, race, religion, disability, or national origin preferences.",
    ],
}


def apply_industry_defaults(kit: Kit) -> Kit:
    industry = kit.compliance.industry
    never = list(dict.fromkeys(kit.never_words + INDUSTRY_NEVER_WORDS.get(industry, INDUSTRY_NEVER_WORDS["general"])))
    disclaimers = list(dict.fromkeys(kit.compliance.required_disclaimers + INDUSTRY_DISCLAIMERS.get(industry, [])))
    rules = list(dict.fromkeys(kit.compliance.rules + INDUSTRY_RULES.get(industry, [])))
    compliance = kit.compliance.model_copy(
        update={
            "required_disclaimers": disclaimers,
            "rules": rules,
            "special_ad_category": kit.compliance.special_ad_category or industry in REGULATED_INDUSTRIES,
        }
    )
    return kit.model_copy(update={"never_words": never, "compliance": compliance})

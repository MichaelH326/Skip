"""Build a brand kit from imported content with the LLM (PRD: AI kit builder)."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from .kit import (
    PLATFORMS,
    Audience,
    Color,
    Compliance,
    Fact,
    Kit,
    PlatformTheme,
    Typography,
    VoiceDials,
    apply_industry_defaults,
)
from .llm import LLM, Usage

MAX_SOURCE_CHARS = 60_000


class DraftTheme(BaseModel):
    platform: Literal["facebook", "instagram", "linkedin", "google", "x"]
    audience: str
    voice_shift: str
    length: str
    hashtags: str
    emoji: str
    cta_style: str


class DraftColor(BaseModel):
    hex: str
    role: Literal["primary", "secondary", "accent", "background"]


class DraftGuess(BaseModel):
    field: str
    reason: str


class KitDraft(BaseModel):
    core_voice: str
    voice_dials: VoiceDials
    always_words: list[str]
    never_words: list[str]
    facts: list[Fact]
    colors: list[DraftColor]
    audiences: list[Audience]
    platform_themes: list[DraftTheme]
    guesses: list[DraftGuess]


SYSTEM = """You build brand kits for Adpress, a tool that writes on-brand ads.

A brand kit captures what stays constant across every ad: voice, words, colors, facts, and audiences.
You receive a company's own website copy and social posts. Infer the kit from that material only.

Rules:
- core_voice: one sentence, at most 300 characters, describing how the brand sounds.
- voice_dials: 1 to 5 for formal, playful, bold, technical, warm, judged from the writing itself.
- always_words: 3 to 10 words or short phrases the brand uses repeatedly and should keep using.
- never_words: words that clash with this voice (for example hype words for a calm brand). Leave compliance words to the system.
- facts: only concrete claims stated in the material (years in business, counts, awards, credentials, service areas), each with the URL it came from. Never invent or round a fact. Numbers must appear exactly as written in the source.
- colors: assign a role to each extracted color you were given. Do not invent colors.
- audiences: up to 3 likely customer groups, described by needs and situation, never by protected traits (race, religion, sex, age, disability, familial status, national origin).
- platform_themes: one per platform that has pasted posts, plus facebook, instagram, and linkedin if the website suggests the brand would advertise there. Describe how the voice shifts for that platform's audience, typical post length, hashtag and emoji habits, and CTA style.
- guesses: list every field you inferred rather than read directly, with a one-line reason. Field names are: core_voice, voice_dials, always_words, never_words, colors, audiences, and platform_themes.<platform>."""


def _source_block(website: list[dict], pasted: list[dict]) -> str:
    parts: list[str] = []
    budget = MAX_SOURCE_CHARS
    for page in website:
        chunk = f"<page url=\"{page['url']}\">\n{page['text']}\n</page>"
        if len(chunk) > budget:
            chunk = chunk[:budget]
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break
    for src in pasted:
        chunk = f"<post platform=\"{src['platform'] or 'unknown'}\" kind=\"{src['kind']}\">\n{src['text']}\n</post>"
        parts.append(chunk[: max(budget, 2000)])
        budget -= len(chunk)
    return "\n\n".join(parts)


def build_kit(
    llm: LLM,
    *,
    name: str,
    industry: str,
    website: list[dict],
    pasted: list[dict],
    colors: list[str],
    fonts: list[str],
    previous: Kit | None = None,
) -> tuple[Kit, Usage]:
    """Return a new kit with every AI-inferred field marked as guessed."""
    material = _source_block(website, pasted)
    user = (
        f"Company: {name}\nIndustry: {industry}\n"
        f"Colors extracted from the website CSS (most used first): {json.dumps(colors)}\n"
        f"Fonts extracted from the website CSS: {json.dumps(fonts)}\n\n"
        f"Company material:\n{material or '(none provided)'}"
    )
    result = llm.structured(
        role="write",
        system=[{"type": "text", "text": SYSTEM}],
        content=[{"type": "text", "text": user}],
        schema=KitDraft,
    )
    draft: KitDraft = result.parsed

    valid_colors: list[Color] = []
    extracted = {c.upper() for c in colors}
    for c in draft.colors:
        try:
            color = Color(hex=c.hex, role=c.role)
        except ValueError:
            continue
        if color.hex in extracted:
            valid_colors.append(color)
    if not valid_colors:
        roles = ["primary", "secondary", "accent", "background"]
        valid_colors = [Color(hex=c, role=roles[min(i, 3)]) for i, c in enumerate(colors[:4])]

    themes: dict[str, PlatformTheme] = {}
    for t in draft.platform_themes:
        if t.platform in PLATFORMS:
            themes[t.platform] = PlatformTheme(**t.model_dump(exclude={"platform"}))

    guessed: dict[str, str] = {}
    for g in draft.guesses:
        guessed[g.field] = g.reason
    default_reasons = {
        "core_voice": "Inferred from the tone of your website and posts.",
        "voice_dials": "Estimated from your writing style.",
        "always_words": "Picked from words your content repeats.",
        "audiences": "Suggested from who your content speaks to.",
        "colors": "Roles assigned from how often each color appears.",
    }
    for key, reason in default_reasons.items():
        guessed.setdefault(key, reason)
    for platform in themes:
        guessed.setdefault(f"platform_themes.{platform}", f"Inferred from your {platform} content and website.")
    guessed = {k: v for k, v in guessed.items() if k.split(".")[0] in Kit.model_fields}

    kit = Kit(
        name=name,
        core_voice=draft.core_voice[:300],
        voice_dials=draft.voice_dials,
        always_words=draft.always_words,
        never_words=draft.never_words,
        facts=draft.facts,
        colors=valid_colors,
        typography=Typography(heading=fonts[0] if fonts else "", body=fonts[1] if len(fonts) > 1 else (fonts[0] if fonts else "")),
        compliance=Compliance(industry=industry),  # type: ignore[arg-type]
        platform_themes=themes,
        audiences=draft.audiences[:3],
        # Keep user-owned lists from the previous kit when rebuilding.
        locations=previous.locations if previous else [],
        offers=previous.offers if previous else [],
        examples=previous.examples if previous else [],
        guessed=guessed,
    )
    if previous:
        kit = kit.model_copy(update={"compliance": previous.compliance.model_copy(update={"industry": industry})})
    return apply_industry_defaults(kit), result.usage

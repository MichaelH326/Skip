"""Ad generation (PRD: Generation pipeline).

Prompt order is fixed so the stable parts cache across requests:
system rules (static) -> brand kit (cached per kit version) -> platform theme + format (cached per platform) -> request.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, create_model

from . import compliance
from .formats import FormatSpec, get_format
from .kit import Kit
from .llm import LLM, LLMError, Usage

MAX_PARALLEL_CALLS = 6

SYSTEM_RULES = """You write ads for Adpress. Every ad must sound like the brand described in the brand kit below.

Rules:
- Write natively for the platform and format given: respect its audience, length, hashtag, emoji, and CTA conventions from the platform theme.
- Keep every field within its recommended length when possible and never over its hard limit.
- Use only facts, numbers, awards, and claims that appear in the brand kit facts or the chosen offer. Never invent statistics, reviews, ratings, or awards. If you have no fact to support a claim, leave the claim out.
- Never use any word in never_words. Prefer words in always_words where natural.
- Follow every compliance rule. Include each required disclaimer verbatim in the ad text.
- Describe the product, service, property, or place, never the kind of person who should buy it. No language about race, color, religion, sex, disability, familial status, national origin, or age.
- When a location is given, use its references and phrasing only where they are listed in the kit. Do not invent local details.
- Each ad in a batch must take a clearly different approach (hook, structure, or benefit), not reword the same sentence.
- Write original copy. Do not reproduce example text word for word.
- image_direction: one or two sentences describing the visual, in the format's aspect ratio, using the brand colors. Empty when the format has no image.
- facts_used: copy each kit fact you relied on, verbatim."""


REFINE_INSTRUCTIONS = {
    "shorter": "Make it noticeably shorter while keeping the core message.",
    "more_local": "Make it more local, using the location's references and phrasing from the kit.",
    "different_angle": "Take a different angle: a new hook and a different main benefit.",
    "more_formal": "Make the tone more formal.",
    "more_casual": "Make the tone more casual.",
}


@lru_cache
def ad_schema(format_key: str) -> type[BaseModel]:
    """Pydantic schema for one batch of ads in a format."""
    fmt = get_format(format_key)
    field_defs: dict[str, Any] = {}
    for spec in fmt.fields:
        field_defs[spec.key] = (list[str], ...) if spec.multi else (str, ...)
    fields_model = create_model(f"Fields_{format_key}", **field_defs)
    ad_model = create_model(
        f"Ad_{format_key}",
        fields=(fields_model, ...),
        cta=(str, ...),
        hashtags=(list[str], ...),
        image_direction=(str, ...),
        angle=(str, ...),
        facts_used=(list[str], ...),
    )
    return create_model(f"Batch_{format_key}", ads=(list[ad_model], ...))


def kit_prompt_json(kit: Kit) -> str:
    """Kit as it goes to the model: stable key order so the cache prefix never changes for a version."""
    data = kit.model_dump(exclude={"guessed", "platform_themes", "locations", "audiences", "offers"})
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def format_block(kit: Kit, fmt: FormatSpec) -> str:
    theme = kit.platform_themes.get(fmt.platform)
    specs = []
    for f in fmt.fields:
        spec = f"- {f.key} ({f.label}): recommended <= {f.recommended} chars, hard limit {f.limit}"
        if f.multi:
            spec += f"; write between {f.multi.min} and {f.multi.max} distinct items, each within the limit"
        if f.counts_hashtags:
            spec += "; hashtags count toward this limit"
        specs.append(spec)
    return (
        f"Platform: {fmt.platform}\nFormat: {fmt.name}\n"
        f"Platform theme: {json.dumps(theme.model_dump() if theme else {}, sort_keys=True)}\n"
        f"Image aspect ratio: {fmt.image_direction or 'none (text-only format)'}\n"
        f"Maximum hashtags: {fmt.max_hashtags}\n"
        f"Fields:\n" + "\n".join(specs)
    )


@dataclass
class Combo:
    format_key: str
    audience: str | None
    location: str | None


@dataclass
class GenParams:
    formats: list[str]
    audiences: list[str | None] = field(default_factory=lambda: [None])
    locations: list[str | None] = field(default_factory=lambda: [None])
    offer: str | None = None
    angle: str | None = None
    count: int = 1

    def combos(self) -> list[Combo]:
        return [
            Combo(f, a, loc)
            for f in self.formats
            for a in (self.audiences or [None])
            for loc in (self.locations or [None])
        ]


def request_block(kit: Kit, combo: Combo, offer: str | None, angle: str | None, count: int,
                  refine: dict[str, Any] | None = None) -> str:
    audience = kit.audience(combo.audience)
    location = kit.location(combo.location)
    chosen_offer = kit.offer(offer)
    lines = [
        f"Audience: {json.dumps(audience.model_dump() if audience else 'general audience for this brand')}",
        f"Location: {json.dumps(location.model_dump() if location else 'no specific location')}",
        f"Offer: {json.dumps(chosen_offer.model_dump() if chosen_offer else 'no specific offer; promote the brand')}",
        f"Angle: {angle or 'your choice; vary it across ads'}",
    ]
    if refine:
        lines.append(
            "\nRewrite this existing ad. Return exactly 1 ad.\n"
            f"Existing ad: {json.dumps(refine['ad'], ensure_ascii=False)}\n"
            f"Instruction: {refine['instruction']}"
        )
    else:
        lines.append(f"\nWrite exactly {count} ads.")
    return "\n".join(lines)


@dataclass
class GeneratedAd:
    combo: Combo
    content: dict[str, Any]
    flags: list[dict[str, Any]]


@dataclass
class GenOutcome:
    ads: list[GeneratedAd]
    usage: Usage
    errors: list[str]


def _write(llm: LLM, kit: Kit, combo: Combo, offer: str | None, angle: str | None, count: int,
           refine: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], Usage]:
    fmt = get_format(combo.format_key)
    system = [
        {"type": "text", "text": SYSTEM_RULES},
        {"type": "text", "text": f"Brand kit:\n{kit_prompt_json(kit)}", "cache_control": {"type": "ephemeral"}},
    ]
    content = [
        {"type": "text", "text": format_block(kit, fmt), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": request_block(kit, combo, offer, angle, count, refine)},
    ]
    result = llm.structured(role="write", system=system, content=content, schema=ad_schema(combo.format_key),
                            max_tokens=min(4000 + 1500 * count, 64000))
    ads = [a.model_dump() for a in result.parsed.ads]
    want = 1 if refine else count
    return ads[:want], result.usage


def _normalize(content: dict[str, Any], fmt: FormatSpec) -> dict[str, Any]:
    content["hashtags"] = [h if h.startswith("#") else f"#{h}" for h in (content.get("hashtags") or []) if h.strip()]
    if fmt.max_hashtags == 0:
        content["hashtags"] = []
    if not fmt.image_direction:
        content["image_direction"] = ""
    return content


def check_ads(llm: LLM | None, kit: Kit, items: list[tuple[FormatSpec, dict[str, Any]]], third_party: list[str],
              review: bool) -> tuple[list[list[dict[str, Any]]], Usage]:
    code = [compliance.code_checks(content, kit, fmt, third_party) for fmt, content in items]
    usage = Usage()
    if review and llm is not None:
        review_flags, usage = compliance.llm_review(llm, kit, [c for _, c in items])
    else:
        review_flags = [[] for _ in items]
    return [compliance.merge_flags(c, r) for c, r in zip(code, review_flags)], usage


def generate(llm: LLM, kit: Kit, params: GenParams, third_party: list[str], review: bool = True,
             on_progress=None) -> GenOutcome:
    combos = params.combos()
    usage = Usage()
    errors: list[str] = []
    results: list[tuple[Combo, list[dict[str, Any]]]] = []

    def run(combo: Combo):
        return combo, _write(llm, kit, combo, params.offer, params.angle, params.count)

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
        futures = [pool.submit(run, c) for c in combos]
        for fut in futures:
            try:
                combo, (ads, u) = fut.result()
                usage.add(u)
                results.append((combo, ads))
            except LLMError as e:
                errors.append(str(e))
            done += 1
            if on_progress:
                on_progress(f"Wrote {done} of {len(combos)} batches")

    items: list[tuple[Combo, FormatSpec, dict[str, Any]]] = []
    for combo, ads in results:
        fmt = get_format(combo.format_key)
        for content in ads:
            items.append((combo, fmt, _normalize(content, fmt)))

    if on_progress:
        on_progress("Checking compliance")
    flags, review_usage = check_ads(llm, kit, [(f, c) for _, f, c in items], third_party, review)
    usage.add(review_usage)
    ads_out = [GeneratedAd(combo=c, content=content, flags=fl) for (c, _, content), fl in zip(items, flags)]
    return GenOutcome(ads=ads_out, usage=usage, errors=errors)


def refine(llm: LLM, kit: Kit, combo: Combo, offer: str | None, angle: str | None, ad_content: dict[str, Any],
           instruction: str, third_party: list[str], review: bool = True) -> tuple[GeneratedAd, Usage]:
    text = REFINE_INSTRUCTIONS.get(instruction, instruction)
    ads, usage = _write(llm, kit, combo, offer, angle, 1, refine={"ad": ad_content, "instruction": text})
    if not ads:
        raise LLMError("The model returned no ad.")
    fmt = get_format(combo.format_key)
    content = _normalize(ads[0], fmt)
    flags, review_usage = check_ads(llm, kit, [(fmt, content)], third_party, review)
    usage.add(review_usage)
    return GeneratedAd(combo=combo, content=content, flags=flags[0]), usage

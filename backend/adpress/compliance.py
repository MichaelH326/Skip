"""Compliance and quality checks run on every ad before the user sees it (PRD: Compliance checker)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from .formats import FormatSpec
from .kit import REGULATED_INDUSTRIES, Kit
from .llm import LLM, LLMError, Usage

BLOCKING = "blocking"
WARNING = "warning"

# Rule ids, matching the PRD table.
NEVER_WORD = "never_word"
OVER_LIMIT = "over_limit"
UNSUPPORTED_CLAIM = "unsupported_claim"
PROTECTED_TRAIT = "protected_trait"
MISSING_DISCLAIMER = "missing_disclaimer"
SUPERLATIVE = "superlative"
OVER_RECOMMENDED = "over_recommended"
THIRD_PARTY_COPY = "third_party_copy"
OFF_BRAND = "off_brand"
MISSING_FIELD = "missing_field"

RULE_LABELS = {
    NEVER_WORD: "Uses a banned word",
    OVER_LIMIT: "Over the character limit",
    UNSUPPORTED_CLAIM: "Claim not in the brand kit",
    PROTECTED_TRAIT: "Protected-trait language",
    MISSING_DISCLAIMER: "Missing required disclaimer",
    SUPERLATIVE: "Superlative or guarantee",
    OVER_RECOMMENDED: "Longer than recommended",
    THIRD_PARTY_COPY: "Copies third-party text",
    OFF_BRAND: "Off-brand",
    MISSING_FIELD: "Missing field",
}

# Phrases that signal preference or exclusion based on protected traits. Lowercase, matched on word boundaries.
PROTECTED_TERMS: list[str] = [
    # familial status
    "families only", "no children", "no kids", "perfect for families", "family-friendly", "ideal for families",
    "great for kids", "adults only", "singles", "bachelor pad", "empty nesters", "newlyweds", "mature couple",
    # age
    "young professionals", "young couple", "retirees", "seniors only", "millennials", "gen z", "digital native",
    "recent graduate",
    # religion
    "christian", "church nearby", "near churches", "jewish", "muslim", "mosque", "synagogue", "catholic",
    # race / national origin
    "hispanic", "latino", "ethnic", "english speakers only",
    "no immigrants", "american-born",
    # disability
    "able-bodied", "no wheelchairs", "physically fit", "healthy only", "not suitable for handicapped",
    # sex
    "ideal for men", "ideal for women", "perfect for a man", "perfect for a woman", "manpower", "salesman",
    "waitress", "gentlemen's",
    # coded location language
    "exclusive neighborhood", "safe neighborhood", "good neighborhood", "desirable community", "traditional neighborhood",
]

SUPERLATIVES: list[str] = [
    "best", "#1", "number one", "guaranteed", "guarantee", "unbeatable", "lowest price", "cheapest", "perfect",
    "never fail", "risk-free", "100%",
]

_NUMBER_RE = re.compile(r"(?<![\w#])\$?\d[\d,]*(?:\.\d+)?(?:\s?%|\+|k|m)?", re.I)
# Number phrases that are not claims.
_ALLOWED_NUMBER_PHRASES = re.compile(r"\b24/7\b|\b24 hours\b|\b365 days\b", re.I)
_WORD_RE = re.compile(r"[a-z0-9']+")
_SUFFIXES = r"(?:s|es|ed|ing|er|ers|ly)?"


def flag(rule: str, severity: str, message: str, *, field: str | None = None, words: str = "",
         suggestion: str | None = None, source: str = "code") -> dict[str, Any]:
    return {
        "rule": rule,
        "label": RULE_LABELS.get(rule, rule),
        "severity": severity,
        "field": field,
        "words": words,
        "message": message,
        "suggestion": suggestion,
        "source": source,
        "overridden": False,
        "override_reason": None,
    }


def ad_text_parts(content: dict[str, Any]) -> list[tuple[str, str]]:
    """(field, text) pairs for every piece of visible ad text."""
    parts: list[tuple[str, str]] = []
    for key, value in (content.get("fields") or {}).items():
        if isinstance(value, list):
            for i, v in enumerate(value):
                parts.append((f"{key}[{i}]", str(v)))
        elif value:
            parts.append((key, str(value)))
    if content.get("cta"):
        parts.append(("cta", str(content["cta"])))
    for i, tag in enumerate(content.get("hashtags") or []):
        parts.append((f"hashtags[{i}]", str(tag)))
    return parts


def full_text(content: dict[str, Any]) -> str:
    return "\n".join(t for _, t in ad_text_parts(content))


def _term_regex(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")
    if term[-1].isalnum():
        escaped += _SUFFIXES + r"\b"
    prefix = r"\b" if term[0].isalnum() else r"(?<!\w)"
    return re.compile(prefix + escaped, re.I)


def _find_term(term: str, text: str) -> str | None:
    m = _term_regex(term).search(text)
    return m.group(0) if m else None


def _digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", s).rstrip(".")


def kit_number_corpus(kit: Kit) -> set[str]:
    """Numbers the kit supports: facts, offers, location details, disclaimers."""
    texts: list[str] = [f.claim for f in kit.facts]
    for o in kit.offers:
        texts += [o.headline, o.proof, o.cta, o.expires_on or ""]
    for loc in kit.locations:
        texts += [loc.name, loc.phrasing, *loc.references, *loc.seasonal_hooks]
    texts += kit.compliance.required_disclaimers
    numbers: set[str] = set()
    for t in texts:
        for m in _NUMBER_RE.findall(t):
            d = _digits(m)
            if d:
                numbers.add(d)
    return numbers


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    words = _WORD_RE.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _field_spec(fmt: FormatSpec, field_key: str):
    base = field_key.split("[")[0]
    return next((f for f in fmt.fields if f.key == base), None)


def code_checks(content: dict[str, Any], kit: Kit, fmt: FormatSpec, third_party_texts: list[str]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    parts = ad_text_parts(content)
    regulated = kit.compliance.industry in REGULATED_INDUSTRIES
    fields = content.get("fields") or {}

    # Required fields and multi-field counts.
    for spec in fmt.fields:
        value = fields.get(spec.key)
        if spec.multi:
            items = [v for v in (value or []) if str(v).strip()]
            if len(items) < spec.multi.min:
                flags.append(flag(MISSING_FIELD, BLOCKING, f"{spec.label} needs at least {spec.multi.min}, has {len(items)}.",
                                  field=spec.key))
            elif len(items) > spec.multi.max:
                flags.append(flag(OVER_LIMIT, BLOCKING, f"{spec.label} allows at most {spec.multi.max}, has {len(items)}.",
                                  field=spec.key))
        elif not value or not str(value).strip():
            flags.append(flag(MISSING_FIELD, BLOCKING, f"{spec.label} is empty.", field=spec.key))

    # Character limits.
    hashtags = content.get("hashtags") or []
    for field_key, text in parts:
        spec = _field_spec(fmt, field_key)
        if not spec:
            continue
        length = len(text)
        if spec.counts_hashtags and hashtags:
            length += sum(len(h) + 1 for h in hashtags)
        if length > spec.limit:
            flags.append(flag(OVER_LIMIT, BLOCKING, f"{spec.label}: {length} characters, limit {spec.limit}.",
                              field=field_key, words=text))
        elif length > spec.recommended:
            flags.append(flag(OVER_RECOMMENDED, WARNING,
                              f"{spec.label}: {length} characters, {spec.recommended} recommended so it isn't cut off.",
                              field=field_key))
    if len(hashtags) > fmt.max_hashtags:
        flags.append(flag(OVER_RECOMMENDED if fmt.max_hashtags else OVER_LIMIT, WARNING if fmt.max_hashtags else BLOCKING,
                          f"{len(hashtags)} hashtags; this format takes at most {fmt.max_hashtags}.", field="hashtags"))

    # Never-words (exact and stemmed).
    for word in kit.never_words:
        if not word.strip():
            continue
        for field_key, text in parts:
            hit = _find_term(word, text)
            if hit:
                flags.append(flag(NEVER_WORD, BLOCKING, f"\"{hit}\" is on this brand's never-use list.",
                                  field=field_key, words=hit, suggestion=""))
                break

    # Numbers not backed by the kit.
    supported = kit_number_corpus(kit)
    for field_key, text in parts:
        if field_key.startswith("hashtags"):
            continue
        for m in _NUMBER_RE.finditer(_ALLOWED_NUMBER_PHRASES.sub(" ", text)):
            raw = m.group(0).strip()
            d = _digits(raw)
            if d and d not in supported:
                flags.append(flag(UNSUPPORTED_CLAIM, BLOCKING,
                                  f"\"{raw}\" isn't in the brand kit's facts or offers. Add it to the kit or remove it.",
                                  field=field_key, words=raw))

    # Protected-trait and coded language.
    seen_terms: set[str] = set()
    for term in PROTECTED_TERMS:
        for field_key, text in parts:
            hit = _find_term(term, text)
            if hit and hit.lower() not in seen_terms:
                seen_terms.add(hit.lower())
                flags.append(flag(PROTECTED_TRAIT, BLOCKING if regulated else WARNING,
                                  f"\"{hit}\" can signal a preference based on a protected trait."
                                  + (" Not allowed in housing, credit, or employment ads." if regulated else ""),
                                  field=field_key, words=hit, suggestion=""))
                break

    # Required disclaimers (anywhere in the ad).
    text_all = full_text(content).lower()
    for disclaimer in kit.compliance.required_disclaimers:
        if disclaimer.strip() and disclaimer.lower() not in text_all:
            flags.append(flag(MISSING_DISCLAIMER, BLOCKING, f"Must include \"{disclaimer}\".", words=disclaimer))

    # Superlatives and guarantees (skip ones already flagged as never-words).
    never_hits = {f["words"].lower() for f in flags if f["rule"] == NEVER_WORD}
    for term in SUPERLATIVES:
        for field_key, text in parts:
            hit = _find_term(term, text)
            if hit and hit.lower() not in never_hits:
                flags.append(flag(SUPERLATIVE, WARNING, f"\"{hit}\" is a superlative or guarantee that may need proof.",
                                  field=field_key, words=hit))
                break

    # Copy reproduced from pasted third-party text.
    if third_party_texts:
        ad_sh = _shingles(text_all)
        for src in third_party_texts:
            overlap = ad_sh & _shingles(src)
            if overlap:
                sample = " ".join(next(iter(overlap)))
                flags.append(flag(THIRD_PARTY_COPY, BLOCKING,
                                  "Reproduces 8+ words from content the brand doesn't own. Rewrite this passage.",
                                  words=sample))
                break
    return flags


class ReviewIssue(BaseModel):
    ad_index: int
    rule: Literal["unsupported_claim", "protected_trait", "off_brand"]
    words: str
    explanation: str
    suggestion: str


class Review(BaseModel):
    issues: list[ReviewIssue]


REVIEW_SYSTEM = """You review ad copy for Adpress before a marketer sees it. Report only real problems.

Check each ad for:
- unsupported_claim: any statistic, award, review, rating, ranking, or factual claim about the business that is not stated in the brand kit facts or offers. General, unverifiable tone ("friendly service") is fine.
- protected_trait: wording that states or implies a preference for or against people based on race, color, religion, sex, disability, familial status, national origin, or age, including coded phrases. Describing a property, product, or place is fine; describing who should buy or live there is not.
- off_brand: clearly contradicts the brand voice or uses a word from never_words in disguise.

For each problem give the exact words from the ad, a one-sentence explanation, and replacement words that fix it.
Return an empty list when an ad has no problems."""


def llm_review(llm: LLM, kit: Kit, ads: list[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]], Usage]:
    """Review a batch of ads with the smaller model. Returns flags per ad."""
    per_ad: list[list[dict[str, Any]]] = [[] for _ in ads]
    if not ads:
        return per_ad, Usage()
    kit_view = {
        "core_voice": kit.core_voice,
        "never_words": kit.never_words,
        "facts": [f.claim for f in kit.facts],
        "offers": [o.model_dump() for o in kit.offers],
        "industry": kit.compliance.industry,
        "compliance_rules": kit.compliance.rules,
    }
    listing = "\n\n".join(f"<ad index=\"{i}\">\n{full_text(a)}\n</ad>" for i, a in enumerate(ads))
    try:
        result = llm.structured(
            role="check",
            system=[{"type": "text", "text": REVIEW_SYSTEM}],
            content=[{"type": "text", "text": f"Brand kit:\n{json.dumps(kit_view, sort_keys=True)}\n\nAds:\n{listing}"}],
            schema=Review,
            max_tokens=8000,
        )
    except LLMError as e:
        for flags in per_ad:
            flags.append(flag(OFF_BRAND, WARNING, f"The automated review could not run: {e}. Review this ad manually.",
                              source="review"))
        return per_ad, Usage()
    regulated = kit.compliance.industry in REGULATED_INDUSTRIES
    for issue in result.parsed.issues:
        if not 0 <= issue.ad_index < len(ads):
            continue
        text = full_text(ads[issue.ad_index])
        # Ignore issues that quote words not actually in the ad.
        if issue.words and issue.words.lower() not in text.lower():
            continue
        severity = BLOCKING if issue.rule == "unsupported_claim" or (issue.rule == "protected_trait" and regulated) else WARNING
        field_key = next((k for k, t in ad_text_parts(ads[issue.ad_index]) if issue.words and issue.words.lower() in t.lower()), None)
        per_ad[issue.ad_index].append(
            flag(issue.rule, severity, issue.explanation, field=field_key, words=issue.words,
                 suggestion=issue.suggestion, source="review")
        )
    return per_ad, result.usage


def merge_flags(code: list[dict[str, Any]], review: list[dict[str, Any]], previous: list[dict[str, Any]] | None = None
                ) -> list[dict[str, Any]]:
    """Combine code and review flags, dropping review duplicates and carrying over prior overrides."""
    out = list(code)
    code_keys = {(f["rule"], f["words"].lower()) for f in code}
    for f in review:
        if (f["rule"], f["words"].lower()) not in code_keys:
            out.append(f)
    if previous:
        overrides = {(f["rule"], f["words"].lower()): f for f in previous if f.get("overridden")}
        for f in out:
            prev = overrides.get((f["rule"], f["words"].lower()))
            if prev:
                f["overridden"] = True
                f["override_reason"] = prev.get("override_reason")
    return out


def blocking_open(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in flags if f["severity"] == BLOCKING and not f.get("overridden")]

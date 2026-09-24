"""Brand kit as a portable markdown file (PRD: Export kit as .md).

The readable sections work in any AI tool. The trailing JSON block lets Adpress re-import the exact kit.
"""

from __future__ import annotations

import json
import re

from .kit import Kit

MARKER = "adpress-kit"


def _list(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none)"


def to_markdown(kit: Kit) -> str:
    d = kit.voice_dials
    out: list[str] = [f"# {kit.name} — Brand kit", ""]
    out += ["Use this kit whenever writing marketing copy for this brand. Follow every rule in it.", ""]

    out += ["## Voice", "", kit.core_voice or "(not set)", ""]
    out += ["Voice dials (1 = low, 5 = high):", ""]
    out += [f"- Formal: {d.formal}", f"- Playful: {d.playful}", f"- Bold: {d.bold}",
            f"- Technical: {d.technical}", f"- Warm: {d.warm}", ""]

    out += ["## Words", "", "Always use:", "", _list(kit.always_words), "", "Never use:", "", _list(kit.never_words), ""]

    out += ["## Facts", "", "The only facts, numbers, and claims ads may use.", ""]
    out += [f"- {f.claim}" + (f" ([source]({f.source_url}))" if f.source_url else "") for f in kit.facts] or ["- (none)"]
    out += [""]

    out += ["## Colors", ""]
    out += [f"- {c.role}: {c.hex}" for c in kit.colors] or ["- (none)"]
    out += ["", "## Typography", "", f"- Headings: {kit.typography.heading or '(not set)'}",
            f"- Body: {kit.typography.body or '(not set)'}", ""]

    c = kit.compliance
    out += ["## Compliance", "", f"- Industry: {c.industry}",
            f"- Special ad category required: {'yes' if c.special_ad_category else 'no'}"]
    out += [f"- Required disclaimer: \"{x}\"" for x in c.required_disclaimers]
    out += [f"- Rule: {r}" for r in c.rules]
    out += [""]

    out += ["## Platforms", ""]
    for platform, t in sorted(kit.platform_themes.items()):
        out += [f"### {platform}", "", f"- Audience: {t.audience}", f"- Voice shift: {t.voice_shift}",
                f"- Length: {t.length}", f"- Hashtags: {t.hashtags}", f"- Emoji: {t.emoji}",
                f"- CTA style: {t.cta_style}"]
        if t.colors:
            out.append(f"- Colors: {', '.join(t.colors)}")
        out.append("")
    if not kit.platform_themes:
        out += ["(none)", ""]

    out += ["## Audiences", ""]
    for a in kit.audiences:
        out += [f"### {a.name}", "", a.who, "", f"- Goals: {'; '.join(a.goals)}",
                f"- Objections: {'; '.join(a.objections)}", f"- Key message: {a.key_message}",
                f"- Best platforms: {', '.join(a.best_platforms)}", f"- CTAs: {'; '.join(a.ctas)}", ""]
    if not kit.audiences:
        out += ["(none)", ""]

    out += ["## Locations", ""]
    for loc in kit.locations:
        out += [f"### {loc.name}", "", f"- References: {'; '.join(loc.references)}", f"- Phrasing: {loc.phrasing}",
                f"- Seasonal hooks: {'; '.join(loc.seasonal_hooks)}", f"- Avoid: {'; '.join(loc.avoid)}", ""]
    if not kit.locations:
        out += ["(none)", ""]

    out += ["## Offers", ""]
    for o in kit.offers:
        out += [f"### {o.headline}", "", f"- Proof: {o.proof}", f"- CTA: {o.cta}",
                f"- Expires: {o.expires_on or 'no expiry'}", ""]
    if not kit.offers:
        out += ["(none)", ""]

    out += ["## Examples", ""]
    for e in kit.examples:
        out += [f"- ({e.rating}, {e.platform or 'any platform'}) {e.text}"]
    if not kit.examples:
        out += ["(none)"]
    out += [""]

    data = kit.model_dump(exclude={"guessed"})
    out += ["## Machine-readable kit", "", f"```json {MARKER}", json.dumps(data, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(out)


_BLOCK_RE = re.compile(r"```json " + MARKER + r"\n(.*?)\n```", re.S)


def from_markdown(text: str) -> Kit:
    m = _BLOCK_RE.search(text)
    if not m:
        raise ValueError("This file has no Adpress kit block. Export a kit from Adpress to get a file you can import.")
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"The kit block is not valid JSON: {e}") from e
    return Kit.model_validate(data)

import os
import re

os.environ.setdefault("ADPRESS_PBKDF2_ITERATIONS", "1000")
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("ADPRESS_FRONTEND_DIST", "/nonexistent")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from adpress import db as dbmod  # noqa: E402
from adpress.llm import LLMResult, Usage, set_llm  # noqa: E402


class FakeLLM:
    """Deterministic stand-in for Claude. Builds answers from the requested schema."""

    def __init__(self):
        self.calls = []
        self.review_issues = []
        self.ad_text = "Find your next home in {loc} with Harbor Realty. Equal Housing Opportunity"

    def structured(self, *, role, system, content, schema, max_tokens=16000):
        self.calls.append({"role": role, "schema": schema.__name__, "system": system, "content": content})
        name = schema.__name__
        text = "\n".join(c["text"] for c in content)
        if name == "KitDraft":
            parsed = schema.model_validate({
                "core_voice": "Warm, local, plain-spoken experts.",
                "voice_dials": {"formal": 2, "playful": 2, "bold": 3, "technical": 2, "warm": 5},
                "always_words": ["neighbors", "home"],
                "never_words": ["cheap"],
                "facts": [{"claim": "Serving Tacoma since 2004", "source_url": "https://harbor.example/about"}],
                "colors": [{"hex": "#0B3D5C", "role": "primary"}, {"hex": "#123456", "role": "accent"}],
                "audiences": [{"name": "First-time buyers", "who": "Renters ready to buy", "goals": ["Own a home"],
                               "objections": ["Costs"], "key_message": "We walk you through it",
                               "best_platforms": ["facebook"], "ctas": ["Book a call"]}],
                "platform_themes": [{"platform": "facebook", "audience": "locals", "voice_shift": "friendly",
                                     "length": "short", "hashtags": "few", "emoji": "rare", "cta_style": "soft"}],
                "guesses": [{"field": "core_voice", "reason": "From the About page"}],
            })
        elif name.startswith("Batch_"):
            m = re.search(r"Write exactly (\d+) ads", text)
            n = int(m.group(1)) if m else 1
            loc = re.search(r'"name": "([^"]+)"', text.split("Location:")[1].split("\n")[0]) if "Location:" in text else None
            ad_model = schema.model_fields["ads"].annotation.__args__[0]
            fields_model = ad_model.model_fields["fields"].annotation
            ads = []
            for i in range(n):
                body = self.ad_text.format(loc=loc.group(1) if loc else "town") + f" #{i}"
                fields = {}
                for key, info in fields_model.model_fields.items():
                    if info.annotation == list[str]:
                        count = 3 if key == "headlines" else 2
                        fields[key] = [f"Harbor home {j}"[:30] for j in range(count)] if key == "headlines" else \
                                      ["Local agents. Equal Housing Opportunity"] * count
                    else:
                        fields[key] = body if key not in ("headline", "short_headline", "card_headline", "description") \
                            else "Harbor Realty"
                ads.append({"fields": fields, "cta": "Learn more", "hashtags": ["tacoma"], "image_direction": "A porch",
                            "angle": f"angle {i}", "facts_used": []})
            parsed = schema.model_validate({"ads": ads})
        elif name == "Review":
            parsed = schema.model_validate({"issues": self.review_issues})
        else:
            raise AssertionError(f"unexpected schema {name}")
        return LLMResult(parsed=parsed, usage=Usage(model="fake", tokens_in=100, tokens_out=50, cost_usd=0.001))


@pytest.fixture
def fake_llm():
    llm = FakeLLM()
    set_llm(llm)
    yield llm
    set_llm(None)


@pytest.fixture
def client(fake_llm):
    dbmod.configure("sqlite://")
    from adpress.main import app

    with TestClient(app) as c:
        yield c


def signup(client, email="owner@example.com", workspace="Harbor"):
    r = client.post("/api/auth/signup", json={"email": email, "password": "password123", "workspace_name": workspace})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}

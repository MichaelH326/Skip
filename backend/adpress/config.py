"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./adpress.db"))
    # Model that writes kits and ads, and the smaller model that reviews them.
    write_model: str = field(default_factory=lambda: _env("ADPRESS_WRITE_MODEL", "claude-opus-5"))
    check_model: str = field(default_factory=lambda: _env("ADPRESS_CHECK_MODEL", "claude-haiku-4-5"))
    # Effort for the write model. Generation is latency-sensitive (PRD: 10 ads < 20 s median).
    write_effort: str = field(default_factory=lambda: _env("ADPRESS_WRITE_EFFORT", "medium"))
    # Set to "0" to disable the LLM review pass (code checks still run).
    llm_review: bool = field(default_factory=lambda: _env("ADPRESS_LLM_REVIEW", "1") != "0")
    fetch_max_pages: int = field(default_factory=lambda: int(_env("ADPRESS_FETCH_MAX_PAGES", "10")))
    fetch_timeout_s: float = field(default_factory=lambda: float(_env("ADPRESS_FETCH_TIMEOUT", "30")))
    # Allow fetching private/loopback addresses. Only for local development and tests.
    fetch_allow_private: bool = field(default_factory=lambda: _env("ADPRESS_FETCH_ALLOW_PRIVATE", "0") == "1")
    user_agent: str = field(
        default_factory=lambda: _env("ADPRESS_USER_AGENT", "AdpressBot/1.0 (+https://adpress.app/bot)")
    )
    token_ttl_days: int = field(default_factory=lambda: int(_env("ADPRESS_TOKEN_TTL_DAYS", "30")))
    max_generation_pairs: int = 50
    max_ads_per_request: int = 200
    daily_cost_alert_usd_per_ad: float = 0.03
    frontend_dist: str = field(
        default_factory=lambda: _env(
            "ADPRESS_FRONTEND_DIST",
            os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
        )
    )


settings = Settings()

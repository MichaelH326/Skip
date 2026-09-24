# Adpress

Adpress turns a company's website and social posts into a reusable brand kit, then writes on-brand ads for each platform and market. Every ad is checked for brand and compliance problems before anyone sees it.

This is the v1 (MVP) build of the Adpress PRD: every P0 feature, plus matrix generation, multiple brands, refine/regenerate, and the approval workflow from P1.

## What it does

1. **Set up a brand.** Enter a website. Adpress reads up to 10 public pages and pulls out copy, colors and fonts. Paste a bio and up to 10 posts per platform (Facebook, Instagram, LinkedIn, Google, X).
2. **Build the kit.** Claude drafts the voice, voice dials, always/never words, facts, color roles, audiences and platform themes. Every inferred field is marked as a guess, with a reason. Ads can't be generated until someone reviews each guess.
3. **Generate.** Pick formats, audiences, locations, an offer, an angle and a count (1–20). Adpress runs every format × audience × location combination, capped at 50 combinations and 200 ads per run.
4. **Check.** Code checks run on every ad: character limits, never-words (including word forms), numbers not in the kit, protected-trait language, required disclaimers, superlatives, and text copied from third-party sources. A smaller model then reviews each ad for unsupported claims, coded language and off-brand copy.
5. **Review and export.** Each ad shows in a mock of its platform. Users can edit it with live character counts, apply a suggested fix in one click, refine it ("shorter", "more local", or a custom instruction), or approve it. Owners can override a blocking flag with a reason, and every override is logged. Approved ads export as a CSV per platform for bulk upload.

The kit also exports as a markdown file that works in any AI tool. That file can be imported back into Adpress.

## Run it

### Docker (Postgres)

```bash
cp .env.example .env        # set ANTHROPIC_API_KEY
docker compose up --build
```

Open http://localhost:8000 and create a workspace.

### Local development

```bash
# API (SQLite by default)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export ANTHROPIC_API_KEY=...
uvicorn adpress.main:app --reload

# Frontend (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

### Tests

```bash
cd backend && python -m pytest -q     # uses a fake LLM; no API key needed
cd frontend && npm run build          # type-checks and builds
```

## Configuration

All settings are environment variables. See `.env.example` for the full list.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | none | Claude API key (required) |
| `DATABASE_URL` | `sqlite:///./adpress.db` | Postgres in production |
| `ADPRESS_WRITE_MODEL` | `claude-opus-5` | Writes kits and ads |
| `ADPRESS_CHECK_MODEL` | `claude-haiku-4-5` | Reviews ads |
| `ADPRESS_WRITE_EFFORT` | `medium` | Write-model effort: `low` to `max`. `medium` targets the PRD's 20-second goal for 10 ads |
| `ADPRESS_LLM_REVIEW` | `1` | Set `0` to skip the AI review pass |

## How it's built

```
backend/adpress/
  main.py          HTTP API (FastAPI) and static frontend
  models.py        Tables: workspaces, users, brands, kit versions, sources, requests, ads, jobs, audit log, events
  kit.py           Brand kit schema and industry defaults (never-words, disclaimers, rules)
  fetcher.py       Website import: same-site crawl, robots.txt, private-network (SSRF) protection
  kit_builder.py   AI kit builder
  generation.py    Prompt assembly (cache-friendly order), fan-out, refine
  compliance.py    Code checks and the AI review pass
  formats.json     Platforms, formats, character limits (config, not code)
  exporter.py      Per-platform CSV
  kit_markdown.py  Kit to markdown and back
  llm.py           Claude API wrapper: structured outputs, retries, refusal fallback, cost tracking
frontend/src/      React app: setup, kit editor, generate, ads review
```

- **Claude calls** use structured outputs (Pydantic schemas), so every response is validated JSON. The write model uses adaptive thinking and server-side refusal fallbacks. Prompts are ordered so that the fixed rules, the kit and the format block are prompt-cached across requests.
- **Kits** are immutable versions. Every ad records the request and the kit version it was written from. Kit saves check the version they started from, so one person's edits can't silently overwrite another's.
- **Long work** (website import, kit build, generation) runs as a background job that the UI polls.
- **Roles:** Owner (everything, including overrides and deletes), Editor (create and edit), Viewer (read only). All data is scoped to the workspace.
- **Instrumentation:** the product events from the PRD are stored in `events`. The per-brand metrics endpoint reports ads kept without edits, ads kept after light edits, flags per 100 ads, and cost per ad.

## Before launch

- **Platform specs.** Character limits in `formats.json` and CSV column names in `exporter.py` are approximate. Check them against each platform's current ad specs and bulk-upload templates.
- **Legal review.** Have fair-housing counsel review the protected-trait word list in `compliance.py` and a sample of generated ads.
- **Accounts.** Sign-in is email + password with bearer tokens. The PRD calls for SSO or magic links, and teammates are added by an owner with a temporary password. Put a password-reset email flow in place before a public launch.
- **Database migrations.** Tables are created on startup. Add Alembic before the first schema change in production.
- **Background jobs.** Jobs run in the web process. At higher volume, move them to a queue (e.g. RQ or Celery) so that a restart can't drop a running job.

# Outbounder

Paste a rough list of people; get back a table that has already done the legwork:
who they actually are (LinkedIn, confirmed title/company, location), working email
candidates with confidence + verification status, a short research brief (bio, company,
recent news, hooks, talking points) and a row of useful links. You write the emails.

Part of the InfiniSaaS umbrella.

## How a row gets enriched

1. **Parse** — the pasted blob goes through the LLM and becomes rows
   (`name / company / title / hints`). Heuristic line parser when no LLM key.
2. **Identify** — Exa searches (LinkedIn, company site, general) → LLM picks the right
   person, confirms title/company, and returns the corporate email domain. LinkedIn URLs
   are only accepted if they appear verbatim in results.
3. **Emails** — web evidence (`"Name" "@domain"`), colleague addresses to infer the company
   pattern, optional Hunter.io, then name permutations ranked by prior × pattern match.
   MX lookup + SMTP `RCPT TO` probe (catch-all detection) when port 25 is reachable.
4. **Research** — Exa (person + company news, homepage via Firecrawl) → LLM brief keyed to
   the list's *context* (what you're reaching out about).
5. **Links** — LinkedIn, company site, Google/Google News/X/Crunchbase searches, and the
   articles that were actually found.

Rows are processed by an in-process queue (claimed with `SKIP LOCKED`, 3 concurrent).
Everything is saved stage-by-stage so the table fills in live.

## Local dev

```sh
cp .env.example .env          # set DATABASE_URL and provider keys
uv sync
uv run uvicorn src.main:app --reload   # init.sql is applied automatically on startup
```

Open http://localhost:8000. With no provider keys the app runs in mock mode (heuristic
parse, no lookups) so the UI can still be exercised.

## Deploy (Railway)

1. Create a Postgres database; set `DATABASE_URL` on the service.
2. Set `APP_PASSWORD` (shared password gate), `ANTHROPIC_API_KEY`, `EXA_API_KEY`,
   optionally `FIRECRAWL_API_KEY`, `HUNTER_API_KEY`.
3. Deploy with the Dockerfile (`railway.toml` handles the healthcheck).

## Lint / test

```sh
uv run ruff check .
uv run pytest
```

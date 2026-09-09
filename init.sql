-- Idempotent schema; applied on every startup.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS lists (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    raw_input   text NOT NULL DEFAULT '',
    context     text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'ready',   -- parsing | ready | error
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS targets (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    list_id             uuid NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    position            integer NOT NULL DEFAULT 0,
    raw_line            text NOT NULL DEFAULT '',

    -- from the parse step
    name                text NOT NULL DEFAULT '',
    company             text NOT NULL DEFAULT '',
    title               text NOT NULL DEFAULT '',
    hints               text NOT NULL DEFAULT '',

    -- pipeline
    status              text NOT NULL DEFAULT 'queued', -- queued | identifying | finding_email | researching | done | error
    stage_started_at    timestamptz,
    error               text,
    attempts            integer NOT NULL DEFAULT 0,

    -- identify
    linkedin_url        text,
    company_domain      text,
    company_url         text,
    location            text,
    confirmed_name      text,
    confirmed_title     text,
    confirmed_company   text,
    identity_confidence real,
    identity_notes      text,

    -- emails: [{email, confidence, source, checks: {...}}]
    emails              jsonb NOT NULL DEFAULT '[]'::jsonb,
    best_email          text,
    email_pattern       text,
    domain_checks       jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- research: {bio, company_summary, recent: [{text, url, date}], hooks: [...], talking_points: [...]}
    research            jsonb NOT NULL DEFAULT '{}'::jsonb,
    links               jsonb NOT NULL DEFAULT '[]'::jsonb,
    sources             jsonb NOT NULL DEFAULT '[]'::jsonb,

    -- mine
    outreach_status     text NOT NULL DEFAULT 'todo', -- todo | drafted | sent | replied | skip
    notes               text NOT NULL DEFAULT '',

    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    enriched_at         timestamptz
);

CREATE INDEX IF NOT EXISTS targets_list_idx ON targets(list_id, position);
CREATE INDEX IF NOT EXISTS targets_status_idx ON targets(status) WHERE status = 'queued';

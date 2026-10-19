-- 0002_episodes_jobs: Phase 3 content pipeline schema (ADR-009).
-- episodes: one short-form vertical video unit per row. The pipeline
-- progresses the status forward: draft -> scripted -> ... -> published.
CREATE TABLE episodes (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    topic         TEXT NOT NULL,
    channel       TEXT NOT NULL DEFAULT 'default',
    status        TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','scripted','storyboarded','rendered','published','failed','cancelled')),
    script_text   TEXT,
    script_method TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_episodes_status  ON episodes(status);
CREATE INDEX idx_episodes_channel ON episodes(channel);

-- jobs: durable queue rows. The queue survives restarts because state
-- lives here, not in memory (ADR-009). Types are NOT constrained by a
-- CHECK: the handler registry in laf.jobs.handlers is the source of
-- truth, so new job types can ship without schema migrations.
CREATE TABLE jobs (
    id              INTEGER PRIMARY KEY,
    type            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    priority        INTEGER NOT NULL DEFAULT 100,
    gpu             INTEGER NOT NULL DEFAULT 0,
    payload         TEXT NOT NULL DEFAULT '{}',
    result          TEXT,
    error           TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    run_after       TEXT,
    idempotency_key TEXT,
    episode_id      INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
    worker_id       TEXT,
    heartbeat_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at      TEXT,
    finished_at     TEXT
);

CREATE INDEX idx_jobs_status  ON jobs(status);
CREATE INDEX idx_jobs_episode ON jobs(episode_id);
-- Plain UNIQUE index: SQLite treats NULLs as distinct, so un-keyed
-- enqueues are unlimited while keyed ones deduplicate exactly once.
CREATE UNIQUE INDEX idx_jobs_idem ON jobs(idempotency_key);

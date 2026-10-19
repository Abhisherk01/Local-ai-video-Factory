-- 0001_initial: Phase 2 baseline schema.
-- Key/value app settings (wizard state, user preferences).
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Single-row marker recording when the schema was first created.
CREATE TABLE IF NOT EXISTS schema_info (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version INTEGER NOT NULL,
    initialized_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT OR IGNORE INTO schema_info (id, schema_version) VALUES (1, 1);

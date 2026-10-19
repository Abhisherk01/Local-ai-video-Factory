-- 0003_storyboards_styles_series: Phase 4 content model.
-- styles: named visual styles that seed scene visual prompts (ADR-011).
-- Builtin rows are seeded here with INSERT OR IGNORE so re-running is
-- impossible anyway (migrations apply once) and fresh databases always
-- start with a usable registry.
CREATE TABLE styles (
    id            INTEGER PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE
                  CHECK (slug GLOB '[a-z0-9_]*'),
    name          TEXT NOT NULL,
    prompt_prefix TEXT NOT NULL DEFAULT '',
    prompt_suffix TEXT NOT NULL DEFAULT '',
    is_builtin    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT OR IGNORE INTO styles (slug, name, prompt_prefix, prompt_suffix, is_builtin) VALUES
    ('dark_cinematic',   'Dark Cinematic',     'dark cinematic lighting, moody atmosphere, high contrast, shallow depth of field, ', 'photorealistic, 9:16 vertical composition', 1),
    ('clean_product',    'Clean Product',      'bright studio lighting, minimal seamless background, crisp product focus, ',        'photorealistic, 9:16 vertical composition', 1),
    ('warm_documentary', 'Warm Documentary',   'warm natural light, candid handheld realism, filmic texture, ',                     'photorealistic, 9:16 vertical composition', 1),
    ('bold_motion',      'Bold Motion',        'flat vector shapes, bold typography, high saturation, kinetic composition, ',       'graphic design style, 9:16 vertical composition', 1),
    ('retro_analog',     'Retro Analog',       '35mm film grain, vintage color grade, soft halation, ',                             'photorealistic, 9:16 vertical composition', 1),
    ('minimal_mono',     'Minimal Monochrome', 'black and white, minimalist composition, generous negative space, ',                'high contrast, 9:16 vertical composition', 1);

-- storyboards: one per episode (latest wins; re-planning replaces).
CREATE TABLE storyboards (
    id               INTEGER PRIMARY KEY,
    episode_id       INTEGER NOT NULL UNIQUE
                     REFERENCES episodes(id) ON DELETE CASCADE,
    style_slug       TEXT NOT NULL,
    method           TEXT,
    scene_count      INTEGER NOT NULL DEFAULT 0,
    total_duration_s REAL NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_storyboards_episode ON storyboards(episode_id);

-- storyboard_scenes: ordered per-scene narration slices + visual prompts.
-- Scene rows are what later render phases consume one by one.
CREATE TABLE storyboard_scenes (
    id            INTEGER PRIMARY KEY,
    storyboard_id INTEGER NOT NULL
                  REFERENCES storyboards(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    narration     TEXT NOT NULL DEFAULT '',
    visual_prompt TEXT NOT NULL DEFAULT '',
    duration_s    REAL NOT NULL DEFAULT 0,
    UNIQUE (storyboard_id, idx)
);

-- series: one premise -> many episode stubs (ADR-011 duplicate policy).
CREATE TABLE series (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    premise         TEXT NOT NULL,
    requested_count INTEGER NOT NULL DEFAULT 20,
    method          TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

ALTER TABLE episodes ADD COLUMN series_id INTEGER REFERENCES series(id) ON DELETE SET NULL;
CREATE INDEX idx_episodes_series ON episodes(series_id);

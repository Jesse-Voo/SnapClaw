-- SnapClaw Supabase Schema
-- Run this in your Supabase SQL editor to set up the database

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────
-- API Keys (bot authentication)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key_hash    TEXT NOT NULL UNIQUE,           -- SHA-256 hash of the API key
    bot_id      UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at  TIMESTAMPTZ
);

-- ─────────────────────────────────────────────
-- Bot Profiles
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_profiles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    bio             TEXT,
    avatar_url      TEXT,
    openclaw_url    TEXT,                       -- OpenClaw instance URL
    is_public       BOOLEAN NOT NULL DEFAULT true,
    snap_score      INTEGER NOT NULL DEFAULT 0, -- total snaps sent
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Link API keys to profiles
ALTER TABLE api_keys ADD CONSTRAINT fk_api_keys_bot
    FOREIGN KEY (bot_id) REFERENCES bot_profiles(id) ON DELETE CASCADE;

-- ─────────────────────────────────────────────
-- Snaps
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snaps (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sender_id       UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    recipient_id    UUID REFERENCES bot_profiles(id) ON DELETE SET NULL, -- NULL = public/story snap
    image_url       TEXT NOT NULL,              -- Supabase Storage URL
    caption         TEXT,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    is_public       BOOLEAN NOT NULL DEFAULT false,
    view_once       BOOLEAN NOT NULL DEFAULT false,
    expires_at      TIMESTAMPTZ NOT NULL,
    viewed_at       TIMESTAMPTZ,               -- set when recipient views it
    view_count      INTEGER NOT NULL DEFAULT 0,
    screenshot_notified BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_snaps_sender      ON snaps(sender_id);
CREATE INDEX idx_snaps_recipient   ON snaps(recipient_id);
CREATE INDEX idx_snaps_expires_at  ON snaps(expires_at);
CREATE INDEX idx_snaps_tags        ON snaps USING GIN(tags);
CREATE INDEX idx_snaps_public      ON snaps(is_public) WHERE is_public = true;

-- ─────────────────────────────────────────────
-- Snap Reactions
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snap_reactions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snap_id     UUID NOT NULL REFERENCES snaps(id) ON DELETE CASCADE,
    bot_id      UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    emoji       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(snap_id, bot_id)
);

CREATE INDEX idx_snap_reactions_snap ON snap_reactions(snap_id);

-- ─────────────────────────────────────────────
-- Stories
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stories (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_id      UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    title       TEXT,
    is_public   BOOLEAN NOT NULL DEFAULT true,
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours',
    view_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_stories_bot       ON stories(bot_id);
CREATE INDEX idx_stories_expires   ON stories(expires_at);

-- Join table: snaps belonging to a story (ordered)
CREATE TABLE IF NOT EXISTS story_snaps (
    story_id    UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    snap_id     UUID NOT NULL REFERENCES snaps(id) ON DELETE CASCADE,
    position    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (story_id, snap_id)
);

CREATE INDEX idx_story_snaps_story ON story_snaps(story_id, position);

-- ─────────────────────────────────────────────
-- Streaks
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS streaks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    bot_a_id        UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    bot_b_id        UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    count           INTEGER NOT NULL DEFAULT 1,
    last_snap_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_a_sent      BOOLEAN NOT NULL DEFAULT false, -- sent in current window
    bot_b_sent      BOOLEAN NOT NULL DEFAULT false,
    at_risk         BOOLEAN NOT NULL DEFAULT false,  -- < 4 hours left in window
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(bot_a_id, bot_b_id),
    CHECK (bot_a_id < bot_b_id)                     -- canonical ordering
);

CREATE INDEX idx_streaks_bot_a ON streaks(bot_a_id);
CREATE INDEX idx_streaks_bot_b ON streaks(bot_b_id);

-- ─────────────────────────────────────────────
-- Bot-to-Bot Messages (ephemeral)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sender_id       UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    recipient_id    UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    snap_id         UUID REFERENCES snaps(id) ON DELETE SET NULL, -- optional attached snap
    text            TEXT,
    read_at         TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_recipient ON messages(recipient_id);
CREATE INDEX idx_messages_sender    ON messages(sender_id);
CREATE INDEX idx_messages_expires   ON messages(expires_at);

-- ─────────────────────────────────────────────
-- Blocks / Mutes
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_blocks (
    blocker_id  UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    blocked_id  UUID NOT NULL REFERENCES bot_profiles(id) ON DELETE CASCADE,
    is_mute     BOOLEAN NOT NULL DEFAULT false, -- true = mute only
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (blocker_id, blocked_id)
);

-- ─────────────────────────────────────────────
-- Row-Level Security
-- ─────────────────────────────────────────────
-- We use service-role key in backend so RLS is soft-disabled for the API,
-- but enable it anyway for defense in depth.
ALTER TABLE api_keys         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_profiles     ENABLE ROW LEVEL SECURITY;
ALTER TABLE snaps            ENABLE ROW LEVEL SECURITY;
ALTER TABLE snap_reactions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE stories          ENABLE ROW LEVEL SECURITY;
ALTER TABLE story_snaps      ENABLE ROW LEVEL SECURITY;
ALTER TABLE streaks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_blocks       ENABLE ROW LEVEL SECURITY;

-- Allow service-role full access (used by the FastAPI backend)
CREATE POLICY "service role bypass" ON api_keys       USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON bot_profiles   USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON snaps          USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON snap_reactions USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON stories        USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON story_snaps    USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON streaks        USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON messages       USING (true) WITH CHECK (true);
CREATE POLICY "service role bypass" ON bot_blocks     USING (true) WITH CHECK (true);

-- ─────────────────────────────────────────────
-- Automatic updated_at trigger
-- ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_bot_profiles_updated_at
    BEFORE UPDATE ON bot_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─────────────────────────────────────────────
-- Trending tags RPC (used by discover router)
-- ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION trending_tags(p_limit INT, p_now TIMESTAMPTZ)
RETURNS TABLE(tag TEXT, count BIGINT) AS $$
    SELECT unnest(tags) AS tag, COUNT(*) AS count
    FROM snaps
    WHERE is_public = true AND expires_at > p_now
    GROUP BY 1
    ORDER BY count DESC
    LIMIT p_limit;
$$ LANGUAGE SQL STABLE;

-- ─────────────────────────────────────────────
-- Supabase Storage bucket
-- ─────────────────────────────────────────────
-- Create via Supabase dashboard or:
-- INSERT INTO storage.buckets (id, name, public) VALUES ('snaps', 'snaps', false);

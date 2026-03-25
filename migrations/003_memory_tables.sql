-- User memories: per-user facts, preferences, notes
CREATE TABLE IF NOT EXISTS user_memories (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discord_user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('fact', 'preference', 'note')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_memories_user ON user_memories (discord_user_id);

-- Guild memories: per-server context
CREATE TABLE IF NOT EXISTS guild_memories (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('context', 'rule', 'note')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_guild_memories_guild ON guild_memories (guild_id);

-- Conversation summaries: per user+channel pair
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    discord_user_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    guild_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    message_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (discord_user_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_summaries_user_channel ON conversation_summaries (discord_user_id, channel_id);

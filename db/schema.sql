CREATE TABLE IF NOT EXISTS teams (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id          INTEGER NOT NULL,
    channel_id        INTEGER NOT NULL UNIQUE,          -- 채널 1개 = 팀 1개
    name              TEXT    NOT NULL,
    start_date        TEXT    NOT NULL,                 -- UTC ISO
    end_date          TEXT    NOT NULL,                 -- /데모 마감으로 바뀔 수 있음
    orig_end_date     TEXT    NOT NULL,                 -- 데모 초기화 때 복원용
    demo_speed        REAL    NOT NULL DEFAULT 1.0,
    demo_offset_hours REAL    NOT NULL DEFAULT 0.0,
    ai_enabled        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    team_id         INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL,
    display_name    TEXT    NOT NULL DEFAULT '',
    joined_at       TEXT    NOT NULL,
    last_suggest_at TEXT,
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS mascots (
    team_id          INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
    hp               REAL    NOT NULL DEFAULT 100,
    skin_level       INTEGER NOT NULL DEFAULT 1,
    revive_count     INTEGER NOT NULL DEFAULT 0,
    acceptance_since TEXT,
    speed_tier       REAL    NOT NULL DEFAULT 1.0,
    last_action_at   TEXT,
    last_decay_at    TEXT    NOT NULL,
    last_nag_at      TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL,
    kind       TEXT    NOT NULL,
    content    TEXT    NOT NULL DEFAULT '',
    hp_delta   REAL    NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_kind_time ON actions (team_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_actions_user ON actions (team_id, user_id, kind, created_at);

CREATE TABLE IF NOT EXISTS classifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    message_id  INTEGER NOT NULL,
    author_id   INTEGER NOT NULL,
    intents     TEXT    NOT NULL,          -- 쉼표 구분 (예: 'chitchat')
    source      TEXT    NOT NULL,          -- 'A', 'B', 'C'
    confidence  REAL    NOT NULL DEFAULT 1.0,
    matched     TEXT,                      -- 일치한 규칙 이름 (메시지 내용은 저장하지 않는다)
    offered     INTEGER NOT NULL DEFAULT 0,
    accepted    INTEGER,                   -- 제안 버튼을 눌렀는지 (NULL = 해당 없음)
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_class_team_time ON classifications (team_id, created_at);

CREATE TABLE IF NOT EXISTS stuck_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id      INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    requester_id INTEGER NOT NULL,
    content      TEXT    NOT NULL,
    helper_id    INTEGER,
    status       TEXT    NOT NULL DEFAULT 'open',      -- 'open' | 'helped'
    message_id   INTEGER,
    created_at   TEXT    NOT NULL,
    resolved_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_stuck_team ON stuck_requests (team_id, status);

CREATE TABLE IF NOT EXISTS votes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id        INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    creator_id     INTEGER NOT NULL,
    title          TEXT    NOT NULL,
    options        TEXT    NOT NULL,                 -- JSON 배열
    allow_multiple INTEGER NOT NULL DEFAULT 0,
    message_id     INTEGER,
    deadline       TEXT    NOT NULL,                 -- UTC ISO (실제 시각)
    closed         INTEGER NOT NULL DEFAULT 0,
    all_awarded    INTEGER NOT NULL DEFAULT 0,       -- 전원 투표 보너스를 이미 줬는지
    created_at     TEXT    NOT NULL,
    closed_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_votes_open ON votes (closed, deadline);

CREATE TABLE IF NOT EXISTS vote_responses (
    vote_id      INTEGER NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL,
    option_index INTEGER NOT NULL,
    PRIMARY KEY (vote_id, user_id, option_index)
);
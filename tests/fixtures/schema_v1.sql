-- Reconstruído a partir das seções 11–12 do PDF v1.1.
-- O anexo SQL original não foi fornecido. Schema inicial, sem migrações ainda.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    created_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'finished')),
    CHECK (finished_at IS NULL OR finished_at >= created_at),
    CHECK (
        (status = 'finished' AND finished_at IS NOT NULL)
        OR (status IN ('running', 'paused') AND finished_at IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS study_intervals (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    started_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL CHECK (last_seen_at >= started_at),
    ended_at INTEGER,
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CHECK (ended_at IS NULL OR last_seen_at <= ended_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_unfinished_session
    ON sessions((1)) WHERE status IN ('running', 'paused');
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_interval_per_session
    ON study_intervals(session_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_intervals_session_started
    ON study_intervals(session_id, started_at);
CREATE INDEX IF NOT EXISTS ix_intervals_started_at
    ON study_intervals(started_at);

CREATE TRIGGER IF NOT EXISTS validate_session_status_transition
BEFORE UPDATE OF status ON sessions
BEGIN
    SELECT CASE
        WHEN NEW.status = 'running' AND (
            SELECT count(*) FROM study_intervals
            WHERE session_id = NEW.id AND ended_at IS NULL
        ) != 1 THEN RAISE(ABORT, 'running requires one open interval')
        WHEN NEW.status IN ('paused', 'finished') AND EXISTS (
            SELECT 1 FROM study_intervals
            WHERE session_id = NEW.id AND ended_at IS NULL
        ) THEN RAISE(ABORT, 'paused or finished cannot have an open interval')
    END;
END;

PRAGMA user_version = 1;
COMMIT;

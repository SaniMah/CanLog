-- ============================================================================
-- CAN Log Analyser - database schema (PostgreSQL)
-- ============================================================================
-- Design notes:
--   * Surrogate primary keys (SERIAL/BIGSERIAL) - stable, simple joins.
--   * One parent table (log_file) and three children that reference it with
--     FOREIGN KEYs + ON DELETE CASCADE, so deleting a log cleans up everything
--     belonging to it. This keeps the data normalised (3NF): file-level facts
--     (vehicle, duration) live once in log_file, not repeated on every frame.
--   * CHECK constraints guard data quality (dlc 0-8, known anomaly types).
--   * A composite index matches the main access pattern (frames of one ID in
--     one log, in time order) - critical with ~180k rows per capture.
-- Run order: this script drops children before parents so it can be re-run.
-- ============================================================================

DROP TABLE IF EXISTS anomaly    CASCADE;
DROP TABLE IF EXISTS id_profile CASCADE;
DROP TABLE IF EXISTS can_frame  CASCADE;
DROP TABLE IF EXISTS log_file   CASCADE;

-- ---------------------------------------------------------------------------
-- log_file: one row per CAN capture loaded (the "parent" of everything).
-- ---------------------------------------------------------------------------
CREATE TABLE log_file (
    log_id         SERIAL       PRIMARY KEY,
    filename       TEXT         NOT NULL,
    source_dataset TEXT,                       -- e.g. 'CANdid'
    vehicle_make   TEXT,
    vehicle_model  TEXT,
    capture_type   TEXT,                       -- e.g. 'Brakes'
    description    TEXT,
    duration_s     DOUBLE PRECISION,
    frame_count    INTEGER,
    loaded_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- stop the same file being loaded twice:
    CONSTRAINT uq_log_file_filename UNIQUE (filename)
);

-- ---------------------------------------------------------------------------
-- can_frame: one row per CAN frame. The fact table (largest by far).
-- ---------------------------------------------------------------------------
CREATE TABLE can_frame (
    frame_id BIGSERIAL        PRIMARY KEY,
    log_id   INTEGER          NOT NULL REFERENCES log_file(log_id) ON DELETE CASCADE,
    ts       DOUBLE PRECISION NOT NULL,        -- Unix epoch seconds (us precision)
    can_id   VARCHAR(8)       NOT NULL,        -- hex id, e.g. '4D1' (11- or 29-bit)
    data     VARCHAR(16),                      -- up to 8 data bytes = 16 hex chars
    dlc      SMALLINT         NOT NULL,
    CONSTRAINT chk_dlc CHECK (dlc BETWEEN 0 AND 8)
);

-- Matches "give me ID X's frames in this log, in time order" - used everywhere.
CREATE INDEX idx_can_frame_log_can_ts ON can_frame (log_id, can_id, ts);

-- ---------------------------------------------------------------------------
-- id_profile: learned "normal" timing per CAN ID per log.
-- ---------------------------------------------------------------------------
CREATE TABLE id_profile (
    profile_id    SERIAL     PRIMARY KEY,
    log_id        INTEGER    NOT NULL REFERENCES log_file(log_id) ON DELETE CASCADE,
    can_id        VARCHAR(8) NOT NULL,
    frame_count   INTEGER    NOT NULL,
    freq_hz       DOUBLE PRECISION,
    median_period DOUBLE PRECISION,
    period_iqr    DOUBLE PRECISION,
    min_period    DOUBLE PRECISION,
    max_period    DOUBLE PRECISION,
    first_ts      DOUBLE PRECISION,
    last_ts       DOUBLE PRECISION,
    -- one profile per ID per log:
    CONSTRAINT uq_id_profile UNIQUE (log_id, can_id)
);

-- ---------------------------------------------------------------------------
-- anomaly: one row per detected fault (filled in Step 4).
-- ---------------------------------------------------------------------------
CREATE TABLE anomaly (
    anomaly_id   BIGSERIAL   PRIMARY KEY,
    log_id       INTEGER     NOT NULL REFERENCES log_file(log_id) ON DELETE CASCADE,
    can_id       VARCHAR(8),                   -- NULL for whole-log anomalies
    anomaly_type VARCHAR(20) NOT NULL,
    start_ts     DOUBLE PRECISION,
    end_ts       DOUBLE PRECISION,
    value        DOUBLE PRECISION,             -- e.g. gap length (s) or ratio
    detail       TEXT,
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_anomaly_type CHECK (anomaly_type IN
        ('dropout', 'timing_drift', 'unknown_id', 'missing_id'))
);

CREATE INDEX idx_anomaly_log_type ON anomaly (log_id, anomaly_type);

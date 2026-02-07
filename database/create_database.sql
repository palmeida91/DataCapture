-- ============================================================================
-- OEE Data Collector - Complete Database Setup
-- ============================================================================
-- Creates ALL tables required by the collector from scratch.
-- Safe to run on an empty 'production' database.
--
-- Usage:
--   psql -U collector -d production -h localhost -f database/create_database.sql
--
-- Tables created:
--   1. cycle_times            - Cycle time readings per sequence
--   2. technical_availability - TA%, fault, blocked, starved times
--   3. quality_counters       - Good/reject/rework part counts
--   4. break_definitions      - Scheduled break times (config)
--   5. actual_breaks          - Detected breaks (runtime)
--   6. connection_events      - OPC UA connect/disconnect log
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. CYCLE TIMES
-- ============================================================================
CREATE TABLE IF NOT EXISTS cycle_times (
    id              SERIAL PRIMARY KEY,
    time            TIMESTAMP NOT NULL,
    sequence_id     INTEGER NOT NULL,
    cycle_time_seconds      DOUBLE PRECISION NOT NULL,
    desired_cycle_time_seconds DOUBLE PRECISION,
    deviation_seconds       DOUBLE PRECISION,
    deviation_percent       DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_cycle_times_sequence_time 
    ON cycle_times(sequence_id, time DESC);

-- ============================================================================
-- 2. TECHNICAL AVAILABILITY
-- ============================================================================
CREATE TABLE IF NOT EXISTS technical_availability (
    id              SERIAL PRIMARY KEY,
    time            TIMESTAMP NOT NULL,
    sequence_id     INTEGER NOT NULL,
    ta_percent      DOUBLE PRECISION NOT NULL,
    fault_time_seconds    DOUBLE PRECISION,
    blocked_time_seconds  DOUBLE PRECISION,
    starved_time_seconds  DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_ta_sequence_time 
    ON technical_availability(sequence_id, time DESC);

-- ============================================================================
-- 3. QUALITY COUNTERS
-- ============================================================================
CREATE TABLE IF NOT EXISTS quality_counters (
    id              SERIAL PRIMARY KEY,
    time            TIMESTAMP NOT NULL,
    shift_number    INTEGER NOT NULL,
    hour_index      INTEGER NOT NULL,
    good_parts      INTEGER DEFAULT 0,
    reject_parts    INTEGER DEFAULT 0,
    rework_parts    INTEGER DEFAULT 0,
    UNIQUE (time, shift_number, hour_index)
);

CREATE INDEX IF NOT EXISTS idx_quality_shift_hour 
    ON quality_counters(shift_number, hour_index, time DESC);

-- ============================================================================
-- 4. BREAK DEFINITIONS (scheduled breaks - configuration data)
-- ============================================================================
-- Columns queried by collector:
--   id, day_of_week, shift_number, break_name, start_time, end_time, duration_minutes
CREATE TABLE IF NOT EXISTS break_definitions (
    id              SERIAL PRIMARY KEY,
    day_of_week     INTEGER NOT NULL,       -- 1=Monday ... 7=Sunday
    shift_number    INTEGER NOT NULL,       -- 1, 2, or 3
    break_name      VARCHAR(100) NOT NULL,
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    duration_minutes INTEGER GENERATED ALWAYS AS (
        EXTRACT(EPOCH FROM (end_time - start_time)) / 60
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_break_defs_day 
    ON break_definitions(day_of_week);

-- ============================================================================
-- 5. ACTUAL BREAKS (detected at runtime by TA freeze)
-- ============================================================================
CREATE TABLE IF NOT EXISTS actual_breaks (
    id                  SERIAL PRIMARY KEY,
    start_time          TIMESTAMP NOT NULL,
    end_time            TIMESTAMP,
    shift_number        INTEGER NOT NULL,
    is_scheduled        BOOLEAN DEFAULT TRUE,
    scheduled_break_id  INTEGER REFERENCES break_definitions(id),
    early_start_minutes INTEGER DEFAULT 0,
    late_end_minutes    INTEGER DEFAULT 0,
    duration_minutes    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_actual_breaks_time 
    ON actual_breaks(start_time DESC);

-- ============================================================================
-- 6. CONNECTION EVENTS (OPC UA connect/disconnect tracking)
-- ============================================================================
CREATE TABLE IF NOT EXISTS connection_events (
    event_id    SERIAL PRIMARY KEY,
    event_time  TIMESTAMP NOT NULL,
    event_type  TEXT NOT NULL,       -- 'connected', 'disconnected', 'reconnected'
    endpoint    TEXT NOT NULL,
    details     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_connection_events_time 
    ON connection_events(event_time DESC);

COMMIT;

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT 'Database setup complete!' AS status;
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;

-- ============================================================================
-- TimescaleDB Data Retention and Compression Configuration
-- ============================================================================
-- This script sets up automatic data retention and compression for your
-- production monitoring database. Run this once to configure the policies.
--
-- What this does:
-- 1. Enables compression on old data (saves 90%+ disk space)
-- 2. Sets up automatic deletion of data older than 90 days
-- 3. Keeps your database size manageable for long-term operation
--
-- Run this script with:
-- docker exec -it production_db psql -U collector -d production -f retention_config.sql
-- ============================================================================

-- Start a transaction (all-or-nothing: either everything succeeds or nothing changes)
BEGIN;

-- ============================================================================
-- SECTION 1: ENABLE COMPRESSION
-- ============================================================================
-- Compression reduces disk space by ~90% for old data while keeping it queryable
-- Data older than 7 days will be automatically compressed

-- Configure compression for cycle_times table
-- compress_segmentby = 'sequence_id' groups data by sequence for better compression
ALTER TABLE cycle_times SET (
    timescaledb.compress,                      -- Enable compression feature
    timescaledb.compress_segmentby = 'sequence_id'  -- Group by sequence for efficiency
);

-- Configure compression for technical_availability table
ALTER TABLE technical_availability SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'sequence_id'
);

-- Configure compression for quality_counters table
-- Group by shift_number since quality is tracked per shift
ALTER TABLE quality_counters SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'shift_number'
);

-- Add compression policy: automatically compress data older than 7 days
-- This runs in the background and doesn't affect queries
SELECT add_compression_policy('cycle_times', INTERVAL '7 days');
SELECT add_compression_policy('technical_availability', INTERVAL '7 days');
SELECT add_compression_policy('quality_counters', INTERVAL '7 days');

RAISE NOTICE 'Compression policies enabled! Data older than 7 days will be compressed.';


-- ============================================================================
-- SECTION 2: SET DATA RETENTION POLICIES
-- ============================================================================
-- Automatically delete data older than 90 days to prevent disk from filling up
-- You can change '90 days' to any interval you prefer (e.g., '30 days', '1 year')

-- Set retention for cycle_times: keep last 90 days
-- Data older than 90 days will be automatically deleted
SELECT add_retention_policy('cycle_times', INTERVAL '90 days');

-- Set retention for technical_availability: keep last 90 days
SELECT add_retention_policy('technical_availability', INTERVAL '90 days');

-- Set retention for quality_counters: keep last 90 days
SELECT add_retention_policy('quality_counters', INTERVAL '90 days');

RAISE NOTICE 'Retention policies set! Data older than 90 days will be automatically deleted.';


-- ============================================================================
-- SECTION 3: VERIFY CONFIGURATION
-- ============================================================================
-- Show all active policies to confirm they were created successfully

-- Display all compression policies
SELECT 
    hypertable_name AS "Table",
    'Compression' AS "Policy Type",
    config->>'compress_after' AS "Compress After"
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_compression';

-- Display all retention policies
SELECT 
    hypertable_name AS "Table",
    'Retention' AS "Policy Type",
    config->>'drop_after' AS "Delete After"
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_retention';


-- ============================================================================
-- OPTIONAL: ADJUST RETENTION PERIODS
-- ============================================================================
-- If you want different retention periods, uncomment and modify these:

-- Keep cycle times for only 30 days (high-frequency data)
-- SELECT remove_retention_policy('cycle_times');
-- SELECT add_retention_policy('cycle_times', INTERVAL '30 days');

-- Keep quality counters for 1 year (valuable data)
-- SELECT remove_retention_policy('quality_counters');
-- SELECT add_retention_policy('quality_counters', INTERVAL '365 days');


-- Commit the transaction (make all changes permanent)
COMMIT;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================
SELECT 'Retention and compression policies configured successfully!' AS "Status";
SELECT 'Data older than 90 days will be deleted automatically.' AS "Info";
SELECT 'Data older than 7 days will be compressed to save space.' AS "Info";

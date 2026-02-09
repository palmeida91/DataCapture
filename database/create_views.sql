-- ============================================================================
-- OEE Calculation Views
-- ============================================================================
-- All OEE calculations using MEDIAN (percentile_cont) instead of AVG
-- to handle outliers from skip cycles, PLC glitches, and transient spikes.
--
-- Usage:
--   psql -U collector -d production -h localhost -f database/create_views.sql
--
-- Run AFTER create_database.sql
--
-- Views created:
--   1. v_sequence_availability   - Median TA% per sequence (time-bucketed)
--   2. v_sequence_performance    - Median performance per sequence (time-bucketed)
--   3. v_sequence_cycle_times    - Median cycle time per sequence (time-bucketed)
--   4. v_sequence_downtime       - Median fault/blocked/starved per sequence (time-bucketed)
--   5. v_line_quality            - Quality % from counters (latest per shift/hour)
--   6. v_line_oee                - Combined line-level OEE
--   7. v_break_compliance        - Break start/end compliance
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. SEQUENCE AVAILABILITY (median TA% per sequence, 5-min buckets)
-- ============================================================================
-- Used by: Availability bar chart, availability trend, detail table
--
-- Grafana usage:
--   SELECT * FROM v_sequence_availability
--   WHERE $__timeFilter(bucket) AND sequence_id IN ($sequence)
-- ============================================================================
CREATE OR REPLACE VIEW v_sequence_availability AS
SELECT
    date_trunc('minute', time) AS bucket,
    sequence_id,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY ta_percent) AS availability_pct
FROM technical_availability
GROUP BY date_trunc('minute', time), sequence_id;


-- ============================================================================
-- 2. SEQUENCE PERFORMANCE (median per-row performance %, 5-min buckets)
-- ============================================================================
-- Calculates performance per individual reading FIRST, then takes the median.
-- This avoids the median(desired)/median(actual) distortion.
--
-- Performance = (desired_cycle_time / actual_cycle_time) * 100
-- Values > 100% mean station is running faster than target (good).
--
-- Grafana usage:
--   SELECT * FROM v_sequence_performance
--   WHERE $__timeFilter(bucket) AND sequence_id IN ($sequence)
-- ============================================================================
CREATE OR REPLACE VIEW v_sequence_performance AS
SELECT
    date_trunc('minute', time) AS bucket,
    sequence_id,
    percentile_cont(0.5) WITHIN GROUP (
        ORDER BY CASE
            WHEN cycle_time_seconds > 0
            THEN desired_cycle_time_seconds / cycle_time_seconds * 100
            ELSE 0
        END
    ) AS performance_pct,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY cycle_time_seconds) AS median_cycle_time_sec,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY desired_cycle_time_seconds) AS median_desired_cycle_sec
FROM cycle_times
GROUP BY date_trunc('minute', time), sequence_id;


-- ============================================================================
-- 3. SEQUENCE CYCLE TIMES (median cycle times, for trend charts)
-- ============================================================================
-- Grafana usage:
--   SELECT * FROM v_sequence_cycle_times
--   WHERE $__timeFilter(bucket) AND sequence_id IN ($sequence)
-- ============================================================================
CREATE OR REPLACE VIEW v_sequence_cycle_times AS
SELECT
    date_trunc('minute', time) AS bucket,
    sequence_id,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY cycle_time_seconds) AS median_cycle_sec,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY desired_cycle_time_seconds) AS median_desired_sec,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY deviation_seconds) AS median_deviation_sec,
    COUNT(*) AS reading_count
FROM cycle_times
GROUP BY date_trunc('minute', time), sequence_id;


-- ============================================================================
-- 4. SEQUENCE DOWNTIME (median fault/blocked/starved per sequence)
-- ============================================================================
-- Grafana usage:
--   SELECT * FROM v_sequence_downtime
--   WHERE $__timeFilter(bucket) AND sequence_id IN ($sequence)
-- ============================================================================
CREATE OR REPLACE VIEW v_sequence_downtime AS
SELECT
    date_trunc('minute', time) AS bucket,
    sequence_id,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY fault_time_seconds) AS median_fault_sec,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY blocked_time_seconds) AS median_blocked_sec,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY starved_time_seconds) AS median_starved_sec
FROM technical_availability
GROUP BY date_trunc('minute', time), sequence_id;


-- ============================================================================
-- 5. LINE QUALITY (latest quality counters per shift/hour)
-- ============================================================================
-- Quality counters are cumulative - the collector upserts them.
-- We want the latest reading per shift/hour combination.
--
-- Grafana usage:
--   SELECT * FROM v_line_quality WHERE $__timeFilter(time)
-- ============================================================================
CREATE OR REPLACE VIEW v_line_quality AS
SELECT
    time,
    shift_number,
    hour_index,
    good_parts,
    reject_parts,
    rework_parts,
    good_parts + reject_parts + rework_parts AS total_parts,
    CASE
        WHEN good_parts + reject_parts + rework_parts > 0 THEN
            ROUND(
                (good_parts::numeric /
                (good_parts + reject_parts + rework_parts) * 100), 1
            )
        ELSE 100
    END AS quality_pct
FROM quality_counters;


-- ============================================================================
-- 6. LINE OEE (combined A * P * Q for overall line)
-- ============================================================================
-- This is a function-like view that calculates line-level OEE.
-- Since quality is line-level (not per-sequence), OEE is also line-level.
--
-- Grafana usage:
--   With time range variables in a stat panel or trend.
--   See grafana guide for specific query.
-- ============================================================================
-- Note: Line-level OEE is best calculated in Grafana queries because it needs
-- the $__timeFilter() macro to aggregate across the selected time range.
-- The per-sequence views above provide the building blocks.
-- See the Grafana guide for the line OEE query.


-- ============================================================================
-- 7. BREAK COMPLIANCE
-- ============================================================================
-- Joins actual detected breaks with scheduled break definitions.
--
-- Grafana usage:
--   SELECT * FROM v_break_compliance
--   WHERE $__timeFilter(break_start)
-- ============================================================================
CREATE OR REPLACE VIEW v_break_compliance AS
SELECT
    ab.id AS break_id,
    ab.start_time AS break_start,
    ab.end_time AS break_end,
    ab.shift_number,
    bd.break_name,
    bd.start_time AS scheduled_start,
    bd.end_time AS scheduled_end,
    bd.duration_minutes AS scheduled_duration_min,
    ab.duration_minutes AS actual_duration_min,
    ab.early_start_minutes,
    ab.late_end_minutes,
    CASE
        WHEN ab.early_start_minutes > 0 AND ab.late_end_minutes > 0 THEN 'Early start, late end'
        WHEN ab.early_start_minutes > 0 THEN 'Early start'
        WHEN ab.late_end_minutes > 0 THEN 'Late end'
        ELSE 'On time'
    END AS compliance_status
FROM actual_breaks ab
LEFT JOIN break_definitions bd ON ab.scheduled_break_id = bd.id
WHERE ab.is_scheduled = TRUE;


COMMIT;

-- ============================================================================
-- GRANT PERMISSIONS
-- ============================================================================
GRANT SELECT ON v_sequence_availability TO collector;
GRANT SELECT ON v_sequence_performance TO collector;
GRANT SELECT ON v_sequence_cycle_times TO collector;
GRANT SELECT ON v_sequence_downtime TO collector;
GRANT SELECT ON v_line_quality TO collector;
GRANT SELECT ON v_break_compliance TO collector;

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT 'Views created successfully!' AS status;
SELECT viewname FROM pg_views WHERE schemaname = 'public' ORDER BY viewname;

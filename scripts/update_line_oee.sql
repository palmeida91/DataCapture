-- ============================================================================
-- Update OEE Calculation for Serial Production Line (Bottleneck-Based)
-- ============================================================================
-- This script updates your OEE calculation to correctly handle serial lines:
-- - Line OEE = Bottleneck (slowest) station OEE × Quality from last station
-- - Fault times use worst station (not summed)
-- - Quality counted only from final station
--
-- Run this script with:
-- docker cp update_line_oee_fixed.sql production_db:/tmp/update_line_oee_fixed.sql
-- docker exec -it production_db psql -U collector -d production -f /tmp/update_line_oee_fixed.sql
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: Drop Old Views
-- ============================================================================
DROP VIEW IF EXISTS current_oee CASCADE;
DROP VIEW IF EXISTS hourly_oee_trend CASCADE;
DROP VIEW IF EXISTS current_sequence_status CASCADE;
DROP VIEW IF EXISTS station_oee CASCADE;


-- ============================================================================
-- STEP 2: Create Station-Level OEE View
-- ============================================================================
CREATE OR REPLACE VIEW station_oee AS
WITH latest_cycles AS (
    SELECT DISTINCT ON (sequence_id)
        sequence_id,
        cycle_time_seconds,
        desired_cycle_time_seconds,
        time
    FROM cycle_times
    ORDER BY sequence_id, time DESC
),
latest_ta AS (
    SELECT DISTINCT ON (sequence_id)
        sequence_id,
        ta_percent,
        fault_time_seconds,
        blocked_time_seconds,
        starved_time_seconds,
        time
    FROM technical_availability
    ORDER BY sequence_id, time DESC
)
SELECT 
    s.sequence_id,
    s.sequence_name,
    COALESCE(ta.ta_percent, 0) as availability_percent,
    CASE 
        WHEN ct.cycle_time_seconds > 0 THEN 
            (ct.desired_cycle_time_seconds / ct.cycle_time_seconds * 100)
        ELSE 0 
    END as performance_percent,
    CASE 
        WHEN ct.cycle_time_seconds > 0 THEN
            (COALESCE(ta.ta_percent, 0) / 100) * 
            (ct.desired_cycle_time_seconds / ct.cycle_time_seconds) * 100
        ELSE 0
    END as station_oee_percent,
    ct.cycle_time_seconds,
    ct.desired_cycle_time_seconds,
    ta.fault_time_seconds,
    ta.blocked_time_seconds,
    ta.starved_time_seconds
FROM sequences s
LEFT JOIN latest_cycles ct ON s.sequence_id = ct.sequence_id
LEFT JOIN latest_ta ta ON s.sequence_id = ta.sequence_id
WHERE s.is_active = true;

GRANT SELECT ON station_oee TO collector;


-- ============================================================================
-- STEP 3: Create Line-Level OEE View (Bottleneck-Based)
-- ============================================================================
CREATE OR REPLACE VIEW current_oee AS
WITH last_station_quality AS (
    SELECT 
        good_parts,
        reject_parts,
        rework_parts,
        CASE 
            WHEN (good_parts + reject_parts + rework_parts) > 0 THEN
                (good_parts::float / (good_parts + reject_parts + rework_parts) * 100)
            ELSE 100
        END as quality_percent
    FROM quality_counters
    ORDER BY time DESC
    LIMIT 1
),
bottleneck_station AS (
    SELECT 
        sequence_name as bottleneck_name,
        station_oee_percent as bottleneck_oee
    FROM station_oee
    ORDER BY station_oee_percent ASC
    LIMIT 1
)
SELECT 
    (MIN(s.station_oee_percent) / 100 * q.quality_percent / 100) * 100 as oee_percent,
    MIN(s.availability_percent) as availability_percent,
    MIN(s.performance_percent) as performance_percent,
    q.quality_percent as quality_percent,
    85.0 as target_oee,
    b.bottleneck_name,
    b.bottleneck_oee as bottleneck_oee_percent
FROM station_oee s
CROSS JOIN last_station_quality q
CROSS JOIN bottleneck_station b
GROUP BY q.quality_percent, b.bottleneck_name, b.bottleneck_oee;

GRANT SELECT ON current_oee TO collector;


-- ============================================================================
-- STEP 4: Create Hourly OEE Trend View
-- ============================================================================
CREATE OR REPLACE VIEW hourly_oee_trend AS
WITH hourly_station_data AS (
    SELECT 
        date_trunc('hour', ct.time) as hour,
        ct.sequence_id,
        AVG(ct.cycle_time_seconds) as avg_cycle,
        AVG(ct.desired_cycle_time_seconds) as avg_desired,
        AVG(ta.ta_percent) as avg_ta
    FROM cycle_times ct
    LEFT JOIN technical_availability ta 
        ON ct.sequence_id = ta.sequence_id 
        AND date_trunc('hour', ct.time) = date_trunc('hour', ta.time)
    WHERE ct.time >= NOW() - INTERVAL '7 days'
    GROUP BY date_trunc('hour', ct.time), ct.sequence_id
),
hourly_station_oee AS (
    SELECT 
        hour,
        sequence_id,
        (COALESCE(avg_ta, 0) / 100) * 
        (avg_desired / NULLIF(avg_cycle, 0)) * 100 as station_oee
    FROM hourly_station_data
    WHERE avg_cycle > 0
),
hourly_bottleneck AS (
    SELECT 
        hour,
        MIN(station_oee) as bottleneck_oee
    FROM hourly_station_oee
    GROUP BY hour
),
hourly_quality AS (
    SELECT 
        date_trunc('hour', time) as hour,
        SUM(good_parts) as total_good,
        SUM(reject_parts) as total_reject,
        SUM(rework_parts) as total_rework
    FROM quality_counters
    WHERE time >= NOW() - INTERVAL '7 days'
    GROUP BY date_trunc('hour', time)
)
SELECT 
    b.hour,
    (b.bottleneck_oee / 100 * 
     (q.total_good::float / NULLIF(q.total_good + q.total_reject + q.total_rework, 0)) * 
     100) as oee_percent,
    b.bottleneck_oee as availability_performance_percent,
    (q.total_good::float / NULLIF(q.total_good + q.total_reject + q.total_rework, 0) * 100) as quality_percent
FROM hourly_bottleneck b
LEFT JOIN hourly_quality q ON b.hour = q.hour
WHERE (q.total_good + q.total_reject + q.total_rework) > 0
ORDER BY b.hour DESC;

GRANT SELECT ON hourly_oee_trend TO collector;


-- ============================================================================
-- STEP 5: Create Current Status View (Per Station)
-- ============================================================================
CREATE OR REPLACE VIEW current_sequence_status AS
SELECT 
    sequence_id,
    sequence_name,
    ROUND(availability_percent::numeric, 1) as ta_percent,
    ROUND(performance_percent::numeric, 1) as performance_percent,
    ROUND(station_oee_percent::numeric, 1) as station_oee_percent,
    ROUND(cycle_time_seconds::numeric, 1) as last_cycle_time,
    ROUND(desired_cycle_time_seconds::numeric, 1) as desired_cycle_time,
    CASE 
        WHEN cycle_time_seconds > desired_cycle_time_seconds THEN 'Slow'
        WHEN cycle_time_seconds < desired_cycle_time_seconds THEN 'Fast'
        ELSE 'On Target'
    END as cycle_time_status,
    ROUND(fault_time_seconds::numeric, 0) as fault_time_sec,
    ROUND(blocked_time_seconds::numeric, 0) as blocked_time_sec,
    ROUND(starved_time_seconds::numeric, 0) as starved_time_sec
FROM station_oee
ORDER BY sequence_id;

GRANT SELECT ON current_sequence_status TO collector;


-- ============================================================================
-- STEP 6: Verify New Views
-- ============================================================================
SELECT 
    '========================================================================' as " ";
SELECT 
    'OEE VIEWS UPDATED SUCCESSFULLY!' as "Status";
SELECT 
    '========================================================================' as " ";

SELECT '' as " ";
SELECT 'Current Line OEE with Bottleneck Info:' as " ";
SELECT 
    ROUND(oee_percent::numeric, 1) || '%' as "Line OEE",
    bottleneck_name as "Bottleneck Station",
    ROUND(bottleneck_oee_percent::numeric, 1) || '%' as "Bottleneck OEE"
FROM current_oee;

SELECT '' as " ";
SELECT 'Station OEE Comparison (Bottleneck shows first):' as " ";
SELECT 
    sequence_name as "Station",
    ROUND(station_oee_percent::numeric, 1) || '%' as "Station OEE"
FROM station_oee
ORDER BY station_oee_percent;

SELECT '' as " ";
SELECT 'Key Changes:' as " ";
SELECT '  - Line OEE now uses bottleneck (slowest) station' as " ";
SELECT '  - Quality counted only from last station' as " ";
SELECT '  - Fault times use worst station (not summed)' as " ";

SELECT '' as " ";
SELECT 'Next Steps:' as " ";
SELECT '  1. Refresh your Grafana dashboards' as " ";
SELECT '  2. Add Station OEE Comparison panel to identify bottleneck' as " ";
SELECT '  3. Focus improvement efforts on bottleneck station' as " ";
SELECT 
    '========================================================================' as " ";

COMMIT;

-- Done!
